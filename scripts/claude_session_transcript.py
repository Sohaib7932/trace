"""Read one owner-selected Claude Code transcript; never write or discover files.

The local installation has no genuine project JSONL available to verify historical
final-message conventions. Explicit ``end_turn`` / ``stop_sequence`` metadata is
therefore required for historical final answers. A native Stop hook may confirm
the last text-only, otherwise unfinished assistant message through ``stop_event``.
This parser does not redact text: the shared canonical writer must do that.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")
_INJECTED_BLOCKS = re.compile(
    r"<(ide_opened_file|ide_selection|system-reminder|environment_context)>"
    r"[\s\S]*?</\1>\s*"
)
_PASTE_WRAPPER = re.compile(r'</?pasted_content(?:\s+id="[^"]*")?\s*>\n?')
_NONHUMAN_PREFIXES = (
    "<command-name>",
    "<local-command",
    "<task-notification>",
    "<system-reminder>",
    "<environment_context>",
    "<ide_opened_file>",
    "<ide_selection>",
    "Caveat:",
    "Another Claude session sent a message",
    "This session is being continued from a previous conversation",
    "# AGENTS.md instructions",
)
_FINAL_REASONS = frozenset({"end_turn", "stop_sequence"})
_SUBAGENT_FIELDS = (
    "isSidechain",
    "is_subagent",
    "agentId",
    "agent_id",
    "agent_type",
    "agent_transcript_path",
)
_META_FIELDS = ("isMeta", "isCompactSummary", "is_summary")


def _scope_path(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _timestamp(row: dict) -> str:
    value = row.get("timestamp")
    if not isinstance(value, str):
        raise ValueError("Claude transcript message has no valid aware timestamp")  # noqa: TRY004
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162 (Python 3.10)
    except ValueError:
        raise ValueError(
            "Claude transcript message has no valid aware timestamp"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Claude transcript message has no valid aware timestamp")
    return value


def _source_id(row: dict) -> str:
    value = row.get("uuid")
    if isinstance(value, str) and _IDENTIFIER.fullmatch(value):
        return value
    message = row.get("message", {})
    value = message.get("id") if isinstance(message, dict) else None
    if isinstance(value, str) and _IDENTIFIER.fullmatch(value):
        # This is an explicit stable fallback from a source identifier, never a
        # fabricated native Claude turn UUID or a hash of private conversation text.
        return "inferred-" + hashlib.sha256(value.encode("utf-8")).hexdigest()
    raise ValueError("Claude transcript message has no stable source identifier")


def _parts(message: dict) -> tuple[list[str], set[str]]:
    content = message.get("content")
    if isinstance(content, str):
        return [content], {"text"}
    if not isinstance(content, list):
        return [], set()
    text, kinds = [], set()
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str):
            continue
        kinds.add(block["type"])
        if block["type"] == "text" and isinstance(block.get("text"), str):
            text.append(block["text"])
    return text, kinds


def _human_text(parts: list[str]) -> str:
    retained = []
    for part in parts:
        text = _PASTE_WRAPPER.sub("", _INJECTED_BLOCKS.sub("", part))
        if text.strip() and not text.lstrip().startswith(_NONHUMAN_PREFIXES):
            retained.append(text)
    return "\n\n".join(retained)


def extract_claude_transcript(
    path: Path, session_id: str, cwd: Path, *, stop_event: bool = False
) -> list[dict]:
    """Extract genuine prompts and proven final text from this one scoped JSONL.

    Invalid identity/scope/timestamps fail closed with content-free errors. A
    partially appended final JSONL line is ignored, not repaired. Tool, context,
    summary and delegated messages are excluded. ``stop_event`` is valid only for
    an actual native primary-session Stop notification, never a historical guess.
    """
    if (
        not isinstance(session_id, str)
        or not _IDENTIFIER.fullmatch(session_id)
        or not isinstance(path, Path)
        or not isinstance(cwd, Path)
        or not cwd.is_absolute()
        or type(stop_event) is not bool
    ):
        raise ValueError("Invalid Claude transcript extraction context")
    if any(
        part.casefold() == "subagents" for part in path.parts
    ) or path.stem.startswith("agent-"):
        raise ValueError("Delegated Claude transcripts are excluded")

    entries: list[dict] = []
    current_turn: str | None = None
    pending: dict | None = None
    confirmed = False
    incomplete_tail = False
    source_turns: dict[str, str | None] = {}
    seen: dict[str, dict] = {}
    expected_cwd = _scope_path(cwd)

    def flush(*, native_stop: bool = False) -> None:
        nonlocal pending, confirmed
        if pending is not None and (confirmed or native_stop):
            entries.append(pending)
        pending, confirmed = None, False

    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if not line.endswith("\n"):
                    incomplete_tail = True
                    break  # An in-flight append has no usable evidence yet.
                raise ValueError("Malformed Claude transcript JSONL") from None
            if not isinstance(row, dict):
                raise ValueError("Malformed Claude transcript record")  # noqa: TRY004
            if any(row.get(field) for field in _SUBAGENT_FIELDS):
                continue
            kind = row.get("type")
            if kind not in {"user", "assistant"}:
                continue
            if any(row.get(field) for field in _META_FIELDS):
                continue
            row_cwd = row.get("cwd")
            if (
                row.get("sessionId") != session_id
                or not isinstance(row_cwd, str)
                or not Path(row_cwd).is_absolute()
                or _scope_path(row_cwd) != expected_cwd
            ):
                raise ValueError("Claude transcript session or project does not match")
            message = row.get("message")
            if not isinstance(message, dict) or message.get("role", kind) != kind:
                raise ValueError("Malformed Claude transcript message")
            parts, kinds = _parts(message)
            parent = row.get("parentUuid")
            inherited = (
                source_turns.get(parent) if isinstance(parent, str) else current_turn
            )
            source = _source_id(row)
            if source in seen:
                if seen[source] != row:
                    raise ValueError("Conflicting Claude transcript source identifiers")
                continue
            seen[source] = row
            source_turns[source] = inherited

            if kind == "user":
                if any(
                    part.lstrip().startswith("[Request interrupted by user")
                    for part in parts
                ):
                    pending, confirmed, current_turn = None, False, None
                    continue
                if "tool_result" in kinds:
                    pending, confirmed = None, False
                    continue
                text = _human_text(parts)
                if not text.strip():
                    continue
                flush()
                current_turn = source
                source_turns[source] = current_turn
                entries.append(
                    {
                        "kind": "PROMPT",
                        "timestamp": _timestamp(row),
                        "text": text,
                        "turn_id": current_turn,
                        "capture_event": "ClaudeTranscript",
                    }
                )
                continue

            # A forked or orphaned assistant message cannot answer the current
            # prompt merely because it happens to appear later in this file.
            if current_turn is None or (
                isinstance(parent, str) and inherited != current_turn
            ):
                if not confirmed:
                    pending = None
                continue
            source_turns[source] = current_turn
            pending, confirmed = None, False
            if kinds - {"text", "thinking", "redacted_thinking"}:
                continue
            text = "\n\n".join(part for part in parts if part.strip())
            reason = message.get("stop_reason", row.get("stop_reason"))
            if not text.strip() or (
                reason is not None and reason not in _FINAL_REASONS
            ):
                continue
            pending = {
                "kind": "RESPONSE",
                "timestamp": _timestamp(row),
                "text": text,
                "turn_id": current_turn,
                "capture_event": "ClaudeTranscript",
            }
            confirmed = reason in _FINAL_REASONS
    flush(native_stop=stop_event and not incomplete_tail)
    return entries
