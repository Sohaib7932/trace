"""Transfer runtime and scheduled retrieval, preserving existing learner history."""

import sqlalchemy as sa

from alembic import op

revision = "0004_transfer_retrieval"
down_revision = "0003_constraint_names"
branch_labels = None
depends_on = None

TRIGGERS = {
    "transfer_prerequisite": (
        "BEFORE INSERT ON learning_sessions WHEN\n        (SELECT lesson"
        "_id FROM lesson_versions WHERE id=NEW.lesson_version_id)='fast"
        "api-nested-payload-transfer'\n        AND NOT EXISTS (SELECT 1 "
        "FROM learning_sessions s JOIN lesson_versions v ON v.id=s.less"
        "on_version_id\n          WHERE s.learner_id=NEW.learner_id AND "
        "s.state='completed' AND v.lesson_id='fastapi-payload-mismatch'"
        ")\n        BEGIN SELECT RAISE(ABORT, 'original completion requi"
        "red'); END"
    ),
    "attempt_mapping_scope": """BEFORE INSERT ON attempts WHEN NOT EXISTS
        (SELECT 1 FROM learning_sessions s JOIN lesson_versions v ON v.id=s.lesson_version_id
         WHERE s.id=NEW.session_id AND
          ((v.lesson_id='fastapi-payload-mismatch' AND NEW.field_name IN ('body','content')) OR
           (v.lesson_id='fastapi-nested-payload-transfer' AND NEW.field_name IN ('flat','nested'))))
        BEGIN SELECT RAISE(ABORT, 'mapping does not belong to lesson'); END""",
    "tasks_run_scope": """BEFORE INSERT ON runtime_tasks WHEN NOT EXISTS
        (SELECT 1 FROM verification_runs r JOIN learning_sessions s ON s.id=r.session_id
         JOIN lesson_versions v ON v.id=s.lesson_version_id WHERE r.id=NEW.run_id
         AND r.status='pending' AND v.lesson_id='fastapi-nested-payload-transfer')
        BEGIN SELECT RAISE(ABORT, 'task requires pending transfer run'); END""",
    "notes_run_scope": """BEFORE INSERT ON runtime_notes WHEN NOT EXISTS
        (SELECT 1 FROM verification_runs r JOIN learning_sessions s ON s.id=r.session_id
         JOIN lesson_versions v ON v.id=s.lesson_version_id WHERE r.id=NEW.run_id
         AND r.status='pending' AND v.lesson_id='fastapi-payload-mismatch')
        BEGIN SELECT RAISE(ABORT, 'note requires pending original run'); END""",
    "checkpoint_source": """BEFORE INSERT ON retrieval_checkpoints WHEN NOT EXISTS
        (SELECT 1 FROM learning_sessions s JOIN lesson_versions v ON v.id=s.lesson_version_id
         WHERE s.id=NEW.transfer_session_id AND s.state='completed'
         AND v.lesson_id='fastapi-nested-payload-transfer') OR NEW.completed_at IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'checkpoint requires completed transfer'); END""",
    "checkpoint_completion": """BEFORE UPDATE ON retrieval_checkpoints WHEN
        OLD.completed_at IS NOT NULL OR NEW.completed_at IS NULL OR
        NEW.completed_at < OLD.due_at OR NEW.id != OLD.id OR
        NEW.transfer_session_id != OLD.transfer_session_id OR NEW.ordinal != OLD.ordinal OR
        NEW.question_id != OLD.question_id OR NEW.question_hash != OLD.question_hash OR
        NEW.due_at != OLD.due_at OR NEW.created_at != OLD.created_at OR
        NOT EXISTS (SELECT 1 FROM retrieval_attempts WHERE checkpoint_id=OLD.id AND correct=1)
        BEGIN SELECT RAISE(ABORT, 'checkpoint identity/schedule/completion protected'); END""",
    "preserve_checkpoints": """BEFORE DELETE ON retrieval_checkpoints
        BEGIN SELECT RAISE(ABORT, 'checkpoint history is preserved'); END""",
    "retrieval_attempt_available": """BEFORE INSERT ON retrieval_attempts WHEN NOT EXISTS
        (SELECT 1 FROM retrieval_checkpoints WHERE id=NEW.checkpoint_id AND completed_at IS NULL
         AND due_at<=NEW.created_at)
        BEGIN SELECT RAISE(ABORT, 'checkpoint not available'); END""",
}


def mapping_constraint(values: str) -> None:
    connection = op.get_bind()
    triggers = connection.execute(
        sa.text("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
    ).all()
    for name, _ in triggers:
        connection.exec_driver_sql('DROP TRIGGER "' + name.replace('"', '""') + '"')
    connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    with op.batch_alter_table("attempts", recreate="always") as batch:
        batch.drop_constraint(op.f("ck_attempts_supported_field"), type_="check")
        batch.create_check_constraint(
            op.f("ck_attempts_supported_field"), f"field_name IN ({values})"
        )
    for _, sql in triggers:
        connection.exec_driver_sql(sql)
    if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("Transfer migration failed foreign-key integrity check")
    connection.exec_driver_sql("PRAGMA defer_foreign_keys=OFF")


def upgrade() -> None:
    mapping_constraint("'body','content','flat','nested'")
    op.create_table(
        "runtime_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("verification_runs.id"), nullable=False, unique=True
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.CheckConstraint("priority IN ('low','normal','high')", name="priority"),
    )
    op.create_table(
        "retrieval_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "transfer_session_id", sa.Uuid(), sa.ForeignKey("learning_sessions.id"), nullable=False
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("question_hash", sa.String(64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("transfer_session_id", "ordinal"),
        sa.CheckConstraint("ordinal IN (1,2)", name="ordinal"),
    )
    op.create_index(
        "ix_retrieval_checkpoints_transfer_session_id",
        "retrieval_checkpoints",
        ["transfer_session_id"],
    )
    op.create_table(
        "retrieval_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "checkpoint_id", sa.Uuid(), sa.ForeignKey("retrieval_checkpoints.id"), nullable=False
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("selection", sa.String(1), nullable=False),
        sa.Column("reasoning", sa.String(2000), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.String(2000), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.UniqueConstraint("checkpoint_id", "number"),
        sa.UniqueConstraint("checkpoint_id", "idempotency_key"),
        sa.CheckConstraint("number > 0", name="positive_number"),
        sa.CheckConstraint("selection IN ('a','b','c')", name="selection"),
    )
    op.create_index("ix_retrieval_attempts_checkpoint_id", "retrieval_attempts", ["checkpoint_id"])
    for name, definition in TRIGGERS.items():
        op.execute(f"CREATE TRIGGER {name} {definition}")
    for table in ("runtime_tasks", "retrieval_attempts"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER immutable_{table}_{operation.lower()} "
                f"BEFORE {operation} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only record'); END"
            )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM learning_sessions s JOIN lesson_versions "
            "v ON v.id=s.lesson_version_id WHERE v.lesson_id='fastapi-neste"
            "d-payload-transfer'"
        )
    ).scalar():
        raise RuntimeError(
            "Downgrade would discard transfer history; export/archive deliberately first"
        )
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    for table in ("runtime_tasks", "retrieval_attempts"):
        for operation in ("update", "delete"):
            op.execute(f"DROP TRIGGER immutable_{table}_{operation}")
    op.drop_table("retrieval_attempts")
    op.drop_table("retrieval_checkpoints")
    op.drop_table("runtime_tasks")
    mapping_constraint("'body','content'")
