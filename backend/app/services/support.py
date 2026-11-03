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
from app.support.knowledge import ReviewedSupportKnowledge
from app.support.receipts import VersionedSupportAnswer


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
        return self.answer_with_provenance(question, subject=subject).response

    def answer_with_provenance(
        self, question: SupportQuestion, *, subject: str = "internal"
    ) -> VersionedSupportAnswer:
        checked = SupportQuestion.model_validate(question.model_dump(warnings=False))
        unavailable = SupportResponse(
            status="unavailable",
            message="Customer support is currently unavailable.",
            source="unavailable",
            escalation=self.escalation,
        )

        def finish(response: SupportResponse) -> VersionedSupportAnswer:
            return VersionedSupportAnswer(response=response)

        try:
            snapshot = (
                self.knowledge.snapshot()
                if isinstance(self.knowledge, ReviewedSupportKnowledge)
                else None
            )
            knowledge = snapshot if snapshot is not None else self.knowledge
            if not knowledge.available:
                return finish(unavailable)
            received = knowledge.retrieve(checked)
            if type(received) is not tuple or len(received) > 3:
                return finish(unavailable)
            passages = tuple(
                SupportMatch.model_validate(p.model_dump(warnings=False)) for p in received
            )
            if len({passage.passage_id for passage in passages}) != len(passages):
                return finish(unavailable)
            versions = tuple(snapshot.resolve(passage) for passage in passages) if snapshot else ()
            if any(version is None for version in versions):
                return finish(unavailable)
        except Exception:
            return finish(unavailable)
        if not passages:
            return finish(
                SupportResponse(
                    status="no_sources",
                    message="No relevant approved documentation was found.",
                    source="unavailable",
                    escalation=self.escalation,
                )
            )
        if self.assistant is None:
            return finish(unavailable)
        try:
            result = self.assistant.select(checked, passages, subject=subject)
            if result is None:
                return finish(unavailable)
            result = SupportSelectionResult.model_validate(result.model_dump(warnings=False))
        except Exception:
            return finish(unavailable)
        selection = result.selection
        # Recheck the same source scope after slow provider work. Expired, edited
        # or newly conflicting documentation must not escape as a stale answer.
        try:
            if snapshot is not None and isinstance(self.knowledge, ReviewedSupportKnowledge):
                fresh = self.knowledge.snapshot()
                if (
                    not fresh.available
                    or fresh.manifest_sha256 != snapshot.manifest_sha256
                    or tuple(fresh.reconstruct(version) for version in versions if version)
                    != passages
                ):
                    return finish(unavailable)
            elif not self.knowledge.available or self.knowledge.retrieve(checked) != passages:
                return finish(unavailable)
        except Exception:
            return finish(unavailable)
        by_id = {passage.passage_id: passage for passage in passages}
        if not set(selection.passage_ids) <= by_id.keys():
            return finish(unavailable)
        fixture = any(passage.approval == "test_fixture" for passage in passages)
        if selection.status == "unsupported":
            return finish(
                SupportResponse(
                    status="unsupported",
                    message="The approved documentation does not establish an answer.",
                    source="test_fixture" if fixture else result.source,
                    escalation=self.escalation,
                )
            )
        response = SupportResponse(
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
        if snapshot is None:
            return finish(response)
        by_version_id = {version.passage_id: version for version in versions if version}
        return VersionedSupportAnswer(
            response=response,
            manifest_sha256=snapshot.manifest_sha256,
            passages=tuple(by_version_id[key] for key in selection.passage_ids),
        )
