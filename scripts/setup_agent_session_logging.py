"""Install opt-in global Claude hooks for explicitly registered Trace checkouts.

The default is a dry run. No global settings are changed without ``--apply``.
This installer never runs a hook, exports a transcript, or changes hook trust.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MANAGED_MARKER = "# Trace managed global agent session logging wrapper v1"
REGISTRY_NAME = "trace-session-log-projects.json"
EXPORTER_RELATIVE = Path("scripts") / "agent_session_logs.py"

WRAPPER = '''# Trace managed global agent session logging wrapper v1
"""Dispatch native Claude events only inside explicitly registered checkouts."""

import json
import subprocess
import sys
from pathlib import Path


def main():
    try:
        raw = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            return 1
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return 1
        if payload.get("hook_event_name") not in {"UserPromptSubmit", "Stop"}:
            return 0
        cwd_value = payload.get("cwd")
        if not isinstance(cwd_value, str) or not cwd_value or not Path(cwd_value).is_absolute():
            return 0
        cwd = Path(cwd_value).resolve(strict=True)
        registry = json.loads(
            (Path(__file__).resolve().parent / "trace-session-log-projects.json")
            .read_text(encoding="utf-8")
        )
        if (
            not isinstance(registry, dict)
            or type(registry.get("version")) is not int
            or registry.get("version") != 1
        ):
            return 1
        roots = registry.get("projects")
        if not isinstance(roots, list) or any(
            not isinstance(root, str) or not Path(root).is_absolute() for root in roots
        ):
            return 1
        matches = []
        for value in roots:
            root = Path(value).resolve()
            if cwd.is_relative_to(root):
                matches.append(root)
        if not matches:
            return 0
        root = max(matches, key=lambda item: len(item.parts))
        exporter = (root / "scripts" / "agent_session_logs.py").resolve(strict=True)
        if not exporter.is_relative_to(root) or not exporter.is_file():
            return 1
        completed = subprocess.run(
            [sys.executable, "-B", str(exporter), "hook", "--agent", "claude"],
            input=raw,
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return completed.returncode
    except Exception:  # noqa: BLE001 - a final CLI boundary must not print private settings
        # Never print native payloads, local paths from errors, or exception text.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


class SetupError(Exception):
    """A constant, safe setup diagnostic without existing configuration values."""


def _object_file(path: Path, missing: dict[str, object]) -> dict[str, object]:
    if not path.exists():
        return copy.deepcopy(missing)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError, UnicodeError):
        raise SetupError(
            "An existing configuration file could not be read as JSON."
        ) from None
    if not isinstance(value, dict):
        raise SetupError("An existing configuration file is not a JSON object.")
    return value


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=".trace-log-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(claude_home: Path, projects: list[Path]) -> dict[Path, bytes]:
    """Validate all inputs and build writes without touching the filesystem."""
    home = claude_home.expanduser().resolve()
    resolved: list[Path] = []
    for project in projects:
        try:
            root = project.expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            raise SetupError("A registered project directory is unavailable.") from None
        if not root.is_dir() or not (root / EXPORTER_RELATIVE).is_file():
            raise SetupError(
                "A registered project is missing the shared logging exporter."
            )
        resolved.append(root)
    if not resolved:
        raise SetupError("At least one explicit project directory is required.")
    wrapper = home / "extract-log.py"
    registry_path, settings_path = home / REGISTRY_NAME, home / "settings.json"
    if any(path.is_symlink() for path in (wrapper, registry_path, settings_path)):
        raise SetupError(
            "Existing configuration links require manual review; no files changed."
        )
    if not (home / "trace-session-logging-backups").resolve().is_relative_to(home):
        raise SetupError(
            "The backup directory must remain inside the private global directory."
        )
    if wrapper.exists():
        try:
            managed = (
                MANAGED_MARKER in wrapper.read_text(encoding="utf-8").splitlines()[:3]
            )
        except (OSError, UnicodeError):
            managed = False
        if not managed:
            raise SetupError(
                "An unmanaged global extract-log.py exists; no files were changed."
            )
    registry = _object_file(registry_path, {"version": 1, "projects": []})
    existing = registry.get("projects")
    if (
        type(registry.get("version")) is not int
        or registry["version"] != 1
        or not isinstance(existing, list)
        or any(
            not isinstance(value, str) or not value or not Path(value).is_absolute()
            for value in existing
        )
    ):
        raise SetupError("The existing project registry has an unsupported format.")
    all_roots = [Path(value).expanduser().resolve() for value in existing] + resolved
    if any(home.is_relative_to(root) for root in all_roots):
        raise SetupError(
            "Global logging configuration and backups must stay outside projects."
        )
    registered = list(existing)
    keys = {os.path.normcase(str(root)) for root in all_roots[: len(existing)]}
    for root in resolved:
        key = os.path.normcase(str(root))
        if key not in keys:
            registered.append(str(root))
            keys.add(key)
    registry["projects"] = registered
    settings = _object_file(settings_path, {})
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SetupError("The existing hooks setting is not an object.")
    # Claude command hooks use a shell. Quote each fixed local argument; no Git,
    # environment expansion, command substitution, or event data enters commands.
    command = " ".join(
        shlex.quote(value) for value in (sys.executable, "-B", str(wrapper))
    )
    for event in ("UserPromptSubmit", "Stop"):
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list) or any(
            not isinstance(group, dict) for group in groups
        ):
            raise SetupError("An existing hook event has an unsupported format.")
        found = False
        for group in groups:
            handlers = group.get("hooks", [])
            if not isinstance(handlers, list) or any(
                not isinstance(item, dict) for item in handlers
            ):
                raise SetupError("An existing hook handler has an unsupported format.")
            found = found or any(
                handler.get("type") == "command" and handler.get("command") == command
                for handler in handlers
            )
        if not found:
            groups.append({"hooks": [{"type": "command", "command": command}]})
    desired = {
        wrapper: WRAPPER.encode("utf-8"),
        registry_path: _json_bytes(registry),
        settings_path: _json_bytes(settings),
    }
    return {
        path: content
        for path, content in desired.items()
        if not path.exists() or path.read_bytes() != content
    }


def install(
    claude_home: Path, projects: list[Path], *, apply: bool = False
) -> dict[str, object]:
    writes = prepare(claude_home, projects)
    backup_dir: Path | None = None
    if apply and writes:
        home = claude_home.expanduser().resolve()
        home.mkdir(parents=True, exist_ok=True)
        existing = [path for path in writes if path.exists()]
        if existing:
            # The standalone installer also supports Python 3.10.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
            backup_dir = (
                home / "trace-session-logging-backups" / f"{stamp}-{uuid4().hex}"
            )
            backup_dir.mkdir(parents=True, mode=0o700)
            for path in existing:
                shutil.copy2(path, backup_dir / path.name)
        for path, content in writes.items():
            _atomic_write(path, content)
    return {
        "mode": "applied" if apply else "dry-run",
        "changed_files": [str(path) for path in writes],
        "backup_directory": str(backup_dir) if backup_dir is not None else None,
        "hook_trust_changed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, action="append", required=True)
    parser.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = install(args.claude_home, args.project, apply=args.apply)
    except SetupError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 1
    except Exception:  # noqa: BLE001 - never print private settings from unexpected failures
        print(
            json.dumps({"status": "blocked", "reason": "Logging setup failed safely."})
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
