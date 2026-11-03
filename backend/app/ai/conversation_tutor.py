"""Provider-neutral conversation port; no repository, execution or grading capability."""

from typing import Protocol

from app.schemas.conversation_tutor import ConversationTutorReply, ConversationTutorRequest


class ConversationTutorProvider(Protocol):
    def answer(
        self,
        request: ConversationTutorRequest,
        *,
        subject: str,
        timeout_seconds: float | None = None,
    ) -> ConversationTutorReply: ...
