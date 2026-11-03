from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.settings import BACKEND_ROOT


def migration_config(dialect: str = "sqlite") -> Config:
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError("Unsupported migration dialect")
    filename = "alembic-postgresql.ini" if dialect == "postgresql" else "alembic.ini"
    config = Config(str(BACKEND_ROOT / filename))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def expected_heads() -> frozenset[str]:
    return frozenset(ScriptDirectory.from_config(migration_config()).get_heads())
