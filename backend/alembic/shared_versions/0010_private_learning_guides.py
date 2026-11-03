"""Add private ungraded instructional guides without changing historical learner records."""

import sqlalchemy as sa

from alembic import op

revision = "0010_private_learning_guides"
down_revision = "0009_durable_ai_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "private_learning_guides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("content", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), nullable=True),
        sa.Column("generation_provenance", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reservation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('generating','ready','unavailable')",
            name=op.f("ck_private_learning_guides_status"),
        ),
        sa.CheckConstraint("version = '1.0.0'", name=op.f("ck_private_learning_guides_version")),
        sa.CheckConstraint(
            "(status = 'ready' AND content IS NOT NULL AND content_sha256 IS NOT NULL "
            "AND source IS NOT NULL AND generation_provenance IS NOT NULL) OR "
            "(status <> 'ready' AND content IS NULL AND content_sha256 IS NULL "
            "AND source IS NULL AND generation_provenance IS NULL)",
            name=op.f("ck_private_learning_guides_content_state"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR source IN ('ai','test_fixture')",
            name=op.f("ck_private_learning_guides_source"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_private_learning_guides_owner_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_private_learning_guides")),
        sa.UniqueConstraint(
            "owner_id",
            "creation_key",
            name=op.f("uq_private_learning_guides_owner_id_creation_key"),
        ),
    )
    op.create_index(
        "ix_private_learning_guides_owner_created",
        "private_learning_guides",
        ["owner_id", "created_at"],
    )


def downgrade() -> None:
    # A routine application rollback must not silently delete private user work.
    # Archival/deletion requires a separate reviewed procedure and authorization.
    if op.get_bind().execute(sa.text("SELECT 1 FROM private_learning_guides LIMIT 1")).first():
        raise RuntimeError("Private guide history exists; downgrade would delete user work")
    op.drop_index("ix_private_learning_guides_owner_created", table_name="private_learning_guides")
    op.drop_table("private_learning_guides")
