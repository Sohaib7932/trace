"""Learner-requested (custom) lessons: requests, lessons, challenges and answers.

Additive and reversible. Answer keys stay server-side; no prompts or raw model output.

Revision ID: 0010_custom_lessons
Revises: 0009_durable_ai_controls
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_custom_lessons"
down_revision = "0009_durable_ai_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_lesson_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("framework", sa.String(length=40), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("goal", sa.String(length=16), nullable=False),
        sa.Column("lesson_count", sa.Integer(), nullable=False),
        sa.Column("practice_styles", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','generating','ready','failed','cancelled','rejected')",
            name=op.f("ck_custom_lesson_requests_status_values"),
        ),
        sa.CheckConstraint(
            "lesson_count BETWEEN 1 AND 3",
            name=op.f("ck_custom_lesson_requests_lesson_count_range"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["users.id"], name=op.f("fk_custom_lesson_requests_account_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_lesson_requests")),
        sa.UniqueConstraint(
            "account_id",
            "idempotency_key",
            name=op.f("uq_custom_lesson_requests_account_id_idempotency_key"),
        ),
    )
    op.create_index(
        op.f("ix_custom_lesson_requests_account_id"),
        "custom_lesson_requests",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "custom_lessons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["users.id"], name=op.f("fk_custom_lessons_account_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["custom_lesson_requests.id"],
            name=op.f("fk_custom_lessons_request_id_custom_lesson_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_lessons")),
        sa.UniqueConstraint(
            "request_id", "position", name=op.f("uq_custom_lessons_request_id_position")
        ),
    )
    op.create_index(
        op.f("ix_custom_lessons_account_id"), "custom_lessons", ["account_id"], unique=False
    )
    op.create_index(
        op.f("ix_custom_lessons_request_id"), "custom_lessons", ["request_id"], unique=False
    )

    op.create_table(
        "custom_lesson_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("hints", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("verification_mode", sa.String(length=16), nullable=False),
        sa.Column("correct_option", sa.Integer(), nullable=True),
        sa.Column("model_answer", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "verification_mode IN ('answer_key','practice_only')",
            name=op.f("ck_custom_lesson_challenges_verification_values"),
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["custom_lessons.id"],
            name=op.f("fk_custom_lesson_challenges_lesson_id_custom_lessons"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_lesson_challenges")),
        sa.UniqueConstraint(
            "lesson_id", "position", name=op.f("uq_custom_lesson_challenges_lesson_id_position")
        ),
    )
    op.create_index(
        op.f("ix_custom_lesson_challenges_lesson_id"),
        "custom_lesson_challenges",
        ["lesson_id"],
        unique=False,
    )

    op.create_table(
        "custom_lesson_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["users.id"], name=op.f("fk_custom_lesson_answers_account_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["custom_lesson_challenges.id"],
            name=op.f("fk_custom_lesson_answers_challenge_id_custom_lesson_challenges"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_lesson_answers")),
        sa.UniqueConstraint(
            "challenge_id",
            "account_id",
            "idempotency_key",
            name=op.f("uq_custom_lesson_answers_challenge_id_account_id_idempotency_key"),
        ),
    )
    op.create_index(
        op.f("ix_custom_lesson_answers_account_id"),
        "custom_lesson_answers",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_custom_lesson_answers_challenge_id"),
        "custom_lesson_answers",
        ["challenge_id"],
        unique=False,
    )


def downgrade() -> None:
    # Children first; dropping a table also drops its indexes.
    for table in (
        "custom_lesson_answers",
        "custom_lesson_challenges",
        "custom_lessons",
        "custom_lesson_requests",
    ):
        op.drop_table(table)
