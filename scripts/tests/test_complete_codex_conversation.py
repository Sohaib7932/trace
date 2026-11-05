"""Explicit recovery uses synthetic logs, transcripts and backups in temp only."""

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "complete_codex_conversation_tests", SCRIPTS / "complete_codex_conversation.py"
)
completion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(completion)
native = completion.native
SESSION = "11111111-1111-4111-8111-111111111111"
STAMP = "2026-11-05T10:00:00Z"
IDENTITY = {
    "author": "Synthetic Developer",
    "github_user": "fixture-user",
    "git_email": "f***@example.test",
    "git_identity_fingerprint": "fixture-fingerprint",
    "github_identity_verified_at": STAMP,
}


def identity(root, previous):
    return IDENTITY.copy()


class ConversationCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "Trace fixture"
        self.root.mkdir()
        self.transcript = self.base / f"rollout-{SESSION}.jsonl"
        self.backups = self.base / "private backups"
        self.rows = [
            {
                "type": "session_meta",
                "timestamp": STAMP,
                "ordinal": 0,
                "payload": {"id": SESSION, "cwd": str(self.root), "source": "vscode"},
            }
        ]
        self.canonical, _ = native.capture(
            self.payload("UserPromptSubmit", "Original prompt"), self.root, identity
        )
        self.protected = {}
        for name in (".env", "trace.db", "trace.db.backup", "private-report.md"):
            path = self.root / name
            path.write_bytes(b"synthetic-protected-local-work")
            self.protected[path] = (path.read_bytes(), path.stat().st_mtime_ns)
        self.addCleanup(self.assert_protected)

    def assert_protected(self):
        for path, (data, stamp) in self.protected.items():
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, stamp)

    def payload(self, event, text, *, turn="turn-1", timestamp=STAMP):
        field = "prompt" if event == "UserPromptSubmit" else "last_assistant_message"
        return {
            "hook_event_name": event,
            "session_id": SESSION,
            "turn_id": turn,
            "cwd": str(self.root),
            "timestamp": timestamp,
            "model": "fixture-native-model",
            field: text,
        }

    def message(self, text, message_id, *, turn="turn-1", role="user", timestamp=STAMP):
        ordinal = len(self.rows)
        metadata = {"turn_id": turn}
        if role == "user":
            metadata["content_item_kinds"] = ["user.text"]
        payload = {
            "type": "message",
            "role": role,
            "id": message_id,
            "internal_chat_message_metadata_passthrough": metadata,
            "content": [
                {
                    "type": "input_text" if role == "user" else "output_text",
                    "text": text,
                }
            ],
        }
        if role == "assistant":
            payload.update(phase="final_answer", status="completed")
        self.rows.append(
            {
                "type": "response_item",
                "timestamp": timestamp,
                "ordinal": ordinal,
                "payload": payload,
            }
        )
        return ordinal

    def write(self):
        self.transcript.write_text(
            "".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8"
        )

    def records(self):
        result = []
        for row in self.rows[1:]:
            value = row["payload"]
            result.append(
                {
                    "session_id": SESSION,
                    "kind": "PROMPT" if value["role"] == "user" else "RESPONSE",
                    "turn_id": value["internal_chat_message_metadata_passthrough"][
                        "turn_id"
                    ],
                    "text": value["content"][0]["text"],
                    "timestamp": row["timestamp"],
                    "cwd": str(self.root),
                    "capture_event": "CodexTranscriptRecovery",
                    "source_message_id": value["id"],
                    "source_record_ordinal": row["ordinal"],
                    "source_record_type": "response_item",
                }
            )
        return result

    def complete(self, *, apply=False, historical_paths=(), backup_dir=None, **options):
        self.write()
        before = self.transcript.read_bytes()
        with (
            patch.object(completion, "project_root", return_value=self.root),
            patch.object(completion, "_common", return_value=self.base / "fixture-git"),
        ):
            result = completion.complete(
                [self.transcript],
                SESSION,
                self.root,
                self.canonical,
                historical_paths=historical_paths,
                backup_dir=self.backups if backup_dir is None else backup_dir,
                apply=apply,
                **options,
            )
        self.assertEqual(self.transcript.read_bytes(), before)
        return result

    def test_same_turn_original_ui_and_steering_preserve_native_fields_and_genuine_order(
        self,
    ):
        _, old = native.read_log(self.canonical, SESSION)
        preserved = dict(old[0])
        self.message("Original prompt", "human-1")
        reply = '<send_user_message_question_reply>[{"answer":"Approved"}]</send_user_message_question_reply>'
        self.message(reply, "human-2")
        self.message("Continue safely", "human-3")
        self.message("Actual final", "assistant-1", role="assistant")
        entries, summary = completion.reconcile(self.records(), old, [], (self.root,))
        for field in (
            "text",
            "timestamp",
            "turn_id",
            "capture_event",
            "timestamp_source",
            "model",
            "cwd",
        ):
            self.assertEqual(entries[0][field], preserved[field])
        self.assertEqual(
            [e["text"] for e in entries],
            ["Original prompt", reply, "Continue safely", "Actual final"],
        )
        self.assertEqual([e["num"] for e in entries], [1, 2, 3, 1])
        self.assertEqual(
            [e.get("is_turn_continuation") for e in entries[:3]], [False, True, True]
        )
        self.assertEqual(
            [e["source_message_id"] for e in entries],
            ["human-1", "human-2", "human-3", "assistant-1"],
        )
        self.assertEqual(summary["same_turn_additional_inputs"], 2)
        self.assertTrue(summary["all_source_records_accounted_for"])
        self.assertEqual(entries[1]["capture_event"], "CodexTranscriptRecovery")

    def test_overlapping_historical_snapshot_never_replaces_canonical_native_provenance(
        self,
    ):
        self.message("Original prompt", "human-1")
        _, old = native.read_log(self.canonical, SESSION)
        historical = [
            {
                **old[0],
                "timestamp": "2026-11-05T09:59:59Z",
                "capture_event": "HistoricalSnapshot",
                "model": "older-model",
            }
        ]
        entries, summary = completion.reconcile(
            self.records(), old, historical, (self.root,)
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["timestamp"], old[0]["timestamp"])
        self.assertEqual(entries[0]["capture_event"], "UserPromptSubmit")
        self.assertEqual(entries[0]["model"], "fixture-native-model")
        self.assertEqual(entries[0]["recovery_preserved_from"], "canonical")
        self.assertEqual(summary["preserved_historical_entries"], 1)

    def test_actual_identical_inputs_with_distinct_ids_survive_ordinal_reconciliation(
        self,
    ):
        self.message("Original prompt", "human-1")
        self.message("continue", "human-2")
        self.message("continue", "human-3")
        _, old = native.read_log(self.canonical, SESSION)
        entries, _ = completion.reconcile(self.records(), old, [], (self.root,))
        self.assertEqual(
            [e["text"] for e in entries], ["Original prompt", "continue", "continue"]
        )
        self.assertEqual([e["source_record_ordinal"] for e in entries], [1, 2, 3])
        replay, _ = completion.reconcile(self.records(), entries, [], (self.root,))
        self.assertEqual(
            [e["source_message_id"] for e in replay], ["human-1", "human-2", "human-3"]
        )
        self.assertEqual([e["num"] for e in replay], [1, 2, 3])

    def test_conflicting_native_entry_fails_closed_before_backup_or_write(self):
        self.message("Conflicting source prompt", "human-1")
        before, stamp = self.canonical.read_bytes(), self.canonical.stat().st_mtime_ns
        with (
            patch.object(completion, "_verified_backup") as backup,
            patch.object(native, "atomic_write") as writer,
            self.assertRaises(ValueError),
        ):
            self.complete(apply=True)
        backup.assert_not_called()
        writer.assert_not_called()
        self.assertEqual(self.canonical.read_bytes(), before)
        self.assertEqual(self.canonical.stat().st_mtime_ns, stamp)

    def test_tied_repeated_input_without_source_identity_fails_closed(self):
        self.message("Original prompt", "human-1")
        self.message("Original prompt", "human-2")
        _, old = native.read_log(self.canonical, SESSION)
        with self.assertRaisesRegex(ValueError, "Ambiguous repeated input"):
            completion.reconcile(self.records(), old, [], (self.root,))

    def test_native_only_entry_outside_active_jsonl_chain_is_preserved_without_source_claim(
        self,
    ):
        native.capture(
            self.payload(
                "UserPromptSubmit", "Genuine native-only prompt", turn="old-branch"
            ),
            self.root,
            identity,
        )
        self.message("Original prompt", "human-1")
        _, old = native.read_log(self.canonical, SESSION)
        preserved = next(entry for entry in old if entry["turn_id"] == "old-branch")
        entries, _ = completion.reconcile(self.records(), old, [], (self.root,))
        native_only = [entry for entry in entries if entry["turn_id"] == "old-branch"]
        self.assertEqual(len(native_only), 1)
        for key in (
            "text",
            "timestamp",
            "turn_id",
            "capture_event",
            "timestamp_source",
            "model",
        ):
            self.assertEqual(native_only[0][key], preserved[key])
        self.assertEqual(native_only[0]["source_coverage"], "native_hook_only")
        self.assertNotIn("source_message_id", native_only[0])
        self.assertNotIn("source_record_ordinal", native_only[0])

    def test_actual_unpaired_final_is_saved_without_fabricating_a_prompt(self):
        self.message(
            "Actual orphan final", "assistant-old", role="assistant", turn="old-turn"
        )
        self.message("Original prompt", "human-1")
        self.message("Actual final", "assistant-1", role="assistant")
        result = self.complete(apply=True)
        self.assertEqual(result["status"], "written")
        _, entries = native.read_log(self.canonical, SESSION)
        unpaired = [entry for entry in entries if entry.get("unpaired_final")]
        self.assertEqual(len(unpaired), 1)
        self.assertEqual(unpaired[0]["kind"], "RESPONSE")
        self.assertEqual(unpaired[0]["num"], 0)
        self.assertEqual(unpaired[0]["turn_id"], "old-turn")
        self.assertEqual(unpaired[0]["source_message_id"], "assistant-old")
        self.assertFalse(
            any(e["kind"] == "PROMPT" and e["turn_id"] == "old-turn" for e in entries)
        )

    def test_dry_run_does_not_create_backup_or_change_canonical_log(self):
        self.message("Original prompt", "human-1")
        self.message("Actual final", "assistant-1", role="assistant")
        before, stamp = self.canonical.read_bytes(), self.canonical.stat().st_mtime_ns
        result = self.complete()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.canonical.read_bytes(), before)
        self.assertEqual(self.canonical.stat().st_mtime_ns, stamp)
        self.assertFalse(self.backups.exists())

    def test_apply_verifies_backup_and_preserves_native_entry_metadata(self):
        self.message("Original prompt", "human-1")
        self.message("Actual final", "assistant-1", role="assistant")
        before = self.canonical.read_bytes()
        _, old = native.read_log(self.canonical, SESSION)
        result = self.complete(apply=True)
        self.assertEqual(result["status"], "written")
        self.assertTrue(result["backup_verified"])
        backups = list(self.backups.glob("*.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertIn(hashlib.sha256(before).hexdigest(), backups[0].name)
        self.assertFalse(backups[0].is_relative_to(self.root))
        metadata, entries = native.read_log(self.canonical, SESSION)
        for key in (
            "text",
            "timestamp",
            "turn_id",
            "capture_event",
            "timestamp_source",
            "model",
            "cwd",
        ):
            self.assertEqual(entries[0][key], old[0][key])
        self.assertEqual(entries[1]["capture_event"], "CodexTranscriptRecovery")
        self.assertEqual(metadata["capture_schema"], 2)
        self.assertTrue(metadata["retrospective_recovery"])
        self.assertEqual(metadata["entry_order"], "chronological")
        self.assertIn("explicit retrospective", metadata["capture_mechanism"])

    def test_identical_replay_has_no_write_no_new_backup_and_no_mtime_change(self):
        self.message("Original prompt", "human-1")
        self.message("Actual final", "assistant-1", role="assistant")
        self.complete(apply=True)
        before, stamp = self.canonical.read_bytes(), self.canonical.stat().st_mtime_ns
        files = {p: p.read_bytes() for p in self.backups.glob("*.md")}
        with patch.object(native, "atomic_write") as writer:
            result = self.complete(apply=True)
        self.assertEqual(result["status"], "unchanged")
        writer.assert_not_called()
        self.assertEqual(self.canonical.read_bytes(), before)
        self.assertEqual(self.canonical.stat().st_mtime_ns, stamp)
        self.assertEqual({p: p.read_bytes() for p in self.backups.glob("*.md")}, files)

    def test_redacted_url_with_checkout_path_replays_using_exact_recovery_policy(self):
        self.message("Original prompt", "human-1")
        self.message(
            f"Read https://example.test/{self.root.as_posix()}/guide?code=private-fixture-value",
            "human-2",
        )
        self.message("Actual final", "final-1", role="assistant")
        self.write()
        first = self.complete(apply=True)
        self.assertEqual(first["status"], "written")
        before = (self.canonical.read_bytes(), self.canonical.stat().st_mtime_ns)
        second = self.complete(apply=True)
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(
            (self.canonical.read_bytes(), self.canonical.stat().st_mtime_ns), before
        )
        self.assertNotIn("private-fixture-value", self.canonical.read_text())

    def test_atomic_write_failure_retains_original_log_and_verified_preimage_backup(
        self,
    ):
        self.message("Original prompt", "human-1")
        self.message("Actual final", "assistant-1", role="assistant")
        before = self.canonical.read_bytes()
        with (
            patch.object(
                native, "atomic_write", side_effect=OSError("synthetic write failure")
            ),
            self.assertRaises(OSError),
        ):
            self.complete(apply=True)
        self.assertEqual(self.canonical.read_bytes(), before)
        backups = list(self.backups.glob("*.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)

    def test_unverified_backup_failure_prevents_canonical_write(self):
        self.message("Original prompt", "human-1")
        before = self.canonical.read_bytes()
        with (
            patch.object(
                completion,
                "_verified_backup",
                side_effect=ValueError("Backup verification failed"),
            ),
            patch.object(native, "atomic_write") as writer,
            self.assertRaises(ValueError),
        ):
            self.complete(apply=True)
        writer.assert_not_called()
        self.assertEqual(self.canonical.read_bytes(), before)

    def test_backup_inside_repository_is_rejected_without_modifying_canonical_log(self):
        self.message("Original prompt", "human-1")
        before = self.canonical.read_bytes()
        backup_dir = self.root / "private-backups"
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            self.complete(apply=True, backup_dir=backup_dir)
        self.assertEqual(self.canonical.read_bytes(), before)
        self.assertFalse(backup_dir.exists())

    def test_historical_snapshot_is_preserved_and_not_created_as_a_second_canonical(
        self,
    ):
        self.message("Original prompt", "human-1")
        self.message("Actual final", "assistant-1", role="assistant")
        metadata, old = native.read_log(self.canonical, SESSION)
        historical = self.canonical.parent / f"2026-11-04_{SESSION}_reconstructed.md"
        historical.write_text(native.render(metadata, old), encoding="utf-8")
        before, stamp = historical.read_bytes(), historical.stat().st_mtime_ns
        result = self.complete(apply=True, historical_paths=(historical,))
        self.assertEqual(result["status"], "written")
        self.assertEqual(historical.read_bytes(), before)
        self.assertEqual(historical.stat().st_mtime_ns, stamp)
        self.assertEqual(len(list(self.canonical.parent.glob("*.md"))), 2)

    def test_real_native_capture_function_still_completes_primary_turn_after_recovery(
        self,
    ):
        self.message("Original prompt", "human-1")
        self.message("Genuine same-turn steering", "human-2")
        self.complete(apply=True)
        metadata, entries = native.read_log(self.canonical, SESSION)
        self.assertEqual(metadata["session_status"], "awaiting_response")
        self.assertEqual([e["is_turn_continuation"] for e in entries], [False, True])
        path, changed = native.capture(
            self.payload("Stop", "Actually emitted final"), self.root, identity
        )
        self.assertTrue(changed)
        self.assertEqual(path, self.canonical)
        metadata, entries = native.read_log(path, SESSION)
        self.assertEqual([e["kind"] for e in entries], ["PROMPT", "PROMPT", "RESPONSE"])
        self.assertEqual(entries[-1]["num"], entries[0]["num"])
        self.assertEqual(entries[-1]["capture_event"], "Stop")
        self.assertEqual(metadata["session_status"], "complete")
        self.assertEqual(
            native.capture(
                self.payload("Stop", "Actually emitted final"), self.root, identity
            ),
            (self.canonical, False),
        )


if __name__ == "__main__":
    unittest.main()
