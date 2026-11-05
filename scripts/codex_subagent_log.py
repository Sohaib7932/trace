"""Append verified delegated briefs/finals to the parent's native Codex log."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_session_log as native


def extract(path: Path, parent: str, agent: str, root: Path) -> list[dict]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Select a real delegated transcript")
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    meta = rows[0].get("payload", {}) if rows else {}
    source = meta.get("source", {})
    delegated = source.get("subagent", {}) if isinstance(source, dict) else {}
    spawn = delegated.get("thread_spawn", {}) if isinstance(delegated, dict) else {}
    if (
        not rows
        or rows[0].get("type") != "session_meta"
        or meta.get("id") != agent
        or spawn.get("parent_thread_id") != parent
        or meta.get("history_base")
        or not Path(meta.get("cwd", "")).resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("Unverified delegated session ancestry or scope")
    entries, turn, pending = [], None, None
    for row in rows[1:]:
        payload = row.get("payload", {})
        if row.get("type") == "event_msg" and payload.get("type") == "user_message":
            text = payload.get("message")
            if not isinstance(text, str) or not text.strip():
                continue
            if pending:
                entries.append(pending)
            turn = 1 + sum(e["kind"] == "SUBAGENT_PROMPT" for e in entries)
            native.instant(row["timestamp"])
            entries.append(
                {
                    "kind": "SUBAGENT_PROMPT",
                    "num": turn,
                    "agent_id": agent,
                    "timestamp": row["timestamp"],
                    "text": native.redact(text),
                    "capture_event": "SubagentTranscript",
                }
            )
            pending = None
        elif (
            row.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "assistant"
            and payload.get("phase") in {"final", "final_answer"}
            and turn
        ):
            text = "\n\n".join(
                b["text"]
                for b in payload.get("content", [])
                if b.get("type") == "output_text" and isinstance(b.get("text"), str)
            )
            if text.strip():
                native.instant(row["timestamp"])
                pending = {
                    "kind": "SUBAGENT_RESPONSE",
                    "num": turn,
                    "agent_id": agent,
                    "timestamp": row["timestamp"],
                    "text": native.redact(text),
                    "capture_event": "SubagentTranscript",
                }
    if pending:
        entries.append(pending)
    return entries


def capture(payload: dict, root: Path = native.ROOT) -> bool:
    session, agent = payload.get("session_id"), payload.get("agent_id")
    if payload.get("hook_event_name") != "SubagentStop" or not all(
        isinstance(v, str) and native.SAFE_ID.fullmatch(v) for v in (session, agent)
    ):
        raise ValueError("A native SubagentStop identity is required")
    cwd, transcript = payload.get("cwd"), payload.get("agent_transcript_path")
    if (
        not isinstance(cwd, str)
        or not Path(cwd).is_absolute()
        or not Path(cwd).resolve().is_relative_to(root.resolve())
        or not isinstance(transcript, str)
        or not Path(transcript).is_absolute()
    ):
        raise ValueError("Invalid subagent hook scope")
    entries = extract(Path(transcript), session, agent, root)
    if not entries or not any(e["kind"] == "SUBAGENT_RESPONSE" for e in entries):
        raise ValueError("No verified delegated prompt and final report")
    final = payload.get("last_assistant_message")
    if (
        isinstance(final, str)
        and final.strip()
        and native.redact(final).strip() != entries[-1]["text"].strip()
    ):
        raise ValueError("Native subagent final and transcript disagree")
    with native.session_lock(root, session):
        paths = list((root / ".claude-logs").glob(f"*_{session}.md"))
        if len(paths) != 1 or paths[0].is_symlink():
            raise ValueError("Capture the parent prompt before its subagent report")
        metadata, primary = native.read_log(paths[0], session)
        old = metadata.get("_subagent_entries", [])
        if [e for e in old if e["agent_id"] == agent] == entries:
            return False
        previous = [e for e in old if e["agent_id"] == agent]
        keys = ("kind", "num", "agent_id", "timestamp", "text")
        if [{k: e[k] for k in keys} for e in entries[: len(previous)]] != [
            {k: e[k] for k in keys} for e in previous
        ]:
            raise ValueError("Delegated update would replace captured history")
        if len(previous) == len(entries):
            return False
        metadata["_subagent_entries"] = [e for e in old if e["agent_id"] != agent] + entries
        native.atomic_write(paths[0], native.render(metadata, primary))
    return True


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        capture(json.load(sys.stdin))
        print("{}")
    except Exception:
        print("Subagent logging failed; no transcript content was printed.", file=sys.stderr)
        raise SystemExit(1) from None
