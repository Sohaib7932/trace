"""Synthetic observed Codex JSONL shapes; never reads genuine conversations."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "codex_session_transcript.py"
SPEC = importlib.util.spec_from_file_location("codex_session_transcript_tests", SCRIPT)
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)
SESSION = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"
STAMP = "2026-11-05T10:00:00Z"


class CodexTranscriptTests(unittest.TestCase):
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
                "session_id": SESSION,
                "source": "vscode",
                "cwd": str(self.root),
                **changes,
            },
        }

    def row(self, kind, payload, **changes):
        value = {
            "type": kind,
            "payload": payload,
            "timestamp": STAMP,
            "ordinal": len(self.rows),
            **changes,
        }
        self.rows.append(value)
        return value

    def prompt(self, text="A genuine fixture prompt", turn="turn-1", kinds=None):
        return self.row(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "id": f"user-{turn}",
                "content": [{"type": "input_text", "text": text}],
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": turn,
                    "content_item_kinds": kinds or ["user.text"],
                },
            },
        )

    def final(
        self, text="A genuine fixture final", turn="turn-1", phase="final_answer"
    ):
        return self.row(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "phase": phase,
                "status": "completed",
                "id": f"assistant-{turn}",
                "content": [{"type": "output_text", "text": text}],
                "internal_chat_message_metadata_passthrough": {"turn_id": turn},
            },
        )

    def write(self, path=None, rows=None):
        target = path or self.path
        data = b"".join(
            (json.dumps(r, ensure_ascii=False) + "\n").encode()
            for r in (self.rows if rows is None else rows)
        )
        target.write_bytes(data)
        return data

    def extract(self, **options):
        self.write()
        before = self.path.read_bytes()
        result = extractor.extract_codex_transcripts(
            [self.path], SESSION, self.root, **options
        )
        self.assertEqual(before, self.path.read_bytes())
        return result

    def test_actual_final_phase_excludes_commentary_tools_reasoning_and_event_mirrors(
        self,
    ):
        self.prompt()
        self.final("private-commentary", phase="commentary")
        self.row("response_item", {"type": "reasoning", "summary": "private-reasoning"})
        self.row(
            "response_item", {"type": "function_call_output", "output": "private-tool"}
        )
        self.row(
            "event_msg",
            {
                "type": "item_completed",
                "turn_id": "turn-1",
                "item": {"type": "AgentMessage", "content": "private-mirror"},
            },
        )
        self.final()
        self.row(
            "event_msg",
            {
                "type": "task_complete",
                "turn_id": "turn-1",
                "last_agent_message": "A genuine fixture final",
            },
        )
        entries = self.extract()
        self.assertEqual([e["kind"] for e in entries], ["PROMPT", "RESPONSE"])
        self.assertEqual(entries[-1]["text"], "A genuine fixture final")
        self.assertNotIn("private-", repr(entries))

    def test_actual_content_kind_metadata_excludes_injected_parts_and_images(self):
        self.row(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "A genuine first part"},
                    {"type": "input_text", "text": "private-environment"},
                    {"type": "input_image", "image_url": "private-image"},
                    {"type": "input_text", "text": "A genuine last part"},
                ],
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": "turn-1",
                    "content_item_kinds": [
                        "user.text",
                        "environments.environment_context",
                        "user.image",
                        "user.text",
                    ],
                },
            },
        )
        self.prompt("private-agents", turn="injected", kinds=["agents_md.instructions"])
        self.final()
        entries = self.extract()
        self.assertEqual(
            entries[0]["text"], "A genuine first part\n\nA genuine last part"
        )
        self.assertEqual(len(entries), 2)
        self.assertNotIn("private-", repr(entries))

    def test_browser_envelope_is_removed_while_actual_request_remains(self):
        self.prompt(
            '<in-app-browser-context source="ambient">private-url</in-app-browser-context>\nFix the fixture.'
        )
        entries = self.extract()
        self.assertEqual(entries[0]["text"], "Fix the fixture.")

    def test_event_prompt_and_response_item_mirrors_are_not_double_counted(self):
        self.row("event_msg", {"type": "task_started", "turn_id": "turn-1"})
        self.row(
            "event_msg",
            {
                "type": "user_message",
                "turn_id": "turn-1",
                "message": "A genuine fixture prompt",
            },
        )
        self.prompt()
        self.final()
        self.row(
            "event_msg",
            {
                "type": "task_complete",
                "turn_id": "turn-1",
                "last_agent_message": "A genuine fixture final",
            },
        )
        self.assertEqual(len(self.extract()), 2)

    def test_empty_or_unrecognized_phase_never_becomes_a_final(self):
        self.prompt()
        self.final("private-final-shape", phase="final")
        self.final("private-commentary", phase="commentary")
        self.row(
            "event_msg",
            {"type": "task_complete", "turn_id": "turn-1", "last_agent_message": None},
        )
        entries = self.extract()
        self.assertEqual([e["kind"] for e in entries], ["PROMPT"])
        self.assertNotIn("private-", repr(entries))

    def test_nonempty_task_completion_can_supply_a_recorded_final_without_fabrication(
        self,
    ):
        self.prompt()
        self.row(
            "event_msg",
            {
                "type": "task_complete",
                "turn_id": "turn-1",
                "last_agent_message": "Recorded terminal text",
            },
        )
        self.assertEqual(self.extract()[-1]["text"], "Recorded terminal text")

    def test_conflicting_final_evidence_fails_closed(self):
        self.prompt()
        self.final()
        self.row(
            "event_msg",
            {
                "type": "task_complete",
                "turn_id": "turn-1",
                "last_agent_message": "A conflicting terminal result",
            },
        )
        with self.assertRaisesRegex(ValueError, "disagree"):
            self.extract()

    def test_orphan_final_is_not_attached_to_an_unrelated_prompt(self):
        self.prompt()
        self.final(turn="other-turn")
        self.assertEqual([e["kind"] for e in self.extract()], ["PROMPT"])

    def test_duplicate_and_conflicting_prompts_are_distinguished(self):
        self.prompt()
        self.prompt()
        self.assertEqual(len(self.extract()), 1)
        self.prompt("A conflicting prompt")
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.extract()

    def test_explicit_worktree_alias_and_per_turn_source_cwd(self):
        alias = self.root / "worktree"
        alias.mkdir()
        self.row("turn_context", {"turn_id": "turn-1", "cwd": str(alias)})
        self.prompt()
        self.final()
        entries = self.extract(source_cwds=(alias,))
        self.assertEqual({e["cwd"] for e in entries}, {str(alias)})
        with self.assertRaisesRegex(ValueError, "unapproved project"):
            self.extract()

    def test_foreign_session_cwd_and_subagent_sources_are_rejected(self):
        for changes in (
            {"id": "another-session"},
            {"cwd": str(self.root.parent)},
            {"source": {"subagent": {"other": "guardian"}}},
            {"source": {"subagent": {"thread_spawn": {"parent_thread_id": SESSION}}}},
            {"agent_id": "delegated-agent"},
        ):
            with self.subTest(changes=changes):
                self.rows = [self.header(**changes)]
                self.prompt()
                with self.assertRaises(ValueError):
                    self.extract()

    def test_absent_or_unknown_primary_source_is_not_assumed_to_be_codex(self):
        for source in (None, "subagent", "unrecognized-agent", 3):
            with self.subTest(source=source):
                self.rows = [self.header(source=source)]
                self.prompt()
                with self.assertRaisesRegex(ValueError, "unknown Codex sources"):
                    self.extract()

    def test_invalid_timestamp_has_a_content_free_error(self):
        self.prompt("private-prompt-canary")["timestamp"] = "not-a-date-private-canary"
        with self.assertRaisesRegex(ValueError, "aware timestamp") as error:
            self.extract()
        self.assertNotIn("private", str(error.exception))

    def test_partially_appended_tail_is_ignored_but_malformed_complete_line_is_rejected(
        self,
    ):
        self.prompt()
        self.write()
        with self.path.open("ab") as stream:
            stream.write(b'{"private-incomplete-tail":')
        entries = extractor.extract_codex_transcripts([self.path], SESSION, self.root)
        self.assertEqual(len(entries), 1)
        with self.path.open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(ValueError, "Invalid Codex transcript record"):
            extractor.extract_codex_transcripts([self.path], SESSION, self.root)

    def segments(self):
        self.prompt("Kept parent prompt")
        self.final("Kept parent final")
        parent_prefix = self.write()
        cutoff = len(parent_prefix)
        ordinal = len(self.rows)
        self.prompt("private-abandoned-parent-tail", turn="abandoned")
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
        self.prompt("A child prompt", turn="turn-2")["ordinal"] = ordinal + 1
        self.final("A child final", turn="turn-2")["ordinal"] = ordinal + 2
        self.write(child)
        return child, cutoff, ordinal

    def test_history_byte_and_ordinal_cutoff_excludes_abandoned_parent_tail(self):
        child, _, _ = self.segments()
        entries = extractor.extract_codex_transcripts(
            [child, self.path], SESSION, self.root
        )
        self.assertEqual(
            [e["text"] for e in entries],
            [
                "Kept parent prompt",
                "Kept parent final",
                "A child prompt",
                "A child final",
            ],
        )
        self.assertNotIn("abandoned", repr(entries))

    def test_missing_parent_and_ambiguous_chains_fail_closed(self):
        child, _, _ = self.segments()
        with self.assertRaisesRegex(ValueError, "parent segment"):
            extractor.extract_codex_transcripts([child], SESSION, self.root)
        unrelated = self.root / "rollout-33333333-3333-4333-8333-333333333333.jsonl"
        self.write(unrelated, [self.header()])
        with self.assertRaises(ValueError):
            extractor.extract_codex_transcripts(
                [child, self.path, unrelated], SESSION, self.root
            )

    def test_nonboundary_and_inconsistent_ordinal_cutoffs_are_rejected(self):
        for field, delta in (("end_byte_offset", -1), ("end_ordinal_exclusive", -1)):
            with self.subTest(field=field):
                self.rows = [self.header()]
                child, _, _ = self.segments()
                self.rows[0]["payload"]["history_base"][field] += delta
                self.write(child)
                with self.assertRaises(ValueError):
                    extractor.extract_codex_transcripts(
                        [self.path, child], SESSION, self.root
                    )

    def test_history_ordinal_cutoff_must_match_the_exact_parent_byte_boundary(self):
        child, _, _ = self.segments()
        self.rows[0]["payload"]["history_base"]["end_ordinal_exclusive"] += 1
        self.write(child)
        with self.assertRaises(ValueError):
            extractor.extract_codex_transcripts([self.path, child], SESSION, self.root)


if __name__ == "__main__":
    unittest.main()
