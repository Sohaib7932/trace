"""Join the published custom-lesson and private-guide/Project Learning histories.

Both branches remain intact. Upgrading applies whichever branch is absent and
then records this merge; the merge itself changes no product tables or records.
The published custom-lesson rollback drops its history without a data guard, so
refuse entry into that rollback while any custom learning history is present.
"""

import sqlalchemy as sa

from alembic import op

revision = "0014_merge_learning_heads"
down_revision = ("0010_custom_lessons", "0013_repository_knowledge")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    tables = (
        "custom_lesson_answers",
        "custom_lesson_challenges",
        "custom_lessons",
        "custom_lesson_requests",
    )
    if any(op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {name}")) for name in tables):
        raise RuntimeError("Custom lesson history exists; downgrade refused")
