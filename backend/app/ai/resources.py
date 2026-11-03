"""Application-owned AI capabilities with disabled, mock and approved free-tier modes."""

from collections.abc import Callable

from app.ai.client import AITransport, BoundedAIClient
from app.ai.providers.bounded_evidence_feedback import BoundedEvidenceFeedbackProvider
from app.ai.providers.bounded_question_generator import BoundedQuestionGenerator
from app.ai.providers.bounded_support import BoundedSupportAssistant
from app.ai.providers.bounded_tutor import BoundedLessonAssistant, BoundedTutorProvider
from app.ai.providers.conversation_tutor import BoundedConversationTutor
from app.core.ai_settings import AIClientSettings
from app.domain.clock import Clock, utc_now
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.services.lesson_assistant import LessonAssistantService
from app.services.support import SupportService
from app.support.knowledge import ReviewedSupportKnowledge

type AITransportFactory = Callable[[], AITransport]


class AIResourceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("AI resources are unavailable.")


class AIResources:
    def __init__(
        self, settings: AIClientSettings, client: BoundedAIClient, clock: Clock = utc_now
    ) -> None:
        self.settings, self.client = settings, client
        self.question_generator = BoundedQuestionGenerator(client)
        self.evidence_feedback_provider = BoundedEvidenceFeedbackProvider(client)
        self.tutor_provider = BoundedTutorProvider(client)
        self.lesson_assistant = LessonAssistantService(BoundedLessonAssistant(client))
        self.conversation_tutor = BoundedConversationTutor(client)
        # Draft/missing/expired review keeps the corpus unavailable. No contact invented.
        self.support = SupportService(
            BoundedSupportAssistant(client),
            ReviewedSupportKnowledge(clock=clock)
            if settings.mode == "gemini_free"
            else ApprovedSupportKnowledge(),
        )

    @classmethod
    def create(
        cls,
        settings: AIClientSettings,
        transport_factory: AITransportFactory | None = None,
        *,
        clock: Clock = utc_now,
    ) -> "AIResources":
        client: BoundedAIClient | None = None
        transport: AITransport | None = None
        try:
            checked = AIClientSettings.model_validate(settings.model_dump(warnings=False))
            if checked.mode == "mock":
                if transport_factory is None:
                    raise AIResourceError()
                transport = transport_factory()
                if getattr(transport, "source", None) != "test_fixture" or not callable(
                    getattr(transport, "complete", None)
                ):
                    raise AIResourceError()
            elif checked.mode == "gemini_free":
                from app.ai.providers.gemini import GeminiTransport

                transport = (
                    transport_factory()
                    if transport_factory is not None
                    else GeminiTransport.from_environment(checked)
                )
                if getattr(transport, "source", None) != "ai" or not callable(
                    getattr(transport, "complete", None)
                ):
                    raise AIResourceError()
            # Disabled mode never constructs a transport, including an injected factory.
            client = BoundedAIClient(checked, transport)
            return cls(checked, client, clock)
        except Exception:
            try:
                if client is not None:
                    client.close()
                elif transport is not None:
                    close = getattr(transport, "close", None)
                    if callable(close):
                        close()
            except Exception:
                pass  # Preserve one constant startup diagnostic; no raw cleanup exception.
            raise AIResourceError() from None

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            raise AIResourceError() from None
