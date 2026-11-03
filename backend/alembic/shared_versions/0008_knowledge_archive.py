"""Durable immutable customer-document governance; no learner-row changes."""

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "0008_knowledge_archive"
down_revision = "0007_tutor_reservations"
branch_labels = None
depends_on = None

TABLES = (
    "knowledge_sources",
    "knowledge_revisions",
    "knowledge_events",
    "knowledge_manifests",
    "knowledge_publications",
    "knowledge_indexes",
    "knowledge_receipts",
)
ADMIN_TABLES = TABLES[:-1]
TRANSITIONS = """
 (NEW.action='ingest' AND NEW.sequence=0 AND NEW.previous_state IS NULL AND NEW.state='ingested') OR
 (NEW.action='parse' AND NEW.previous_state='ingested' AND NEW.state='parsed') OR
 (NEW.action='normalize' AND NEW.previous_state='parsed' AND NEW.state='normalized') OR
 (NEW.action='chunk' AND NEW.previous_state='normalized' AND NEW.state='chunked') OR
 (NEW.action='index' AND NEW.previous_state='chunked' AND NEW.state='indexed') OR
 (NEW.action='validate' AND NEW.previous_state='indexed' AND NEW.state='validated') OR
 (NEW.action='review' AND NEW.previous_state='validated' AND NEW.state='reviewed') OR
 (NEW.action='approve' AND NEW.previous_state='reviewed' AND NEW.state='approved') OR
 (NEW.action='adopt_existing_review' AND NEW.previous_state='validated' AND NEW.state='approved') OR
 (NEW.action='publish' AND NEW.previous_state='approved' AND NEW.state='published') OR
 (NEW.action='reject' AND NEW.previous_state IN
 ('ingested','parsed','normalized','chunked','indexed','validated','reviewed')
 AND NEW.state='rejected') OR
 (NEW.action='revoke' AND NEW.previous_state IN ('approved','published') AND NEW.state='revoked') OR
 (NEW.action='expire' AND NEW.previous_state IN ('approved','published') AND NEW.state='expired')
"""


def actor_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def payload_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("source_id", sa.String(64), primary_key=True),
        *actor_columns(),
    )
    op.create_table(
        "knowledge_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_id", sa.String(64), sa.ForeignKey("knowledge_sources.source_id"), nullable=False
        ),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.Column("creation_key", sa.Uuid(), nullable=False, unique=True),
        *actor_columns(),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_sha256", sa.String(64), nullable=False),
        *payload_columns(),
        sa.UniqueConstraint("source_id", "revision"),
    )
    op.create_index("ix_knowledge_revisions_source_id", "knowledge_revisions", ["source_id"])
    op.create_table(
        "knowledge_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "revision_id", sa.Uuid(), sa.ForeignKey("knowledge_revisions.id"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.Column("previous_event_sha256", sa.String(64)),
        sa.Column("previous_state", sa.String(32)),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        *actor_columns(),
        *payload_columns(),
        sa.UniqueConstraint("revision_id", "sequence"),
        sa.UniqueConstraint("revision_id", "operation_key"),
        sa.CheckConstraint("sequence >= 0", name="sequence"),
        sa.CheckConstraint(
            "state IN ('ingested','parsed','normalized','chunked','indexed','validated',"
            "'reviewed','approved','published','rejected','revoked','expired')",
            name="state",
        ),
        sa.CheckConstraint(
            "action IN ('ingest','parse','normalize','chunk','index','validate','review',"
            "'approve','adopt_existing_review','publish','reject','revoke','expire')",
            name="action",
        ),
    )
    op.create_index("ix_knowledge_events_revision_id", "knowledge_events", ["revision_id"])
    op.create_table(
        "knowledge_manifests",
        sa.Column("content_sha256", sa.String(64), primary_key=True),
        *actor_columns(),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "knowledge_publications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False, unique=True),
        sa.Column("operation_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "previous_manifest_sha256",
            sa.String(64),
            sa.ForeignKey("knowledge_manifests.content_sha256"),
        ),
        sa.Column(
            "manifest_sha256",
            sa.String(64),
            sa.ForeignKey("knowledge_manifests.content_sha256"),
            nullable=False,
        ),
        *actor_columns(),
        *payload_columns(),
        sa.CheckConstraint("sequence >= 0", name="sequence"),
    )
    op.create_table(
        "knowledge_indexes",
        sa.Column("index_sha256", sa.String(64), primary_key=True),
        sa.Column(
            "manifest_sha256",
            sa.String(64),
            sa.ForeignKey("knowledge_manifests.content_sha256"),
            nullable=False,
        ),
        sa.Column("operation_key", sa.Uuid(), nullable=False, unique=True),
        *actor_columns(),
        sa.Column("embedding_space_sha256", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_indexes_manifest_sha256", "knowledge_indexes", ["manifest_sha256"]
    )
    op.create_table(
        "knowledge_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id_sha256", sa.String(64), nullable=False),
        sa.Column(
            "manifest_sha256",
            sa.String(64),
            sa.ForeignKey("knowledge_manifests.content_sha256"),
            nullable=False,
        ),
        sa.Column("index_sha256", sa.String(64), sa.ForeignKey("knowledge_indexes.index_sha256")),
        *payload_columns(),
    )
    op.create_index(
        "ix_knowledge_receipts_request_id_sha256", "knowledge_receipts", ["request_id_sha256"]
    )
    op.create_index(
        "ix_knowledge_receipts_manifest_sha256", "knowledge_receipts", ["manifest_sha256"]
    )
    _guards(op.get_bind().dialect.name)


def _guards(dialect: str) -> None:
    last_state = (
        "SELECT state FROM knowledge_events WHERE revision_id=NEW.revision_id "
        "ORDER BY sequence DESC LIMIT 1"
    )
    last_hash = (
        "SELECT content_sha256 FROM knowledge_events WHERE revision_id=NEW.revision_id "
        "ORDER BY sequence DESC LIMIT 1"
    )
    last_manifest = (
        "SELECT manifest_sha256 FROM knowledge_publications ORDER BY sequence DESC LIMIT 1"
    )
    operator = "IS NOT" if dialect == "sqlite" else "IS DISTINCT FROM"
    event_chain = f"""
      NEW.sequence != COALESCE((SELECT MAX(sequence)+1 FROM knowledge_events
        WHERE revision_id=NEW.revision_id),0) OR
      NEW.previous_state {operator} ({last_state}) OR
      NEW.previous_event_sha256 {operator} ({last_hash})
    """
    publication_chain = f"""
      NEW.sequence != COALESCE((SELECT MAX(sequence)+1 FROM knowledge_publications),0) OR
      NEW.previous_manifest_sha256 {operator} ({last_manifest})
    """
    if dialect == "sqlite":
        for table in TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER preserve_{table}_{action.lower()} "
                    f"BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'knowledge history preserved'); END"
                )
        for table in ADMIN_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_admin BEFORE INSERT ON {table} WHEN NOT EXISTS "
                "(SELECT 1 FROM users JOIN user_roles ON users.id=user_roles.user_id "
                "WHERE users.id=NEW.actor_id AND users.status='active' "
                "AND user_roles.role='admin') "
                "BEGIN SELECT RAISE(ABORT,'knowledge administration requires active admin'); END"
            )
        op.execute(
            "CREATE TRIGGER knowledge_event_transition BEFORE INSERT ON knowledge_events "
            f"WHEN NOT COALESCE(({TRANSITIONS}),0) "
            "BEGIN SELECT RAISE(ABORT,'invalid knowledge transition'); END"
        )
        op.execute(
            "CREATE TRIGGER knowledge_event_chain BEFORE INSERT ON knowledge_events "
            f"WHEN {event_chain} BEGIN SELECT RAISE(ABORT,'knowledge predecessor mismatch'); END"
        )
        op.execute(
            "CREATE TRIGGER knowledge_publication_chain "
            "BEFORE INSERT ON knowledge_publications "
            f"WHEN {publication_chain} "
            "BEGIN SELECT RAISE(ABORT,'knowledge publication predecessor mismatch'); END"
        )
        return
    if dialect != "postgresql":
        raise RuntimeError("Knowledge archive requires a supported database dialect")
    op.execute("""CREATE FUNCTION knowledge_immutable_guard()
      RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'knowledge history preserved' USING ERRCODE='23514'; END $$""")
    op.execute("""CREATE FUNCTION knowledge_admin_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NOT EXISTS (SELECT 1 FROM users JOIN user_roles ON users.id=user_roles.user_id
      WHERE users.id=NEW.actor_id AND users.status='active' AND user_roles.role='admin') THEN
      RAISE EXCEPTION 'knowledge administration requires active admin' USING ERRCODE='23514';
      END IF; RETURN NEW; END $$""")
    op.execute(f"""CREATE FUNCTION knowledge_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF {event_chain} OR NOT COALESCE(({TRANSITIONS}),FALSE)
      THEN RAISE EXCEPTION 'invalid knowledge predecessor or transition'
      USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
    op.execute(f"""CREATE FUNCTION knowledge_publication_guard()
      RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF {publication_chain}
      THEN RAISE EXCEPTION 'knowledge publication predecessor mismatch'
      USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER preserve_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION knowledge_immutable_guard()"
        )
    for table in ADMIN_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_admin BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION knowledge_admin_guard()"
        )
    op.execute(
        "CREATE TRIGGER knowledge_event_chain BEFORE INSERT ON knowledge_events "
        "FOR EACH ROW EXECUTE FUNCTION knowledge_event_guard()"
    )
    op.execute(
        "CREATE TRIGGER knowledge_publication_chain BEFORE INSERT ON knowledge_publications "
        "FOR EACH ROW EXECUTE FUNCTION knowledge_publication_guard()"
    )


def downgrade() -> None:
    if any(op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {table}")) for table in TABLES):
        raise RuntimeError("Knowledge history exists; downgrade refused to preserve provenance")
    for table in reversed(TABLES):
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        for function in (
            "knowledge_publication_guard",
            "knowledge_event_guard",
            "knowledge_admin_guard",
            "knowledge_immutable_guard",
        ):
            op.execute(f"DROP FUNCTION {function}()")
