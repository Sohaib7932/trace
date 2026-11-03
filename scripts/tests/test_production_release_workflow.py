"""Exercise the manual release input guard without YAML packages or cloud commands."""

import ast
import io
import os
import re
import subprocess
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/deploy-production.yml"
MARKER = "synthetic_sensitive_input_do_not_echo"


def inline_guard():
    """Extract only this controlled Python heredoc; never execute workflow shell."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "python - <<'PY'")
    end = next(index for index in range(start + 1, len(lines)) if lines[index].strip() == "PY")
    source = textwrap.dedent("\n".join(lines[start + 1 : end]))
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    if imports != {"os", "re", "subprocess", "sys"} or any(
        isinstance(node, ast.ImportFrom) for node in ast.walk(tree)
    ):
        raise AssertionError("Release guard imports changed; review before executing it in tests")
    return compile(tree, "<controlled-production-release-guard>", "exec")


def valid_environment():
    # Format fixtures only: no real project, identity, image, approval or SDK call.
    prefix = "us-central1-docker.pkg.dev/trace-test-project/trace-backend/trace-backend"
    return {
        "APPROVED_PROJECT": "trace-test-project",
        "APPROVED_REGION": "us-central1",
        "RUN_SERVICE": "trace-api",
        "MIGRATION_JOB": "trace-migrate",
        "GCLOUD_VERSION": "123.45.6",
        "RELEASE_COMMIT": "a" * 40,
        "RELEASE_OWNER": "synthetic-test-owner",
        "CHANGE_APPROVAL": "synthetic-review-123",
        "BUDGET_APPROVAL": "synthetic-budget-123",
        "RELEASE_ACTION": "deploy_candidate",
        "APPROVED_IMAGE_PREFIX": prefix,
        "RELEASE_IMAGE": prefix + "@sha256:" + "b" * 64,
        "RELEASE_REVISION": "",
        "BACKUP_REFERENCE": "",
    }


CASES = (
    ("valid_candidate", {}, True, 0),
    ("unknown_action", {"RELEASE_ACTION": "other"}, False, 0),
    ("sensitive_owner_is_sanitized", {"RELEASE_OWNER": MARKER + "@invalid"}, False, 0),
    ("unapproved_repository", {"RELEASE_IMAGE": "evil.example/x@sha256:" + "b" * 64}, False, 0),
    (
        "mutable_image_tag",
        {"RELEASE_IMAGE": valid_environment()["APPROVED_IMAGE_PREFIX"] + ":latest"},
        False,
        0,
    ),
    (
        "image_shell_injection",
        {"RELEASE_IMAGE": valid_environment()["RELEASE_IMAGE"] + ";id"},
        False,
        0,
    ),
    ("region_shell_injection", {"APPROVED_REGION": "bad;id"}, False, 0),
    ("missing_budget_approval", {"BUDGET_APPROVAL": ""}, False, 0),
    ("unpinned_sdk", {"GCLOUD_VERSION": "latest"}, False, 0),
    ("non_sha_release_commit", {"RELEASE_COMMIT": "main"}, False, 0),
    (
        "revision_shell_injection",
        {"RELEASE_ACTION": "promote", "RELEASE_REVISION": "bad;id"},
        False,
        0,
    ),
    ("migration_requires_backup", {"RELEASE_ACTION": "migrate"}, False, 0),
    (
        "rollback_requires_backup",
        {"RELEASE_ACTION": "rollback", "RELEASE_REVISION": "trace-api-old"},
        False,
        0,
    ),
    ("commit_not_on_main", {}, False, 1),
    (
        "valid_migration",
        {"RELEASE_ACTION": "migrate", "BACKUP_REFERENCE": "synthetic-restore-123"},
        True,
        0,
    ),
    (
        "valid_promotion",
        {"RELEASE_ACTION": "promote", "RELEASE_REVISION": "trace-api-reviewed"},
        True,
        0,
    ),
    (
        "valid_rollback",
        {
            "RELEASE_ACTION": "rollback",
            "RELEASE_REVISION": "trace-api-old",
            "BACKUP_REFERENCE": "synthetic-restore-123",
        },
        True,
        0,
    ),
)


class ProductionReleaseInputTests(unittest.TestCase):
    def check_case(self, changes, accepted, ancestry):
        environment, output = {**valid_environment(), **changes}, io.StringIO()
        failed = False
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(
                subprocess, "run", return_value=SimpleNamespace(returncode=ancestry)
            ) as git,
            redirect_stdout(output),
            redirect_stderr(output),
        ):
            try:
                exec(inline_guard(), {})
            except SystemExit as error:
                failed = True
                self.assertNotIn(MARKER, str(error))
        self.assertEqual(not failed, accepted)
        self.assertNotIn(MARKER, output.getvalue())
        if accepted or ancestry:
            git.assert_called_once_with(
                [
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    environment["RELEASE_COMMIT"],
                    "origin/main",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            git.assert_not_called()


def case_test(changes, accepted, ancestry):
    def test(self):
        self.check_case(changes, accepted, ancestry)

    return test


for name, changes, accepted, ancestry in CASES:
    setattr(ProductionReleaseInputTests, "test_" + name, case_test(changes, accepted, ancestry))


class ProductionReleaseWiringTests(unittest.TestCase):
    def test_trigger_is_manual_only_and_production_requires_main(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        trigger = source.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(re.findall(r"^  ([a-z_]+):", trigger, re.MULTILINE), ["workflow_dispatch"])
        self.assertIn("    environment: production", source)
        self.assertIn("    if: github.ref == 'refs/heads/main'", source)
        self.assertIn("  cancel-in-progress: false", source)

    def test_actions_are_commit_pinned_and_cloud_commands_remain_outside_tested_guard(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        actions = re.findall(r"uses:\s+([^\s#]+)", source)
        self.assertTrue(actions)
        self.assertTrue(all(re.fullmatch(r"[^@]+@[a-f0-9]{40}", value) for value in actions))
        self.assertIn("      id-token: write", source)
        self.assertIn("      contents: read", source)
        self.assertNotIn("credentials_json:", source)
        tree = inline_guard()
        self.assertNotIn("gcloud", tree.co_names)


if __name__ == "__main__":
    unittest.main()
