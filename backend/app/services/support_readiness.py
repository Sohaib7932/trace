"""Prepare explicit support inputs without loading files or activating a corpus.

Freshness is an owner-supplied expiration, not an inferred TTL. Conflicts are
explicit review flags, not semantic contradiction detection. This inactive helper
does not replace human source review or wire knowledge into application resources.
"""

import hashlib
import json
from datetime import datetime

from app.domain.clock import as_utc
from app.repositories.support_knowledge import ApprovedSupportKnowledge
from app.schemas.support import SupportDocument
from app.schemas.support_readiness import (
    ReadinessCode,
    SupportReadinessIssue,
    SupportReadinessReport,
    SupportSourceReview,
)


def support_document_digest(document: SupportDocument) -> str:
    checked = SupportDocument.model_validate(document.model_dump(warnings=False))
    return hashlib.sha256(
        json.dumps(
            checked.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def prepare_support_knowledge(
    documents: tuple[SupportDocument, ...] = (),
    reviews: tuple[SupportSourceReview, ...] = (),
    *,
    now: datetime,
    allow_test_fixtures: bool = False,
) -> tuple[SupportReadinessReport, ApprovedSupportKnowledge]:
    """Return filtered inputs and diagnostics; application activation is separate.

    The trusted caller supplies typed documents/reviews and an explicit aware
    server timestamp. No client path, document selection or arbitrary filesystem
    source is accepted. Unknown/missing review or freshness information excludes
    the document. Unaffected explicitly reviewed documents may still be prepared.
    """
    if (
        type(documents) is not tuple
        or type(reviews) is not tuple
        or len(documents) > 32
        or len(reviews) > 32
        or type(allow_test_fixtures) is not bool
    ):
        raise ValueError("Use bounded explicit support document and review tuples")
    if any(not isinstance(document, SupportDocument) for document in documents) or any(
        not isinstance(review, SupportSourceReview) for review in reviews
    ):
        raise ValueError("Use typed support documents and explicit review metadata")
    at = as_utc(now)
    checked_documents = tuple(
        SupportDocument.model_validate(document.model_dump(warnings=False))
        for document in documents
    )
    checked_reviews = tuple(
        SupportSourceReview.model_validate(review.model_dump(warnings=False)) for review in reviews
    )
    by_id = {document.source_id: document for document in checked_documents}
    by_review = {review.source_id: review for review in checked_reviews}
    if len(by_id) != len(checked_documents) or len(by_review) != len(checked_reviews):
        raise ValueError("Support document and review identifiers must be unique")
    # Validate global source/passage integrity even for excluded review inputs.
    ApprovedSupportKnowledge(checked_documents, allow_test_fixtures=True)
    issues: list[SupportReadinessIssue] = [
        SupportReadinessIssue(source_id=source_id, code="missing_document")
        for source_id in sorted(by_review.keys() - by_id.keys())
    ]
    eligible: list[SupportDocument] = []
    for source_id in sorted(by_id):
        document, review = by_id[source_id], by_review.get(source_id)
        code: ReadinessCode | None = None
        if review is None:
            code = "missing_review"
        elif review.review_status == "draft":
            code = "draft"
        elif review.review_status != "approved":
            code = "unapproved"
        elif document.approval == "test_fixture" and not allow_test_fixtures:
            code = "fixture_not_enabled"
        elif review.document_sha256 != support_document_digest(document):
            code = "content_mismatch"
        elif review.declared_conflict:
            code = "declared_conflict"
        elif review.reviewed_at is None or review.valid_until is None:
            code = "missing_freshness"
        elif review.reviewed_at > at:
            code = "future_review"
        elif review.valid_until <= review.reviewed_at:
            code = "invalid_review_window"
        elif review.valid_until <= at:
            code = "stale"
        if code is not None:
            issues.append(SupportReadinessIssue(source_id=source_id, code=code))
        else:
            eligible.append(document)
    prepared = tuple(eligible)
    return SupportReadinessReport(
        status="prepared" if prepared else "unavailable",
        evaluated_at=at,
        prepared_source_ids=tuple(document.source_id for document in prepared),
        issues=tuple(issues),
        fixture_mode=allow_test_fixtures,
    ), ApprovedSupportKnowledge(prepared, allow_test_fixtures=allow_test_fixtures)
