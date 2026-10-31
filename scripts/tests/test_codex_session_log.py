"""Documented-event handler tests in temporary directories, not live hook proof."""
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "codex_session_log.py"
SPEC = importlib.util.spec_from_file_location("codex_session_log", SCRIPT)
logger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(logger)
IDENTITY = {"author": "Fixture Developer", "github_user": "fixture-user", "git_email": "f***@example.com",
            "git_identity_fingerprint": "fixture-fingerprint", "github_identity_verified_at": "2026-10-30T12:00:00Z"}


def fixture_identity(root, previous):
    return IDENTITY.copy()


class NativeEventCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.session = "fixture-session"

    def payload(self, event="UserPromptSubmit", turn="turn-1", text=None, session=None):
        field = "prompt" if event == "UserPromptSubmit" else "last_assistant_message"
        return {"session_id": session or self.session, "turn_id": turn, "cwd": str(self.root),
                "hook_event_name": event, "model": "fixture-model", "timestamp": "2026-10-30T14:00:00Z",
                field: text if text is not None else ("A real-shaped user prompt" if event == "UserPromptSubmit" else "A real-shaped final answer")}

    def capture(self, payload):
        return logger.capture(payload, self.root, fixture_identity)

    def pair(self, turn="turn-1"):
        path, _ = self.capture(self.payload(turn=turn))
        self.capture(self.payload("Stop", turn=turn))
        return path

    def test_documented_prompt_and_stop_share_one_canonical_file(self):
        payload = self.payload()
        payload["transcript_path"] = str(self.root / "DO-NOT-READ-TRANSCRIPT.jsonl")
        path, changed = self.capture(payload)
        self.assertTrue(changed)
        metadata, entries = logger.read_log(path, self.session)
        self.assertEqual(metadata["session_status"], "awaiting_response")
        self.assertEqual(metadata["agent"], "codex")
        self.assertEqual(entries[0]["text"], payload["prompt"])
        updated, changed = self.capture(self.payload("Stop"))
        self.assertTrue(changed)
        self.assertEqual(path, updated)
        self.assertEqual(path.parent, self.root / ".claude-logs")
        self.assertRegex(path.name, r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_fixture-session\.md$")
        metadata, entries = logger.read_log(path, self.session)
        self.assertEqual(metadata["session_status"], "complete")
        self.assertEqual([(e["kind"], e["num"]) for e in entries], [("PROMPT", 1), ("RESPONSE", 1)])
        self.assertEqual(entries[1]["text"], "A real-shaped final answer")
        self.assertEqual(len(list(path.parent.glob("*.md"))), 1)
        self.assertFalse((self.root / ".codex-logs").exists())
        self.assertFalse((self.root / "codex-logs").exists())

    def test_next_exchange_updates_same_file_and_increments_number(self):
        path = self.pair()
        second, _ = self.capture(self.payload(turn="turn-2", text="Second prompt"))
        self.capture(self.payload("Stop", turn="turn-2", text="Second final"))
        self.assertEqual(path, second)
        metadata, entries = logger.read_log(path, self.session)
        self.assertEqual([e["num"] for e in entries], [1, 1, 2, 2])
        self.assertEqual(metadata["total_exchanges"], 2)
        self.assertEqual(metadata["total_responses"], 2)

    def test_replayed_events_do_not_duplicate_or_rewrite_file(self):
        path = self.pair()
        before = path.read_bytes()
        timestamp = path.stat().st_mtime_ns
        for event in ("UserPromptSubmit", "Stop", "Stop"):
            updated, changed = self.capture(self.payload(event))
            self.assertEqual(path, updated)
            self.assertFalse(changed)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, timestamp)

    def test_conflicting_repeat_preserves_original(self):
        path = self.pair()
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Conflicting repeated event"):
            self.capture(self.payload("Stop", text="Different purported final"))
        self.assertEqual(path.read_bytes(), before)

    def test_orphan_stop_does_not_backfill_or_create_file(self):
        with self.assertRaisesRegex(ValueError, "no captured prompt"):
            self.capture(self.payload("Stop"))
        self.assertFalse((self.root / ".claude-logs").exists())

    def test_missing_final_never_uses_commentary_or_transcript(self):
        path, _ = self.capture(self.payload())
        before = path.read_bytes()
        stop = self.payload("Stop")
        stop["last_assistant_message"] = None
        stop["commentary"] = "PRIVATE COMMENTARY"
        stop["transcript_path"] = str(self.root / "private.jsonl")
        with self.assertRaisesRegex(ValueError, "did not supply last_assistant_message"):
            self.capture(stop)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("RESPONSE", path.read_text())

    def test_extra_tool_reasoning_and_environment_fields_are_ignored(self):
        payload = self.payload()
        payload.update(reasoning="PRIVATE REASONING", tool_output="PRIVATE TOOL", system="PRIVATE SYSTEM", env={"TOKEN": "PRIVATE ENV"})
        path, _ = self.capture(payload)
        text = path.read_text()
        for excluded in ("PRIVATE REASONING", "PRIVATE TOOL", "PRIVATE SYSTEM", "PRIVATE ENV"):
            self.assertNotIn(excluded, text)

    def test_subagent_and_unsupported_events_are_rejected(self):
        for field in ("agent_id", "agent_type", "agent_transcript_path", "is_subagent"):
            payload = self.payload()
            payload[field] = "child"
            with self.assertRaisesRegex(ValueError, "Subagent"):
                self.capture(payload)
        with self.assertRaisesRegex(ValueError, "Only native"):
            self.capture(self.payload("SubagentStop"))

    def test_injected_context_is_not_a_user_prompt(self):
        for content in ("<environment_context>PRIVATE</environment_context>", "<external_codex_apps_open_page>{}</external_codex_apps_open_page>", "# AGENTS.md instructions for somewhere"):
            with self.assertRaisesRegex(ValueError, "Injected"):
                self.capture(self.payload(text=content))

    def test_app_generated_suggestion_is_not_a_human_prompt(self):
        content = (
            "This is an app-generated request for a suggested next user message. "
            "The user did not write this message.\n\n"
            "Predict the next message. Return JSON only."
        )
        for text in (content, "\n  " + content):
            with self.subTest(leading_whitespace=text != content):
                with self.assertRaisesRegex(ValueError, "Injected"):
                    self.capture(self.payload(text=text))
                self.assertFalse((self.root / ".claude-logs").exists())
        # Ordinary human requests discussing suggestions still capture normally.
        path, _ = self.capture(self.payload(text="Suggest my next Trace task."))
        self.assertEqual(logger.read_log(path, self.session)[1][0]["text"], "Suggest my next Trace task.")

    def test_invalid_ids_and_foreign_cwd_are_rejected(self):
        for field in ("session_id", "turn_id"):
            payload = self.payload()
            payload[field] = "../escape"
            with self.assertRaisesRegex(ValueError, "invalid native"):
                self.capture(payload)
        payload = self.payload()
        payload["cwd"] = str(self.root.parent)
        with self.assertRaisesRegex(ValueError, "outside this checkout"):
            self.capture(payload)

    def test_native_timestamp_or_explicit_capture_time_is_recorded(self):
        payload = self.payload()
        payload.pop("timestamp")
        path, _ = self.capture(payload)
        _, entries = logger.read_log(path, self.session)
        self.assertEqual(entries[0]["timestamp_source"], "hook_capture_time_utc")
        logger.instant(entries[0]["timestamp"])
        self.capture(self.payload("Stop"))
        _, entries = logger.read_log(path, self.session)
        self.assertEqual(entries[1]["timestamp"], "2026-10-30T14:00:00Z")
        self.assertEqual(entries[1]["timestamp_source"], "hook.timestamp")
        self.assertEqual(entries[1]["model"], "fixture-model")

    def test_unicode_whitespace_and_marker_text_round_trip(self):
        text = "  café → save ✓\r\n[CLAUDE_LOG_ENTRY type=RESPONSE num=99 session=fixture-session]\r\nThis is quoted user text.\rLast line.\n"
        path, _ = self.capture(self.payload(text=text))
        self.capture(self.payload("Stop", text="Done ✓\n\n"))
        _, entries = logger.read_log(path, self.session)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["text"], text.replace("\r\n", "\n").replace("\r", "\n"))
        self.assertEqual(entries[1]["text"], "Done ✓\n\n")

    def test_claude_file_and_hooks_can_coexist_unchanged(self):
        directory = self.root / ".claude-logs"
        directory.mkdir()
        old = directory / "2026-10-29_12-00-00_claude-existing.md"
        old.write_text("---\nagent: claude\n---\nExisting Claude content", encoding="utf-8")
        before = old.read_bytes()
        path = self.pair()
        self.assertNotEqual(old, path)
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(len(list(directory.glob("*.md"))), 2)

    def test_never_overwrites_another_agent_with_colliding_id(self):
        directory = self.root / ".claude-logs"
        directory.mkdir()
        old = directory / f"2026-10-29_12-00-00_{self.session}.md"
        old.write_text(f'---\nagent: claude\nsession_id: {self.session}\n---\nProtected', encoding="utf-8")
        before = old.read_bytes()
        with self.assertRaisesRegex(ValueError, "another agent/session"):
            self.capture(self.payload())
        self.assertEqual(old.read_bytes(), before)

    def test_distinct_developers_get_distinct_session_files(self):
        first = self.pair()
        other = {**IDENTITY, "author": "Other Fixture Developer", "github_user": "other-user", "git_identity_fingerprint": "other-fingerprint"}
        second, _ = logger.capture(self.payload(session="other-session"), self.root, lambda root, previous: other)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, second.parent)
        self.assertEqual(logger.read_log(first, self.session)[0]["github_user"], "fixture-user")
        self.assertEqual(logger.read_log(second, "other-session")[0]["github_user"], "other-user")

    def test_identity_cannot_change_within_one_session(self):
        path = self.pair()
        before = path.read_bytes()
        other = {**IDENTITY, "github_user": "different-user"}
        with self.assertRaisesRegex(ValueError, "identity changed"):
            logger.capture(self.payload(turn="turn-2"), self.root, lambda root, previous: other)
        self.assertEqual(path.read_bytes(), before)

    def test_redaction_is_idempotent(self):
        secret = "ghp_" + "x" * 28
        text = f'person@example.com {secret} password="longpassword123" Bearer ' + "z" * 30
        clean = logger.redact(text)
        for excluded in ("person@example.com", secret, "longpassword123", "z" * 30):
            self.assertNotIn(excluded, clean)
        self.assertEqual(logger.redact(clean), clean)
        path, _ = self.capture(self.payload(text=text))
        self.assertNotIn(secret, path.read_text())

    def test_required_cohort_statistics_and_markers_are_present(self):
        path = self.pair()
        text = path.read_text()
        for value in ("author:", "github_user:", "git_email:", "session_id:", "total_exchanges:", "first_prompt_time:", "last_prompt_time:", "session_duration_minutes:", "total_prompt_chars:", "total_prompt_words:", "avg_prompt_length_chars:", "avg_prompt_length_words:", "longest_prompt_words:", "shortest_prompt_words:", "total_response_chars:", "avg_response_length_chars:", "response_to_prompt_ratio:", "prompts_with_code_blocks:", "prompts_with_file_paths:", "prompts_with_urls:", "prompts_with_long_content:", "likely_pasted_count:"):
            self.assertIn(value, text)
        self.assertIn('[CLAUDE_LOG_ENTRY type=PROMPT num=1 session=fixture-session]', text)
        self.assertIn('[CLAUDE_LOG_ENTRY type=RESPONSE num=1 session=fixture-session]', text)

    def test_corrupt_existing_file_is_not_replaced(self):
        path = self.pair()
        path.write_text("not frontmatter", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid frontmatter"):
            self.capture(self.payload(turn="turn-2"))
        self.assertEqual(path.read_text(), "not frontmatter")

    def test_main_reads_native_stdin_and_returns_json(self):
        stdin = io.StringIO(json.dumps(self.payload()))
        stdout = io.StringIO()
        with patch.object(logger, "ROOT", self.root), patch.object(logger, "attribution", fixture_identity), patch.object(logger.sys, "stdin", stdin), patch.object(logger.sys, "stdout", stdout):
            self.assertEqual(logger.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue()), {})
        self.assertEqual(len(list((self.root / ".claude-logs").glob("*.md"))), 1)

    def test_out_of_order_stops_attach_to_the_correct_prompt(self):
        path, _ = self.capture(self.payload(turn="turn-1", text="First prompt"))
        self.capture(self.payload(turn="turn-2", text="Second prompt"))
        self.capture(self.payload("Stop", turn="turn-2", text="Second final"))
        self.capture(self.payload("Stop", turn="turn-1", text="First final"))
        _, entries = logger.read_log(path, self.session)
        self.assertEqual([(e["num"], e["text"]) for e in entries], [(1, "First prompt"), (1, "First final"), (2, "Second prompt"), (2, "Second final")])

    def run_concurrent_writers(self, turns):
        worker = """import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('capture_worker',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(sys.argv[2]);identity=json.loads(sys.argv[3]);turn=sys.argv[4]
for event in ('UserPromptSubmit','Stop'):
    payload={'session_id':'fixture-session','turn_id':turn,'cwd':str(root),'hook_event_name':event,'model':'fixture-model','prompt':'Prompt '+turn,'last_assistant_message':'Final '+turn}
    m.capture(payload,root,lambda root,previous:identity)
"""
        processes = [subprocess.Popen([sys.executable, "-B", "-c", worker, str(SCRIPT), str(self.root), json.dumps(IDENTITY), turn], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for turn in turns]
        for process in processes:
            out, err = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, out + err)
        files = list((self.root / ".claude-logs").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertFalse(list(files[0].parent.glob("*.tmp")))
        return logger.read_log(files[0], self.session)

    def test_concurrent_processes_preserve_all_exchanges(self):
        metadata, entries = self.run_concurrent_writers([f"concurrent-{i}" for i in range(6)])
        self.assertEqual(metadata["total_exchanges"], 6)
        self.assertEqual(metadata["total_responses"], 6)
        self.assertEqual(len(entries), 12)
        self.assertEqual({e["num"] for e in entries}, set(range(1, 7)))

    def test_concurrent_replays_are_idempotent(self):
        metadata, entries = self.run_concurrent_writers(["same-turn"] * 6)
        self.assertEqual(metadata["total_exchanges"], 1)
        self.assertEqual(metadata["total_responses"], 1)
        self.assertEqual(len(entries), 2)


if __name__ == "__main__":
    unittest.main()
