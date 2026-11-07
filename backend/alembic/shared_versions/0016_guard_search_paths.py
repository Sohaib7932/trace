"""Pin existing invoker trigger guards to their application schema.

Only function-local search paths change. Bodies, ownership, grants, trigger
bindings and learner/application rows remain unchanged. PostgreSQL's temporary
schema must be explicitly last so caller-created TEMP relations cannot shadow
the application's authority or lifecycle tables. SQLite has no such setting.
"""

import sqlalchemy as sa

from alembic import op

revision = "0016_guard_search_paths"
down_revision = "0015_project_learning_paths"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "knowledge_immutable_guard",
    "knowledge_admin_guard",
    "knowledge_event_guard",
    "knowledge_publication_guard",
    "github_snapshot_immutable",
    "github_knowledge_immutable",
    "github_learning_path_immutable",
)


def _configure(*, enabled: bool) -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        return
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Trigger hardening requires a supported database dialect")
    schema = connection.scalar(sa.text("SELECT pg_catalog.current_schema()"))
    if not isinstance(schema, str) or not schema:
        raise RuntimeError("The application schema is unavailable for trigger hardening")
    quote = connection.dialect.identifier_preparer.quote_identifier
    path = f"SET search_path TO pg_catalog, {quote(schema)}, pg_temp"
    for function in FUNCTIONS:
        action = path if enabled else "RESET search_path"
        op.execute(sa.text(f"ALTER FUNCTION {quote(schema)}.{quote(function)}() {action}"))


def upgrade() -> None:
    _configure(enabled=True)


def downgrade() -> None:
    # These seven historical definitions originally had no function-local path.
    # Reset only this setting; do not recreate functions or alter their bodies.
    _configure(enabled=False)
