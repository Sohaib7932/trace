"""Operator-local, read-only status. Never probes AI or prints identities/credentials."""

import json

from sqlalchemy import func, select, text

from app.core.accounting_settings import AccountingSettings
from app.core.ai_settings import AIClientSettings
from app.core.embedding_settings import EmbeddingSettings
from app.core.settings import Settings
from app.db.accounting import SqlAIControls
from app.db.knowledge import SqlKnowledgeRepository
from app.db.knowledge_models import KnowledgeEventRow, KnowledgeIndexRow, KnowledgeReceiptRow
from app.db.migrations import expected_heads
from app.db.session import Database
from app.domain.clock import utc_now
from app.support.database import DatabaseSupportKnowledge


def collect_status(database: Database, accounting: AccountingSettings) -> dict[str, object]:
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
    snapshot = DatabaseSupportKnowledge(SqlKnowledgeRepository(database)).snapshot()
    expiry_seconds = min(
        (
            int((source.valid_until - utc_now()).total_seconds())
            for source in snapshot.sources
            if source.valid_until is not None
        ),
        default=None,
    )
    return {
        "database": "reachable",
        "schema_current": heads == expected_heads(),
        "knowledge": {
            "available": snapshot.available,
            "source_count": len(snapshot.sources),
            "issues": sorted({issue.code for issue in snapshot.issues}),
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


def main() -> int:
    database = None
    try:
        settings = Settings()
        ai, embeddings, accounting = (
            AIClientSettings(_env_file=None),
            EmbeddingSettings(_env_file=None),
            AccountingSettings(_env_file=None),
        )
        database = Database(settings)
        report = collect_status(database, accounting)
        report.update(text_mode=ai.mode, embedding_mode=embeddings.mode)
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
