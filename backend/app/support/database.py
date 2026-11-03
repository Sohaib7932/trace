"""Current published SQL manifest; historical archives never imply serving permission."""

from datetime import datetime

from app.domain.clock import Clock, as_utc, utc_now
from app.domain.learning import LearningError
from app.repositories.knowledge import KnowledgeRepository, KnowledgeStore
from app.schemas.support import SupportMatch, SupportQuestion
from app.support.archive import ArchivedSupportSnapshot, ArchivedSupportSourceVersion
from app.support.versioning import SupportSnapshotIssue


def archive_snapshot(store: KnowledgeStore, now: datetime) -> ArchivedSupportSnapshot:
    at = as_utc(now)
    publication = store.current_publication()
    if publication is None:
        return ArchivedSupportSnapshot(
            status="unavailable",
            evaluated_at=at,
            issues=(SupportSnapshotIssue(code="missing_review"),),
        )
    manifest = store.manifest(publication.manifest_sha256)
    if manifest is None:
        raise LearningError("conflict", "Published knowledge manifest is missing.")
    sources, issues = [], []
    for revision_id in manifest.revision_ids:
        history = store.history(revision_id)
        if history is None:
            raise LearningError("conflict", "Published knowledge source is missing.")
        approval = history.approval
        source_id = history.revision.source_id
        if history.state in {"revoked", "expired"}:
            issues.append(
                SupportSnapshotIssue(
                    source_id=source_id,
                    code="source_revoked" if history.state == "revoked" else "stale",
                )
            )
        elif (
            history.state not in {"approved", "published"}
            or approval is None
            or history.index_sha256 is None
        ):
            issues.append(SupportSnapshotIssue(source_id=source_id, code="unapproved"))
        elif approval.valid_until is None or approval.valid_until <= at:
            issues.append(SupportSnapshotIssue(source_id=source_id, code="stale"))
        elif approval.created_at > at:
            issues.append(SupportSnapshotIssue(source_id=source_id, code="future_review"))
        else:
            sources.append(
                ArchivedSupportSourceVersion(
                    record=history.revision,
                    approval=approval,
                    passages=history.chunks,
                    lexical_index_sha256=history.index_sha256,
                )
            )
    if issues:
        return ArchivedSupportSnapshot(status="unavailable", evaluated_at=at, issues=tuple(issues))
    return ArchivedSupportSnapshot(
        status="prepared",
        evaluated_at=at,
        publication_sequence=publication.sequence,
        manifest=manifest,
        sources=tuple(sources),
    )


class DatabaseSupportKnowledge:
    def __init__(self, repository: KnowledgeRepository, clock: Clock = utc_now) -> None:
        self.repository, self.clock = repository, clock

    def snapshot(self, *, audience: str = "public_customer") -> ArchivedSupportSnapshot:
        try:
            at = as_utc(self.clock())
            if audience != "public_customer":
                return ArchivedSupportSnapshot(
                    status="unavailable",
                    evaluated_at=at,
                    issues=(SupportSnapshotIssue(code="unsupported_audience"),),
                )
            with self.repository.read() as store:
                return archive_snapshot(store, at)
        except Exception:
            return ArchivedSupportSnapshot(
                status="unavailable",
                evaluated_at=utc_now(),
                issues=(SupportSnapshotIssue(code="package_unavailable"),),
            )

    @property
    def available(self) -> bool:
        return self.snapshot().available

    def retrieve(self, question: SupportQuestion) -> tuple[SupportMatch, ...]:
        return self.snapshot().retrieve(question)
