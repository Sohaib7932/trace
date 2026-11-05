"""Global logging installation and wrapper tests use temporary fixtures only."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "setup_agent_session_logging.py"
SPEC = importlib.util.spec_from_file_location("setup_agent_session_logging", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class LoggingSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        # Resolve once: on Windows runners the temp dir is a short 8.3 name (RUNNER~1) that the
        # code under test resolves to the long one, so compare against the resolved path.
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "private-global-claude"
        self.project = self.make_project("Trace project $literal & spaces")

    def tearDown(self):
        self.temporary.cleanup()

    def make_project(self, name):
        root = self.base / name
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "agent_session_logs.py").write_text(
            "import json, pathlib, sys\n"
            "payload = sys.stdin.buffer.read()\n"
            "pathlib.Path('dispatched.json').write_text(json.dumps({"
            "'argv': sys.argv[1:], 'stdin': payload.decode(), 'cwd': str(pathlib.Path.cwd())}))\n"
            "print('synthetic-child-output-must-not-escape')\n"
            "print('synthetic-child-error-must-not-escape', file=sys.stderr)\n",
            encoding="utf-8",
        )
        return root

    def write_settings(self, value):
        self.home.mkdir(parents=True, exist_ok=True)
        target = self.home / "settings.json"
        target.write_text(json.dumps(value), encoding="utf-8")
        return target

    def apply(self, projects=None):
        return setup.install(self.home, projects or [self.project], apply=True)

    def invoke_wrapper(self, payload):
        return subprocess.run(
            [sys.executable, "-B", str(self.home / "extract-log.py")],
            input=json.dumps(payload).encode(),
            capture_output=True,
            timeout=10,
            check=False,
        )

    def test_default_dry_run_does_not_create_global_directory(self):
        result = setup.install(self.home, [self.project])
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(len(result["changed_files"]), 3)
        self.assertFalse(self.home.exists())
        self.assertFalse((self.project / ".claude-logs").exists())

    def test_dry_run_cli_and_safe_local_command_quoting(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = setup.main(
                ["--project", str(self.project), "--claude-home", str(self.home)]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "dry-run")
        writes = setup.prepare(self.home, [self.project])
        settings = json.loads(writes[self.home / "settings.json"])
        for event in ("UserPromptSubmit", "Stop"):
            command = settings["hooks"][event][0]["hooks"][0]["command"]
            self.assertEqual(
                shlex.split(command),
                [sys.executable, "-B", str(self.home / "extract-log.py")],
            )

    def test_apply_preserves_every_unrelated_setting_and_hook(self):
        session_start = [{"hooks": [{"type": "command", "command": "existing-start"}]}]
        native_prompt = [
            {"matcher": "", "hooks": [{"type": "command", "command": "existing"}]}
        ]
        original = {
            "autoUpdatesChannel": "latest",
            "permissions": {"allow": ["Read"]},
            "env": {"SYNTHETIC_SETTING": "preserve-this-value"},
            "hooks": {"SessionStart": session_start, "UserPromptSubmit": native_prompt},
        }
        target = self.write_settings(original)
        original_bytes = target.read_bytes()
        result = self.apply()
        changed = json.loads(target.read_text())
        self.assertEqual(changed["autoUpdatesChannel"], original["autoUpdatesChannel"])
        self.assertEqual(changed["env"], original["env"])
        self.assertEqual(changed["permissions"], original["permissions"])
        self.assertEqual(changed["hooks"]["SessionStart"], session_start)
        self.assertEqual(changed["hooks"]["UserPromptSubmit"][0], native_prompt[0])
        self.assertEqual(len(changed["hooks"]["UserPromptSubmit"]), 2)
        self.assertEqual(len(changed["hooks"]["Stop"]), 1)
        backup = Path(result["backup_directory"])
        self.assertEqual((backup / "settings.json").read_bytes(), original_bytes)
        self.assertFalse(backup.is_relative_to(self.project))
        self.assertFalse(result["hook_trust_changed"])

    def test_identical_reinstall_makes_no_changes_or_new_backups(self):
        self.write_settings({"hooks": {"SessionStart": []}})
        self.apply()
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.home.rglob("*")
            if path.is_file()
        }
        result = self.apply()
        after = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.home.rglob("*")
            if path.is_file()
        }
        self.assertEqual(result["changed_files"], [])
        self.assertIsNone(result["backup_directory"])
        self.assertEqual(before, after)

    def test_additional_registration_preserves_prior_projects_and_unknown_registry_fields(
        self,
    ):
        self.apply()
        registry = self.home / setup.REGISTRY_NAME
        existing = json.loads(registry.read_text())
        existing["operator_note"] = "synthetic-preserved-setting"
        registry.write_text(json.dumps(existing), encoding="utf-8")
        another = self.make_project("another Trace")
        self.apply([another, self.project])
        changed = json.loads(registry.read_text())
        self.assertEqual(changed["projects"], [str(self.project), str(another)])
        self.assertEqual(changed["operator_note"], existing["operator_note"])

    def test_unknown_existing_wrapper_blocks_all_writes(self):
        target = self.write_settings({"hooks": {"SessionStart": []}})
        wrapper = self.home / "extract-log.py"
        wrapper.write_text("# user-owned unrelated script\n", encoding="utf-8")
        before = {target: target.read_bytes(), wrapper: wrapper.read_bytes()}
        with self.assertRaises(setup.SetupError):
            self.apply()
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertFalse((self.home / setup.REGISTRY_NAME).exists())
        self.assertFalse((self.home / "trace-session-logging-backups").exists())

    def test_managed_wrapper_upgrade_is_backed_up(self):
        self.home.mkdir()
        wrapper = self.home / "extract-log.py"
        old = setup.MANAGED_MARKER + "\n# synthetic older managed implementation\n"
        wrapper.write_text(old, encoding="utf-8")
        result = self.apply()
        self.assertEqual(
            (Path(result["backup_directory"]) / wrapper.name).read_text(), old
        )
        self.assertEqual(wrapper.read_text(), setup.WRAPPER)

    def test_malformed_existing_settings_fail_without_printing_contents(self):
        target = self.write_settings({})
        target.write_text('{"synthetic-private-canary":', encoding="utf-8")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = setup.main(
                [
                    "--project",
                    str(self.project),
                    "--claude-home",
                    str(self.home),
                    "--apply",
                ]
            )
        self.assertEqual(code, 1)
        self.assertNotIn("synthetic-private-canary", captured.getvalue())
        self.assertEqual(target.read_text(), '{"synthetic-private-canary":')
        self.assertFalse((self.home / "extract-log.py").exists())

    def test_global_config_inside_registered_project_is_rejected(self):
        with self.assertRaises(setup.SetupError):
            setup.install(self.project / ".claude", [self.project], apply=True)
        self.assertFalse((self.project / ".claude").exists())

    def test_invalid_hook_shapes_and_registry_fail_before_writes(self):
        for hooks in (
            [],
            {"Stop": "wrong"},
            {"Stop": ["wrong"]},
            {"Stop": [{"hooks": {}}]},
        ):
            with self.subTest(hooks=hooks):
                self.write_settings({"hooks": hooks})
                with self.assertRaises(setup.SetupError):
                    self.apply()
                self.assertFalse((self.home / "extract-log.py").exists())
        self.write_settings({})
        (self.home / setup.REGISTRY_NAME).write_text(
            json.dumps({"version": True, "projects": []}), encoding="utf-8"
        )
        with self.assertRaises(setup.SetupError):
            self.apply()

    def test_wrapper_forwards_exact_native_payload_for_registered_subdirectory_only(
        self,
    ):
        self.apply()
        cwd = self.project / "backend"
        cwd.mkdir()
        for event in ("UserPromptSubmit", "Stop"):
            payload = {
                "hook_event_name": event,
                "cwd": str(cwd),
                "session_id": "synthetic-session",
                "prompt": "Synthetic native prompt",
                "transcript_path": str(self.base / "exact-transcript.jsonl"),
            }
            completed = self.invoke_wrapper(payload)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout, b"")
            self.assertEqual(completed.stderr, b"")
            dispatched = json.loads((self.project / "dispatched.json").read_text())
            self.assertEqual(dispatched["argv"], ["hook", "--agent", "claude"])
            self.assertEqual(json.loads(dispatched["stdin"]), payload)
            self.assertEqual(dispatched["cwd"], str(self.project))

    def test_wrapper_never_dispatches_unregistered_project_or_same_prefix_sibling(self):
        self.apply()
        outside = self.make_project("unregistered")
        sibling = self.make_project(self.project.name + "-other")
        for cwd in (outside, sibling):
            with self.subTest(cwd=cwd):
                completed = self.invoke_wrapper(
                    {"hook_event_name": "Stop", "cwd": str(cwd)}
                )
                self.assertEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout + completed.stderr, b"")
                self.assertFalse((cwd / "dispatched.json").exists())
        self.assertFalse((self.project / "dispatched.json").exists())

    def test_wrapper_ignores_unsupported_events_missing_cwd_and_environment_fallbacks(
        self,
    ):
        self.apply()
        for payload in (
            {"hook_event_name": "SessionStart", "cwd": str(self.project)},
            {"hook_event_name": "Stop"},
            {"hook_event_name": "Stop", "cwd": 1},
            {"hook_event_name": "Stop", "cwd": "relative-project"},
        ):
            completed = self.invoke_wrapper(payload)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout + completed.stderr, b"")
        self.assertFalse((self.project / "dispatched.json").exists())

    def test_wrapper_rejects_corrupt_registry_without_dispatch_or_payload_output(self):
        self.apply()
        registry = self.home / setup.REGISTRY_NAME
        for value in (
            {"version": True, "projects": [str(self.project)]},
            {"version": 1, "projects": ["relative-project"]},
            {"version": 1, "projects": [3]},
        ):
            with self.subTest(value=value):
                registry.write_text(json.dumps(value), encoding="utf-8")
                completed = self.invoke_wrapper(
                    {"hook_event_name": "Stop", "cwd": str(self.project)}
                )
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stdout + completed.stderr, b"")
        self.assertFalse((self.project / "dispatched.json").exists())

    def test_missing_exporter_blocks_registration_without_creating_global_files(self):
        (self.project / "scripts" / "agent_session_logs.py").unlink()
        with self.assertRaises(setup.SetupError):
            self.apply()
        self.assertFalse(self.home.exists())

    def test_wrapper_chooses_most_specific_registered_checkout(self):
        nested = self.project / "nested"
        (nested / "scripts").mkdir(parents=True)
        (nested / "scripts" / "agent_session_logs.py").write_bytes(
            (self.project / "scripts" / "agent_session_logs.py").read_bytes()
        )
        self.apply([self.project, nested])
        completed = self.invoke_wrapper({"hook_event_name": "Stop", "cwd": str(nested)})
        self.assertEqual(completed.returncode, 0)
        self.assertTrue((nested / "dispatched.json").exists())
        self.assertFalse((self.project / "dispatched.json").exists())

    def test_wrapper_malformed_payload_and_exporter_errors_remain_silent(self):
        self.apply()
        completed = subprocess.run(
            [sys.executable, "-B", str(self.home / "extract-log.py")],
            input=b"synthetic malformed payload",
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout + completed.stderr, b"")
        exporter = self.project / "scripts" / "agent_session_logs.py"
        exporter.write_text(
            "raise RuntimeError('synthetic-private-error')", encoding="utf-8"
        )
        completed = self.invoke_wrapper(
            {"hook_event_name": "Stop", "cwd": str(self.project)}
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout + completed.stderr, b"")


if __name__ == "__main__":
    unittest.main()
