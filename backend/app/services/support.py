"""Stateless support orchestration with extractive grounding and explicit availability."""

from collections.abc import Callable

from app.ai.support_assistant import SupportAssistant
from app.ai.support_diagnostics import SupportObserver, observe_support
from app.repositories.support_knowledge import ApprovedSupportKnowledge, SupportKnowledge
from app.schemas.support import (
    SupportEscalation,
    SupportMatch,
    SupportQuestion,
    SupportReference,
    SupportResponse,
    SupportSelectionResult,
)
from app.support.contracts import VersionedSupportKnowledge
from app.support.receipts import VersionedSupportAnswer
from app.support.semantic import BoundRetrievalOutcome, SemanticSupportKnowledge


class SupportService:
    def __init__(
        self,
        assistant: SupportAssistant | None = None,
        knowledge: SupportKnowledge | None = None,
        *,
        escalation: SupportEscalation | None = None,
        remaining_seconds: Callable[[], float] | None = None,
        observer: SupportObserver | None = None,
    ) -> None:
        self.assistant = assistant
        self.remaining_seconds = remaining_seconds
        self.observer = observer
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
            outcome: BoundRetrievalOutcome | None = None
            if isinstance(self.knowledge, SemanticSupportKnowledge):
                remaining = self.remaining_seconds() if self.remaining_seconds else None
                if remaining is not None and remaining <= 0:
                    observe_support(self.observer, "retrieval", "deadline_exhausted")
                    return finish(unavailable)
                outcome = self.knowledge.retrieve_with_snapshot(
                    checked, timeout_seconds=remaining, subject=subject
                )
            snapshot = (
                outcome.snapshot
                if outcome is not None
                else (
                    self.knowledge.snapshot()
                    if isinstance(self.knowledge, VersionedSupportKnowledge)
                    else None
                )
            )
            knowledge = snapshot if snapshot is not None else self.knowledge
            if not knowledge.available:
                observe_support(self.observer, "knowledge", "unavailable")
                if snapshot is not None:
                    for issue in getattr(snapshot, "issues", ()):
                        observe_support(self.observer, "knowledge", issue.code)
                return finish(unavailable)
            observe_support(self.observer, "knowledge", "available")
            received = outcome.matches if outcome is not None else knowledge.retrieve(checked)
            if type(received) is not tuple or len(received) > 3:
                observe_support(self.observer, "retrieval", "invalid_matches")
                return finish(unavailable)
            passages = tuple(
                SupportMatch.model_validate(p.model_dump(warnings=False)) for p in received
            )
            if len({passage.passage_id for passage in passages}) != len(passages):
                observe_support(self.observer, "retrieval", "duplicate_passages", len(passages))
                return finish(unavailable)
            versions = tuple(snapshot.resolve(passage) for passage in passages) if snapshot else ()
            if any(version is None for version in versions):
                observe_support(self.observer, "retrieval", "unresolved_version", len(passages))
                return finish(unavailable)
        except Exception:
            observe_support(self.observer, "retrieval", "failed")
            return finish(unavailable)
        if not passages:
            observe_support(self.observer, "retrieval", "no_sources", 0)
            return finish(
                SupportResponse(
                    status="no_sources",
                    message="No relevant approved documentation was found.",
                    source="unavailable",
                    escalation=self.escalation,
                )
            )
        observe_support(self.observer, "retrieval", "ready", len(passages))
        if self.assistant is None:
            observe_support(self.observer, "provider", "missing_assistant", len(passages))
            return finish(unavailable)
        try:
            if self.remaining_seconds is not None and self.remaining_seconds() <= 0:
                observe_support(self.observer, "provider", "deadline_exhausted", len(passages))
                return finish(unavailable)
            result = self.assistant.select(checked, passages, subject=subject)
            if result is None:
                observe_support(self.observer, "provider", "result_unavailable", len(passages))
                return finish(unavailable)
            result = SupportSelectionResult.model_validate(result.model_dump(warnings=False))
        except Exception:
            observe_support(self.observer, "provider", "failed", len(passages))
            return finish(unavailable)
        selection = result.selection
        # Recheck the same source scope after slow provider work. Expired, edited
        # or newly conflicting documentation must not escape as a stale answer.
        try:
            if outcome is not None and isinstance(self.knowledge, SemanticSupportKnowledge):
                if not self.knowledge.revalidate(outcome):
                    observe_support(self.observer, "source_validation", "changed", len(passages))
                    return finish(unavailable)
            elif snapshot is not None and isinstance(self.knowledge, VersionedSupportKnowledge):
                fresh = self.knowledge.snapshot()
                if (
                    not fresh.available
                    or fresh.manifest_sha256 != snapshot.manifest_sha256
                    or tuple(fresh.reconstruct(version) for version in versions if version)
                    != passages
                ):
                    observe_support(self.observer, "source_validation", "changed", len(passages))
                    return finish(unavailable)
            elif not self.knowledge.available or self.knowledge.retrieve(checked) != passages:
                observe_support(self.observer, "source_validation", "changed", len(passages))
                return finish(unavailable)
        except Exception:
            observe_support(self.observer, "source_validation", "failed", len(passages))
            return finish(unavailable)
        observe_support(self.observer, "source_validation", "verified", len(passages))
        by_id = {passage.passage_id: passage for passage in passages}
        if not set(selection.passage_ids) <= by_id.keys():
            observe_support(self.observer, "selection", "invalid_citation", len(passages))
            return finish(unavailable)
        fixture = any(passage.approval == "test_fixture" for passage in passages)
        if selection.status == "unsupported":
            observe_support(self.observer, "selection", "unsupported", len(passages))
            return finish(
                SupportResponse(
                    status="unsupported",
                    message="The approved documentation does not establish an answer.",
                    source="test_fixture" if fixture else result.source,
                    escalation=self.escalation,
                )
            )
        observe_support(self.observer, "selection", "answered", len(passages))
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
            retrieval_profile=outcome.mode
            if outcome is not None and outcome.mode != "unavailable"
            else "lexical",
            index_sha256=outcome.index_sha256 if outcome is not None else None,
        )
