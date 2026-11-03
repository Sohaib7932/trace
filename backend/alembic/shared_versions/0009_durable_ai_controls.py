"""Append-only durable AI usage and shared admission; zero paid budget."""

import sqlalchemy as sa

from alembic import op

revision = "0009_durable_ai_controls"
down_revision = "0008_knowledge_archive"
branch_labels = None
depends_on = None

TABLES = (
    "ai_control_policies",
    "ai_admission_leases",
    "ai_control_reconciliations",
    "ai_provider_attempts",
    "ai_admission_releases",
    "ai_provider_usage",
)


def upgrade() -> None:
    op.create_table(
        "ai_control_policies",
        sa.Column("scope", sa.String(96), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('allowance','admission')", name=op.f("ck_ai_control_policies_kind")
        ),
        sa.PrimaryKeyConstraint("scope", name=op.f("pk_ai_control_policies")),
    )
    op.create_table(
        "ai_admission_leases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(96), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scope"],
            ["ai_control_policies.scope"],
            name=op.f("fk_ai_admission_leases_scope_ai_control_policies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_admission_leases")),
    )
    op.create_index(
        op.f("ix_ai_admission_scope_subject"),
        "ai_admission_leases",
        ["scope", "subject_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_admission_scope_window"),
        "ai_admission_leases",
        ["scope", "window_start"],
        unique=False,
    )
    op.create_table(
        "ai_control_reconciliations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_kind IN ('provider','admission')",
            name=op.f("ck_ai_control_reconciliations_target_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["users.id"],
            name=op.f("fk_ai_control_reconciliations_operator_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_control_reconciliations")),
        sa.UniqueConstraint(
            "target_kind",
            "target_id",
            name=op.f("uq_ai_control_reconciliations_target_kind_target_id"),
        ),
    )
    op.create_table(
        "ai_provider_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(96), nullable=False),
        sa.Column("capability", sa.String(16), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("estimated_input_bytes", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "capability IN ('generation','tutor','support','embedding')",
            name=op.f("ck_ai_provider_attempts_capability"),
        ),
        sa.CheckConstraint(
            "estimated_input_bytes >= 0", name=op.f("ck_ai_provider_attempts_input_bound")
        ),
        sa.CheckConstraint(
            "item_count BETWEEN 1 AND 128", name=op.f("ck_ai_provider_attempts_items")
        ),
        sa.ForeignKeyConstraint(
            ["scope"],
            ["ai_control_policies.scope"],
            name=op.f("fk_ai_provider_attempts_scope_ai_control_policies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_provider_attempts")),
    )
    op.create_index(
        op.f("ix_ai_provider_attempt_scope_subject"),
        "ai_provider_attempts",
        ["scope", "subject_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_provider_attempt_scope_window"),
        "ai_provider_attempts",
        ["scope", "window_start"],
        unique=False,
    )
    op.create_table(
        "ai_admission_releases",
        sa.Column("lease_id", sa.Uuid(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["ai_admission_leases.id"],
            name=op.f("fk_ai_admission_releases_lease_id_ai_admission_leases"),
        ),
        sa.PrimaryKeyConstraint("lease_id", name=op.f("pk_ai_admission_releases")),
    )
    op.create_table(
        "ai_provider_usage",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("provider_duration_ms", sa.Integer(), nullable=True),
        sa.Column("accounted_cost_microusd", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name=op.f("ck_ai_provider_usage_input_tokens"),
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name=op.f("ck_ai_provider_usage_output_tokens"),
        ),
        sa.CheckConstraint(
            "provider_duration_ms IS NULL OR provider_duration_ms >= 0",
            name=op.f("ck_ai_provider_usage_duration"),
        ),
        sa.CheckConstraint(
            "status IN ('success','refusal','truncated','timeout','error','unknown')",
            name=op.f("ck_ai_provider_usage_status"),
        ),
        sa.CheckConstraint(
            "accounted_cost_microusd IS NULL OR accounted_cost_microusd >= 0",
            name=op.f("ck_ai_provider_usage_known_cost"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["ai_provider_attempts.id"],
            name=op.f("fk_ai_provider_usage_attempt_id_ai_provider_attempts"),
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_ai_provider_usage")),
    )
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        schema = connection.dialect.identifier_preparer.quote(
            connection.scalar(sa.text("SELECT current_schema()"))
        )
        op.execute(
            f"CREATE FUNCTION ai_controls_immutable() RETURNS trigger LANGUAGE plpgsql "
            f"SET search_path={schema},pg_catalog AS $guard$ BEGIN "
            "RAISE EXCEPTION 'AI control history is append-only' "
            "USING ERRCODE='23514'; END; $guard$"
        )
    for table in TABLES:
        for event in ("UPDATE", "DELETE"):
            if connection.dialect.name == "sqlite":
                op.execute(
                    f"CREATE TRIGGER immutable_{table}_{event.lower()} BEFORE {event} ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'AI control history is append-only'); END"
                )
            elif connection.dialect.name == "postgresql":
                op.execute(
                    f"CREATE TRIGGER immutable_{table}_{event.lower()} BEFORE {event} ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION ai_controls_immutable()"
                )
            else:
                raise RuntimeError("Unsupported AI control persistence dialect")


def downgrade() -> None:
    connection = op.get_bind()
    if any(connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")) for table in TABLES):
        raise RuntimeError("AI control history exists; downgrade refused to preserve auditability")
    for table in reversed(TABLES):
        op.drop_table(table)
    if connection.dialect.name == "postgresql":
        op.execute("DROP FUNCTION ai_controls_immutable()")
