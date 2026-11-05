"""Same-turn primary conversation recovery from synthetic, temporary JSONL only."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "codex_conversation_records_tests", SCRIPTS / "codex_conversation_records.py"
)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)
SESSION = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"
STAMP = "2026-11-05T10:00:00Z"


class ConversationRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / f"rollout-{SESSION}.jsonl"
        self.rows = [self.header()]

    def header(self, **changes):
        return {
            "type": "session_meta",
            "timestamp": STAMP,
            "ordinal": 0,
            "payload": {
                "id": SESSION,
                "cwd": str(self.root),
                "source": "vscode",
                **changes,
            },
        }

    def row(self, kind, payload, **changes):
        value = {
            "type": kind,
            "payload": payload,
            "ordinal": len(self.rows),
            "timestamp": STAMP,
            **changes,
        }
        self.rows.append(value)
        return value

    def message(
        self, text, identity, *, role="user", turn="turn-1", phase="final_answer"
    ):
        payload = {
            "type": "message",
            "role": role,
            "id": identity,
            "content": [
                {
                    "type": "input_text" if role == "user" else "output_text",
                    "text": text,
                }
            ],
            "internal_chat_message_metadata_passthrough": {"turn_id": turn},
        }
        if role == "user":
            payload["internal_chat_message_metadata_passthrough"][
                "content_item_kinds"
            ] = ["user.text"]
        else:
            payload.update(phase=phase, status="completed")
        return self.row("response_item", payload)

    def complete(self, text, turn="turn-1"):
        return self.row(
            "event_msg",
            {"type": "task_complete", "turn_id": turn, "last_agent_message": text},
        )

    def write(self, path=None, rows=None):
        target = path or self.path
        data = b"".join(
            (json.dumps(row) + "\n").encode()
            for row in (self.rows if rows is None else rows)
        )
        target.write_bytes(data)
        return data

    def extract(self, **options):
        self.write()
        before = self.path.read_bytes()
        entries = reader.extract_conversation_records(
            [self.path], SESSION, self.root, **options
        )
        self.assertEqual(self.path.read_bytes(), before)
        return entries

    def test_same_turn_original_ui_reply_and_steering_are_distinct_genuine_messages(
        self,
    ):
        reply = '<send_user_message_question_reply>[{"answer":"Approved"}]</send_user_message_question_reply>'
        self.message("Original instruction", "message-1")
        self.message(reply, "message-2")
        self.message("Continue with the existing implementation", "message-3")
        self.message("Actual final", "message-4", role="assistant")
        self.complete("Actual final")
        entries = self.extract()
        self.assertEqual(
            [e["text"] for e in entries],
            [
                "Original instruction",
                reply,
                "Continue with the existing implementation",
                "Actual final",
            ],
        )
        self.assertEqual(
            [e["source_message_id"] for e in entries],
            ["message-1", "message-2", "message-3", "message-4"],
        )
        self.assertEqual([e["source_record_ordinal"] for e in entries], [1, 2, 3, 4])
        self.assertTrue(all(e["turn_id"] == "turn-1" for e in entries))
        self.assertTrue(
            all(e["capture_event"] == "CodexTranscriptRecovery" for e in entries)
        )
        self.assertTrue(
            all(e["source_record_type"] == "response_item" for e in entries)
        )

    def test_identical_text_with_distinct_message_ids_is_never_collapsed(self):
        self.message("continue", "message-1")
        self.message("continue", "message-2")
        entries = self.extract()
        self.assertEqual(len(entries), 2)
        self.assertEqual([e["text"] for e in entries], ["continue", "continue"])

    def test_same_message_id_exact_replay_is_deduplicated(self):
        self.message("Original", "message-1")
        self.message("Original", "message-1")
        self.assertEqual(len(self.extract()), 1)

    def test_same_message_id_conflicting_text_or_turn_is_rejected(self):
        for text, turn in (("Different", "turn-1"), ("Original", "turn-2")):
            with self.subTest(text=text, turn=turn):
                self.rows = [self.header()]
                self.message("Original", "message-1")
                self.message(text, "message-1", turn=turn)
                with self.assertRaisesRegex(ValueError, "Conflicting.*replay"):
                    self.extract()

    def test_missing_message_id_uses_real_record_identity_without_inventing_an_id(self):
        for _ in range(2):
            row = self.message("continue", "temporary")
            del row["payload"]["id"]
        entries = self.extract()
        self.assertEqual(len(entries), 2)
        self.assertTrue(all("source_message_id" not in e for e in entries))
        self.assertEqual([e["source_record_ordinal"] for e in entries], [1, 2])

    def test_only_user_text_parts_survive_and_ambient_context_is_removed(self):
        row = self.message("Human text", "message-1")
        row["payload"]["content"] = [
            {"type": "input_text", "text": "Human first"},
            {"type": "input_text", "text": "private-environment"},
            {"type": "input_image", "image_url": "private-image"},
            {
                "type": "input_text",
                "text": '<in-app-browser-context source="ambient">private-url</in-app-browser-context>\nHuman last',
            },
        ]
        row["payload"]["internal_chat_message_metadata_passthrough"][
            "content_item_kinds"
        ] = [
            "user.text",
            "environments.environment_context",
            "user.image",
            "user.text",
        ]
        entries = self.extract()
        self.assertEqual(entries[0]["text"], "Human first\n\nHuman last")
        self.assertNotIn("private-", repr(entries))

    def test_user_role_without_explicit_human_provenance_is_ignored(self):
        row = self.message("private-context", "message-1")
        del row["payload"]["internal_chat_message_metadata_passthrough"][
            "content_item_kinds"
        ]
        self.assertEqual(self.extract(), [])

    def test_known_injected_prefixes_are_excluded_even_if_mislabeled_user_text(self):
        for index, prefix in enumerate(
            (
                "# AGENTS.md instructions",
                "<environment_context>",
                "<system-reminder>",
                "<external_codex_apps_open_page>",
                "This is an app-generated request for a suggested next user message.",
            )
        ):
            self.message(prefix + " private-content", f"message-{index}")
        self.assertEqual(self.extract(), [])

    def test_tools_commentary_unknown_phases_and_guardian_messages_are_excluded(self):
        self.message("Human", "message-1")
        for index, phase in enumerate(("commentary", "analysis", "unknown", None)):
            self.message(
                "private-commentary",
                f"assistant-{index}",
                role="assistant",
                phase=phase,
            )
        self.row(
            "response_item", {"type": "function_call_output", "output": "private-tool"}
        )
        self.row("response_item", {"type": "reasoning", "summary": "private-thinking"})
        row = self.message("private-guardian", "guardian", role="assistant")
        row["payload"]["agent_type"] = "guardian"
        self.row(
            "event_msg",
            {
                "type": "user_message",
                "message": "private-event-mirror",
                "turn_id": "turn-1",
            },
        )
        self.assertEqual([e["text"] for e in self.extract()], ["Human"])

    def test_subagent_header_is_rejected_and_delegated_record_metadata_is_excluded(
        self,
    ):
        for source in ({"subagent": "spawned"}, "guardian"):
            with self.subTest(source=source):
                self.rows = [self.header(source=source)]
                with self.assertRaises(ValueError):
                    self.extract()
        self.rows = [self.header()]
        self.message("Human", "message-1")
        for level in ("row", "payload", "metadata"):
            row = self.message("private-child", f"child-{level}", role="assistant")
            target = row if level == "row" else row["payload"]
            if level == "metadata":
                target = target["internal_chat_message_metadata_passthrough"]
            target["agent_id"] = "child-agent"
        self.assertEqual([e["text"] for e in self.extract()], ["Human"])

    def test_completed_mirror_without_actual_final_answer_never_fabricates_a_response(
        self,
    ):
        self.message("Human", "message-1")
        self.complete("Unproven final mirror")
        self.assertEqual([e["kind"] for e in self.extract()], ["PROMPT"])

    def test_final_mirror_conflicts_are_rejected_without_exposing_content(self):
        self.message("Human", "message-1")
        self.message("Actual final", "assistant-1", role="assistant")
        self.complete("private-conflicting-mirror")
        with self.assertRaisesRegex(ValueError, "evidence disagree") as error:
            self.extract()
        self.assertNotIn("private", str(error.exception))

    def test_mirror_before_final_can_corroborate_but_cannot_replace_it(self):
        self.message("Human", "message-1")
        self.complete("Actual final")
        self.message("Actual final", "assistant-1", role="assistant")
        self.assertEqual([e["text"] for e in self.extract()], ["Human", "Actual final"])

    def test_distinct_real_finals_and_their_matching_mirrors_remain_in_record_order(
        self,
    ):
        self.message("Human", "message-1")
        self.message("First final", "assistant-1", role="assistant")
        self.complete("First final")
        self.message("Steering", "message-2")
        self.message("Second final", "assistant-2", role="assistant")
        self.complete("Second final")
        self.assertEqual(
            [e["text"] for e in self.extract()],
            ["Human", "First final", "Steering", "Second final"],
        )

    def test_orphan_final_without_preceding_human_prompt_is_not_returned(self):
        self.message("Orphan", "assistant-1", role="assistant")
        self.message("Human after orphan", "message-1")
        self.assertEqual([e["text"] for e in self.extract()], ["Human after orphan"])

    def test_opt_in_retains_real_unpaired_final_without_inventing_human_input(self):
        self.message(
            "Actual unpaired final", "assistant-1", role="assistant", turn="old-turn"
        )
        self.complete("Actual unpaired final", turn="old-turn")
        self.message("Observed human", "human-1", turn="new-turn")
        entries = self.extract(include_unpaired_finals=True)
        self.assertEqual([e["kind"] for e in entries], ["RESPONSE", "PROMPT"])
        self.assertEqual(entries[0]["text"], "Actual unpaired final")
        self.assertTrue(entries[0]["unpaired_final"])
        self.assertEqual(entries[0]["turn_id"], "old-turn")
        self.assertEqual(entries[0]["source_message_id"], "assistant-1")
        self.assertEqual(entries[0]["source_record_ordinal"], 1)
        self.assertEqual(sum(e["kind"] == "PROMPT" for e in entries), 1)

    def test_unpaired_opt_in_does_not_create_an_association_with_later_same_turn_input(
        self,
    ):
        self.message("Earlier final", "assistant-1", role="assistant")
        self.message("Later human", "human-1")
        self.assertEqual(
            [e["text"] for e in self.extract(include_unpaired_finals=True)],
            ["Later human"],
        )
        with self.assertRaises(ValueError):
            self.extract(include_unpaired_finals="yes")

    def test_automatic_resume_final_retains_only_allowlisted_trigger_metadata(self):
        self.row(
            "event_msg",
            {
                "type": "task_started",
                "turn_id": "resumed-turn",
                "turn_attribution": {
                    "turn_trigger": "resume_interrupted_task",
                    "private_extra": "synthetic-private-metadata",
                },
            },
        )
        self.message(
            "Actual resumed final",
            "resumed-final",
            role="assistant",
            turn="resumed-turn",
        )
        entries = self.extract(include_unpaired_finals=True)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["unpaired_final"])
        self.assertEqual(entries[0]["source_turn_trigger"], "resume_interrupted_task")
        self.assertNotIn("synthetic-private-metadata", json.dumps(entries))

    def test_cutoff_excludes_final_and_future_content_without_calling_a_provider(self):
        self.message("Human", "message-1")
        self.message("Actual final", "assistant-1", role="assistant")
        self.complete("Actual final")
        self.assertEqual(len(self.extract(end_ordinal_exclusive=0)), 0)
        entries = self.extract(end_ordinal_exclusive=2)
        self.assertEqual([e["text"] for e in entries], ["Human"])

    def test_bad_cutoff_and_record_ordinals_fail_closed(self):
        self.message("Human", "message-1")
        for value in (True, -1, 1.2, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.extract(end_ordinal_exclusive=value)
        for value in (None, True, -1, 0):
            with self.subTest(ordinal=value):
                self.rows[-1]["ordinal"] = value
                with self.assertRaises(ValueError):
                    self.extract()

    def test_naive_or_invalid_timestamps_do_not_become_capture_time(self):
        row = self.message("Human", "message-1")
        for stamp in (None, "invalid", "2026-11-05T10:00:00"):
            with self.subTest(stamp=stamp):
                row["timestamp"] = stamp
                with self.assertRaisesRegex(ValueError, "aware timestamp"):
                    self.extract()

    def test_missing_native_turn_id_is_not_inferred_from_message_position(self):
        row = self.message("Human", "message-1", turn=None)
        self.assertEqual(self.extract(), [])
        row["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = (
            "../invalid"
        )
        with self.assertRaises(ValueError):
            self.extract()

    def test_explicit_turn_context_and_cwd_alias_preserve_native_source_location(self):
        alias = self.root / "original-checkout"
        self.rows[0]["payload"]["cwd"] = str(alias)
        self.row("turn_context", {"turn_id": "turn-1", "cwd": str(alias)})
        self.message("Human", "message-1", turn=None)
        entries = self.extract(source_cwds=(alias,))
        self.assertEqual(entries[0]["turn_id"], "turn-1")
        self.assertEqual(entries[0]["cwd"], str(alias))
        with self.assertRaises(ValueError):
            self.extract()

    def test_foreign_session_or_turn_cwd_cannot_enter_target_project(self):
        self.rows[0]["payload"]["id"] = CHILD
        with self.assertRaises(ValueError):
            self.extract()
        self.rows = [self.header()]
        self.row(
            "turn_context", {"turn_id": "turn-1", "cwd": str(self.root / "foreign")}
        )
        with self.assertRaisesRegex(ValueError, "unapproved project"):
            self.extract()

    def test_source_ids_must_be_real_bounded_identifiers_if_present(self):
        row = self.message("Human", "temporary")
        for identity in (True, "", "../secret", "x" * 257):
            with self.subTest(identity=identity):
                row["payload"]["id"] = identity
                with self.assertRaises(ValueError):
                    self.extract()

    def test_verified_ancestry_discards_abandoned_parent_tail(self):
        self.message("Parent human", "message-1")
        self.message("Parent final", "assistant-1", role="assistant")
        prefix = self.write()
        cutoff, ordinal = len(prefix), len(self.rows)
        self.message("private-abandoned-tail", "message-abandoned")
        self.write()
        child = self.root / f"rollout-{SESSION}_{CHILD}.jsonl"
        self.rows = [
            self.header(
                history_base={
                    "thread_id": SESSION,
                    "end_byte_offset": cutoff,
                    "end_ordinal_exclusive": ordinal,
                }
            )
        ]
        self.rows[0]["ordinal"] = ordinal
        self.message("Child steering", "message-2")["ordinal"] = ordinal + 1
        self.message("Child final", "assistant-2", role="assistant")["ordinal"] = (
            ordinal + 2
        )
        self.write(child)
        entries = reader.extract_conversation_records(
            [child, self.path], SESSION, self.root
        )
        self.assertEqual(
            [e["text"] for e in entries],
            ["Parent human", "Parent final", "Child steering", "Child final"],
        )
        self.assertNotIn("private", repr(entries))
        with self.assertRaisesRegex(ValueError, "parent segment"):
            reader.extract_conversation_records([child], SESSION, self.root)

    def test_partial_tail_does_not_create_a_final(self):
        self.message("Human", "message-1")
        self.write()
        with self.path.open("ab") as stream:
            stream.write(b'{"type":"response_item","unfinished":')
        entries = reader.extract_conversation_records([self.path], SESSION, self.root)
        self.assertEqual([e["kind"] for e in entries], ["PROMPT"])


if __name__ == "__main__":
    unittest.main()
