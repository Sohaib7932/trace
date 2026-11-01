"""Stateless support orchestration with extractive grounding and explicit availability."""

from app.ai.support_assistant import SupportAssistant
from app.repositories.support_knowledge import ApprovedSupportKnowledge, SupportKnowledge
from app.schemas.support import (
    SupportEscalation,
    SupportMatch,
    SupportQuestion,
    SupportReference,
    SupportResponse,
    SupportSelectionResult,
)


class SupportService:
    def __init__(
        self,
        assistant: SupportAssistant | None = None,
        knowledge: SupportKnowledge | None = None,
        *,
        escalation: SupportEscalation | None = None,
    ) -> None:
        self.assistant = assistant
        self.knowledge = knowledge if knowledge is not None else ApprovedSupportKnowledge()
        self.escalation = (
            SupportEscalation.model_validate(escalation.model_dump(warnings=False))
            if escalation
            else None
        )

    def answer(self, question: SupportQuestion, *, subject: str = "internal") -> SupportResponse:
        checked = SupportQuestion.model_validate(question.model_dump(warnings=False))
        unavailable = SupportResponse(
            status="unavailable",
            message="Customer support is currently unavailable.",
            source="unavailable",
            escalation=self.escalation,
        )
        try:
            if not self.knowledge.available:
                return unavailable
            received = self.knowledge.retrieve(checked)
            if type(received) is not tuple or len(received) > 3:
                return unavailable
            passages = tuple(
                SupportMatch.model_validate(p.model_dump(warnings=False)) for p in received
            )
            if len({passage.passage_id for passage in passages}) != len(passages):
                return unavailable
        except Exception:
            return unavailable
        if not passages:
            return SupportResponse(
                status="no_sources",
                message="No relevant approved documentation was found.",
                source="unavailable",
                escalation=self.escalation,
            )
        if self.assistant is None:
            return unavailable
        try:
            result = self.assistant.select(checked, passages, subject=subject)
            if result is None:
                return unavailable
            result = SupportSelectionResult.model_validate(result.model_dump(warnings=False))
        except Exception:
            return unavailable
        selection = result.selection
        by_id = {passage.passage_id: passage for passage in passages}
        if not set(selection.passage_ids) <= by_id.keys():
            return unavailable
        fixture = any(passage.approval == "test_fixture" for passage in passages)
        if selection.status == "unsupported":
            return SupportResponse(
                status="unsupported",
                message="The approved documentation does not establish an answer.",
                source="test_fixture" if fixture else result.source,
                escalation=self.escalation,
            )
        return SupportResponse(
            status="answered",
            message="Relevant approved documentation is quoted below.",
            references=tuple(
                SupportReference(
                    source_id=by_id[key].source_id,
                    source_name=by_id[key].title,
                    passage_id=key,
                    quote=by_id[key].text,
                )
                for key in selection.passage_ids
            ),
            source="test_fixture" if fixture else result.source,
            escalation=self.escalation,
        )
