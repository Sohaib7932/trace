"""Add private GitHub App grants and immutable pinned Project Learning snapshots."""

import sqlalchemy as sa

from alembic import op

revision = "0011_github_projects"
down_revision = "0010_private_learning_guides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_authorization_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_github_authorization_states_owner_id", "github_authorization_states", ["owner_id"]
    )
    op.create_table(
        "github_installation_grants",
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("installation_id", sa.BigInteger(), primary_key=True),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("repository_ids", sa.JSON(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "installation_id > 0 AND github_user_id > 0",
            name=op.f("ck_github_installation_grants_positive_ids"),
        ),
    )
    op.create_table(
        "github_repository_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(201), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "repository_id"),
        sa.ForeignKeyConstraint(
            ["owner_id", "installation_id"],
            ["github_installation_grants.owner_id", "github_installation_grants.installation_id"],
        ),
        sa.CheckConstraint(
            "repository_id > 0 AND installation_id > 0",
            name=op.f("ck_github_repository_connections_positive_ids"),
        ),
    )
    op.create_index(
        "ix_github_repository_connections_owner_id", "github_repository_connections", ["owner_id"]
    )
    op.create_table(
        "github_project_snapshots",
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("github_repository_connections.id"),
            primary_key=True,
        ),
        sa.Column("commit_sha", sa.String(40), primary_key=True),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(commit_sha) = 40 AND length(digest) = 64",
            name=op.f("ck_github_project_snapshots_digest_lengths"),
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER github_snapshots_no_{action.lower()} BEFORE {action} "
                "ON github_project_snapshots BEGIN "
                "SELECT RAISE(ABORT, 'immutable project snapshot'); END"
            )
    else:
        op.execute("""CREATE FUNCTION github_snapshot_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'immutable project snapshot'; END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER github_snapshot_immutable BEFORE UPDATE OR DELETE
        ON github_project_snapshots FOR EACH ROW EXECUTE FUNCTION github_snapshot_immutable()""")


def downgrade() -> None:
    tables = (
        "github_project_snapshots",
        "github_repository_connections",
        "github_installation_grants",
    )
    if any(op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {name}")) for name in tables):
        raise RuntimeError("Project Learning history exists; downgrade refused")
    op.drop_table("github_project_snapshots")
    op.drop_table("github_repository_connections")
    op.drop_table("github_installation_grants")
    op.drop_table("github_authorization_states")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION github_snapshot_immutable()")
