"""The legacy endpoint shares exclusions without rewriting historical receipts."""

from uuid import UUID

import pytest

from app.core.errors import ApplicationError
from app.schemas.github_projects import ProjectSnapshot
from app.services.github_projects import allowed_source, digest, reference
from tests.integration.test_github_projects import connected
from tests.integration.test_github_projects import project as project  # noqa: F401


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/library/index.js",
        "dist/client.js",
        "build/server.py",
        "coverage/report.json",
        "src/generated/schema.ts",
        "src/api.generated.ts",
        "package-lock.json",
        "src/identity.d.ts",
        "src/person@example.com.py",
    ],
)
def test_legacy_source_excludes_dependency_build_generated_and_private_paths(path):
    assert not allowed_source(path)


@pytest.mark.parametrize("operation", ["snapshot", "sync", "learning_path"])
def test_unsafe_old_receipt_is_withheld_without_rewriting_its_hash(project, operation):
    connection = connected(project)
    identity = UUID(connection.id)
    lease = project.service.authorize_connection(project.owner, identity)
    sha = "b" * 40
    item = reference("source", "node_modules/library/index.js", "export const x = 1;", sha)
    assert item is not None
    payload = {
        "schema_version": "project-snapshot-v1",
        "connection_id": connection.id,
        "commit_sha": sha,
        "references": [item.model_dump(mode="json")],
        "omitted_files": 0,
        "complete_repository": False,
    }
    saved = ProjectSnapshot.model_validate({**payload, "digest": digest(payload)})
    assert project.service.repository.save_snapshot(saved, project.clock(), lease=lease)
    with pytest.raises(ApplicationError) as failure:
        getattr(project.service, operation)(project.owner, identity, sha)
    assert failure.value.status_code == 503
    assert project.service.repository.load_snapshot(identity, sha) == saved
    assert project.ai.calls == []
