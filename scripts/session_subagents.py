"""Company-format delegated briefs and reports; no intermediate operations."""

from __future__ import annotations

import json
import re
from pathlib import Path

HEADING = "# Subagents\n"
MARKER = re.compile(
    r"\[CLAUDE_LOG_ENTRY type=(SUBAGENT_PROMPT|SUBAGENT_RESPONSE) num=(\d+) session=([A-Za-z0-9_-]+) agent=([A-Za-z0-9_-]+)\]\n"
)


def render(entries: list[dict], session: str) -> str:
    import codex_session_log as native

    if not entries:
        return ""
    lines = [HEADING.rstrip(), ""]
    groups = {}
    for entry in entries:
        groups.setdefault(entry["agent_id"], []).append(entry)
    for agent, values in sorted(
        groups.items(), key=lambda pair: native.instant(pair[1][0]["timestamp"])
    ):
        for entry in values:
            text = native.redact(entry["text"])
            lines.extend(
                [
                    f"[CLAUDE_LOG_ENTRY type={entry['kind']} num={entry['num']} session={session} agent={agent}]",
                    f"timestamp: {entry['timestamp']}",
                    f"chars: {len(text)}",
                    f"capture_event: {json.dumps(entry.get('capture_event', 'SubagentTranscript'))}",
                    "",
                    text,
                    "",
                ]
            )
    return "\n".join(lines)


def parse(text: str, session: str) -> list[dict]:
    import codex_session_log as native

    if not text.startswith(HEADING):
        raise ValueError("Invalid subagent section")
    cursor = len(HEADING)
    entries = []
    while cursor < len(text):
        while cursor < len(text) and text[cursor] == "\n":
            cursor += 1
        if cursor == len(text):
            break
        match = MARKER.match(text, cursor)
        if not match or match[3] != session:
            raise ValueError("Invalid subagent entry marker")
        cursor = match.end()
        fields = {}
        while True:
            end = text.find("\n", cursor)
            if end < 0:
                raise ValueError("Incomplete subagent metadata")
            line, cursor = text[cursor:end], end + 1
            if not line:
                break
            key, sep, value = line.partition(": ")
            if not sep:
                raise ValueError("Invalid subagent metadata")
            try:
                fields[key] = json.loads(value)
            except ValueError:
                fields[key] = value
        size = fields.get("chars")
        if type(size) is not int or size < 0 or cursor + size > len(text):
            raise ValueError("Invalid subagent entry length")
        native.instant(fields["timestamp"])
        entries.append(
            {
                **fields,
                "kind": match[1],
                "num": int(match[2]),
                "agent_id": match[4],
                "text": text[cursor : cursor + size],
            }
        )
        cursor += size
    return entries


def claude_entries(
    path: Path, session: str, agent: str, root: Path, *, stopped: bool = False
) -> list[dict]:
    import codex_session_log as native
    from claude_session_transcript import _human_text, _parts, _timestamp

    if not native.SAFE_ID.fullmatch(agent) or path.is_symlink():
        raise ValueError("Invalid delegated transcript")
    entries, pending, number = [], None, 0
    handback = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            raise ValueError("Incomplete delegated transcript") from None
        if row.get("type") not in {"user", "assistant"}:
            continue
        if (
            row.get("sessionId") != session
            or row.get("agentId") != agent
            or not Path(row.get("cwd", "")).resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("Delegated transcript identity or project mismatch")
        if row.get("isMeta") or row.get("isCompactSummary"):
            continue
        message = row.get("message", {})
        parts, kinds = _parts(message)
        if row["type"] == "user":
            if "tool_result" in kinds:
                if not handback:
                    pending = None
                continue
            text = _human_text(parts)
            if not text or text.startswith("[Request interrupted"):
                continue
            if pending:
                entries.append(pending)
            number += 1
            entries.append(
                {
                    "kind": "SUBAGENT_PROMPT",
                    "num": number,
                    "agent_id": agent,
                    "timestamp": _timestamp(row),
                    "text": native.redact(text),
                }
            )
            pending, handback = None, False
        elif number:
            content = message.get("content", [])
            reports = (
                [
                    b.get("input", {}).get("message")
                    for b in content
                    if isinstance(b, dict)
                    and b.get("type") == "tool_use"
                    and b.get("name") == "SubagentHandback"
                ]
                if isinstance(content, list)
                else []
            )
            text = next((v for v in reports if isinstance(v, str) and v.strip()), None)
            if text:
                handback = True
            elif handback:
                continue
            elif kinds <= {"text", "thinking", "redacted_thinking"} and message.get(
                "stop_reason"
            ) in {"end_turn", "stop_sequence"}:
                text = "\n\n".join(parts)
            else:
                pending = None
                continue
            if text:
                pending = {
                    "kind": "SUBAGENT_RESPONSE",
                    "num": number,
                    "agent_id": agent,
                    "timestamp": _timestamp(row),
                    "text": native.redact(text),
                }
    if pending:
        entries.append(pending)
    return entries


def collect_claude(transcript: Path, session: str, root: Path) -> list[dict]:
    directory = transcript.parent / session / "subagents"
    if directory.is_symlink():
        raise ValueError("Delegated transcript directory cannot be a symlink")
    entries = []
    for path in sorted(directory.glob("agent-*.jsonl")):
        entries.extend(claude_entries(path, session, path.stem.removeprefix("agent-"), root))
    return entries
