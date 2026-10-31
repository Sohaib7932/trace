from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.settings import BACKEND_ROOT


def migration_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def expected_heads() -> frozenset[str]:
    return frozenset(ScriptDirectory.from_config(migration_config()).get_heads())
