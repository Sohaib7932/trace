"""Immutable candidate snapshots and review events, separate from learner history."""

import sqlalchemy as sa

from alembic import op

revision = "0006_candidate_lifecycle"
down_revision = "0005_account_identity"
branch_labels = None
depends_on = None

STATES = (
    "'composed','validated','validation_unavailable','human_reviewed',"
    "'production_approved','rejected'"
)
TRIGGERS = {
    "candidate_event_chain": """BEFORE INSERT ON candidate_lifecycle_events WHEN
      NEW.revision != COALESCE((SELECT MAX(revision)+1 FROM candidate_lifecycle_events
        WHERE candidate_id=NEW.candidate_id),0) OR
      NEW.previous_state IS NOT (SELECT state FROM candidate_lifecycle_events
        WHERE candidate_id=NEW.candidate_id ORDER BY revision DESC LIMIT 1)
      BEGIN SELECT RAISE(ABORT,'candidate revision or predecessor mismatch'); END""",
    "candidate_event_transition": """BEFORE INSERT ON candidate_lifecycle_events WHEN NOT COALESCE((
      (NEW.action='created' AND NEW.revision=0 AND NEW.previous_state IS NULL
        AND NEW.state='composed') OR
      (NEW.action='validation' AND NEW.previous_state IN ('composed','validation_unavailable')
        AND NEW.state IN ('validated','validation_unavailable','rejected')) OR
      (NEW.action='human_review' AND NEW.previous_state='validated'
        AND NEW.state='human_reviewed') OR
      (NEW.action='production_approval' AND NEW.previous_state='human_reviewed'
        AND NEW.state='production_approved') OR
      (NEW.action='reject' AND NEW.previous_state IN ('validated','human_reviewed')
        AND NEW.state='rejected')),0)
      BEGIN SELECT RAISE(ABORT,'invalid candidate state transition'); END""",
    "candidate_event_admin": """BEFORE INSERT ON candidate_lifecycle_events WHEN
      NEW.action IN ('human_review','production_approval','reject') AND NOT EXISTS (
        SELECT 1 FROM users JOIN user_roles ON users.id=user_roles.user_id
        WHERE users.id=NEW.actor_id AND users.status='active' AND user_roles.role='admin')
      BEGIN SELECT RAISE(ABORT,'candidate review requires active admin'); END""",
}
for _table in ("generated_candidates", "candidate_lifecycle_events"):
    for _operation in ("UPDATE", "DELETE"):
        TRIGGERS[f"preserve_{_table}_{_operation.lower()}"] = (
            f"BEFORE {_operation} ON {_table} "
            "BEGIN SELECT RAISE(ABORT,'candidate history preserved'); END"
        )


def upgrade() -> None:
    op.create_table(
        "generated_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("generation_request_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("creation_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("composition_sha256", sa.String(64), nullable=False),
        sa.Column("release_eligible", sa.Boolean(), nullable=False),
        sa.CheckConstraint("release_eligible = 0", name="unreleased"),
    )
    op.create_table(
        "candidate_lifecycle_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id", sa.Uuid(), sa.ForeignKey("generated_candidates.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("previous_state", sa.String(32)),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("release_eligible", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("candidate_id", "revision"),
        sa.UniqueConstraint("candidate_id", "operation_key"),
        sa.CheckConstraint("revision >= 0", name="revision"),
        sa.CheckConstraint("release_eligible = 0", name="unreleased"),
        sa.CheckConstraint(f"state IN ({STATES})", name="state"),
        sa.CheckConstraint(
            "action IN ('created','validation','human_review','production_approval','reject')",
            name="action",
        ),
    )
    op.create_index(
        "ix_candidate_lifecycle_events_candidate_id", "candidate_lifecycle_events", ["candidate_id"]
    )
    for name, body in TRIGGERS.items():
        op.execute(f"CREATE TRIGGER {name} {body}")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM generated_candidates")) or (
        op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM candidate_lifecycle_events"))
    ):
        raise RuntimeError("Candidate history exists; downgrade refused to preserve provenance.")
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    op.drop_table("candidate_lifecycle_events")
    op.drop_table("generated_candidates")
