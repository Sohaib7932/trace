import json
from pathlib import Path

from app.core.settings import Settings
from app.main import create_app


def main() -> None:
    # No lifespan/database/network access is needed to export the real API schema.
    app = create_app(Settings(_env_file=None))
    target = Path(__file__).resolve().parents[1] / "openapi.json"
    target.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
