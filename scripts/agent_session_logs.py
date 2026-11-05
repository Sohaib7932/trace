#!/usr/bin/env python3
"""Canonical transcript export and Claude hooks; native Codex capture stays separate."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import codex_session_log as native
from claude_session_transcript import extract_claude_transcript
from codex_session_transcript import extract_codex_transcripts

SCHEMA = "agent-transcript-v1"
ROOT = Path(__file__).resolve().parent.parent


def project_root(cwd: Path) -> Path:
    value = native.command(
        cwd, ["git", "--no-optional-locks", "rev-parse", "--show-toplevel"]
    )
    root = Path(value).resolve()
    if not cwd.resolve().is_relative_to(root):
        raise ValueError("Session working directory is outside the project")
    return root


def _common(root: Path) -> Path:
    value = native.command(
        root, ["git", "--no-optional-locks", "rev-parse", "--git-common-dir"]
    )
    return (root / value).resolve()


def _read_managed(path: Path, session: str, agent: str) -> tuple[dict, list[dict]]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("Existing log is not managed by this exporter")
    head, body = text[4:].split("\n---\n", 1)
    metadata = {}
    for line in head.splitlines():
        key, separator, value = line.partition(": ")
        if not separator:
            raise ValueError("Invalid existing session metadata")
        try:
            metadata[key] = json.loads(value)
        except ValueError:
            metadata[key] = value
    if (
        metadata.get("capture_schema") != SCHEMA
        or metadata.get("agent") != agent
        or metadata.get("session_id") != session
    ):
        raise ValueError("Preserving an existing native or legacy session log")
    result = []
    match = native.MARKER.search(body)
    if match is None:
        raise ValueError("Existing managed session has no valid entry markers")
    cursor = match.start()
    while cursor < len(body):
        match = native.MARKER.match(body, cursor)
        if not match or match[3] != session:
            raise ValueError("Invalid existing session marker")
        cursor = match.end()
        fields = {}
        while True:
            end = body.find("\n", cursor)
            if end < 0:
                raise ValueError("Incomplete existing session metadata")
            line, cursor = body[cursor:end], end + 1
            if not line:
                break
            key, sep, value = line.partition(": ")
            if not sep:
                raise ValueError("Invalid existing entry metadata")
            try:
                fields[key] = json.loads(value)
            except ValueError:
                fields[key] = value
        length = fields.get("chars")
        if type(length) is not int or length < 0 or cursor + length > len(body):
            raise ValueError("Invalid existing entry length")
        result.append(
            {"kind": match[1], "text": body[cursor : cursor + length], **fields}
        )
        cursor += length
        while cursor < len(body) and body[cursor] == "\n":
            cursor += 1
    return metadata, result


def render(metadata: dict, entries: list[dict]) -> str:
    # Reuse the same statistics and marker renderer; correct the agent heading.
    value = native.render(metadata, entries)
    if metadata["agent"] == "claude-code":
        value = value.replace("# Codex Session Log - ", "# Claude Session Log - ", 1)
    return value


def session_files(directory: Path, session: str) -> list[Path]:
    """Recognize legacy reconstruction names too; never duplicate their session."""
    result = []
    if not directory.exists():
        return result
    name_pattern = re.compile(r"(?:^|_)" + re.escape(session) + r"(?:_|\.md$)")
    for path in directory.glob("*.md"):
        named = bool(name_pattern.search(path.name))
        if path.is_symlink():
            if named:
                result.append(path)
            continue
        with path.open(encoding="utf-8-sig") as stream:
            header = stream.read(16384)
        match = None
        if header.startswith("---\n") and "\n---\n" in header[4:]:
            match = re.search(
                r"(?m)^session_id: (.+)$", header[4:].split("\n---\n", 1)[0]
            )
        identity = None
        if match:
            try:
                identity = json.loads(match[1])
            except ValueError:
                identity = match[1]
        if named or identity == session:
            result.append(path)
    return result


def export_session(
    paths: list[Path],
    agent: str,
    session: str,
    root: Path,
    *,
    source_cwds: tuple[Path, ...] = (),
    hook_payload: dict | None = None,
    dry_run: bool = False,
    identity_provider=native.attribution,
) -> dict:
    root = root.resolve()
    if agent not in {"codex", "claude"} or not native.SAFE_ID.fullmatch(session):
        raise ValueError("Invalid agent or session identifier")
    if not paths or any(
        p.is_symlink() or not p.is_file() or p.suffix != ".jsonl" for p in paths
    ):
        raise ValueError("Select explicit existing JSONL transcripts")
    for alias in source_cwds:
        if _common(project_root(alias)) != _common(root):
            raise ValueError("A transcript alias belongs to another repository")
    agent_label = "codex" if agent == "codex" else "claude-code"
    directory = root / ".claude-logs"
    if directory.is_symlink() or (
        directory.exists() and not directory.resolve().is_relative_to(root)
    ):
        raise ValueError("The canonical log directory must remain in the checkout")
    with native.session_lock(root, session):
        existing = session_files(directory, session)
        if len(existing) > 1:
            return {"status": "preserved", "reason": "multiple_existing_session_files"}
        previous, old_entries = {}, []
        if existing:
            if existing[0].is_symlink():
                raise ValueError("Refusing a symbolic-link session log")
            try:
                previous, old_entries = _read_managed(existing[0], session, agent_label)
            except ValueError:
                return {
                    "status": "preserved",
                    "reason": "existing_native_or_legacy_log",
                }
        if agent == "codex":
            entries = extract_codex_transcripts(
                paths, session, root, source_cwds=source_cwds
            )
        else:
            if len(paths) != 1:
                raise ValueError("Claude hooks select one exact session transcript")
            cwd = Path(hook_payload["cwd"]) if hook_payload else root
            entries = extract_claude_transcript(
                paths[0],
                session,
                cwd,
                stop_event=bool(
                    hook_payload and hook_payload.get("hook_event_name") == "Stop"
                ),
            )
            if (
                hook_payload
                and hook_payload.get("hook_event_name") == "UserPromptSubmit"
            ):
                prompt = hook_payload.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    prompts = [e for e in entries if e["kind"] == "PROMPT"]
                    # Claude may invoke the prompt hook before appending JSONL.
                    # Never fabricate its original timestamp or turn identifier.
                    if not prompts or prompts[-1]["text"].strip() != prompt.strip():
                        return {
                            "status": "pending",
                            "reason": "prompt_not_yet_in_transcript",
                        }
            if hook_payload and isinstance(
                hook_payload.get("last_assistant_message"), str
            ):
                final = [e for e in entries if e["kind"] == "RESPONSE"]
                if hook_payload["last_assistant_message"].strip() and (
                    not final
                    or final[-1]["text"].strip()
                    != hook_payload["last_assistant_message"].strip()
                ):
                    raise ValueError("Native final and transcript evidence disagree")
        if not entries or not any(e["kind"] == "PROMPT" for e in entries):
            return {"status": "empty", "reason": "no_primary_prompts"}
        numbered, turns = [], {}
        for entry in entries:
            entry = dict(entry)
            if not native.SAFE_ID.fullmatch(entry["turn_id"]):
                raise ValueError("Transcript entry has an invalid turn identifier")
            native.instant(entry["timestamp"])
            entry["text"] = native.redact(
                entry["text"].replace("\r\n", "\n").replace("\r", "\n")
            )
            entry["timestamp_source"] = "transcript.timestamp"
            if entry["kind"] == "PROMPT":
                if entry["turn_id"] in turns:
                    raise ValueError("Duplicate transcript prompt")
                turns[entry["turn_id"]] = len(turns) + 1
            if entry["turn_id"] not in turns:
                raise ValueError("Transcript final lacks its genuine prompt")
            entry["num"] = turns[entry["turn_id"]]
            numbered.append(entry)
        content_keys = ("kind", "turn_id", "text", "timestamp")
        old = [{k: e[k] for k in content_keys} for e in old_entries]
        new = [{k: e[k] for k in content_keys} for e in numbered]
        if old and new[: len(old)] != old:
            raise ValueError(
                "Transcript update would replace existing authentic entries"
            )
        if old == new:
            return {"status": "unchanged", "path": str(existing[0])}
        if dry_run:
            return {
                "status": "ready",
                "prompts": len(turns),
                "responses": sum(e["kind"] == "RESPONSE" for e in numbered),
            }
        identity = identity_provider(root, previous)
        if previous and any(
            previous.get(k) != identity.get(k)
            for k in ("author", "github_user", "git_identity_fingerprint")
        ):
            raise ValueError(
                "Developer identity changed; existing session is preserved"
            )
        first = native.instant(numbered[0]["timestamp"]).astimezone()
        metadata = previous or {
            "session_id": session,
            "date": first.date().isoformat(),
            "agent": agent_label,
            "project": root.name,
            "cwd": str(root),
            "capture_schema": SCHEMA,
            "capture_mechanism": "genuine JSONL transcript export",
            "automatic_hook_triggered": hook_payload is not None,
            **identity,
        }
        directory.mkdir(exist_ok=True)
        destination = (
            existing[0]
            if existing
            else directory / f"{first:%Y-%m-%d_%H-%M-%S}_{session}.md"
        )
        native.atomic_write(destination, render(metadata, numbered))
        return {
            "status": "written",
            "path": str(destination),
            "prompts": len(turns),
            "responses": sum(e["kind"] == "RESPONSE" for e in numbered),
        }


def hook(agent: str, payload: dict) -> dict:
    if (
        agent != "claude"
        or payload.get("hook_event_name") not in {"UserPromptSubmit", "Stop"}
        or any(
            payload.get(k)
            for k in (
                "agent_id",
                "agent_type",
                "agent_transcript_path",
                "isSidechain",
                "is_subagent",
            )
        )
    ):
        raise ValueError("Only primary Claude prompt and stop hooks are accepted")
    cwd = Path(payload.get("cwd", ""))
    if not cwd.is_absolute() or project_root(cwd) != ROOT:
        raise ValueError("The hook belongs to another checkout")
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError("A native transcript path is required")
    return export_session(
        [Path(path)], agent, payload.get("session_id", ""), ROOT, hook_payload=payload
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    live = sub.add_parser("hook")
    live.add_argument("--agent", choices=["claude"], required=True)
    export = sub.add_parser("export")
    export.add_argument("--agent", choices=["claude", "codex"], required=True)
    export.add_argument("--session-id", required=True)
    export.add_argument("--transcript", action="append", type=Path, required=True)
    export.add_argument("--project", type=Path, default=ROOT)
    export.add_argument("--source-cwd", action="append", type=Path, default=[])
    export.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == "hook":
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise ValueError("Invalid native hook payload")
            hook(args.agent, payload)
            print("{}")
        else:
            result = export_session(
                args.transcript,
                args.agent,
                args.session_id,
                project_root(args.project),
                source_cwds=tuple(args.source_cwd),
                dry_run=args.dry_run,
            )
            print(json.dumps(result))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        # No raw exception, stdin, file contents or credentials cross this boundary.
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "session_export_failed",
                    "error_type": type(error).__name__,
                }
            )
        )
        return 0 if args.operation == "hook" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
