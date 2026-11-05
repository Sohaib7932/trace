"""Append generated paths to their existing owner-bound immutable source snapshots."""

import sqlalchemy as sa

from alembic import op

revision = "0015_project_learning_paths"
down_revision = "0014_merge_learning_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_project_learning_paths",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id", "commit_sha"],
            ["github_project_snapshots.connection_id", "github_project_snapshots.commit_sha"],
        ),
        sa.CheckConstraint(
            "length(commit_sha) = 40 AND length(snapshot_digest) = 64 "
            "AND length(payload_digest) = 64",
            name=op.f("ck_github_project_learning_paths_digest_lengths"),
        ),
    )
    op.create_index(
        "ix_github_learning_paths_latest",
        "github_project_learning_paths",
        ["owner_id", "connection_id", "commit_sha", "generated_at"],
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER github_learning_paths_no_{action.lower()} BEFORE {action} "
                "ON github_project_learning_paths BEGIN "
                "SELECT RAISE(ABORT, 'immutable project learning path'); END"
            )
    else:
        op.execute("""CREATE FUNCTION github_learning_path_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'immutable project learning path'; END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER github_learning_path_immutable BEFORE UPDATE OR DELETE
        ON github_project_learning_paths FOR EACH ROW
        EXECUTE FUNCTION github_learning_path_immutable()""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM github_project_learning_paths")):
        raise RuntimeError("Project learning path history exists; downgrade refused")
    op.drop_index("ix_github_learning_paths_latest", table_name="github_project_learning_paths")
    op.drop_table("github_project_learning_paths")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION github_learning_path_immutable()")
