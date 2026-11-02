"""Release-authorized feedback facade, reused by the guarded HTTP integration."""

from uuid import UUID

from app.domain.accounts import Principal
from app.domain.clock import Clock, as_utc, utc_now
from app.domain.learning import LearningError
from app.schemas.feedback_release import ReleaseSessionState
from app.schemas.public_feedback import FeedbackVisibilityPolicy, PublicFeedbackReply
from app.services.feedback_release import FeedbackReleaseService
from app.services.public_feedback_projection import (
    project_public_feedback,
    validate_public_projection,
)


class LearnerFeedbackService:
    def __init__(
        self,
        release: FeedbackReleaseService,
        policy: FeedbackVisibilityPolicy | None = None,
        clock: Clock = utc_now,
        *,
        allowed_states: tuple[ReleaseSessionState, ...] | None = None,
    ) -> None:
        self.release, self.clock = release, clock
        selected = policy if policy is not None else FeedbackVisibilityPolicy.disabled()
        self.policy = FeedbackVisibilityPolicy.model_validate(selected.model_dump(warnings=False))
        self.allowed_states = allowed_states

    def feedback(self, principal: Principal, session_id: UUID) -> PublicFeedbackReply:
        """Identity comes from authentication; the caller supplies no evidence/window.

        The release service owns initial authorization, stage eligibility, source
        extraction/evaluation and fresh storage release. The pure public layer
        cannot authorize a client-supplied envelope or bypass those checks.
        """
        policy = FeedbackVisibilityPolicy.model_validate(self.policy.model_dump(warnings=False))
        if self.allowed_states is None:
            released = self.release.evaluate(principal, session_id, scope=policy.scope)
        else:
            # HTTP integration may narrow the approved reflection scope. The
            # release service applies this before evidence/provider evaluation,
            # then performs the same fresh authorization on every result path.
            released = self.release.evaluate(
                principal, session_id, scope=policy.scope, allowed_states=self.allowed_states
            )
        projected = project_public_feedback(released, policy)
        checked = validate_public_projection(released, policy, projected)
        # Projection and validation consume CPU after the final storage snapshot.
        # Enforce the known expiry at handoff as well; no new provider/read loop.
        now = as_utc(self.clock())
        if now < released.released_at or now >= released.released_authorization.valid_until:
            raise LearningError(
                "unauthenticated", "The learner authorization is invalid or expired."
            )
        return checked
