"""Reuse fresh owned lesson authorization; keep dialogue stateless and untrusted."""

import hashlib
from uuid import UUID

from app.ai.conversation_tutor import ConversationTutorProvider
from app.ai.providers.conversation_tutor import unavailable_conversation
from app.domain.accounts import Principal
from app.domain.learning import LearningError
from app.schemas.conversation_tutor import (
    ConversationTutorContext,
    ConversationTutorReply,
    ConversationTutorRequest,
    TutorConversationCreate,
    explanatory_text,
)
from app.services.catalog import (
    LESSON_ID,
    PUBLIC_CONTENT,
    TRANSFER_CONTENT,
    lesson_hash,
    transfer_hash,
)
from app.services.lesson_tutoring import LessonTutoringService


class ConversationTutoringService:
    def __init__(
        self,
        context_source: LessonTutoringService,
        provider: ConversationTutorProvider,
        *,
        timeout_seconds: float,
    ) -> None:
        self.context_source, self.provider = context_source, provider
        self.timeout_seconds = timeout_seconds

    def answer(
        self, owner: Principal, session_id: UUID, body: TutorConversationCreate
    ) -> ConversationTutorReply:
        checked = TutorConversationCreate.model_validate(body.model_dump(warnings=False))
        # The existing C1-backed capture owns authentication, account role/status,
        # session ownership/expiry, supported pin/hash and snapshot signature rules.
        context_question = "Prepare the owned public lesson context."
        before, public, choices = self.context_source._capture(
            owner, session_id, context_question, include_visible_context=True
        )
        digest = (
            lesson_hash(PUBLIC_CONTENT, "content", "rejected")
            if public.context.lesson_id == LESSON_ID
            else transfer_hash(TRANSFER_CONTENT)
        )
        observed = (
            "passed"
            if "observed-success" in choices
            else "failed"
            if "observed-failure" in choices
            else "unknown"
        )
        request = ConversationTutorRequest(
            trusted_context=ConversationTutorContext.model_validate(
                {
                    "lesson_digest": digest,
                    "public": public.context.model_dump(mode="json"),
                    "latest_saved_verification": observed,
                }
            ),
            untrusted_dialogue=checked,
        )
        if owner.account is None:
            raise LearningError("unauthenticated", "Sign in to use the engineering tutor.")
        subject = "conversation:" + hashlib.sha256(str(owner.account.id).encode()).hexdigest()
        # No source read/write transaction survives the capture or provider call.
        try:
            supplied = self.provider.answer(
                request, subject=subject, timeout_seconds=self.timeout_seconds
            )
            reply = ConversationTutorReply.model_validate(supplied.model_dump(warnings=False))
            if reply.status != "unavailable":
                explanatory_text(reply.text)
        except Exception:
            reply = unavailable_conversation()
        after, _, _ = self.context_source._capture(
            owner, session_id, context_question, include_visible_context=True
        )
        if before != after:
            raise LearningError("conflict", "Saved work changed. Refresh progress and ask again.")
        return ConversationTutorReply.model_validate(reply.model_dump(warnings=False))
