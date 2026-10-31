#!/usr/bin/env python3
"""Capture documented Codex lifecycle payloads in the cohort Markdown format.

Only UserPromptSubmit.prompt and Stop.last_assistant_message are read. No rollout
parsing, history discovery, polling, model calls, commits, pushes, or global edits.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENT_ROLES = {"UserPromptSubmit": "PROMPT", "Stop": "RESPONSE"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
MARKER = re.compile(r"(?m)^\[CLAUDE_LOG_ENTRY type=(PROMPT|RESPONSE) num=(\d+) session=([A-Za-z0-9_-]+)\]\n")
REDACTIONS = (
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----", "[PRIVATE KEY REDACTED]"),
    (r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", "[GITHUB TOKEN REDACTED]"),
    (r"\bsk-(?:ant-|proj-|live_|test_)?[A-Za-z0-9_-]{16,}", "[API KEY REDACTED]"),
    (r"\b(?:sb_secret_|sb_publishable_|sbp_)[A-Za-z0-9_-]{16,}", "[API KEY REDACTED]"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "[JWT REDACTED]"),
    (r"(?i)(bearer\s+)[A-Za-z0-9_.=-]{16,}", r"\1[REDACTED]"),
    (r"(?i)((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/]+:)[^\s@]+@", r"\1[REDACTED]@"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[AWS KEY REDACTED]"),
    (r"\bAIza[0-9A-Za-z_-]{30,}", "[GOOGLE KEY REDACTED]"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "[SLACK TOKEN REDACTED]"),
    (r"(?i)([\"']?(?:password|passwd|secret|token|api[_-]?key|client[_-]?secret)[\"']?\s*[:=]\s*[\"'])([^\"'\r\n]{8,})([\"'])", r"\1[REDACTED]\3"),
    (r"(?im)^(\s*(?:export\s+)?[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*\s*[=:]\s*)[^\s\r\n]{12,}", r"\1[REDACTED]"),
    (r"[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email redacted]"),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def instant(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("A timestamp must include its timezone")
    return value


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = re.sub(pattern, replacement, text)
    return text


def command(root: Path, args: list[str], timeout: int = 5) -> str:
    result = subprocess.run(args, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if result.returncode:
        raise ValueError(f"Required attribution command failed: {args[0]}; check local Git/GitHub CLI setup")
    return result.stdout.strip()


def attribution(root: Path, previous: dict) -> dict:
    """Verify each person's own local account; never infer it from the repo owner."""
    author = command(root, ["git", "--no-optional-locks", "config", "user.name"])
    email = command(root, ["git", "--no-optional-locks", "config", "user.email"])
    if not author or "@" not in email:
        raise ValueError("Set this checkout's Git author name and email before logging")
    fingerprint = hashlib.sha256((author + "\0" + email).encode()).hexdigest()
    status = json.loads(command(root, ["gh", "auth", "status", "--active", "--json", "hosts"]))
    accounts = [a for a in status.get("hosts", {}).get("github.com", []) if a.get("active") and a.get("state") == "success"]
    if len(accounts) != 1 or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", accounts[0].get("login", "")):
        raise ValueError("Sign in to your own GitHub CLI account before logging")
    active_login = accounts[0]["login"]
    if previous.get("github_user") == active_login and previous.get("git_identity_fingerprint") == fingerprint:
        verified_at = previous["github_identity_verified_at"]
    else:
        actual_login = command(root, ["gh", "api", "user", "--jq", ".login"])
        if actual_login != active_login:
            raise ValueError("The authenticated GitHub API identity does not match the active CLI account")
        verified_at = now()
    local, _, domain = email.partition("@")
    public_email = email if email.endswith("@users.noreply.github.com") else f"{local[:1]}***@{domain}"
    return {"author": author, "github_user": active_login, "git_email": public_email,
            "git_email_redacted": public_email != email, "git_identity_fingerprint": fingerprint,
            "github_identity_verified_at": verified_at}


def validate_event(payload: dict, root: Path) -> dict:
    event = payload.get("hook_event_name")
    if event not in EVENT_ROLES:
        raise ValueError("Only native UserPromptSubmit and Stop events are supported")
    if any(payload.get(k) for k in ("agent_id", "agent_type", "agent_transcript_path", "isSidechain", "is_subagent")):
        raise ValueError("Subagent events are excluded")
    session = payload.get("session_id", "")
    turn = payload.get("turn_id", "")
    if not isinstance(session, str) or not SAFE_ID.fullmatch(session):
        raise ValueError("Missing or invalid native session_id")
    if not isinstance(turn, str) or not SAFE_ID.fullmatch(turn):
        raise ValueError("Missing or invalid native turn_id")
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).resolve().is_relative_to(root.resolve()):
        raise ValueError("The native hook cwd is outside this checkout")
    field = "prompt" if event == "UserPromptSubmit" else "last_assistant_message"
    text = payload.get(field)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Native {event} did not supply {field}; no response or history will be invented")
    # These are harness envelopes, not human prompts. Normal pasted code is retained.
    if event == "UserPromptSubmit" and text.lstrip().startswith((
        "<environment_context>", "<external_codex_apps_open_page>", "# AGENTS.md instructions",
        "This is an app-generated request for a suggested next user message. The user did not write this message.",
    )):
        raise ValueError("Injected environment/Page/instruction context is excluded")
    text = redact(text.replace("\r\n", "\n").replace("\r", "\n"))
    supplied_timestamp = payload.get("timestamp")
    timestamp = supplied_timestamp if isinstance(supplied_timestamp, str) else now()
    instant(timestamp)
    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("Unsupported native model field")
    return {"kind": EVENT_ROLES[event], "session_id": session, "turn_id": turn, "text": text,
            "timestamp": timestamp, "timestamp_source": "hook.timestamp" if supplied_timestamp is not None else "hook_capture_time_utc",
            "model": redact(model) if model else None, "cwd": str(Path(cwd).resolve()), "capture_event": event}


@contextmanager
def session_lock(root: Path, session: str):
    """OS advisory lock outside the repository; released even after process failure."""
    name = hashlib.sha256((os.path.normcase(str(root.resolve())) + "\0" + session).encode()).hexdigest()
    path = Path(tempfile.gettempdir()) / f"trace-cohort-session-{name}.lock"
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError("Another capture process holds this session lock; retry the event") from None
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    # Keep the one-byte OS-temp lock file: unlinking it can split concurrent locks.


def read_log(path: Path, session: str) -> tuple[dict, list[dict]]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("Existing session file has invalid frontmatter; refusing to overwrite it")
    head, body = text[4:].split("\n---\n", 1)
    metadata = {}
    for line in head.splitlines():
        key, separator, value = line.partition(": ")
        if not separator:
            raise ValueError("Existing log metadata is malformed")
        try:
            metadata[key] = json.loads(value)
        except ValueError:
            metadata[key] = value
    if metadata.get("agent", "").lower() != "codex" or metadata.get("session_id") != session:
        raise ValueError("Existing session belongs to another agent/session; refusing to overwrite it")
    if metadata.get("capture_schema") != 2:
        raise ValueError("Existing Codex session uses another schema; no silent migration or backfill")
    entries = []
    match = MARKER.search(body)
    cursor = match.start() if match else len(body)
    while cursor < len(body):
        match = MARKER.match(body, cursor)
        if not match or match[3] != session:
            raise ValueError("Existing session entry marker is malformed")
        cursor = match.end()
        fields = {}
        while True:
            end = body.find("\n", cursor)
            if end < 0:
                raise ValueError("Existing entry metadata is incomplete")
            line = body[cursor:end]
            cursor = end + 1
            if not line:
                break
            key, separator, value = line.partition(": ")
            if not separator:
                raise ValueError("Existing entry metadata is malformed")
            try:
                fields[key] = json.loads(value)
            except ValueError:
                fields[key] = value
        count = fields.get("chars")
        if not isinstance(count, int) or count < 0 or cursor + count > len(body):
            raise ValueError("Existing entry length is invalid")
        value = body[cursor:cursor + count]
        cursor += count
        if not SAFE_ID.fullmatch(str(fields.get("turn_id", ""))):
            raise ValueError("Existing entry has no valid turn association")
        entries.append({"kind": match[1], "num": int(match[2]), "session_id": session,
                        "text": value, **fields})
        while cursor < len(body) and body[cursor] == "\n":
            cursor += 1
    if not entries:
        raise ValueError("Existing Codex file contains no captured entries")
    return metadata, entries


def paste_indicators(text: str) -> dict:
    flags = {"has_code_block": "```" in text,
             "has_file_paths": bool(re.search(r"[A-Za-z]:[\\/]|(?:/[\w.-]+){2,}|[\w.-]+\.(?:py|ts|tsx|js|md):\d+", text)),
             "has_urls": bool(re.search(r"https?://", text)), "is_long": len(text) > 500,
             "has_stack_trace": bool(re.search(r'File ".*", line \d+|at \w+.*:\d+:\d+', text)),
             "has_structured_data": text.lstrip().startswith(("{", "[")) and "{" in text and "}" in text}
    flags["likely_pasted"] = sum(flags.values()) >= 2 or flags["is_long"]
    return flags


def statistics(entries: list[dict]) -> dict:
    prompts = [e for e in entries if e["kind"] == "PROMPT"]
    responses = [e for e in entries if e["kind"] == "RESPONSE"]
    times = sorted(instant(e["timestamp"]) for e in prompts)
    duration = (times[-1] - times[0]).total_seconds() / 60
    chars = [len(e["text"]) for e in prompts]
    words = [len(e["text"].split()) for e in prompts]
    stats = {"first_prompt_time": times[0].isoformat(), "last_prompt_time": times[-1].isoformat(),
             "session_duration_minutes": round(duration, 1), "total_prompt_chars": sum(chars),
             "total_prompt_words": sum(words), "avg_prompt_length_chars": round(sum(chars) / len(chars), 1),
             "avg_prompt_length_words": round(sum(words) / len(words), 1), "longest_prompt_words": max(words),
             "shortest_prompt_words": min(words)}
    if len(prompts) > 1:
        stats["avg_time_between_prompts_minutes"] = round(duration / (len(prompts) - 1), 1)
    if responses:
        response_chars = sum(len(e["text"]) for e in responses)
        stats.update(total_response_chars=response_chars, avg_response_length_chars=round(response_chars / len(responses), 1),
                     response_to_prompt_ratio=round(response_chars / sum(chars), 2))
    flags = [paste_indicators(e["text"]) for e in prompts]
    for flag, name in (("has_code_block", "code_blocks"), ("has_file_paths", "file_paths"), ("has_urls", "urls"), ("is_long", "long_content")):
        stats[f"prompts_with_{name}"] = sum(bool(f[flag]) for f in flags)
    stats["likely_pasted_count"] = sum(bool(f["likely_pasted"]) for f in flags)
    return stats


def render(metadata: dict, entries: list[dict]) -> str:
    prompts = [e for e in entries if e["kind"] == "PROMPT"]
    replies = {e["num"] for e in entries if e["kind"] == "RESPONSE"}
    pending = [e["num"] for e in prompts if e["num"] not in replies]
    metadata = {**metadata, "generated_at": now(), "total_exchanges": len(prompts), "total_responses": len(replies),
                "session_status": "awaiting_response" if pending else "complete",
                "last_entry_type": "user" if pending else "assistant", **statistics(entries)}
    lines = ["---", *(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in metadata.items()), "---", "",
             f"# Codex Session Log - {metadata['date']}", "",
             f"Session: `{metadata['session_id']}` | Project: `{metadata['project']}` | Author: `{metadata['author']}` | GitHub: `{metadata['github_user']}`", "", "---"]
    for entry in sorted(entries, key=lambda e: (e["num"], e["kind"] == "RESPONSE")):
        lines.extend(["", f"[CLAUDE_LOG_ENTRY type={entry['kind']} num={entry['num']} session={metadata['session_id']}]",
                      f"timestamp: {entry['timestamp']}", f"time: {instant(entry['timestamp']).astimezone():%Y-%m-%d %H:%M}",
                      f"chars: {len(entry['text'])}"])
        for key in ("turn_id", "capture_event", "timestamp_source", "model", "cwd"):
            lines.append(f"{key}: {json.dumps(entry.get(key), ensure_ascii=False)}")
        if entry["kind"] == "PROMPT":
            flags = paste_indicators(entry["text"])
            lines.append(f"words: {len(entry['text'].split())}")
            lines.extend(f"{key}: {json.dumps(flags[key])}" for key in ("has_code_block", "has_file_paths", "has_urls", "likely_pasted"))
        lines.extend(["", entry["text"], ""])
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=".cohort-capture-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(10):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(.05)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def capture(payload: dict, root: Path = ROOT, identity_provider=attribution) -> tuple[Path, bool]:
    root = root.resolve()
    entry = validate_event(payload, root)
    session = entry["session_id"]
    directory = root / ".claude-logs"
    if directory.exists() and (directory.is_symlink() or not directory.resolve().is_relative_to(root)):
        raise ValueError("The canonical log directory must remain in this checkout")
    with session_lock(root, session):
        paths = list(directory.glob(f"*_{session}.md")) if directory.exists() else []
        if len(paths) > 1:
            raise ValueError("Multiple files already exist for this session; refusing an ambiguous update")
        previous, entries = read_log(paths[0], session) if paths else ({}, [])
        identity = identity_provider(root, previous)
        if previous and any(previous.get(k) != identity.get(k) for k in ("author", "github_user", "git_identity_fingerprint")):
            raise ValueError("Developer identity changed for this session; refusing to mix developers")
        same = [e for e in entries if e["turn_id"] == entry["turn_id"] and e["kind"] == entry["kind"]]
        if same:
            if any(e["text"] == entry["text"] for e in same):
                return paths[0], False
            raise ValueError("Conflicting repeated event for this turn; preserving the original entry")
        if entry["kind"] == "PROMPT":
            entry["num"] = 1 + max((e["num"] for e in entries), default=0)
        else:
            matching = [e for e in entries if e["turn_id"] == entry["turn_id"] and e["kind"] == "PROMPT"]
            if len(matching) != 1:
                raise ValueError("Stop has no captured prompt for this turn; no historical backfill will be performed")
            entry["num"] = matching[0]["num"]
        entries.append(entry)
        first = instant(entry["timestamp"]).astimezone()
        metadata = previous or {"session_id": session, "date": first.date().isoformat(), "agent": "codex",
                                "project": root.name, "cwd": str(root), "capture_schema": 2,
                                "capture_mechanism": "native Codex UserPromptSubmit and Stop event payloads",
                                "capture_started_at": entry["timestamp"], **identity}
        directory.mkdir(exist_ok=True)
        path = paths[0] if paths else directory / f"{first:%Y-%m-%d_%H-%M-%S}_{session}.md"
        if path.is_symlink():
            raise ValueError("Refusing to replace a symbolic-link log")
        atomic_write(path, render(metadata, entries))
        return path, True


def main() -> int:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("A native hook payload must be a JSON object")
        capture(payload, ROOT, attribution)
        print("{}")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Surface a failure without logging stdin, credentials, or blocking the turn.
        print(json.dumps({"systemMessage": f"Codex cohort capture failed: {type(error).__name__}: {error}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
