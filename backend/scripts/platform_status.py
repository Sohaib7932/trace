"""Operator-local, read-only status. Never probes AI or prints identities/credentials."""

import json
from collections.abc import Sequence
from contextlib import nullcontext

from sqlalchemy import and_, func, select, text

from app.core.accounting_settings import AccountingSettings
from app.core.ai_activation import SafeArgumentParser, activated_gemini_environment
from app.core.ai_settings import AIClientSettings
from app.core.embedding_settings import EmbeddingSettings
from app.core.settings import Settings
from app.db.accounting import SqlAIControls
from app.db.knowledge import SqlKnowledgeRepository
from app.db.knowledge_models import (
    KnowledgeEventRow,
    KnowledgeIndexRow,
    KnowledgePublicationRow,
    KnowledgeReceiptRow,
    KnowledgeRevisionRow,
    KnowledgeSourceRow,
)
from app.db.migrations import expected_heads
from app.db.session import Database
from app.domain.clock import Clock, utc_now
from app.support.archive import ArchivedSupportSnapshot
from app.support.database import DatabaseSupportKnowledge
from app.support.knowledge import ReviewedSupportKnowledge
from app.support.versioning import SupportKnowledgeSnapshot


def snapshot_status(
    snapshot: ArchivedSupportSnapshot | SupportKnowledgeSnapshot,
) -> dict[str, object]:
    """Only validated aggregate eligibility; unavailable does not prove corrupt digests."""
    return {
        "available": snapshot.available,
        "source_count": len(snapshot.sources),
        "passage_count": sum(len(source.passages) for source in snapshot.sources),
        "issues": sorted({issue.code for issue in snapshot.issues}),
        "digests_valid": True if snapshot.available else None,
    }


def collect_status(
    database: Database,
    accounting: AccountingSettings,
    *,
    settings: Settings | None = None,
    ai: AIClientSettings | None = None,
    clock: Clock = utc_now,
) -> dict[str, object]:
    with database.consistent_read() as session:
        heads = frozenset(
            session.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
        session.execute(text("SELECT 1"))
        events: dict[str, int] = {
            state: count
            for state, count in session.execute(
                select(KnowledgeEventRow.state, func.count()).group_by(KnowledgeEventRow.state)
            )
        }
        indexes = session.scalar(select(func.count()).select_from(KnowledgeIndexRow)) or 0
        receipts = session.scalar(select(func.count()).select_from(KnowledgeReceiptRow)) or 0
        revisions = session.scalar(select(func.count()).select_from(KnowledgeRevisionRow)) or 0
        sources = session.scalar(select(func.count()).select_from(KnowledgeSourceRow)) or 0
        publications = (
            session.scalar(select(func.count()).select_from(KnowledgePublicationRow)) or 0
        )
        latest = (
            select(
                KnowledgeEventRow.revision_id,
                func.max(KnowledgeEventRow.sequence).label("sequence"),
            )
            .group_by(KnowledgeEventRow.revision_id)
            .subquery()
        )
        states = {
            state: count
            for state, count in session.execute(
                select(KnowledgeEventRow.state, func.count())
                .join(
                    latest,
                    and_(
                        KnowledgeEventRow.revision_id == latest.c.revision_id,
                        KnowledgeEventRow.sequence == latest.c.sequence,
                    ),
                )
                .group_by(KnowledgeEventRow.state)
            )
        }
    snapshot = DatabaseSupportKnowledge(SqlKnowledgeRepository(database), clock).snapshot()
    environment = settings.environment if settings is not None else "development"
    mode = ai.mode if ai is not None else "disabled"
    if environment == "production" or accounting.mode == "durable":
        configured_backend = "database_archive"
        configured_support = snapshot_status(snapshot)
    elif mode == "gemini_free":
        configured_backend = "reviewed_package"
        configured_support = snapshot_status(ReviewedSupportKnowledge(clock=clock).snapshot())
    else:
        configured_backend = "empty"
        configured_support = {
            "available": False,
            "source_count": 0,
            "passage_count": 0,
            "issues": ["ai_mode_not_enabled"],
            "digests_valid": None,
        }
    expiry_seconds = min(
        (
            int((source.valid_until - clock()).total_seconds())
            for source in snapshot.sources
            if source.valid_until is not None
        ),
        default=None,
    )
    return {
        "database": "reachable",
        "schema_current": heads == expected_heads(),
        "configuration_scope": "current_cli_process",
        "running_application_configuration": "unknown",
        "configured_knowledge_backend": configured_backend,
        "configured_support": configured_support,
        "knowledge": {
            "backend": "database_archive",
            **snapshot_status(snapshot),
            "archived_source_count": sources,
            "revision_count": revisions,
            "current_revision_states": states,
            "publication_count": publications,
            "revocation_events": events.get("revoked", 0),
            "expiration_events": events.get("expired", 0),
            "nearest_expiry_seconds": expiry_seconds,
            "expires_within_24h": expiry_seconds is not None and expiry_seconds <= 86400,
            "archived_embedding_indexes": indexes,
            "release_receipts": receipts,
        },
        "accounting_mode": accounting.mode,
        "usage": SqlAIControls(database).summary(accounting.scope)
        if accounting.mode == "durable" and accounting.scope is not None
        else None,
        "provider_availability": "not_probed",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument(
        "--gemini-profile",
        action="store_true",
        help="Inspect the approved launcher profile locally; no server or provider request.",
    )
    parser.add_argument("--confirm-free-tier-project", action="store_true")
    args = parser.parse_args(argv)
    if args.confirm_free_tier_project and not args.gemini_profile:
        parser.error("Free-tier confirmation requires the explicit Gemini profile.")
    database = None
    try:
        context = (
            activated_gemini_environment(confirm_free_tier_project=args.confirm_free_tier_project)
            if args.gemini_profile
            else nullcontext()
        )
        with context:
            settings = Settings()
            ai, embeddings, accounting = (
                AIClientSettings(_env_file=None),
                EmbeddingSettings(_env_file=None),
                AccountingSettings(_env_file=None),
            )
            database = Database(settings)
            report = collect_status(database, accounting, settings=settings, ai=ai)
            report.update(
                text_mode=ai.mode,
                embedding_mode=embeddings.mode,
                configuration_profile="approved_gemini_launcher"
                if args.gemini_profile
                else "ambient_cli",
            )
            print(json.dumps(report, sort_keys=True))
            return 0
    except Exception:
        print(json.dumps({"status": "unavailable", "error_code": "operator_status_unavailable"}))
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
