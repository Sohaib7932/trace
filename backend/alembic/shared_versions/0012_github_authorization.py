"""Persist encrypted owner-bound GitHub authorization and reversible disconnects."""

import sqlalchemy as sa

from alembic import op

revision = "0012_github_authorization"
down_revision = "0011_github_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("github_installation_grants", sa.Column("token_ciphertext", sa.Text()))
    op.add_column(
        "github_installation_grants",
        sa.Column("credential_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "github_installation_grants", sa.Column("disconnected_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "github_installation_grants",
        sa.Column("authorization_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "github_repository_connections", sa.Column("disconnected_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "github_repository_connections",
        sa.Column("connection_revision", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    authorization = bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM github_installation_grants "
            "WHERE token_ciphertext IS NOT NULL OR disconnected_at IS NOT NULL "
            "OR authorization_revision > 1"
        )
    )
    connections = bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM github_repository_connections "
            "WHERE disconnected_at IS NOT NULL OR connection_revision > 1"
        )
    )
    if authorization or connections:
        raise RuntimeError("GitHub authorization history exists; downgrade refused")
    for column in ("connection_revision", "disconnected_at"):
        op.drop_column("github_repository_connections", column)
    for column in (
        "authorization_revision",
        "disconnected_at",
        "credential_expires_at",
        "token_ciphertext",
    ):
        op.drop_column("github_installation_grants", column)
