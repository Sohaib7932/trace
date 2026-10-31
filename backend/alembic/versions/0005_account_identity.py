"""Permanent Trace accounts and exclusive learner ownership; no learning rows rewritten."""

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "0005_account_identity"
down_revision = "0004_transfer_retrieval"
branch_labels = None
depends_on = None

TABLES = (
    "users",
    "auth_subjects",
    "user_roles",
    "role_grant_events",
    "account_learners",
    "account_action_limits",
)
TRIGGERS = {
    "account_owner_exclusive": """BEFORE INSERT ON account_learners WHEN
        EXISTS (SELECT 1 FROM learner_credentials WHERE learner_id=NEW.learner_id
                AND revoked_at IS NULL) OR
        (NEW.claimed_credential_id IS NOT NULL AND NOT EXISTS
          (SELECT 1 FROM learner_credentials WHERE id=NEW.claimed_credential_id
           AND learner_id=NEW.learner_id AND revoked_at IS NOT NULL))
        BEGIN SELECT RAISE(ABORT, 'revoke guest credentials before attaching account'); END""",
    "account_credential_insert": """BEFORE INSERT ON learner_credentials WHEN EXISTS
        (SELECT 1 FROM account_learners WHERE learner_id=NEW.learner_id)
        BEGIN SELECT RAISE(ABORT, 'account learner cannot receive guest credentials'); END""",
    "account_credential_update": """BEFORE UPDATE ON learner_credentials WHEN EXISTS
        (SELECT 1 FROM account_learners WHERE learner_id IN (NEW.learner_id, OLD.learner_id))
        AND (NEW.revoked_at IS NULL OR NEW.learner_id != OLD.learner_id
             OR NEW.token_hash != OLD.token_hash OR NEW.expires_at != OLD.expires_at)
        BEGIN SELECT RAISE(ABORT, 'claimed credentials cannot be reactivated'); END""",
}
for _table in ("account_learners", "role_grant_events", "auth_subjects"):
    TRIGGERS[f"preserve_{_table}"] = (
        f"BEFORE DELETE ON {_table} BEGIN SELECT RAISE(ABORT, 'account history preserved'); END"
    )
    # Auth subject last_seen_at is mutable; identity mapping itself is immutable.
    _when = (
        " WHEN NEW.id != OLD.id OR NEW.issuer != OLD.issuer OR NEW.subject != OLD.subject"
        " OR NEW.user_id != OLD.user_id OR NEW.created_at != OLD.created_at"
        if _table == "auth_subjects"
        else ""
    )
    TRIGGERS[f"immutable_{_table}"] = (
        f"BEFORE UPDATE ON {_table}{_when} "
        "BEGIN SELECT RAISE(ABORT, 'account identity is immutable'); END"
    )


def row_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        *row_columns(),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','disabled')", name="status"),
    )
    op.create_table(
        "auth_subjects",
        *row_columns(),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_index("ix_auth_subjects_user_id", "auth_subjects", ["user_id"])
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role", sa.String(16), primary_key=True),
        sa.CheckConstraint("role IN ('learner','creator','admin')", name="role"),
    )
    op.create_table(
        "role_grant_events",
        *row_columns(),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("operator", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("role IN ('creator','admin')", name="role"),
    )
    op.create_index("ix_role_grant_events_user_id", "role_grant_events", ["user_id"])
    op.create_table(
        "account_learners",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("learner_id", sa.Uuid(), sa.ForeignKey("learners.id"), nullable=False),
        sa.Column("claim_key", sa.String(36)),
        sa.Column("claimed_credential_id", sa.Uuid(), sa.ForeignKey("learner_credentials.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("learner_id"),
        sa.CheckConstraint(
            "(claim_key IS NULL) = (claimed_credential_id IS NULL)", name="claim_receipt"
        ),
    )
    op.create_table(
        "account_action_limits",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("action", sa.String(32), primary_key=True),
        sa.Column("window", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    for name, body in TRIGGERS.items():
        op.execute(f"CREATE TRIGGER {name} {body}")


def downgrade() -> None:
    # Reverting an unused schema is supported. Deleting an account is not a migration.
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM users")):
        raise RuntimeError(
            "Account data exists; downgrade refused to preserve ownership and history."
        )
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    for name in reversed(TABLES):
        op.drop_table(name)
