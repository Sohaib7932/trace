"""Pure checks and bounded orchestration for the exact existing pilot corpus."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid5

from app.domain.clock import utc_now
from app.domain.knowledge import (
    KnowledgeEvent,
    KnowledgeHistory,
    KnowledgeManifest,
    KnowledgePublication,
    KnowledgeRevision,
    canonical_json,
    sealed,
)
from app.schemas.accounts import AccountResponse
from app.support.knowledge import (
    ReviewedSupportKnowledge,
    SupportCorpusPackage,
    load_corpus_package,
    support_corpus_digest,
)
from app.support.versioning import canonical_digest
from scripts.operator_http import OperatorHTTP, OperatorHTTPError

PACKAGE_SHA256 = "1fa44fda7549fcac866926c07c56c9778deaa8e29955309b1f8bab80c24f5063"
PUBLICATION_REASON = "Explicit initial publication of the exact historically reviewed pilot corpus."
_IMPORT = "/api/v1/admin/knowledge/import-reviewed-corpus"
_PUBLISH = "/api/v1/admin/knowledge/publications"


class CorpusOperatorError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("corpus_integrity_unavailable")


def decode_history(value: object) -> KnowledgeHistory:
    """Decode strict JSON nodes before the domain's tuple conversion boundary."""
    if (
        not isinstance(value, dict)
        or set(value) != {"revision", "events"}
        or not isinstance(value["events"], list)
        or not 1 <= len(value["events"]) <= 512
    ):
        raise CorpusOperatorError
    return KnowledgeHistory(
        revision=KnowledgeRevision.model_validate_json(canonical_json(value["revision"])),
        events=tuple(
            KnowledgeEvent.model_validate_json(canonical_json(event)) for event in value["events"]
        ),
    )


def checked_package(clock: Callable[[], datetime] = utc_now) -> SupportCorpusPackage:
    try:
        package = load_corpus_package()
        if (
            support_corpus_digest(package) != PACKAGE_SHA256
            or package.revoked_source_ids
            or len(package.documents) != 9
            or sum(len(document.passages) for document in package.documents) != 19
            or not ReviewedSupportKnowledge(clock=clock, loader=lambda: package).available
        ):
            raise CorpusOperatorError
        return package
    except Exception:
        raise CorpusOperatorError from None


def plan(clock: Callable[[], datetime] = utc_now) -> dict[str, object]:
    checked_package(clock)
    return {
        "status": "offline_plan",
        "http_requests": 0,
        "source_count": 9,
        "passage_count": 19,
        "package_sha256": PACKAGE_SHA256,
        "initial_publication_only": True,
        "automatic_retries": 0,
        "import_knowledge_calls": 1,
        "publish_knowledge_calls": 2,
    }


def _histories(
    value: object,
    package: SupportCorpusPackage,
    actor: UUID,
    now: datetime,
) -> tuple[KnowledgeHistory, ...]:
    if not isinstance(value, list) or len(value) != 9:
        raise CorpusOperatorError
    try:
        histories = tuple(decode_history(item) for item in value)
        by_source = {history.revision.source_id: history for history in histories}
        if len(by_source) != 9 or set(by_source) != set(package.document_digests):
            raise CorpusOperatorError
        for document in package.documents:
            history = by_source[document.source_id]
            revision, approval = history.revision, history.approval
            review = revision.imported_review
            if (
                history.state not in {"approved", "published"}
                or revision.actor_id != str(actor)
                or revision.revision != package.revision
                or revision.document() != document.document()
                or revision.normalized_sha256 != package.document_digests[document.source_id]
                or len(history.chunks) != len(document.passages)
                or history.index_sha256 is None
                or review is None
                or review.package_sha256 != PACKAGE_SHA256
                or review.package_revision != package.revision
                or review.reviewer_label != package.reviewed_by
                or review.reviewed_at != package.reviewed_at
                or review.valid_until != package.valid_until
                or approval is None
                or approval.action != "adopt_existing_review"
                or approval.actor_id != str(actor)
                or approval.review_origin != "imported_record"
                or approval.historical_reviewer_label != package.reviewed_by
                or approval.historical_reviewed_at != package.reviewed_at
                or approval.valid_until != package.valid_until
                or approval.valid_until <= now
            ):
                raise CorpusOperatorError
        return tuple(by_source[source] for source in sorted(by_source))
    except Exception:
        raise CorpusOperatorError from None


def execute(
    client: OperatorHTTP,
    *,
    operation_id: UUID,
    publish: bool,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, object]:
    """Explicit same-key import, optionally followed by initial-only publication.

    The default knowledge allowance is five requests/minute. This uses one or
    two, not nine additional history reads. A conflict/429/uncertain response
    stops the command. Only a deliberate operator rerun reuses these keys.
    """
    package = checked_package(clock)
    try:
        actor = AccountResponse.model_validate(client.request("GET", "/api/v1/account/me"))
        if actor.status != "active" or "admin" not in actor.roles:
            raise OperatorHTTPError("forbidden")
    except OperatorHTTPError:
        raise
    except Exception:
        raise OperatorHTTPError("invalid_response") from None
    root = uuid5(operation_id, str(actor.user_id) + ":" + PACKAGE_SHA256)
    import_key, publication_key = uuid5(root, "import"), uuid5(root, "initial-publication")
    value = client.request(
        "POST",
        _IMPORT,
        body={"operation_key": str(import_key), "adopt_existing_review": True},
    )
    try:
        histories = _histories(value, package, actor.user_id, clock())
    except CorpusOperatorError:
        raise OperatorHTTPError("invalid_response", outcome_unknown=True) from None
    result: dict[str, object] = {
        "status": "review_adopted",
        "source_count": 9,
        "passage_count": 19,
        "package_sha256": PACKAGE_SHA256,
        "published": False,
        "active_manifest_status": "not_checked",
    }
    if not publish:
        return result
    manifest = sealed(
        KnowledgeManifest,
        revision_ids=tuple(h.revision.id for h in histories),
        revision_sha256=tuple(h.revision.content_sha256 for h in histories),
        approval_sha256=tuple(h.approval.content_sha256 for h in histories if h.approval),
        chunk_ids=tuple(chunk.chunk_id for h in histories for chunk in h.chunks),
        lexical_index_sha256=tuple(h.index_sha256 for h in histories),
    )
    revision_ids = [h.revision.id for h in histories]
    value = client.request(
        "POST",
        _PUBLISH,
        body={
            "revision_ids": revision_ids,
            "expected_sequence": -1,
            "operation_key": str(publication_key),
            "reason": PUBLICATION_REASON,
        },
    )
    try:
        publication = KnowledgePublication.model_validate_json(canonical_json(value))
        expected_command = canonical_digest(
            {
                "revision_ids": sorted(revision_ids),
                "expected_sequence": -1,
                "actor_id": str(actor.user_id),
                "reason": PUBLICATION_REASON,
            }
        )
        if (
            publication.actor_id != str(actor.user_id)
            or publication.sequence != 0
            or publication.previous_manifest_sha256 is not None
            or publication.operation_key != str(publication_key)
            or publication.command_sha256 != expected_command
            or publication.manifest_sha256 != manifest.content_sha256
            or publication.reason != PUBLICATION_REASON
        ):
            raise CorpusOperatorError
    except Exception:
        # A POST may have committed. Never turn an invalid receipt into a retry.
        raise OperatorHTTPError("invalid_response", outcome_unknown=True) from None
    result.update(
        status="initial_publication_receipt_confirmed",
        published=True,
        manifest_sha256=publication.manifest_sha256,
        publication_sequence=publication.sequence,
    )
    return result
