"""Establish a migration baseline without premature learner tables.

Alembic creates/updates its own version table. Product schema arrives with Module 2.
"""

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
