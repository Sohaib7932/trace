"""Reject tracked runtime data while preserving local files and shared agent logs."""

import fnmatch
import subprocess
import unittest
from pathlib import Path


class RepositoryPrivateFilesTests(unittest.TestCase):
    def test_git_snapshot_excludes_private_runtime_files(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["git", "-c", "core.bare=false", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            timeout=15,
        )
        paths = result.stdout.decode("utf-8").split("\0")
        forbidden = []
        database_patterns = (
            "*.db",
            "*.db-*",
            "*.db.*",
            "*.sqlite",
            "*.sqlite-*",
            "*.sqlite.*",
            "*.sqlite3",
            "*.sqlite3-*",
            "*.sqlite3.*",
        )
        for path in filter(None, paths):
            name = Path(path).name.lower()
            environment = (
                name == ".env" or name.startswith(".env.") or name.endswith(".env")
            ) and not name.endswith(".example")
            database = any(fnmatch.fnmatchcase(name, pattern) for pattern in database_patterns)
            private_key = name.endswith((".pem", ".p12", ".pfx", ".key"))
            if environment or database or private_key:
                forbidden.append(path)
        self.assertEqual([], forbidden, "Private runtime files must remain outside Git.")


if __name__ == "__main__":
    unittest.main()
