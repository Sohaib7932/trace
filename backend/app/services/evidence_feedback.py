"""Internal authenticated feedback orchestration, without a learner-facing route.

The existing evidence service and repository establish facts. Deterministic
policy authorizes the entire response before an optional wording selection.
Neither provider output nor this service writes learner/evidence history.
"""

from uuid import UUID

from app.ai.evidence_feedback import EvidenceFeedbackProvider
from app.domain.accounts import Account, Principal
from app.domain.clock import Clock, as_utc, utc_now
from app.domain.learning import LearningError
from app.repositories.learning import LearningRepository
from app.schemas.engineering_evidence import EngineeringEvidenceBatch, EvidenceQuery
from app.schemas.evidence_feedback import (
    FallbackReason,
    FeedbackCompletion,
    FeedbackQuery,
    FeedbackReply,
    FeedbackRequest,
)
from app.schemas.lesson_assistant import PublicLessonContent
from app.services.catalog import LESSON_ID, PUBLIC_CONTENT, TRANSFER_CONTENT
from app.services.engineering_evidence import EngineeringEvidenceService
from app.services.evidence_feedback_policy import build_feedback_request
from app.services.evidence_feedback_validation import (
    render_feedback,
    unavailable_feedback,
    validate_feedback_selection,
)


class EvidenceFeedbackService:
    def __init__(
        self,
        repository: LearningRepository,
        provider: EvidenceFeedbackProvider,
        clock: Clock = utc_now,
    ) -> None:
        self.repository, self.provider, self.clock = repository, provider, clock
        self.evidence = EngineeringEvidenceService(repository)

    def _authorize(self, principal: Principal) -> None:
        inactive = False
        try:
            now = as_utc(self.clock())
            valid = (
                isinstance(principal, Principal)
                and isinstance(principal.learner_id, UUID)
                and as_utc(principal.expires_at) > now
            )
            if principal.credential is not None:
                valid = valid and (
                    principal.credential.learner_id == principal.learner_id
                    and principal.credential.revoked_at is None
                    and as_utc(principal.credential.expires_at) > now
                )
            if principal.account is not None:
                valid = valid and isinstance(principal.account, Account)
                if isinstance(principal.account, Account):
                    valid = valid and isinstance(principal.account.status, str)
                    inactive = principal.account.status != "active"
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise LearningError(
                "unauthenticated", "The learner authorization is invalid or expired."
            )
        if inactive:
            raise LearningError("forbidden", "The learner account is unavailable.")

    def _public_lesson(
        self, principal: Principal, batch: EngineeringEvidenceBatch
    ) -> PublicLessonContent:
        # A separate short read ends before provider execution. No LessonVersion
        # serialization, private siblings, raw submission or whole progress DTO.
        with self.repository.read() as store:
            session = store.owned_session(principal.learner_id, batch.query.session_id)
            if session is None:
                raise LearningError("not_found", "Session not found.")
            if (session.id, session.learner_id, session.lesson_version_id) != (
                batch.query.session_id,
                principal.learner_id,
                batch.lesson.version_id,
            ):
                raise LearningError(
                    "evidence_integrity", "The pinned lesson could not be validated."
                )
            version = store.version_by_id(session.lesson_version_id)
            pin = batch.lesson
            expected = PUBLIC_CONTENT if pin.lesson_id == LESSON_ID else TRANSFER_CONTENT
            if (version.id, version.lesson_id, version.version, version.content_hash) != (
                pin.version_id,
                pin.lesson_id,
                pin.version,
                pin.content_hash,
            ) or version.public_content != expected:
                raise LearningError(
                    "evidence_integrity", "The pinned lesson could not be validated."
                )
            return PublicLessonContent.model_validate(dict(version.public_content))

    def feedback(self, principal: Principal, query: FeedbackQuery) -> FeedbackReply:
        """Principal comes from existing authentication, never from a client body.

        Future public integration must separately review prediction-visibility,
        hint policies and credential revocation. No current learner route exposes
        this internal capability or accepts correctness/evidence assertions.
        """
        checked = FeedbackQuery.model_validate(query.model_dump(warnings=False))
        self._authorize(principal)
        try:
            batch = self.evidence.extract(
                EvidenceQuery(
                    owner_learner_id=principal.learner_id,
                    session_id=checked.session_id,
                    start_at=checked.start_at,
                    end_at=checked.end_at,
                    as_of=checked.as_of,
                    max_records=checked.max_records,
                )
            )
            content = self._public_lesson(principal, batch)
            request = build_feedback_request(checked.request_id, batch, content)
        except LearningError as error:
            if error.code in {"unauthenticated", "forbidden", "not_found"}:
                raise
            reasons: dict[str, FallbackReason] = {
                "dependency_unavailable": "source_unavailable",
                "evidence_limit": "context_limit",
            }
            self._authorize(principal)
            return unavailable_feedback(
                checked.request_id,
                checked.session_id,
                reasons.get(error.code, "source_invalid"),
            )
        except (ValueError, TypeError):
            self._authorize(principal)
            return unavailable_feedback(checked.request_id, checked.session_id, "source_invalid")
        self._authorize(principal)
        if request.state == "insufficient_evidence":
            return render_feedback(request)
        reason: FallbackReason
        try:
            # Give provider code a detached immutable copy. It cannot mutate the
            # policy snapshot used to validate and render the original claims.
            received = self.provider.explain(
                FeedbackRequest.model_validate(request.model_dump(warnings=False))
            )
        except TimeoutError:
            reason = "provider_timeout"
        except Exception:
            reason = "provider_exception"
        else:
            try:
                completion = FeedbackCompletion.model_validate(received.model_dump(warnings=False))
                if completion.status == "success":
                    selection = validate_feedback_selection(request, completion)
                    self._authorize(principal)
                    return render_feedback(request, selection, delivery="mock")
                reason = (
                    "provider_timeout"
                    if completion.status == "timeout"
                    else "disabled"
                    if completion.error_code == "disabled"
                    else "provider_unavailable"
                )
            except LearningError:
                raise
            except (ValueError, TypeError, AttributeError, RecursionError):
                reason = "invalid_output"
        self._authorize(principal)
        # This is an entirely new render of backend-authorized text and refs,
        # not a provider conclusion kept after deleting its invalid citations.
        return render_feedback(request, fallback_reason=reason)
