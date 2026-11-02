"""A single server-owned corpus file, rechecked for review, digest and expiry on use."""

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.ai.json_output import strict_json_object
from app.domain.clock import Clock, utc_now
from app.domain.lesson_spec.fields import Digest, Items, LocalId, Value, Version
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.schemas.support import SupportDocument, SupportMatch, SupportPassage, SupportQuestion
from app.schemas.support_readiness import SupportSourceReview
from app.services.support_readiness import prepare_support_knowledge

CORPUS_FILE = Path(__file__).with_name("corpus.json")


class CorpusDocument(Value):
    source_id: LocalId
    title: str = Field(min_length=1, max_length=120)
    passages: Items[SupportPassage] = Field(min_length=1, max_length=8, repr=False)

    def document(self) -> SupportDocument:
        return SupportDocument(
            source_id=self.source_id,
            title=self.title,
            approval="approved_customer_safe",
            passages=self.passages,
        )


class SupportCorpusPackage(Value):
    schema_version: Literal["support-corpus-v1"]
    revision: Version
    review_status: Literal["draft", "approved"]
    reviewed_by: LocalId | None
    reviewed_at: AwareDatetime | None
    valid_until: AwareDatetime | None
    document_digests: dict[LocalId, Digest] = Field(max_length=32)
    documents: Items[CorpusDocument] = Field(min_length=1, max_length=32, repr=False)

    @model_validator(mode="after")
    def review_integrity(self) -> "SupportCorpusPackage":
        ids = [item.source_id for item in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("Corpus source identifiers must be unique")
        # Validate public-copy bounds and passage uniqueness even before approval.
        ApprovedSupportKnowledge(tuple(item.document() for item in self.documents))
        if self.review_status == "approved" and (
            self.reviewed_by is None
            or self.reviewed_at is None
            or self.valid_until is None
            or self.valid_until <= self.reviewed_at
            or set(self.document_digests) != set(ids)
        ):
            raise ValueError("Approved corpus requires explicit complete review metadata")
        return self


def load_corpus_package() -> SupportCorpusPackage:
    # There is no request-selected path, directory discovery or model-chosen file.
    if CORPUS_FILE.stat().st_size > 131072:
        raise ValueError("Support corpus exceeds its file limit")
    raw = CORPUS_FILE.read_text(encoding="utf-8")
    strict_json_object(raw, max_bytes=131072)
    return SupportCorpusPackage.model_validate_json(raw)


class ReviewedSupportKnowledge:
    def __init__(
        self,
        *,
        clock: Clock = utc_now,
        loader: Callable[[], SupportCorpusPackage] = load_corpus_package,
    ) -> None:
        self.clock, self.loader = clock, loader

    def _prepare(self) -> ApprovedSupportKnowledge:
        try:
            package = SupportCorpusPackage.model_validate(self.loader().model_dump(warnings=False))
            if package.review_status != "approved":
                return ApprovedSupportKnowledge()
            documents = tuple(item.document() for item in package.documents)
            reviews = tuple(
                SupportSourceReview(
                    source_id=item.source_id,
                    revision=package.revision,
                    document_sha256=package.document_digests[item.source_id],
                    review_status="approved",
                    reviewed_at=package.reviewed_at,
                    valid_until=package.valid_until,
                )
                for item in documents
            )
            report, knowledge = prepare_support_knowledge(documents, reviews, now=self.clock())
            # The deployed package is one reviewed revision; a partial or changed
            # corpus fails closed instead of silently changing approved source scope.
            return knowledge if not report.issues else ApprovedSupportKnowledge()
        except Exception:
            return ApprovedSupportKnowledge()

    @property
    def available(self) -> bool:
        return self._prepare().available

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]:
        return self._prepare().retrieve(question)
