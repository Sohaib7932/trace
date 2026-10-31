from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.domain.health import DependencyState


class SqlReadinessProbe:
    def __init__(self, engine: Engine, expected_heads: frozenset[str]) -> None:
        self.engine, self.expected_heads = engine, expected_heads

    def check(self) -> DependencyState:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                actual = frozenset(MigrationContext.configure(connection).get_current_heads())
                return DependencyState(connected=True, schema_current=actual == self.expected_heads)
        except SQLAlchemyError:
            # Dependency failure is explicitly not-ready, not a fabricated success.
            return DependencyState(connected=False, schema_current=False)
