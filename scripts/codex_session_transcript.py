"""Read explicitly selected primary Codex JSONL; never discover, write or infer replies."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
INJECTED = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<system-reminder>",
    "This is an app-generated request for a suggested next user message.",
)


def _path(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def _header(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        try:
            row = json.loads(next(stream))
        except (ValueError, StopIteration):
            raise ValueError("Invalid Codex transcript header") from None
    meta = row.get("payload", {})
    if row.get("type") != "session_meta" or not isinstance(meta, dict):
        raise ValueError("Missing Codex session metadata")
    if (
        meta.get("source") not in {"cli", "exec", "vscode", "app-server", "app_server"}
        if isinstance(meta.get("source"), str)
        else True
    ) or meta.get("agent_id"):
        raise ValueError("Delegated or unknown Codex sources are excluded")
    return {**meta, "_record_ordinal": row.get("ordinal")}


def _records(paths: list[Path], session: str, scopes: set[str]):
    segments = {}
    for path in paths:
        meta = _header(path)
        if meta.get("id") != session or _path(meta.get("cwd", "")) not in scopes:
            raise ValueError("Codex session or project does not match")
        ids = UUID.findall(path.stem)
        storage = ids[-1] if ids else session
        if storage in segments:
            raise ValueError("Ambiguous Codex transcript segments")
        segments[storage] = (path, meta)
    parents = {
        m[1]["history_base"]["thread_id"]
        for m in segments.values()
        if isinstance(m[1].get("history_base"), dict)
    }
    leaves = set(segments) - parents
    if len(leaves) != 1:
        raise ValueError("Select one complete Codex history chain")
    chain, seen = [], set()
    current = leaves.pop()
    while current not in seen:
        seen.add(current)
        if current not in segments:
            raise ValueError("A required Codex parent segment was not supplied")
        path, meta = segments[current]
        chain.append((path, meta))
        base = meta.get("history_base")
        if base is None:
            break
        if not isinstance(base, dict) or not isinstance(base.get("thread_id"), str):
            raise TypeError("Invalid Codex history checkpoint")
        if meta.get("_record_ordinal") != base.get("end_ordinal_exclusive"):
            raise ValueError(
                "Codex child ordinal does not match its history checkpoint"
            )
        current = base["thread_id"]
    else:
        raise ValueError("Cyclic Codex history chain")
    if len(chain) != len(segments):
        raise ValueError("Unrelated Codex history segment supplied")
    chain.reverse()
    for index, (path, _) in enumerate(chain):
        boundary = (
            chain[index + 1][1]["history_base"] if index + 1 < len(chain) else None
        )
        limit = boundary.get("end_byte_offset") if boundary else None
        ordinal = boundary.get("end_ordinal_exclusive") if boundary else None
        if boundary and (
            type(limit) is not int or limit < 0 or type(ordinal) is not int
        ):
            raise ValueError("Invalid Codex history cutoff")
        with path.open("rb") as stream:
            last_ordinal = None
            while limit is None or stream.tell() < limit:
                line = stream.readline()
                if not line:
                    if limit is not None and stream.tell() != limit:
                        raise ValueError("Incomplete Codex parent segment")
                    break
                if limit is not None and stream.tell() > limit:
                    raise ValueError("Codex history cutoff is not a record boundary")
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    if limit is None and not line.endswith(b"\n"):
                        break
                    raise ValueError("Invalid Codex transcript record") from None
                if not isinstance(row, dict):
                    raise TypeError("Invalid Codex transcript record")
                if ordinal is not None and (
                    type(row.get("ordinal")) is not int or row["ordinal"] >= ordinal
                ):
                    raise ValueError("Codex history ordinal cutoff does not match")
                if ordinal is not None:
                    if last_ordinal is not None and row["ordinal"] <= last_ordinal:
                        raise ValueError("Codex parent ordinals are not ordered")
                    last_ordinal = row["ordinal"]
                yield row
            if (
                ordinal is not None
                and (0 if last_ordinal is None else last_ordinal + 1) != ordinal
            ):
                raise ValueError("Codex byte and ordinal history checkpoints disagree")


def extract_codex_transcripts(
    paths: list[Path], session_id: str, cwd: Path, *, source_cwds: tuple[Path, ...] = ()
) -> list[dict]:
    """Support observed final_answer records and task_complete mirrors, without duplicates.

    All pagination ancestors must be explicitly supplied. Parent tails after the
    child's byte/ordinal checkpoint are discarded. Unknown assistant phases never
    become finals; tools, commentary and delegated records are not retained.
    """
    scopes = {_path(p) for p in (cwd, *source_cwds)}
    prompts, responses, completions, order = {}, {}, {}, []
    current_turn, current_cwd = None, str(cwd)

    def add(target: dict, turn: str, text: str, row: dict, kind: str) -> None:
        stamp = row.get("timestamp")
        try:
            # Python 3.10 does not accept a bare Z suffix.
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))  # noqa: FURB162
            if parsed.utcoffset() is None:
                raise ValueError()
        except (ValueError, AttributeError, TypeError):
            raise ValueError("Codex message lacks an aware timestamp") from None
        value = {
            "kind": kind,
            "turn_id": turn,
            "text": text,
            "timestamp": stamp,
            "cwd": current_cwd,
            "capture_event": "CodexTranscript",
        }
        previous = target.get(turn)
        if previous and previous["text"] != text:
            raise ValueError("Conflicting Codex messages for one turn")
        if not previous:
            target[turn] = value
            if kind == "PROMPT":
                order.append(turn)

    for row in _records(paths, session_id, scopes):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if row.get("type") == "turn_context":
            if payload.get("turn_id"):
                current_turn = payload["turn_id"]
            if payload.get("cwd"):
                if _path(payload["cwd"]) not in scopes:
                    raise ValueError("Codex turn belongs to an unapproved project")
                current_cwd = payload["cwd"]
            continue
        if row.get("type") == "event_msg":
            event = payload.get("type")
            turn = payload.get("turn_id") or current_turn
            if event in {"task_started", "turn_started"}:
                current_turn = turn
            elif (
                event == "user_message"
                and isinstance(payload.get("message"), str)
                and turn
            ):
                text = payload["message"]
                if text.strip() and not text.lstrip().startswith(INJECTED):
                    add(prompts, turn, text, row, "PROMPT")
            elif event == "task_complete" and turn:
                text = payload.get("last_agent_message")
                if isinstance(text, str) and text.strip():
                    add(completions, turn, text, row, "RESPONSE")
            continue
        if row.get("type") != "response_item" or payload.get("type") != "message":
            continue
        meta = payload.get("internal_chat_message_metadata_passthrough") or {}
        if not isinstance(meta, dict):
            raise TypeError("Invalid Codex message metadata")
        turn = meta.get("turn_id") or payload.get("turn_id") or current_turn
        if not isinstance(turn, str) or not turn:
            continue  # Do not invent an association from position or content.
        content = payload.get("content")
        if not isinstance(content, list):
            continue
        role = payload.get("role")
        if role == "user":
            kinds = meta.get("content_item_kinds")
            text = []
            for index, part in enumerate(content):
                if not isinstance(part, dict) or part.get("type") != "input_text":
                    continue
                value = part.get("text")
                if not isinstance(value, str):
                    continue
                if kinds is not None and (
                    not isinstance(kinds, list)
                    or index >= len(kinds)
                    or kinds[index] != "user.text"
                ):
                    continue
                value = re.sub(
                    r"<in-app-browser-context\b[^>]*>[\s\S]*?</in-app-browser-context>\s*",
                    "",
                    value,
                )
                if value.strip() and not value.lstrip().startswith(INJECTED):
                    text.append(value)
            if text:
                add(prompts, turn, "\n\n".join(text), row, "PROMPT")
        elif role == "assistant" and payload.get("phase") == "final_answer":
            text = [
                p["text"]
                for p in content
                if isinstance(p, dict)
                and p.get("type") == "output_text"
                and isinstance(p.get("text"), str)
            ]
            if text and "\n\n".join(text).strip():
                add(responses, turn, "\n\n".join(text), row, "RESPONSE")
    for turn, completion in completions.items():
        if turn in responses and responses[turn]["text"] != completion["text"]:
            raise ValueError("Codex completion and final-answer evidence disagree")
        responses.setdefault(turn, completion)
    result = []
    for turn in order:
        result.append(prompts[turn])
        if turn in responses:
            result.append(responses[turn])
    return result
