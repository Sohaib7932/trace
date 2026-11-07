"""Exercise Docker's real context filter with synthetic private-file canaries."""

import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from uuid import uuid4


def test_local_database_backups_keys_and_environments_never_enter_build_context(tmp_path):
    root = Path(__file__).resolve().parents[2]
    context = tmp_path / "context"
    context.mkdir()
    shutil.copyfile(root / ".dockerignore", context / ".dockerignore")
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /context/\n", encoding="utf-8")
    (context / "public.txt").write_text("public fixture", encoding="utf-8")
    private = (
        "backend/trace.db.before-0010.bak",
        "backend/trace.db",
        "backend/trace.db-wal",
        "backend/learner.sqlite3",
        "backend/private.backup",
        "backend/private.pem",
        "backend/private.key",
        "backend/private.p12",
        "backend/private.pfx",
        "backend/.env",
        "backend/.env.gemini",
        "backend/github.env",
    )
    for name in private:
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic private canary; not a credential", encoding="utf-8")
    owner = uuid4().hex
    label = "com.trace.build-context-test"
    image = f"trace-context-test-{owner}:local"
    container = None

    def docker(*args):
        return subprocess.run(["docker", *args], capture_output=True, timeout=45)

    try:
        built = docker(
            "build",
            "--pull=false",
            "--network=none",
            "--no-cache",
            "--progress=plain",
            "--label",
            f"{label}={owner}",
            "--tag",
            image,
            str(context),
        )
        assert built.returncode == 0, "The isolated scratch build must succeed."
        created = docker("create", "--label", f"{label}={owner}", image, "/not-executed")
        assert created.returncode == 0, "Create an unstarted test container for inspection."
        container = created.stdout.decode("ascii").strip()
        exported = docker("export", container)
        assert exported.returncode == 0
        # Read only the generated tar; never extract arbitrary member paths.
        with tarfile.open(fileobj=io.BytesIO(exported.stdout)) as archive:
            names = set(archive.getnames())
            public = archive.extractfile("context/public.txt")
            assert public is not None and public.read() == b"public fixture"
            assert all("context/" + name not in names for name in private)
        assert all((context / name).exists() for name in private), "Local originals stay intact."
    finally:
        # Cleanup is restricted to this test's random tag/ID and verified label.
        if container is not None:
            inspected = docker("inspect", container)
            assert inspected.returncode == 0
            assert json.loads(inspected.stdout)[0]["Config"]["Labels"].get(label) == owner
            assert docker("rm", container).returncode == 0
        inspected_image = docker("image", "inspect", image)
        if inspected_image.returncode == 0:
            assert json.loads(inspected_image.stdout)[0]["Config"]["Labels"].get(label) == owner
            assert docker("image", "rm", "--no-prune", image).returncode == 0
