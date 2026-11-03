"""Application-owned AI capabilities with disabled, mock and approved free-tier modes."""

import time
from collections.abc import Callable

from app.ai.accounting import AIUsageLedger, AllowancePolicy
from app.ai.client import AITransport, BoundedAIClient
from app.ai.embeddings import BoundedEmbeddingClient, EmbeddingTransport
from app.ai.providers.bounded_evidence_feedback import BoundedEvidenceFeedbackProvider
from app.ai.providers.bounded_question_generator import BoundedQuestionGenerator
from app.ai.providers.bounded_support import BoundedSupportAssistant
from app.ai.providers.bounded_tutor import BoundedLessonAssistant, BoundedTutorProvider
from app.ai.providers.conversation_tutor import BoundedConversationTutor
from app.core.ai_settings import AIClientSettings
from app.core.embedding_settings import EmbeddingSettings
from app.domain.clock import Clock, utc_now
from app.repositories.support_knowledge import ApprovedSupportKnowledge, SupportKnowledge
from app.services.lesson_assistant import LessonAssistantService
from app.services.support import SupportService
from app.support.knowledge import ReviewedSupportKnowledge

type AITransportFactory = Callable[[], AITransport]
type EmbeddingTransportFactory = Callable[[], EmbeddingTransport]


class AIResourceError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("AI resources are unavailable.")


class AIResources:
    def __init__(
        self,
        settings: AIClientSettings,
        client: BoundedAIClient,
        clock: Clock = utc_now,
        *,
        embeddings: BoundedEmbeddingClient | None = None,
        knowledge: SupportKnowledge | None = None,
    ) -> None:
        self.settings, self.client = settings, client
        self.embeddings = embeddings or BoundedEmbeddingClient(EmbeddingSettings(_env_file=None))
        self.question_generator = BoundedQuestionGenerator(client)
        self.evidence_feedback_provider = BoundedEvidenceFeedbackProvider(client)
        self.tutor_provider = BoundedTutorProvider(client)
        self.lesson_assistant = LessonAssistantService(BoundedLessonAssistant(client))
        self.conversation_tutor = BoundedConversationTutor(client)
        # Draft/missing/expired review keeps the corpus unavailable. No contact invented.
        self.support = SupportService(
            BoundedSupportAssistant(client),
            knowledge
            if knowledge is not None
            else ReviewedSupportKnowledge(clock=clock)
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
        ledger: AIUsageLedger | None = None,
        allowance_policy: AllowancePolicy | None = None,
        embedding_settings: EmbeddingSettings | None = None,
        embedding_transport_factory: EmbeddingTransportFactory | None = None,
        knowledge: SupportKnowledge | None = None,
    ) -> "AIResources":
        client: BoundedAIClient | None = None
        transport: AITransport | None = None
        embeddings: BoundedEmbeddingClient | None = None
        embedding_transport: EmbeddingTransport | None = None
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
            client = BoundedAIClient(
                checked, transport, ledger=ledger, allowance_policy=allowance_policy
            )
            embedding_config = embedding_settings or EmbeddingSettings(_env_file=None)
            if embedding_config.mode == "gemini_free":
                from app.ai.providers.gemini_embeddings import GeminiEmbeddingTransport

                embedding_transport = (
                    embedding_transport_factory()
                    if embedding_transport_factory is not None
                    else GeminiEmbeddingTransport.from_environment(embedding_config)
                )
            elif embedding_config.mode == "mock":
                if embedding_transport_factory is None:
                    raise AIResourceError()
                embedding_transport = embedding_transport_factory()
            embeddings = BoundedEmbeddingClient(
                embedding_config,
                embedding_transport,
                ledger=ledger,
                allowance_policy=allowance_policy,
            )
            return cls(checked, client, clock, embeddings=embeddings, knowledge=knowledge)
        except Exception:
            try:
                if embeddings is not None:
                    embeddings.close()
                elif embedding_transport is not None:
                    embedding_transport.close()
            except Exception:
                pass
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
            try:
                self.embeddings.close()
            finally:
                self.client.close()
        except Exception:
            raise AIResourceError() from None

    def stop_admission(self) -> None:
        self.client.stop_admission()
        self.embeddings.stop_admission()

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        end = time.monotonic() + timeout if timeout is not None else None
        for client in (self.client, self.embeddings):
            remaining = max(0, end - time.monotonic()) if end is not None else None
            if not client.wait_for_idle(remaining):
                return False
        return True
