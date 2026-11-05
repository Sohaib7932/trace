"""Read explicit primary Codex messages without collapsing same-turn human input.

This recovery reader is separate from the strict one-prompt-per-turn exporter.
Only observed user.text parts and actual final_answer messages are returned. It
does not discover transcripts, write logs, redact source text or invent turn IDs.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from codex_session_transcript import INJECTED, _path, _records

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")
_TURN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_AMBIENT = re.compile(
    r"<in-app-browser-context\b[^>]*>[\s\S]*?</in-app-browser-context>\s*"
)
_INJECTED_PREFIXES = (*INJECTED, "<external_codex_apps_open_page>")
_DELEGATED = (
    "agent_id",
    "agent_type",
    "agent_transcript_path",
    "isSidechain",
    "is_subagent",
)


def _aware_timestamp(row: dict) -> str:
    stamp = row.get("timestamp")
    try:
        # Keep recovery compatible with Python 3.10, which cannot parse bare Z.
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))  # noqa: FURB162
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        raise ValueError(
            "Codex conversation message lacks an aware timestamp"
        ) from None
    return stamp


def _turn(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _TURN_ID.fullmatch(value):
        raise ValueError("Invalid native Codex turn identifier")
    return value


def extract_conversation_records(
    paths: list[Path],
    session_id: str,
    cwd: Path,
    *,
    source_cwds: tuple[Path, ...] = (),
    end_ordinal_exclusive: int | None = None,
    include_unpaired_finals: bool = False,
) -> list[dict]:
    """Return real human messages and associated finals in original record order.

    Distinct message IDs remain distinct even when text and turn ID repeat.
    Exact message-ID replays are deduplicated; conflicting replays fail closed.
    A task_complete event is only corroborating evidence, never a final answer.
    Explicit opt-in retains real finals whose turn has no observed human input,
    labels them unpaired, and never manufactures a corresponding prompt.
    Headers, approved cwd aliases and pagination ancestors use the same validated
    chain reader as the existing exporter. No arbitrary path discovery occurs.
    """
    if (
        not isinstance(session_id, str)
        or not _TURN_ID.fullmatch(session_id)
        or not paths
        or any(
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.is_symlink()
            or not path.is_file()
            or path.suffix != ".jsonl"
            for path in paths
        )
        or not isinstance(cwd, Path)
        or not cwd.is_absolute()
        or type(include_unpaired_finals) is not bool
        or any(
            not isinstance(alias, Path) or not alias.is_absolute()
            for alias in source_cwds
        )
        or (
            end_ordinal_exclusive is not None
            and (type(end_ordinal_exclusive) is not int or end_ordinal_exclusive < 0)
        )
    ):
        raise ValueError("Invalid Codex conversation extraction context")
    scopes = {_path(value) for value in (cwd, *source_cwds)}
    current_cwd, current_turn = str(cwd), None
    last_ordinal = -1
    entries: list[dict] = []
    seen: dict[tuple[str, object], dict] = {}
    prompted: set[str] = set()
    latest_final: dict[str, str] = {}
    pending_mirrors: dict[str, list[str]] = {}
    turn_triggers: dict[str, str] = {}
    unpaired: list[dict] = []

    def add(row: dict, payload: dict, kind: str, turn: str, text: str) -> None:
        identifier = payload.get("id")
        if identifier is not None and (
            not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier)
        ):
            raise ValueError("Invalid native Codex message identifier")
        entry = {
            "kind": kind,
            "session_id": session_id,
            "turn_id": turn,
            "text": text,
            "timestamp": _aware_timestamp(row),
            "cwd": current_cwd,
            "capture_event": "CodexTranscriptRecovery",
            "source_record_ordinal": row["ordinal"],
            "source_record_type": row["type"],
        }
        if identifier is not None:
            entry["source_message_id"] = identifier
        if turn in turn_triggers:
            entry["source_turn_trigger"] = turn_triggers[turn]
        key = (
            ("message", identifier)
            if identifier is not None
            else ("ordinal", row["ordinal"])
        )
        previous = seen.get(key)
        if previous is not None:
            comparable = ("kind", "turn_id", "text", "timestamp", "cwd")
            if any(previous[field] != entry[field] for field in comparable):
                raise ValueError("Conflicting Codex conversation message replay")
            return
        seen[key] = entry
        if kind == "PROMPT":
            prompted.add(turn)
            entries.append(entry)
        else:
            for mirror in pending_mirrors.pop(turn, []):
                if mirror != text:
                    raise ValueError(
                        "Codex completion and final-answer evidence disagree"
                    )
            latest_final[turn] = text
            if turn in prompted:
                entries.append(entry)
            else:
                unpaired.append(entry)

    for row in _records(paths, session_id, scopes):
        ordinal = row.get("ordinal")
        if type(ordinal) is not int or ordinal < 0 or ordinal <= last_ordinal:
            raise ValueError("Codex conversation record ordinals are not ordered")
        if end_ordinal_exclusive is not None and ordinal >= end_ordinal_exclusive:
            break
        last_ordinal = ordinal
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if row.get("type") == "session_meta":
            if (
                payload.get("id") != session_id
                or _path(payload.get("cwd", "")) not in scopes
            ):
                raise ValueError("Codex conversation session or project does not match")
            if (
                not isinstance(payload.get("source"), str)
                or payload["source"]
                not in {"cli", "exec", "vscode", "app-server", "app_server"}
                or any(payload.get(key) for key in _DELEGATED)
            ):
                raise ValueError("Delegated or unknown Codex sources are excluded")
            current_cwd = payload["cwd"]
            continue
        if any(row.get(key) or payload.get(key) for key in _DELEGATED):
            continue
        if row.get("type") == "turn_context":
            turn = _turn(payload.get("turn_id"))
            if turn is not None:
                current_turn = turn
            if payload.get("cwd") is not None:
                value = payload["cwd"]
                if not isinstance(value, str) or _path(value) not in scopes:
                    raise ValueError(
                        "Codex conversation turn belongs to an unapproved project"
                    )
                current_cwd = value
            continue
        if row.get("type") == "event_msg":
            event = payload.get("type")
            turn = _turn(payload.get("turn_id")) or current_turn
            if event in {"task_started", "turn_started"}:
                current_turn = turn
                attribution = payload.get("turn_attribution")
                if (
                    turn is not None
                    and isinstance(attribution, dict)
                    and attribution.get("turn_trigger") == "resume_interrupted_task"
                ):
                    turn_triggers[turn] = "resume_interrupted_task"
            elif event == "task_complete" and turn is not None:
                text = payload.get("last_agent_message")
                if isinstance(text, str) and text.strip():
                    _aware_timestamp(row)
                    if turn in latest_final:
                        if latest_final[turn] != text:
                            raise ValueError(
                                "Codex completion and final-answer evidence disagree"
                            )
                    else:
                        pending_mirrors.setdefault(turn, []).append(text)
            continue
        if row.get("type") != "response_item" or payload.get("type") != "message":
            continue
        metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
        if not isinstance(metadata, dict):
            raise TypeError("Invalid Codex conversation message metadata")
        if any(metadata.get(key) for key in _DELEGATED):
            continue
        turn = _turn(metadata.get("turn_id") or payload.get("turn_id")) or current_turn
        if turn is None:
            continue  # Position/content is never a replacement for a native turn ID.
        content = payload.get("content")
        if not isinstance(content, list):
            continue
        if payload.get("role") == "user":
            kinds = metadata.get("content_item_kinds")
            if not isinstance(kinds, list):
                continue  # Require actual user.text provenance, not a role-only guess.
            parts = []
            for index, part in enumerate(content):
                if (
                    index >= len(kinds)
                    or kinds[index] != "user.text"
                    or not isinstance(part, dict)
                    or part.get("type") != "input_text"
                    or not isinstance(part.get("text"), str)
                ):
                    continue
                value = _AMBIENT.sub("", part["text"])
                if value.strip() and not value.lstrip().startswith(_INJECTED_PREFIXES):
                    parts.append(value)
            if parts:
                add(row, payload, "PROMPT", turn, "\n\n".join(parts))
        elif (
            payload.get("role") == "assistant"
            and payload.get("phase") == "final_answer"
            and payload.get("status") in {None, "completed"}
            and payload.get("recipient") in {None, "all"}
        ):
            parts = [
                part["text"]
                for part in content
                if isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ]
            text = "\n\n".join(parts)
            if text.strip():
                add(row, payload, "RESPONSE", turn, text)
    if include_unpaired_finals:
        for entry in unpaired:
            if entry["turn_id"] not in prompted:
                entries.append({**entry, "unpaired_final": True})
        entries.sort(key=lambda entry: entry["source_record_ordinal"])
    return entries
