"""Synthetic Claude transcript fixtures; these are not proof of live Claude hooks."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "claude_session_transcript.py"
SPEC = importlib.util.spec_from_file_location("claude_session_transcript", SCRIPT)
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)


class ClaudeTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "fixture-session.jsonl"
        self.rows = []

    def row(self, kind, text, identifier, *, parent=None, reason=None, **changes):
        value = {
            "type": kind,
            "sessionId": "fixture-session",
            "cwd": str(self.root),
            "uuid": identifier,
            "parentUuid": parent,
            "timestamp": "2026-11-05T10:00:00Z",
            "message": {"role": kind, "content": text},
        }
        if kind == "assistant":
            value["message"]["stop_reason"] = reason
        value.update(changes)
        self.rows.append(value)
        return value

    def extract(self, *, stop_event=False):
        self.path.write_text(
            "".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8"
        )
        return extractor.extract_claude_transcript(
            self.path, "fixture-session", self.root, stop_event=stop_event
        )

    def pair(self, reason="end_turn"):
        self.row("user", "A genuine prompt", "human-1")
        self.row(
            "assistant",
            "A final answer",
            "assistant-1",
            parent="human-1",
            reason=reason,
        )

    def test_explicit_final_is_linked_to_real_user_uuid_and_keeps_aware_timestamp(self):
        self.pair()
        entries = self.extract()
        self.assertEqual([entry["kind"] for entry in entries], ["PROMPT", "RESPONSE"])
        self.assertEqual(
            [entry["turn_id"] for entry in entries], ["human-1", "human-1"]
        )
        self.assertEqual(entries[-1]["text"], "A final answer")
        self.assertEqual(entries[-1]["timestamp"], "2026-11-05T10:00:00Z")

    def test_stop_sequence_is_an_explicit_terminal_reason(self):
        self.pair("stop_sequence")
        self.assertEqual(len(self.extract()), 2)

    def test_unknown_finality_is_not_guessed_from_next_prompt_or_end_of_file(self):
        self.pair(None)
        self.row("user", "A subsequent prompt", "human-2")
        self.row("assistant", "Still working", "assistant-2", parent="human-2")
        self.assertEqual([e["kind"] for e in self.extract()], ["PROMPT", "PROMPT"])

    def test_native_stop_can_confirm_only_the_latest_text_for_the_current_turn(self):
        self.row("user", "A prompt", "human-1")
        self.row("assistant", "Intermediate", "assistant-1", parent="human-1")
        self.row("assistant", "Final", "assistant-2", parent="assistant-1")
        entries = self.extract(stop_event=True)
        self.assertEqual([e["text"] for e in entries], ["A prompt", "Final"])

    def test_interruption_never_promotes_an_intermediate_response_even_on_stop(self):
        self.pair(None)
        self.row(
            "user", "[Request interrupted by user]", "interrupt", parent="assistant-1"
        )
        self.row("assistant", "Late canceled output", "assistant-2", parent="interrupt")
        self.assertEqual([e["kind"] for e in self.extract(stop_event=True)], ["PROMPT"])

    def test_interruption_also_discards_pending_explicit_final(self):
        self.pair()
        self.row("user", "[Request interrupted by user for tool use]", "interrupt")
        self.assertEqual([e["kind"] for e in self.extract(stop_event=True)], ["PROMPT"])

    def test_max_tokens_tool_use_and_pause_cannot_be_promoted_by_stop(self):
        for reason in ("max_tokens", "tool_use", "pause_turn", "refusal", "unknown"):
            with self.subTest(reason=reason):
                self.rows = []
                self.pair(reason)
                self.assertEqual(len(self.extract(stop_event=True)), 1)

    def test_tool_calls_results_and_thinking_are_excluded(self):
        self.row("user", "A prompt", "human-1")
        self.row(
            "assistant",
            [
                {"type": "text", "text": "Intermediate tool narration"},
                {"type": "tool_use", "id": "tool-1", "input": {"private": "never-log"}},
            ],
            "assistant-1",
            parent="human-1",
            reason="tool_use",
        )
        self.row(
            "user",
            [{"type": "tool_result", "content": "private-tool-result"}],
            "tool-result",
            parent="assistant-1",
        )
        self.row(
            "assistant",
            [
                {"type": "thinking", "thinking": "private-thinking"},
                {"type": "redacted_thinking", "data": "private-redacted-thinking"},
                {"type": "text", "text": "Only the final text"},
            ],
            "assistant-2",
            parent="tool-result",
            reason="end_turn",
        )
        entries = self.extract()
        self.assertEqual(
            [e["text"] for e in entries], ["A prompt", "Only the final text"]
        )
        self.assertNotIn("private", repr(entries))

    def test_tool_result_after_text_disqualifies_native_stop_fallback(self):
        self.pair(None)
        self.row(
            "user",
            [{"type": "tool_result", "content": "private"}],
            "tool-result",
            parent="assistant-1",
        )
        self.assertEqual(len(self.extract(stop_event=True)), 1)

    def test_attachments_and_ide_context_are_removed_but_human_text_is_kept(self):
        self.row(
            "user",
            [
                {
                    "type": "text",
                    "text": "<ide_opened_file>private-path</ide_opened_file>",
                },
                {"type": "image", "source": {"data": "private-image"}},
                {"type": "document", "source": {"data": "private-document"}},
                {
                    "type": "text",
                    "text": '<pasted_content id="p1">Human pasted text</pasted_content>',
                },
                {"type": "text", "text": "Human follow-up"},
            ],
            "human-1",
        )
        entries = self.extract()
        self.assertEqual(entries[0]["text"], "Human pasted text\n\nHuman follow-up")
        self.assertNotIn("private", repr(entries))

    def test_meta_sidechain_and_compact_summaries_are_not_conversation(self):
        self.pair()
        for flag in (
            "isMeta",
            "isCompactSummary",
            "is_summary",
            "isSidechain",
            "is_subagent",
        ):
            self.row("user", "private-context", f"context-{flag}", **{flag: True})
            self.row(
                "assistant",
                "private-result",
                f"result-{flag}",
                reason="end_turn",
                **{flag: True},
            )
        self.assertEqual(
            [e["text"] for e in self.extract()], ["A genuine prompt", "A final answer"]
        )

    def test_command_harness_and_summary_string_prompts_are_excluded(self):
        for index, text in enumerate(
            (
                "<command-name>/clear</command-name>",
                "<local-command-stdout>private</local-command-stdout>",
                "Caveat: private",
                "<task-notification>private</task-notification>",
                "Another Claude session sent a message: private",
                "This session is being continued from a previous conversation that ran out of context.",
            )
        ):
            self.row("user", text, f"context-{index}")
        self.assertEqual(self.extract(), [])

    def test_wrong_session_or_cwd_is_rejected_without_revealing_contents(self):
        for changes in (
            {"sessionId": "other"},
            {"cwd": str(self.root.parent / "other")},
            {"cwd": "relative"},
            {"cwd": None},
        ):
            with self.subTest(changes=changes):
                self.rows = []
                self.row("user", "private-content", "human-1", **changes)
                with self.assertRaises(ValueError) as error:
                    self.extract()
                self.assertNotIn("private-content", str(error.exception))

    def test_invalid_timestamp_is_rejected_without_inventing_capture_time(self):
        for timestamp in (None, "invalid", "2026-11-05T10:00:00"):
            with self.subTest(timestamp=timestamp):
                self.rows = []
                self.row("user", "Prompt", "human-1", timestamp=timestamp)
                with self.assertRaises(ValueError):
                    self.extract()

    def test_explicit_offsets_are_preserved(self):
        self.row("user", "Prompt", "human-1", timestamp="2026-11-05T15:30:00+05:30")
        self.assertEqual(self.extract()[0]["timestamp"], "2026-11-05T15:30:00+05:30")

    def test_source_id_fallback_is_stable_and_does_not_hash_conversation(self):
        row = self.row("user", "Prompt", "temporary")
        del row["uuid"]
        row["message"]["id"] = "stable-source-id"
        first = self.extract()[0]["turn_id"]
        row["message"]["content"] = "Changed private prompt"
        self.assertEqual(self.extract()[0]["turn_id"], first)
        self.assertTrue(first.startswith("inferred-"))

    def test_missing_source_identifier_fails_closed(self):
        row = self.row("user", "Prompt", "temporary")
        del row["uuid"]
        with self.assertRaises(ValueError):
            self.extract()

    def test_duplicate_identical_rows_are_idempotent(self):
        self.pair()
        self.rows.append(self.rows[-1].copy())
        first = self.extract()
        self.assertEqual(len(first), 2)
        self.assertEqual(self.extract(), first)

    def test_conflicting_source_identifiers_fail_closed(self):
        self.row("user", "First", "human-1")
        self.row("user", "Different", "human-1")
        with self.assertRaises(ValueError):
            self.extract()

    def test_orphan_and_old_branch_assistant_text_cannot_answer_new_prompt(self):
        self.row("assistant", "Orphan", "assistant-0", reason="end_turn")
        self.row("user", "First", "human-1")
        self.row(
            "assistant",
            "Old answer",
            "assistant-1",
            parent="human-1",
            reason="end_turn",
        )
        self.row("user", "Second", "human-2", parent="assistant-1")
        self.row(
            "assistant",
            "Stale branch",
            "assistant-2",
            parent="human-1",
            reason="end_turn",
        )
        self.assertEqual(
            [e["text"] for e in self.extract(stop_event=True)],
            ["First", "Old answer", "Second"],
        )

    def test_partial_last_json_line_is_not_repaired_or_exported(self):
        self.pair()
        self.extract()
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write('{"type":"user","private":"unfinished')
        result = extractor.extract_claude_transcript(
            self.path, "fixture-session", self.root
        )
        self.assertEqual(len(result), 2)

    def test_malformed_complete_jsonl_line_is_rejected(self):
        self.path.write_text("private-malformed-json\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "^Malformed Claude transcript JSONL$"):
            extractor.extract_claude_transcript(self.path, "fixture-session", self.root)

    def test_partial_tail_cannot_make_intermediate_text_a_final_on_stop(self):
        self.pair(None)
        self.extract()
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write('{"type":"assistant","unfinished_tool_call":')
        result = extractor.extract_claude_transcript(
            self.path, "fixture-session", self.root, stop_event=True
        )
        self.assertEqual([entry["kind"] for entry in result], ["PROMPT"])

    def test_foreign_branch_cannot_confirm_the_current_intermediate_text_on_stop(self):
        self.row("user", "First", "human-1")
        self.row(
            "assistant",
            "Old answer",
            "assistant-1",
            parent="human-1",
            reason="end_turn",
        )
        self.row("user", "Second", "human-2", parent="assistant-1")
        self.row("assistant", "Intermediate", "assistant-2", parent="human-2")
        self.row(
            "assistant", "Old fork", "assistant-3", parent="human-1", reason="end_turn"
        )
        self.assertEqual(
            [e["text"] for e in self.extract(stop_event=True)],
            ["First", "Old answer", "Second"],
        )

    def test_subagent_file_path_is_rejected_before_read(self):
        for path in (
            self.root / "subagents" / "child.jsonl",
            self.root / "agent-child.jsonl",
        ):
            with self.assertRaisesRegex(
                ValueError, "Delegated Claude transcripts are excluded"
            ):
                extractor.extract_claude_transcript(path, "fixture-session", self.root)

    def test_extraction_does_not_redact_or_write_original_transcript(self):
        self.row("user", "api_key=synthetic-only-value", "human-1")
        self.extract()
        before = self.path.read_bytes()
        result = extractor.extract_claude_transcript(
            self.path, "fixture-session", self.root
        )
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(result[0]["text"], "api_key=synthetic-only-value")
        self.assertEqual(list(self.root.iterdir()), [self.path])


if __name__ == "__main__":
    unittest.main()
