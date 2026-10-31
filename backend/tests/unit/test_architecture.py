import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_domain_is_independent_of_transport_database_and_providers() -> None:
    forbidden = ("fastapi", "sqlalchemy", "app.api", "app.db", "app.ai", "anthropic", "google")
    for path in (ROOT / "backend/app/domain").rglob("*.py"):
        assert not any(name.startswith(forbidden) for name in imports(path)), str(path)


def test_api_handlers_do_not_embed_database_implementation() -> None:
    for path in (ROOT / "backend/app/api/v1").rglob("*.py"):
        assert not any(name.startswith(("sqlalchemy", "app.db")) for name in imports(path)), str(
            path
        )


def test_services_do_not_import_http_or_provider_implementations() -> None:
    for path in (ROOT / "backend/app/services").rglob("*.py"):
        assert not any(
            name.startswith(("fastapi", "app.db", "app.ai.providers", "anthropic", "google"))
            for name in imports(path)
        ), str(path)


def test_frontend_has_only_contract_coupling_to_backend() -> None:
    for path in (ROOT / "src").rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        for target in re.findall(
            r'(?:from\s+|import\s*\()["\x27]([^"\x27]+)', path.read_text(encoding="utf-8")
        ):
            assert "backend/" not in target and not target.endswith(".py"), str(path)
