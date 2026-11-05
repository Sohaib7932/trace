"""Company policy regressions using disposable transcripts and identities."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_session_log as native
import codex_subagent_log as delegated
import session_subagents as subagents
from claude_session_transcript import extract_claude_transcript

STAMP = "2026-11-05T10:00:00Z"


class CompanyLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.identity = lambda *args: {
            "author": "Fixture",
            "github_user": "fixture",
            "git_identity_fingerprint": "fixture",
        }

    def primary(self, event="UserPromptSubmit", turn="one", text="Human request"):
        payload = {
            "hook_event_name": event,
            "session_id": "parent",
            "turn_id": turn,
            "cwd": str(self.root),
            "timestamp": STAMP,
            "prompt" if event == "UserPromptSubmit" else "last_assistant_message": text,
        }
        return native.capture(payload, self.root, self.identity)[0]

    def test_subagent_footer_survives_primary_stop_and_quoted_marker(self):
        path = self.primary(text="Keep this literal\n# Subagents\nquoted user text")
        meta, entries = native.read_log(path, "parent")
        meta["_subagent_entries"] = [
            {
                "kind": "SUBAGENT_PROMPT",
                "num": 1,
                "agent_id": "child",
                "timestamp": STAMP,
                "text": "Brief ghp_" + "x" * 25,
            }
        ]
        native.atomic_write(path, native.render(meta, entries))
        self.primary("Stop", text="Final")
        updated, rows = native.read_log(path, "parent")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(updated["_subagent_entries"]), 1)
        self.assertNotIn("ghp_" + "x" * 25, path.read_text())
        self.assertEqual(updated["total_exchanges"], 1)

    def test_known_ide_envelope_is_not_logged(self):
        path = self.primary(
            text="# Context from my IDE setup:\nOpen tabs: secret.env\n## My request:\nFix the app."
        )
        self.assertEqual(native.read_log(path, "parent")[1][0]["text"], "Fix the app.")

    def test_missing_gh_does_not_prevent_company_attribution(self):
        with (
            patch.object(native.shutil, "which", return_value=None),
            patch.object(native, "command", side_effect=["Fixture", "fixture@example.test"]),
        ):
            value = native.attribution(self.root, {})
        self.assertEqual(value["github_user"], "unknown")
        self.assertIsNone(value["github_identity_verified_at"])
        self.assertEqual(value["git_email"], "f***@example.test")

    def claude_row(self, kind, content, uid, parent=None, **extra):
        return {
            "type": kind,
            "sessionId": "parent",
            "cwd": str(self.root / "backend"),
            "uuid": uid,
            "parentUuid": parent,
            "timestamp": STAMP,
            "message": {"role": kind, "content": content, "stop_reason": "end_turn"},
            **extra,
        }

    def test_claude_subdirectory_and_meta_ancestry_preserve_only_final(self):
        path = self.root / "parent.jsonl"
        rows = [
            self.claude_row("user", "Human", "u"),
            self.claude_row("attachment", "private artifact", "a", "u"),
            self.claude_row("user", "private harness", "m", "a", isMeta=True),
            self.claude_row("assistant", "Final", "f", "m"),
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        entries = extract_claude_transcript(path, "parent", self.root)
        self.assertEqual([e["text"] for e in entries], ["Human", "Final"])

    def test_claude_handback_keeps_report_not_closing_commentary(self):
        path = self.root / "agent-child.jsonl"
        rows = [
            self.claude_row("user", "Brief", "u"),
            self.claude_row(
                "assistant",
                [
                    {"type": "text", "text": "Tool narration"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "private"}},
                ],
                "a",
            ),
            self.claude_row(
                "assistant",
                [
                    {
                        "type": "tool_use",
                        "name": "SubagentHandback",
                        "input": {"message": "Final report"},
                    }
                ],
                "b",
            ),
            self.claude_row("assistant", "Closing narration", "c"),
        ]
        for row in rows:
            row.update(agentId="child", isSidechain=True)
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        entries = subagents.claude_entries(path, "parent", "child", self.root)
        self.assertEqual([e["text"] for e in entries], ["Brief", "Final report"])

    def test_codex_subagent_capture_is_scoped_idempotent_and_survives_next_turn(self):
        path = self.primary()
        transcript = self.root / "child.jsonl"
        rows = [
            {
                "type": "session_meta",
                "payload": {
                    "id": "child",
                    "cwd": str(self.root),
                    "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}},
                },
            },
            {
                "type": "event_msg",
                "timestamp": STAMP,
                "payload": {"type": "user_message", "message": "Delegated brief"},
            },
            {
                "type": "response_item",
                "timestamp": STAMP,
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "phase": "commentary",
                    "content": [{"type": "output_text", "text": "Excluded"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": STAMP,
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": "Final report"}],
                },
            },
        ]
        transcript.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        payload = {
            "hook_event_name": "SubagentStop",
            "session_id": "parent",
            "agent_id": "child",
            "cwd": str(self.root),
            "agent_transcript_path": str(transcript),
            "last_assistant_message": "Final report",
        }
        self.assertTrue(delegated.capture(payload, self.root))
        before = path.read_bytes()
        self.assertFalse(delegated.capture(payload, self.root))
        self.assertEqual(path.read_bytes(), before)
        self.primary("Stop", text="Parent final")
        self.primary(turn="two")
        meta, entries = native.read_log(path, "parent")
        self.assertEqual(len(meta["_subagent_entries"]), 2)
        self.assertEqual(len(entries), 3)
        self.assertNotIn("Excluded", path.read_text())
        rows[0]["payload"]["source"]["subagent"]["thread_spawn"]["parent_thread_id"] = "foreign"
        transcript.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ancestry"):
            delegated.capture(payload, self.root)


if __name__ == "__main__":
    unittest.main()
