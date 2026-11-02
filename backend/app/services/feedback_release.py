"""Fresh authorization and source-current evaluation for guarded orchestration."""

from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.accounts import Principal
from app.domain.clock import Clock, as_utc, utc_now
from app.domain.learning import (
    Attempt,
    LearningError,
    LearningSession,
    LessonVersion,
    Prediction,
    VerificationRun,
)
from app.repositories.feedback_release import FeedbackReleaseRead, FeedbackReleaseRepository
from app.repositories.learning import LearningStore
from app.schemas.engineering_evidence import EvidenceQuery, LessonPin
from app.schemas.evidence_feedback import FeedbackReply, FeedbackRequest
from app.schemas.feedback_release import (
    FeedbackEvaluationEnvelope,
    FeedbackReleaseScope,
    FreshAuthorization,
    ReleasedFeedbackResult,
    ReleaseSession,
    ReleaseSessionState,
    SelectedAttempt,
    SelectedRun,
    feedback_release_digest,
)
from app.schemas.lesson_assistant import PublicLessonContent
from app.services.catalog import (
    LESSON_ID,
    PUBLIC_CONTENT,
    TRANSFER_CONTENT,
    lesson_hash,
    transfer_hash,
)
from app.services.engineering_evidence import EngineeringEvidenceService
from app.services.evidence_feedback import EvidenceFeedbackService
from app.services.evidence_feedback_policy import build_feedback_request
from app.services.evidence_feedback_validation import unavailable_feedback


class _BorrowedRepository:
    """Reuse the authoritative extractor in the adapter's same consistent read."""

    def __init__(self, store: LearningStore) -> None:
        self.store = store

    @contextmanager
    def read(self) -> Iterator[LearningStore]:
        yield self.store

    def write(self) -> AbstractContextManager[LearningStore]:
        raise AssertionError("Feedback evaluation is read-only")


def _row(value: object) -> dict[str, object]:
    if not is_dataclass(value) or isinstance(value, type):
        raise ValueError("Feedback sources must be detached repository records")
    return asdict(value)


def _rows(values: Iterable[object]) -> list[dict[str, object]]:
    return [_row(value) for value in sorted(values, key=lambda item: str(getattr(item, "id", "")))]


def _session(value: LearningSession) -> ReleaseSession:
    return ReleaseSession.model_validate(
        {
            "session_id": value.id,
            "owner_learner_id": value.learner_id,
            "lesson_version_id": value.lesson_version_id,
            "state": value.state,
            "created_at": value.created_at,
            "completed_at": value.completed_at,
        }
    )


def _source_head(
    read: FeedbackReleaseRead,
) -> tuple[str, list[Attempt], list[VerificationRun], Prediction | None]:
    """Include pending and post-cutoff sources, not just emitted observations.

    Private source text is hashed transiently and never copied into an envelope
    or provider context. LearningEvent/bootstrap metadata does not establish
    evidence and is deliberately excluded. The source guard never truncates.
    """
    store, session = read.learning, read.session
    prediction = store.prediction(session.id)
    attempts, runs = store.attempts(session.id), store.runs(session.id)
    hints, operations = store.hints(session.id), store.hint_operations(session.id)
    checkpoints = [
        item
        for item in store.checkpoints(session.learner_id)
        if item.transfer_session_id == session.id
    ]
    count = (
        2
        + int(prediction is not None)
        + len(attempts)
        + len(runs)
        + len(hints)
        + len(operations)
        + len(checkpoints)
    )

    def guard(extra: int = 0) -> None:
        nonlocal count
        count += extra
        if count > 10000:
            raise LearningError("evidence_limit", "The source history exceeds the evidence limit.")

    guard()
    run_records = []
    for run in sorted(runs, key=lambda item: str(item.id)):
        checks = store.checks(run.id)
        runtime = (
            store.notes(run.id)
            if read.lesson.lesson_id == LESSON_ID
            else store.tasks(run.id)
            if read.lesson.lesson_id == "fastapi-nested-payload-transfer"
            else ()
        )
        guard(len(checks) + len(runtime))
        run_records.append({"run": _row(run), "checks": _rows(checks), "runtime": _rows(runtime)})
    recall_records = []
    for checkpoint in sorted(checkpoints, key=lambda item: str(item.id)):
        answers = store.retrieval_attempts(checkpoint.id)
        guard(len(answers))
        recall_records.append({"checkpoint": _row(checkpoint), "answers": _rows(answers)})
    head = {
        "schema_version": "feedback-source-head-v1",
        "session": _row(session),
        "lesson": _row(read.lesson),
        "prediction": _row(prediction) if prediction is not None else None,
        "attempts": _rows(attempts),
        "runs": run_records,
        "hints": _rows(hints),
        "operations": _rows(operations),
        "recall": recall_records,
    }
    return feedback_release_digest(head), attempts, runs, prediction


def _supported_lesson(
    session: LearningSession,
    lesson: LessonVersion,
) -> tuple[LessonPin | None, PublicLessonContent | None]:
    if lesson.id != session.lesson_version_id:
        raise ValueError("The lesson does not match its session pin")
    if lesson.version != "1.0.0" or lesson.lesson_id not in {
        LESSON_ID,
        "fastapi-nested-payload-transfer",
    }:
        return None, None
    if lesson.lesson_id == LESSON_ID:
        public = PUBLIC_CONTENT
        digest = lesson_hash(lesson.public_content, lesson.expected_field, lesson.prediction_answer)
        expected = lesson_hash(PUBLIC_CONTENT, "content", "rejected")
    else:
        public = TRANSFER_CONTENT
        if (lesson.expected_field, lesson.prediction_answer) != ("nested", "rejected"):
            raise ValueError("The legacy definition is invalid")
        digest, expected = transfer_hash(lesson.public_content), transfer_hash(TRANSFER_CONTENT)
    if lesson.public_content != public or lesson.content_hash != digest or digest != expected:
        raise ValueError("The pinned legacy definition is invalid")
    # This validates authored definition integrity, not a learner prediction.
    return LessonPin.model_validate(
        {
            "version_id": lesson.id,
            "lesson_id": lesson.lesson_id,
            "version": lesson.version,
            "content_hash": digest,
        }
    ), PublicLessonContent.model_validate(dict(lesson.public_content))


def _ready(
    session: LearningSession,
    attempts: list[Attempt],
    prediction: Prediction | None,
    cutoff: datetime,
) -> bool:
    if not attempts:
        return False
    if prediction is None or prediction.session_id != session.id:
        raise ValueError("Attempt provenance requires its owned prediction")
    for attempt in attempts:
        if (
            not isinstance(attempt.id, UUID)
            or attempt.session_id != session.id
            or type(attempt.number) is not int
            or attempt.number < 1
            or as_utc(attempt.created_at) < as_utc(session.created_at)
            or as_utc(prediction.created_at) > as_utc(attempt.created_at)
        ):
            raise ValueError("Invalid attempt provenance")
    return any(as_utc(attempt.created_at) < cutoff for attempt in attempts)


def _selected(
    plan: FeedbackRequest | None,
    attempts: list[Attempt],
    runs: list[VerificationRun],
) -> tuple[SelectedAttempt | None, SelectedRun | None]:
    if plan is None or plan.focus is None or plan.focus.kind != "attempt":
        return None, None
    attempt = next(item for item in attempts if item.id == plan.focus.record_id)
    selected_attempt = SelectedAttempt(
        attempt_id=attempt.id,
        number=attempt.number,
        created_at=attempt.created_at,
    )
    cited = {
        identity
        for claim in plan.claims
        if claim.claim_id
        in {"verification-passed", "verification-failed", "verification-unavailable"}
        for identity in claim.evidence_ids
    }
    sources = {item.source.record_id for item in plan.evidence.observations if item.id in cited}
    relevant = [
        item
        for item in runs
        if item.attempt_id == attempt.id and (not sources or item.id in sources)
    ]
    if not relevant:
        return selected_attempt, None
    run = max(relevant, key=lambda item: (item.created_at, str(item.id)))
    return selected_attempt, SelectedRun.model_validate(
        {
            "run_id": run.id,
            "attempt_id": run.attempt_id,
            "status": run.status,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
        }
    )


class FeedbackReleaseService:
    def __init__(
        self,
        repository: FeedbackReleaseRepository,
        feedback: EvidenceFeedbackService,
        clock: Clock = utc_now,
    ) -> None:
        self.repository, self.feedback, self.clock = repository, feedback, clock

    def _capture(
        self,
        principal: Principal,
        session_id: UUID,
        scope: FeedbackReleaseScope,
        allowed_states: tuple[ReleaseSessionState, ...] | None = None,
    ) -> FeedbackEvaluationEnvelope:
        cutoff = as_utc(self.clock())
        request_id = uuid4()
        with self.repository.read(principal, session_id, cutoff) as read:
            authorization = FreshAuthorization.model_validate(read.auth.model_dump(warnings=False))
            session = _session(read.session)
            head, attempts, runs, prediction = _source_head(read)
            lesson, public, evidence, plan = None, None, None, None
            availability = "unavailable"
            try:
                lesson, public = _supported_lesson(read.session, read.lesson)
                if (
                    authorization.mode not in scope.allowed_modes
                    or (allowed_states is not None and session.state not in allowed_states)
                    or (
                        session.state in {"completed", "abandoned"}
                        and not scope.allow_terminal_reflection
                    )
                    or lesson is None
                ):
                    availability = "not_supported"
                elif cutoff <= session.created_at or not _ready(
                    read.session, attempts, prediction, cutoff
                ):
                    availability = "not_ready"
                else:
                    evidence = EngineeringEvidenceService(
                        _BorrowedRepository(read.learning)
                    ).extract(
                        EvidenceQuery(
                            owner_learner_id=authorization.learner_id,
                            session_id=session_id,
                            start_at=session.created_at,
                            end_at=cutoff,
                            as_of=cutoff,
                            max_records=64,
                        )
                    )
                    assert public is not None
                    plan = build_feedback_request(request_id, evidence, public)
                    availability = "evaluated"
            except LearningError as error:
                if error.code in {"unauthenticated", "forbidden", "not_found"}:
                    raise
            except (ValueError, TypeError, KeyError, StopIteration):
                pass
            try:
                selected_attempt, selected_run = _selected(plan, attempts, runs)
            except (ValueError, TypeError, KeyError, StopIteration):
                selected_attempt, selected_run, plan = None, None, None
                availability = "unavailable"
            body = {
                "schema_version": "feedback-evaluation-v1",
                "policy_version": "evidence-feedback-policy-v1",
                "request_id": request_id,
                "authorization": authorization,
                "scope": scope,
                "scope_fingerprint": feedback_release_digest(scope),
                "session": session,
                "lesson": lesson,
                "public_content": public,
                "cutoff": cutoff,
                "availability": availability,
                "evidence": evidence,
                "plan": plan,
                "source_fingerprint": head,
                "cohort_fingerprint": feedback_release_digest(evidence)
                if evidence is not None
                else None,
                "selected_attempt": selected_attempt,
                "selected_run": selected_run,
            }
            return FeedbackEvaluationEnvelope.model_validate(
                {
                    **body,
                    "envelope_fingerprint": feedback_release_digest(body),
                }
            )

    def _release(
        self,
        principal: Principal,
        envelope: FeedbackEvaluationEnvelope,
    ) -> tuple[FreshAuthorization, datetime]:
        now = as_utc(self.clock())
        with self.repository.read(principal, envelope.session.session_id, now) as read:
            # The adapter authenticates first. Any auth failure propagates before
            # provider fallback, source diagnostics, or stale-state comparisons.
            current = FreshAuthorization.model_validate(read.auth.model_dump(warnings=False))
            try:
                head, _, _, _ = _source_head(read)
                if (
                    current.identity() != envelope.authorization.identity()
                    or _session(read.session) != envelope.session
                    or head != envelope.source_fingerprint
                ):
                    raise ValueError("Feedback source state changed")
                if envelope.evidence is not None:
                    fresh = EngineeringEvidenceService(_BorrowedRepository(read.learning)).extract(
                        envelope.evidence.query
                    )
                    if feedback_release_digest(fresh) != envelope.cohort_fingerprint:
                        raise ValueError("Feedback evidence cohort changed")
            except LearningError as error:
                if error.code in {"unauthenticated", "forbidden", "not_found"}:
                    raise
                raise LearningError(
                    "feedback_changed", "Feedback changed while it was being prepared. Try again."
                ) from error
            except (ValueError, TypeError, KeyError, StopIteration) as error:
                raise LearningError(
                    "feedback_changed", "Feedback changed while it was being prepared. Try again."
                ) from error
        # The storage snapshot began at observed_at. A long source audit must
        # not release after the credential's known deadline has elapsed.
        decided_at = as_utc(self.clock())
        self._time_valid(current, decided_at)
        return current, decided_at

    @staticmethod
    def _time_valid(authorization: FreshAuthorization, now: datetime) -> None:
        if now < authorization.observed_at or now >= authorization.valid_until:
            raise LearningError(
                "unauthenticated", "The learner authorization is invalid or expired."
            )

    def evaluate(
        self,
        principal: Principal,
        session_id: UUID,
        *,
        scope: FeedbackReleaseScope,
        allowed_states: tuple[ReleaseSessionState, ...] | None = None,
    ) -> ReleasedFeedbackResult:
        """Only server-side authenticated callers may supply this typed scope.

        No transaction or ORM session spans provider work. Storage authority is
        observed in the final consistent read; released_at records the post-read
        decision. Known expiry is checked again after result validation, just
        before handoff. Later storage commits cannot retract an emitted result.
        This service does not own a cache, retry loop or authorization token.
        The HTTP integration adds its own admission/deadline boundary and can
        narrow eligible session states without changing legacy internal scope.
        """
        if not isinstance(session_id, UUID):
            raise ValueError("A feedback session identifier must be a UUID")
        checked_scope = FeedbackReleaseScope.model_validate(scope.model_dump(warnings=False))
        envelope = self._capture(principal, session_id, checked_scope, allowed_states)
        reply: FeedbackReply | None = None
        try:
            self._time_valid(envelope.authorization, as_utc(self.clock()))
            if envelope.plan is not None:
                reply = self.feedback.evaluate_prepared(envelope.plan)
            elif envelope.availability == "unavailable":
                reply = unavailable_feedback(envelope.request_id, session_id, "source_invalid")
        finally:
            # Also executes for insufficient/unavailable/pre-ready/disabled paths,
            # and overrides an evaluator exception if authorization was revoked.
            released, decided_at = self._release(principal, envelope)
        body = {
            "schema_version": "released-feedback-v1",
            "envelope": envelope,
            "reply": reply,
            "released_authorization": released,
            "released_at": decided_at,
        }
        result = ReleasedFeedbackResult.model_validate(
            {
                **body,
                "release_fingerprint": feedback_release_digest(body),
            }
        )
        self._time_valid(released, as_utc(self.clock()))
        return result
