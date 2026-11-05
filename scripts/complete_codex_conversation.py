"""Explicit, backed-up completion of one existing Codex conversation log.

Never installed as a hook. Native hooks remain responsible for new prompt/final
events. This command reconciles owner-selected primary JSONL with an existing
canonical file, preserving genuine entries and labelling retrospective recovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

import codex_session_log as native
from agent_session_logs import _common, project_root
from codex_conversation_records import extract_conversation_records

RESOURCE = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?![0-9a-f])"
)
URL = re.compile(r"https?://[^\s<>\"'`]+")


def comparison_text(value: str, roots: tuple[Path, ...]) -> str:
    """Compare known publication sanitization, without fuzzy text matching."""
    value = native.redact(value.replace("\r\n", "\n").replace("\r", "\n"))
    value = unquote(URL.sub("[URL REDACTED]", value))
    value = re.sub(r"/{2,}", "/", value.replace("\\", "/"))
    for root in sorted(roots, key=lambda path: len(str(path)), reverse=True):
        value = value.replace(root.as_posix(), "<TRACE_REPOSITORY>")
    value = value.replace(Path.home().as_posix() + "/.codex", "<CODEX_HOME>")
    value = value.replace(Path.home().as_posix(), "<USER_HOME>")
    value = value.replace("<USER_HOME>/.codex", "<CODEX_HOME>")
    value = RESOURCE.sub("[RESOURCE ID REDACTED]", value)
    value = value.replace("[PRIVATE CONTACT REDACTED]", "[email redacted]")
    # Historical publication copies replaced whole callback/opaque URLs.
    # Matching still requires the identical native turn, kind and remaining text.
    value = URL.sub("[URL REDACTED]", value)
    return re.sub(r"\s+", " ", value).strip()


def _safe_recovered_text(value: str, roots: tuple[Path, ...]) -> str:
    value = native.redact(value.replace("\r\n", "\n").replace("\r", "\n"))
    for root in sorted(roots, key=lambda path: len(str(path)), reverse=True):
        for spelling in (str(root), root.as_posix()):
            value = value.replace(spelling, "<TRACE_REPOSITORY>")
    for spelling in (str(Path.home() / ".codex"), (Path.home() / ".codex").as_posix()):
        value = value.replace(spelling, "<CODEX_HOME>")
    for spelling in (str(Path.home()), Path.home().as_posix()):
        value = value.replace(spelling, "<USER_HOME>")
    # Resource identifiers in conversation prose are not needed for attribution;
    # actual source/session/turn identifiers stay intact in structured provenance.
    value = RESOURCE.sub("[RESOURCE ID REDACTED]", value)
    value = re.sub(
        r"([?&#][A-Za-z_][A-Za-z0-9_-]*=)[^&#\s<>\"')`]+",
        r"\1[REDACTED]",
        value,
    )
    return "\n".join(line.rstrip(" \t") for line in value.splitlines()).strip()


def reconcile(
    records: list[dict],
    existing: list[dict],
    historical: list[dict],
    roots: tuple[Path, ...],
) -> tuple[list[dict], dict]:
    """Keep actual input messages separate, including same-turn human replies."""
    by_turn: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        by_turn[(record["kind"], record["turn_id"])].append(index)
    selected, matched, retained = {}, set(), []
    # Prefer the active native file over an older, already-sanitized snapshot.
    for origin, entries in (
        ("canonical", existing),
        ("historical_snapshot", historical),
    ):
        for entry in entries:
            key = (entry["kind"], entry["turn_id"])
            candidates = by_turn.get(key, [])
            source_present = bool(candidates)
            ordinal = entry.get("source_record_ordinal")
            if ordinal is not None:
                candidates = [
                    i
                    for i in candidates
                    if records[i]["source_record_ordinal"] == ordinal
                ]
            if entry.get("source_message_id"):
                candidates = [
                    i
                    for i in candidates
                    if records[i].get("source_message_id") == entry["source_message_id"]
                ]
            target = comparison_text(entry["text"], roots)
            candidates = [
                i
                for i in candidates
                if (
                    entry["text"] == _safe_recovered_text(records[i]["text"], roots)
                    if entry.get("capture_event") == "CodexTranscriptRecovery"
                    else comparison_text(records[i]["text"], roots) == target
                )
            ]
            if len(candidates) > 1:
                raise ValueError(
                    "Ambiguous repeated input; preserving the existing log"
                )
            if not candidates:
                # Pagination may retain the primary conversation while trimming
                # an interrupted parent tail. Its genuine native log survives.
                if origin == "canonical" and not source_present:
                    preserved = dict(entry)
                    preserved["source_coverage"] = "native_hook_only"
                    preserved["recovery_preserved_from"] = origin
                    retained.append(preserved)
                    continue
                if origin == "canonical":
                    raise ValueError(
                        "An existing native entry conflicts with its source"
                    )
                raise ValueError("A historical entry has no unambiguous source match")
            index = candidates[0]
            if index in matched and origin == "canonical":
                raise ValueError("Existing log duplicates a source message")
            if index not in selected:
                selected[index] = dict(entry)
                if entry.get("capture_event") != "CodexTranscriptRecovery":
                    selected[index].setdefault("recovery_preserved_from", origin)
            matched.add(index)

    result, primary_numbers = [], {}
    prompt_number = 0
    ordered_sources = [
        (source, selected.get(index)) for index, source in enumerate(records)
    ]
    ordered_sources.extend((entry, entry) for entry in retained)
    ordered_sources.sort(
        key=lambda pair: (
            native.instant(pair[0]["timestamp"]),
            pair[0].get("source_record_ordinal", float("inf")),
        )
    )
    for source, selected_entry in ordered_sources:
        entry = selected_entry
        if entry is None:
            entry = dict(source)
            entry["text"] = _safe_recovered_text(source["text"], roots)
            entry["timestamp_source"] = "transcript.timestamp"
            entry["capture_event"] = "CodexTranscriptRecovery"
        elif entry.get("capture_event") != "CodexTranscriptRecovery":
            entry["original_exchange_number"] = entry.get(
                "original_exchange_number", entry["num"]
            )
        for field in (
            "source_message_id",
            "source_record_ordinal",
            "source_record_type",
            "source_turn_trigger",
        ):
            if source.get(field) is not None:
                entry[field] = source[field]
        if source.get("source_record_ordinal") is not None:
            entry["source_timestamp"] = source["timestamp"]
        entry["session_id"] = source["session_id"]
        if entry["kind"] == "PROMPT":
            prompt_number += 1
            entry["num"] = prompt_number
            entry["is_turn_continuation"] = entry["turn_id"] in primary_numbers
            primary_numbers.setdefault(entry["turn_id"], prompt_number)
        else:
            if entry["turn_id"] not in primary_numbers:
                if not source.get("unpaired_final"):
                    raise ValueError("A final answer has no genuine human input")
                entry["num"] = 0
                entry["unpaired_final"] = True
            else:
                entry["num"] = primary_numbers[entry["turn_id"]]
        result.append(entry)
    summary = {
        "source_prompts": sum(e["kind"] == "PROMPT" for e in records),
        "source_finals": sum(e["kind"] == "RESPONSE" for e in records),
        "same_turn_additional_inputs": sum(
            bool(e.get("is_turn_continuation")) for e in result
        ),
        "unpaired_actual_finals": sum(bool(e.get("unpaired_final")) for e in result),
        "native_only_entries_preserved": len(retained),
        "canonical_prompts": sum(e["kind"] == "PROMPT" for e in result),
        "canonical_finals": sum(e["kind"] == "RESPONSE" for e in result),
        "preserved_native_entries": len(existing),
        "preserved_historical_entries": len(historical),
        "recovered_entries": len(records) - len(matched),
        "all_source_records_accounted_for": len(result) == len(records) + len(retained),
    }
    return result, summary


def _verified_backup(path: Path, directory: Path) -> Path:
    if directory.is_symlink():
        raise ValueError("A linked backup directory is not permitted")
    directory = directory.resolve()
    if directory.is_relative_to(project_root(path.parent)):
        raise ValueError("The private backup must be outside the repository")
    if directory.is_symlink():
        raise ValueError("A linked backup directory is not permitted")
    directory.mkdir(parents=True, exist_ok=True)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    backup = directory / f"{path.stem}.before-completion-{digest}.md"
    if backup.exists():
        if backup.is_symlink() or backup.read_bytes() != data:
            raise ValueError("The existing backup does not match")
    else:
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if backup.read_bytes() != data:
            raise ValueError("Backup verification failed")
    return backup


def complete(
    paths: list[Path],
    session: str,
    root: Path,
    canonical: Path,
    *,
    historical_paths: tuple[Path, ...] = (),
    source_cwds: tuple[Path, ...] = (),
    backup_dir: Path | None = None,
    apply: bool = False,
    end_ordinal_exclusive: int | None = None,
) -> dict:
    if canonical.is_symlink() or (root / ".claude-logs").is_symlink():
        raise ValueError("Linked canonical logs are not permitted")
    root, canonical = root.resolve(), canonical.resolve()
    if project_root(root) != root or canonical.parent != root / ".claude-logs":
        raise ValueError("Select the canonical log inside this checkout")
    if (
        not native.SAFE_ID.fullmatch(session)
        or not canonical.is_file()
        or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_" + re.escape(session) + r"\.md",
            canonical.name,
        )
    ):
        raise ValueError("An existing genuine session log is required")
    for alias in source_cwds:
        if _common(project_root(alias)) != _common(root):
            raise ValueError(
                "An approved source checkout belongs to another repository"
            )
    if any(p.is_symlink() or not p.is_file() for p in paths):
        raise ValueError("Select explicit unlinked JSONL sources")
    records = extract_conversation_records(
        paths,
        session,
        root,
        source_cwds=source_cwds,
        end_ordinal_exclusive=end_ordinal_exclusive,
        include_unpaired_finals=True,
    )
    if not records:
        raise ValueError("No genuine primary conversation was found")
    with native.session_lock(root, session):
        metadata, old = native.read_log(canonical, session)
        historical = []
        for path in historical_paths:
            if path.is_symlink() or path.resolve().parent != root / ".claude-logs":
                raise ValueError(
                    "Historical snapshots must be inside the same log directory"
                )
            if path.resolve() == canonical:
                raise ValueError("The canonical file is not a historical snapshot")
            _, previous = native.read_log(path, session)
            historical.extend(previous)
        roots = (root, *source_cwds)
        entries, summary = reconcile(records, old, historical, roots)
        comparable = (
            "kind",
            "turn_id",
            "text",
            "timestamp",
            "num",
            "source_message_id",
            "source_record_ordinal",
            "is_turn_continuation",
            "source_timestamp",
            "source_turn_trigger",
            "unpaired_final",
            "source_coverage",
            "original_exchange_number",
            "recovery_preserved_from",
            "provenance",
            "reconstructed",
        )
        old_view = [{k: e.get(k) for k in comparable} for e in old]
        new_view = [{k: e.get(k) for k in comparable} for e in entries]
        if old_view == new_view:
            return {"status": "unchanged", **summary}
        if not apply:
            return {"status": "ready", **summary}
        if backup_dir is None:
            raise ValueError("An explicit private backup directory is required")
        backup = _verified_backup(canonical, backup_dir)
        metadata = {
            **metadata,
            "agent_name": "OpenAI Codex",
            "capture_mechanism": "native Codex hooks plus explicit retrospective JSONL recovery",
            "conversation_completion_schema": 1,
            "conversation_completed_at": native.now(),
            "entry_order": "chronological",
            "numbering": "human input sequence; finals reference the first input of their native turn",
            "retrospective_recovery": True,
            "recovery_source_segment_count": len(paths),
            "recovery_source_cutoff_ordinal_exclusive": end_ordinal_exclusive,
            "historical_snapshot_files": [p.name for p in historical_paths],
            "historical_snapshot_policy": "preserved dated snapshots; deduplicate by native source/session/turn identity",
            "recovery_verification": summary,
        }
        rendered = native.render(metadata, entries)
        _, preview_entries = native.parse_log(rendered, session)
        preview_view = [{k: e.get(k) for k in comparable} for e in preview_entries]
        if preview_view != new_view:
            raise ValueError(
                "Rendered conversation verification failed before replacement"
            )
        native.atomic_write(canonical, rendered)
        verified_meta, verified_entries = native.read_log(canonical, session)
        verified_view = [{k: e.get(k) for k in comparable} for e in verified_entries]
        if verified_view != new_view or verified_meta.get("agent") != "codex":
            raise ValueError(
                "Written conversation verification failed; private backup retained"
            )
        return {"status": "written", "backup_verified": backup.is_file(), **summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, action="append", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--canonical-log", type=Path, required=True)
    parser.add_argument("--historical-log", type=Path, action="append", default=[])
    parser.add_argument("--source-cwd", type=Path, action="append", default=[])
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--end-ordinal-exclusive", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = complete(
            args.transcript,
            args.session_id,
            args.project,
            args.canonical_log,
            historical_paths=tuple(args.historical_log),
            source_cwds=tuple(args.source_cwd),
            backup_dir=args.backup_dir,
            apply=args.apply,
            end_ordinal_exclusive=args.end_ordinal_exclusive,
        )
    except (OSError, ValueError, TypeError, KeyError):
        print(
            json.dumps(
                {"status": "blocked", "reason": "conversation_completion_failed_safely"}
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
