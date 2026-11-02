"""Durable tutoring reservations; existing guidance records remain append-only."""

import sqlalchemy as sa

from alembic import op

revision = "0007_tutor_reservations"
down_revision = "0006_candidate_lifecycle"
branch_labels = None
depends_on = None

GUARDS = {
    "hint_operation_identity": """BEFORE UPDATE ON hint_operations WHEN
        NEW.id IS NOT OLD.id OR NEW.session_id IS NOT OLD.session_id OR
        NEW.attempt_id IS NOT OLD.attempt_id OR NEW.sequence IS NOT OLD.sequence OR
        NEW.idempotency_key IS NOT OLD.idempotency_key OR
        NEW.created_at IS NOT OLD.created_at OR NEW.deadline_at IS NOT OLD.deadline_at OR
        OLD.status != 'pending' OR NEW.status != 'finalized' OR NEW.completed_at IS NULL
        BEGIN SELECT RAISE(ABORT, 'hint operation is immutable'); END""",
    "hint_operation_preserve": """BEFORE DELETE ON hint_operations
        BEGIN SELECT RAISE(ABORT, 'hint request history is preserved'); END""",
    "hint_operation_sequence": """BEFORE INSERT ON hint_operations WHEN
        NEW.status != 'pending' OR NEW.completed_at IS NOT NULL OR
        NEW.sequence != COALESCE((SELECT MAX(sequence) FROM (
          SELECT sequence FROM tutor_interactions WHERE session_id=NEW.session_id
          UNION ALL SELECT sequence FROM hint_operations WHERE session_id=NEW.session_id
        )), 0) + 1 OR EXISTS (
          SELECT 1 FROM tutor_interactions WHERE session_id=NEW.session_id
          AND idempotency_key=NEW.idempotency_key)
        BEGIN SELECT RAISE(ABORT, 'hint operation must reserve the next request'); END""",
    "hint_operation_result": """BEFORE UPDATE OF status ON hint_operations WHEN NOT EXISTS (
        SELECT 1 FROM tutor_interactions WHERE id=NEW.id AND session_id=NEW.session_id
        AND attempt_id IS NEW.attempt_id AND sequence=NEW.sequence
        AND idempotency_key=NEW.idempotency_key AND created_at=NEW.completed_at)
        BEGIN SELECT RAISE(ABORT, 'hint finalization requires matching result'); END""",
    "hint_result_reservation": """BEFORE INSERT ON tutor_interactions WHEN EXISTS (
        SELECT 1 FROM hint_operations WHERE id=NEW.id OR
        (session_id=NEW.session_id AND
          (sequence=NEW.sequence OR idempotency_key=NEW.idempotency_key)))
        AND NOT EXISTS (
        SELECT 1 FROM hint_operations WHERE id=NEW.id AND status='pending'
        AND session_id=NEW.session_id AND attempt_id IS NEW.attempt_id
        AND sequence=NEW.sequence AND idempotency_key=NEW.idempotency_key)
        BEGIN SELECT RAISE(ABORT, 'hint result must match its pending reservation'); END""",
}


def upgrade() -> None:
    op.create_table(
        "hint_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hint_operations")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            name=op.f("fk_hint_operations_session_id_learning_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "session_id"],
            ["attempts.id", "attempts.session_id"],
            name=op.f("fk_hint_operations_attempt_id_attempts"),
        ),
        sa.UniqueConstraint(
            "session_id", "sequence", name=op.f("uq_hint_operations_session_id_sequence")
        ),
        sa.UniqueConstraint(
            "session_id",
            "idempotency_key",
            name=op.f("uq_hint_operations_session_id_idempotency_key"),
        ),
        sa.CheckConstraint("sequence BETWEEN 1 AND 3", name=op.f("ck_hint_operations_hint_limit")),
        sa.CheckConstraint(
            "status IN ('pending','finalized')", name=op.f("ck_hint_operations_status")
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (completed_at IS NULL)",
            name=op.f("ck_hint_operations_completion_time"),
        ),
        sa.CheckConstraint("deadline_at > created_at", name=op.f("ck_hint_operations_deadline")),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name=op.f("ck_hint_operations_completed_after_request"),
        ),
    )
    op.create_index(op.f("ix_hint_operations_session_id"), "hint_operations", ["session_id"])
    op.create_index(
        "uq_hint_operations_pending_session",
        "hint_operations",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
    )
    for name, body in GUARDS.items():
        op.execute(f"CREATE TRIGGER {name} {body}")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM hint_operations")).scalar_one():
        raise RuntimeError("Cannot downgrade while tutoring reservation history exists")
    for name in GUARDS:
        op.execute(f"DROP TRIGGER {name}")
    op.drop_table("hint_operations")
