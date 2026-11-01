"""Explicitly approved support-copy retrieval. No filesystem ingestion or DB access."""

import re
from typing import Protocol

from app.schemas.support import SupportDocument, SupportMatch, SupportQuestion

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "can",
        "do",
        "does",
        "for",
        "how",
        "i",
        "is",
        "it",
        "my",
        "of",
        "on",
        "the",
        "to",
        "what",
        "with",
    }
)


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{2,}", value.lower())) - _STOP_WORDS


class SupportKnowledge(Protocol):
    @property
    def available(self) -> bool: ...

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]: ...


class ApprovedSupportKnowledge:
    """Bounded lexical retrieval over an injected allowlist, empty by default.

    Callers must approve customer-safe copy before constructing documents. Text
    guards are supplementary; they cannot turn arbitrary repository files into
    reviewed product documentation. Test sources require explicit fixture mode.
    """

    def __init__(
        self, documents: tuple[SupportDocument, ...] = (), *, allow_test_fixtures: bool = False
    ) -> None:
        if type(documents) is not tuple or len(documents) > 32:
            raise ValueError("Use at most 32 explicitly approved support documents")
        if any(not isinstance(doc, SupportDocument) for doc in documents):
            raise ValueError("Use explicitly approved typed support documents")
        checked = tuple(
            SupportDocument.model_validate(doc.model_dump(warnings=False)) for doc in documents
        )
        self._documents = tuple(
            doc
            for doc in checked
            if doc.approval == "approved_customer_safe" or allow_test_fixtures
        )
        source_ids = [doc.source_id for doc in self._documents]
        passage_ids = [passage.passage_id for doc in self._documents for passage in doc.passages]
        if len(source_ids) != len(set(source_ids)) or len(passage_ids) != len(set(passage_ids)):
            raise ValueError("Support source and passage identifiers must be globally unique")

    @property
    def available(self) -> bool:
        return bool(self._documents)

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]:
        checked = SupportQuestion.model_validate(question.model_dump(warnings=False))
        words = _words(checked.question)
        ranked = []
        for document in self._documents:
            for passage in document.passages:
                score = len(words & _words(document.title + " " + passage.text))
                if score:
                    ranked.append((score, document, passage))
        ranked.sort(key=lambda entry: (-entry[0], entry[1].source_id, entry[2].passage_id))
        return tuple(
            SupportMatch(
                source_id=document.source_id,
                title=document.title,
                passage_id=passage.passage_id,
                text=passage.text,
                approval=document.approval,
            )
            for _, document, passage in ranked[:3]
        )
