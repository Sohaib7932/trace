"""Archive bounded pinned repository knowledge without changing V1 snapshots."""

import sqlalchemy as sa

from alembic import op

revision = "0013_repository_knowledge"
down_revision = "0012_github_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_repository_knowledge",
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
            name=op.f("ck_github_repository_knowledge_digest_lengths"),
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER github_knowledge_no_{action.lower()} BEFORE {action} "
                "ON github_repository_knowledge BEGIN "
                "SELECT RAISE(ABORT, 'immutable repository knowledge'); END"
            )
    else:
        op.execute("""CREATE FUNCTION github_knowledge_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'immutable repository knowledge'; END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER github_knowledge_immutable BEFORE UPDATE OR DELETE
        ON github_repository_knowledge FOR EACH ROW
        EXECUTE FUNCTION github_knowledge_immutable()""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM github_repository_knowledge")):
        raise RuntimeError("Repository knowledge history exists; downgrade refused")
    op.drop_table("github_repository_knowledge")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION github_knowledge_immutable()")
