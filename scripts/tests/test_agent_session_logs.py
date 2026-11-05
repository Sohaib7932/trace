"""Canonical exporters and hook dispatch use synthetic temporary transcripts only."""

import importlib.util
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "agent_session_logs_tests", SCRIPTS / "agent_session_logs.py"
)
logs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(logs)
IDENTITY = {
    "author": "Synthetic Developer",
    "github_user": "fixture-user",
    "git_email": "f***@example.test",
    "git_identity_fingerprint": "fixture-fingerprint",
    "github_identity_verified_at": "2026-11-05T10:00:00Z",
}
STAMP = "2026-11-05T10:00:00Z"
SESSION = "11111111-1111-4111-8111-111111111111"


def fixture_identity(root, previous):
    return IDENTITY.copy()


class AgentSessionExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "Trace fixture"
        self.root.mkdir()
        self.transcript = self.root.parent / f"rollout-{SESSION}.jsonl"
        self.protected = {}
        for name in (".env", "trace.db", "trace.db.backup", "user-report.md"):
            path = self.root / name
            path.write_bytes(b"private-local-fixture-must-remain-unchanged")
            self.protected[path] = (path.read_bytes(), path.stat().st_mtime_ns)
        self.addCleanup(self.assert_protected)

    def assert_protected(self):
        for path, (data, stamp) in self.protected.items():
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, stamp)

    def write(self, rows):
        self.transcript.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def codex_rows(
        self, *, final=True, turn="turn-1", prompt="A genuine fixture prompt"
    ):
        rows = [
            {
                "type": "session_meta",
                "timestamp": STAMP,
                "ordinal": 0,
                "payload": {"id": SESSION, "source": "vscode", "cwd": str(self.root)},
            }
        ]
        rows.append(
            {
                "type": "response_item",
                "timestamp": STAMP,
                "ordinal": 1,
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                    "internal_chat_message_metadata_passthrough": {
                        "turn_id": turn,
                        "content_item_kinds": ["user.text"],
                    },
                },
            }
        )
        if final:
            rows.append(
                {
                    "type": "response_item",
                    "timestamp": STAMP,
                    "ordinal": 2,
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [
                            {"type": "output_text", "text": "A genuine fixture final"}
                        ],
                        "internal_chat_message_metadata_passthrough": {"turn_id": turn},
                    },
                }
            )
        return rows

    def claude_rows(self, *, final=True):
        rows = [
            {
                "type": "user",
                "sessionId": SESSION,
                "cwd": str(self.root),
                "uuid": "human-1",
                "timestamp": STAMP,
                "message": {"role": "user", "content": "A genuine fixture prompt"},
            }
        ]
        if final:
            rows.append(
                {
                    "type": "assistant",
                    "sessionId": SESSION,
                    "cwd": str(self.root),
                    "uuid": "assistant-1",
                    "parentUuid": "human-1",
                    "timestamp": STAMP,
                    "message": {
                        "role": "assistant",
                        "content": "A genuine fixture final",
                        "stop_reason": "end_turn",
                    },
                }
            )
        return rows

    def export(self, agent="codex", **options):
        return logs.export_session(
            [self.transcript],
            agent,
            SESSION,
            self.root,
            identity_provider=fixture_identity,
            **options,
        )

    def read(self, result, agent="codex"):
        return logs._read_managed(
            Path(result["path"]),
            SESSION,
            "codex" if agent == "codex" else "claude-code",
        )

    def test_both_genuine_agent_shapes_use_one_canonical_format_and_correct_attribution(
        self,
    ):
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                self.write(
                    self.codex_rows() if agent == "codex" else self.claude_rows()
                )
                result = self.export(agent)
                self.assertEqual(result["status"], "written")
                path = Path(result["path"])
                self.assertEqual(path.parent, self.root / ".claude-logs")
                first = logs.native.instant(STAMP).astimezone()
                self.assertEqual(path.name, f"{first:%Y-%m-%d_%H-%M-%S}_{SESSION}.md")
                metadata, entries = self.read(result, agent)
                self.assertEqual(
                    metadata["agent"], "codex" if agent == "codex" else "claude-code"
                )
                self.assertEqual(metadata["author"], IDENTITY["author"])
                self.assertEqual(metadata["github_user"], IDENTITY["github_user"])
                self.assertEqual(metadata["capture_schema"], "agent-transcript-v1")
                self.assertFalse(metadata["automatic_hook_triggered"])
                self.assertEqual(metadata["total_exchanges"], 1)
                self.assertEqual(metadata["total_responses"], 1)
                self.assertEqual([e["kind"] for e in entries], ["PROMPT", "RESPONSE"])
                self.assertEqual(
                    [int(m[2]) for m in logs.native.MARKER.finditer(path.read_text())],
                    [1, 1],
                )
                self.assertIn(
                    "# Codex Session Log"
                    if agent == "codex"
                    else "# Claude Session Log",
                    path.read_text(),
                )
                path.unlink()  # Only this synthetic test's own log, to isolate the second agent.

    def test_identical_export_preserves_bytes_and_mtime(self):
        self.write(self.codex_rows())
        first = self.export()
        path = Path(first["path"])
        data, stamp = path.read_bytes(), path.stat().st_mtime_ns
        second = self.export()
        self.assertEqual(second, {"status": "unchanged", "path": str(path)})
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_partial_append_and_later_completed_final_update_same_file_without_fabrication(
        self,
    ):
        rows = self.codex_rows(final=False)
        self.write(rows)
        first = self.export()
        path = Path(first["path"])
        self.assertEqual(self.read(first)[0]["session_status"], "awaiting_response")
        data, stamp = path.read_bytes(), path.stat().st_mtime_ns
        with self.transcript.open("ab") as stream:
            stream.write(b'{"private-incomplete-final":')
        self.assertEqual(self.export()["status"], "unchanged")
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(path.stat().st_mtime_ns, stamp)
        self.write(self.codex_rows())
        second = self.export()
        self.assertEqual(second["path"], str(path))
        self.assertEqual(len(self.read(second)[1]), 2)
        self.assertEqual(len(list(path.parent.glob("*.md"))), 1)

    def test_concurrent_global_and_project_hook_exports_share_one_file(self):
        self.write(self.claude_rows())
        barrier = Barrier(2)
        payload = {
            "hook_event_name": "Stop",
            "cwd": str(self.root),
            "last_assistant_message": "A genuine fixture final",
        }

        def export():
            barrier.wait(timeout=5)
            return self.export("claude", hook_payload=payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(export) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sorted(r["status"] for r in results), ["unchanged", "written"])
        path = Path(results[0]["path"])
        self.assertEqual(len(list(path.parent.glob("*.md"))), 1)
        metadata, entries = self.read(results[0], "claude")
        self.assertTrue(metadata["automatic_hook_triggered"])
        self.assertEqual(len(entries), 2)

    def test_exports_redact_credentials_oauth_parameters_and_environment_values(self):
        sensitive = (
            "GEMINI_API_KEY=fixture-private-key-value\n"
            "$env:TRACE_GITHUB_APP_CLIENT_SECRET = 'fixture-private-secret'\n"
            "export TRACE_MODE=fixture-private-mode\n"
            "https://example.test/callback?code=fixture-oauth-code&state=fixture-oauth-state\n"
            "https://example.test/#access_token=fixture-oauth-token\n"
            "password: fixture-private-password"
        )
        self.write(self.codex_rows(prompt=sensitive))
        result = self.export()
        content = Path(result["path"]).read_text()
        for value in (
            "fixture-private-key-value",
            "fixture-private-secret",
            "fixture-private-mode",
            "fixture-oauth-code",
            "fixture-oauth-state",
            "fixture-oauth-token",
            "fixture-private-password",
        ):
            self.assertNotIn(value, content)
        self.assertIn("[ENV VALUE REDACTED]", content)
        self.assertIn("[REDACTED]", content)

    def test_legacy_native_and_different_agent_logs_are_never_overwritten(self):
        self.write(self.codex_rows())
        directory = self.root / ".claude-logs"
        directory.mkdir()
        path = directory / f"2026-11-05_10-00-00_{SESSION}.md"
        for content in (
            "A preserved legacy document\n",
            '---\nagent: "codex"\n---\nlegacy\n',
        ):
            with self.subTest(content=content):
                path.write_text(content)
                before = path.read_bytes()
                self.assertEqual(self.export()["status"], "preserved")
                self.assertEqual(path.read_bytes(), before)
        path.unlink()
        original = self.export()
        before = Path(original["path"]).read_bytes()
        self.write(self.claude_rows())
        self.assertEqual(self.export("claude")["status"], "preserved")
        self.assertEqual(Path(original["path"]).read_bytes(), before)

    def test_existing_reconstructed_filename_is_preserved_without_duplicate_session_file(
        self,
    ):
        self.write(self.codex_rows())
        directory = self.root / ".claude-logs"
        directory.mkdir()
        path = directory / f"2026-11-05_{SESSION}_reconstructed.md"
        path.write_text("Preserve this real-shaped legacy filename.\n")
        before = path.read_bytes()
        self.assertEqual(self.export()["status"], "preserved")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list(directory.glob("*.md"))), 1)

    def test_managed_header_with_unmarked_body_is_preserved_before_export_or_writes(
        self,
    ):
        self.write(self.codex_rows())
        directory = self.root / ".claude-logs"
        directory.mkdir()
        path = directory / f"2026-11-05_10-00-00_{SESSION}.md"
        path.write_text(
            f'---\nsession_id: "{SESSION}"\nagent: "codex"\n'
            'capture_schema: "agent-transcript-v1"\n---\n'
            "Valuable authentic body whose entry markers are missing.\n",
            encoding="utf-8",
        )
        before, stamp = path.read_bytes(), path.stat().st_mtime_ns
        with self.assertRaisesRegex(ValueError, "no valid entry markers"):
            logs._read_managed(path, SESSION, "codex")
        with (
            patch.object(logs.native, "atomic_write") as writer,
            patch.object(logs, "extract_codex_transcripts") as extractor,
        ):
            result = self.export()
        self.assertEqual(result["status"], "preserved")
        writer.assert_not_called()
        extractor.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, stamp)
        self.assertEqual(list(directory.glob("*.md")), [path])

    def test_existing_native_capture_is_preserved_byte_for_byte(self):
        path, _ = logs.native.capture(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": SESSION,
                "turn_id": "turn-1",
                "cwd": str(self.root),
                "timestamp": STAMP,
                "prompt": "A genuine fixture prompt",
            },
            self.root,
            fixture_identity,
        )
        before, stamp = path.read_bytes(), path.stat().st_mtime_ns
        self.write(self.codex_rows())
        self.assertEqual(self.export()["status"], "preserved")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_ambiguous_same_session_files_and_metadata_only_collisions_are_preserved(
        self,
    ):
        self.write(self.codex_rows())
        directory = self.root / ".claude-logs"
        directory.mkdir()
        first = directory / f"2026-11-05_{SESSION}.md"
        second = directory / "legacy-custom-name.md"
        first.write_text("Preserve the first synthetic historical log.\n")
        second.write_text(
            f'---\nsession_id: "{SESSION}"\nagent: "codex"\n---\nPreserve history.\n'
        )
        before = {path: path.read_bytes() for path in (first, second)}
        self.assertEqual(self.export()["status"], "preserved")
        self.assertEqual(len(list(directory.glob("*.md"))), 2)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_atomic_write_failure_preserves_the_previously_committed_log(self):
        self.write(self.codex_rows(final=False))
        original = self.export()
        path = Path(original["path"])
        before = path.read_bytes()
        self.write(self.codex_rows())
        with (
            patch.object(
                logs.native, "atomic_write", side_effect=OSError("synthetic failure")
            ),
            self.assertRaises(OSError),
        ):
            self.export()
        self.assertEqual(path.read_bytes(), before)

    def test_only_canonical_log_destination_can_reach_the_writer(self):
        self.write(self.codex_rows())
        real_writer = logs.native.atomic_write
        destinations = []

        def guarded(path, text):
            destinations.append(path)
            self.assertEqual(path.parent, self.root / ".claude-logs")
            self.assertNotIn(path, self.protected)
            real_writer(path, text)

        with patch.object(logs.native, "atomic_write", side_effect=guarded):
            self.export()
        self.assertEqual(len(destinations), 1)

    def test_conflicting_update_or_developer_identity_cannot_replace_existing_entries(
        self,
    ):
        self.write(self.codex_rows())
        result = self.export()
        path = Path(result["path"])
        before = path.read_bytes()
        self.write(self.codex_rows(prompt="A conflicting purported prompt"))
        with self.assertRaisesRegex(ValueError, "replace existing authentic entries"):
            self.export()
        self.assertEqual(path.read_bytes(), before)
        rows = self.codex_rows()
        more = self.codex_rows(turn="turn-2", prompt="A second prompt")[1:]
        for index, row in enumerate(more, start=3):
            row["ordinal"] = index
        self.write(rows + more)
        with self.assertRaisesRegex(ValueError, "Developer identity changed"):
            logs.export_session(
                [self.transcript],
                "codex",
                SESSION,
                self.root,
                identity_provider=lambda root, previous: {
                    **IDENTITY,
                    "github_user": "different-user",
                },
            )
        self.assertEqual(path.read_bytes(), before)

    def test_dry_run_and_invalid_transcript_do_not_create_logs_or_change_sources(self):
        self.write(self.codex_rows())
        before = self.transcript.read_bytes()
        self.assertEqual(self.export(dry_run=True)["status"], "ready")
        self.assertFalse((self.root / ".claude-logs").exists())
        self.assertEqual(self.transcript.read_bytes(), before)
        self.write(
            [
                {
                    "type": "session_meta",
                    "payload": {"id": "different", "cwd": str(self.root)},
                }
            ]
        )
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse((self.root / ".claude-logs").exists())

    def test_unsupported_agent_invalid_id_and_nonjsonl_sources_fail_closed(self):
        self.write(self.codex_rows())
        for agent, session in (("unknown", SESSION), ("codex", "../private")):
            with (
                self.subTest(agent=agent, session=session),
                self.assertRaises(ValueError),
            ):
                logs.export_session(
                    [self.transcript],
                    agent,
                    session,
                    self.root,
                    identity_provider=fixture_identity,
                )
        with self.assertRaises(ValueError):
            logs.export_session(
                [self.root / ".env"],
                "codex",
                SESSION,
                self.root,
                identity_provider=fixture_identity,
            )

    def test_symbolic_link_targets_are_rejected_before_any_write(self):
        self.write(self.codex_rows())
        directory = self.root / ".claude-logs"
        original = Path.is_symlink
        for target in (directory, self.transcript):
            with (
                self.subTest(target=target),
                patch.object(
                    Path,
                    "is_symlink",
                    lambda path, target=target: path == target or original(path),
                ),
                self.assertRaises(ValueError),
            ):
                self.export()
        self.assertFalse(directory.exists())

    def test_alias_from_a_different_repository_is_rejected(self):
        self.write(self.codex_rows())
        alias = self.root.parent / "other-checkout"
        alias.mkdir()
        with (
            patch.object(logs, "project_root", return_value=alias),
            patch.object(logs, "_common", side_effect=lambda p: p / ".git"),
            self.assertRaisesRegex(ValueError, "another repository"),
        ):
            self.export(source_cwds=(alias,))
        self.assertFalse((self.root / ".claude-logs").exists())

    def test_hook_rejects_foreign_unsupported_and_delegated_events_before_export(self):
        base = {
            "hook_event_name": "Stop",
            "cwd": str(self.root),
            "session_id": SESSION,
            "transcript_path": str(self.transcript),
        }
        with (
            patch.object(logs, "ROOT", self.root),
            patch.object(logs, "project_root", return_value=self.root),
            patch.object(logs, "export_session") as export,
        ):
            for change in (
                {"hook_event_name": "SubagentStop"},
                {"agent_id": "child"},
                {"isSidechain": True},
                {"cwd": "relative"},
                {"transcript_path": "relative.jsonl"},
            ):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    logs.hook("claude", {**base, **change})
            with self.assertRaises(ValueError):
                logs.hook("codex", base)
            export.assert_not_called()
        with (
            patch.object(logs, "ROOT", self.root),
            patch.object(logs, "project_root", return_value=self.root.parent),
            self.assertRaisesRegex(ValueError, "another checkout"),
        ):
            logs.hook("claude", base)

    def test_native_stop_mismatch_and_early_prompt_hook_never_fabricate_entries(self):
        self.write(self.claude_rows())
        payload = {
            "hook_event_name": "Stop",
            "cwd": str(self.root),
            "last_assistant_message": "Different purported final",
        }
        with self.assertRaisesRegex(ValueError, "evidence disagree"):
            self.export("claude", hook_payload=payload)
        self.assertFalse((self.root / ".claude-logs").exists())
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.root),
            "prompt": "A prompt not appended to the transcript yet",
        }
        self.assertEqual(
            self.export("claude", hook_payload=payload)["status"], "pending"
        )
        self.assertFalse((self.root / ".claude-logs").exists())


class NativeRedactionTests(unittest.TestCase):
    def test_legacy_provider_credentials_are_redacted_in_prose(self):
        for value in (
            "re_" + "f" * 20,
            "sb_secret_test",
            "sb_publishable_test",
        ):
            with self.subTest(prefix=value.split("_")[0]):
                text = f"The fixture credential is {value}; keep the surrounding prose."
                redacted = logs.native.redact(text)
                self.assertNotIn(value, redacted)
                self.assertIn("The fixture credential is ", redacted)
                self.assertIn("; keep the surrounding prose.", redacted)
                self.assertEqual(logs.native.redact(redacted), redacted)
        for placeholder in (
            "sb_secret_[REDACTED]",
            "sb_publishable_[REDACTED]",
            "re_[REDACTED]",
            "[API KEY REDACTED]",
        ):
            with self.subTest(placeholder=placeholder):
                self.assertEqual(logs.native.redact(placeholder), placeholder)

    def test_legacy_sensitive_colon_assignment_names_are_redacted(self):
        for name in (
            "DB_PASSWD",
            "DATABASE_URL",
            "SUPABASE_SERVICE_ROLE",
            "RESEND_APIKEY",
        ):
            with self.subTest(name=name):
                value = "SyntheticFixtureCredential123"
                redacted = logs.native.redact(f"{name}: {value}")
                self.assertEqual(redacted, f"{name}: [REDACTED]")
                self.assertEqual(logs.native.redact(redacted), redacted)

    def test_database_password_control_and_nonassignment_prose_are_preserved(self):
        value = "SyntheticFixtureCredential123"
        text = f"postgresql://fixture:{value}@database.invalid/fixture"
        redacted = logs.native.redact(text)
        self.assertNotIn(value, redacted)
        self.assertIn("://fixture:[REDACTED]@", redacted)
        self.assertEqual(logs.native.redact(redacted), redacted)
        prose = "Explain DATABASE_URL and PASSWD configuration and the Resend APIKEY."
        self.assertEqual(logs.native.redact(prose), prose)

    def test_oauth_query_and_fragment_values_are_removed_without_disclosing_them(self):
        text = "https://example.test/callback?code=fixture-code&state=fixture-state#access_token=fixture-token"
        redacted = logs.native.redact(text)
        self.assertEqual(
            redacted,
            "https://example.test/callback?code=[REDACTED]&state=[REDACTED]#access_token=[REDACTED]",
        )
        for value in ("fixture-code", "fixture-state", "fixture-token"):
            self.assertNotIn(value, redacted)
        self.assertIn("?code=[REDACTED]&state=[REDACTED]", redacted)
        self.assertEqual(
            logs.native.redact("https://example.test/#access_token=fixture-token"),
            "https://example.test/#access_token=[REDACTED]",
        )
        self.assertEqual(logs.native.redact(redacted), redacted)

    def test_environment_assignments_are_redacted_and_nonassignment_prose_is_preserved(
        self,
    ):
        for assignment in (
            "GEMINI_API_KEY=fixture-value",
            "export TRACE_MODE=fixture-value",
            "$env:TRACE_CLIENT_SECRET = 'fixture-value'",
            "  TRACE_TOKEN = fixture-value",
        ):
            with self.subTest(assignment=assignment):
                redacted = logs.native.redact(assignment)
                self.assertNotIn("fixture-value", redacted)
                self.assertIn("[ENV VALUE REDACTED]", redacted)
                self.assertEqual(logs.native.redact(redacted), redacted)
        self.assertEqual(
            logs.native.redact("Explain the code and state validation."),
            "Explain the code and state validation.",
        )


if __name__ == "__main__":
    unittest.main()
