"""Application-owned internal AI capabilities. Only disabled/explicit mock operation exists."""

from collections.abc import Callable

from app.ai.client import AITransport, BoundedAIClient
from app.ai.providers.bounded_question_generator import BoundedQuestionGenerator
from app.ai.providers.bounded_support import BoundedSupportAssistant
from app.ai.providers.bounded_tutor import BoundedLessonAssistant, BoundedTutorProvider
from app.core.ai_settings import AIClientSettings
from app.services.lesson_assistant import LessonAssistantService
from app.services.support import SupportService

type AITransportFactory = Callable[[], AITransport]


class AIResourceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("AI resources are unavailable.")


class AIResources:
    def __init__(self, settings: AIClientSettings, client: BoundedAIClient) -> None:
        self.settings, self.client = settings, client
        self.question_generator = BoundedQuestionGenerator(client)
        self.tutor_provider = BoundedTutorProvider(client)
        self.lesson_assistant = LessonAssistantService(BoundedLessonAssistant(client))
        # No corpus/contact is approved. This service remains unavailable by default.
        self.support = SupportService(BoundedSupportAssistant(client))

    @classmethod
    def create(
        cls,
        settings: AIClientSettings,
        transport_factory: AITransportFactory | None = None,
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
            # Disabled mode never constructs a transport, including an injected factory.
            client = BoundedAIClient(checked, transport)
            return cls(checked, client)
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
