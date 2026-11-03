"""A single server-owned corpus file, rechecked for review, digest and expiry on use."""

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.ai.json_output import strict_json_object
from app.domain.clock import Clock, as_utc, utc_now
from app.domain.lesson_spec.fields import Digest, Items, LocalId, Value, Version
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.schemas.support import SupportDocument, SupportMatch, SupportPassage, SupportQuestion
from app.schemas.support_readiness import SupportSourceReview
from app.services.support_readiness import prepare_support_knowledge
from app.support.versioning import (
    SupportKnowledgeSnapshot,
    SupportSnapshotIssue,
    canonical_digest,
    version_source,
)

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
    # Operator-owned removal fence, never selected by a question or model.
    # Revocation only removes eligibility and does not renew a review window.
    revoked_source_ids: Items[LocalId] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def review_integrity(self) -> "SupportCorpusPackage":
        ids = [item.source_id for item in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("Corpus source identifiers must be unique")
        if len(self.revoked_source_ids) != len(set(self.revoked_source_ids)) or not set(
            self.revoked_source_ids
        ).issubset(ids):
            raise ValueError("Revocations must name unique sources in this corpus")
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


def support_corpus_digest(package: SupportCorpusPackage) -> str:
    """Preserve the original reviewed-package digest independently of defaults.

    This is the explicit authored v1 content/review identity, not eligibility.
    Revocations must also be checked; they never silently renew source approval.
    """
    checked = SupportCorpusPackage.model_validate(package.model_dump(warnings=False))
    return canonical_digest(
        checked.model_dump(
            mode="json",
            include={
                "schema_version",
                "revision",
                "review_status",
                "reviewed_by",
                "reviewed_at",
                "valid_until",
                "document_digests",
                "documents",
            },
        )
    )


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

    def snapshot(self, *, audience: str = "public_customer") -> SupportKnowledgeSnapshot:
        """Read one immutable current manifest without changing public response schemas."""
        try:
            at = as_utc(self.clock())
        except Exception:
            return SupportKnowledgeSnapshot(
                status="unavailable",
                evaluated_at=utc_now(),
                issues=(SupportSnapshotIssue(code="package_unavailable"),),
            )
        if audience != "public_customer":
            return SupportKnowledgeSnapshot(
                status="unavailable",
                evaluated_at=at,
                issues=(SupportSnapshotIssue(code="unsupported_audience"),),
            )
        try:
            package = SupportCorpusPackage.model_validate(self.loader().model_dump(warnings=False))
            if package.review_status != "approved":
                return SupportKnowledgeSnapshot(
                    status="unavailable",
                    evaluated_at=at,
                    package_revision=package.revision,
                    issues=(SupportSnapshotIssue(code="draft"),),
                )
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
            report, _ = prepare_support_knowledge(documents, reviews, now=at)
            issues = tuple(
                SupportSnapshotIssue(code=issue.code, source_id=issue.source_id)
                for issue in report.issues
            ) + tuple(
                SupportSnapshotIssue(code="source_revoked", source_id=source_id)
                for source_id in sorted(package.revoked_source_ids)
            )
            # The deployed package is one reviewed revision; a partial or changed
            # corpus fails closed instead of silently changing approved source scope.
            if issues:
                return SupportKnowledgeSnapshot(
                    status="unavailable",
                    evaluated_at=at,
                    package_revision=package.revision,
                    issues=issues,
                )
            if (
                package.reviewed_by is None
                or package.reviewed_at is None
                or package.valid_until is None
            ):
                raise ValueError("Approved source review metadata must be complete")
            sources = tuple(
                version_source(
                    document,
                    revision=package.revision,
                    reviewed_by=package.reviewed_by,
                    reviewed_at=package.reviewed_at,
                    valid_until=package.valid_until,
                )
                for document in sorted(documents, key=lambda document: document.source_id)
            )
            manifest = {
                "schema_version": "support-knowledge-snapshot-v1",
                "package_revision": package.revision,
                "sources": [source.model_dump(mode="json") for source in sources],
            }
            return SupportKnowledgeSnapshot(
                status="prepared",
                evaluated_at=at,
                package_revision=package.revision,
                manifest_sha256=canonical_digest(manifest),
                sources=sources,
            )
        except (ValueError, TypeError, AttributeError):
            return SupportKnowledgeSnapshot(
                status="unavailable",
                evaluated_at=at,
                issues=(SupportSnapshotIssue(code="invalid_package"),),
            )
        except Exception:
            return SupportKnowledgeSnapshot(
                status="unavailable",
                evaluated_at=at,
                issues=(SupportSnapshotIssue(code="package_unavailable"),),
            )

    @property
    def available(self) -> bool:
        return self.snapshot().available

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]:
        return self.snapshot().retrieve(question)
