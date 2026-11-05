"""Integrity checks for private saved paths and their immutable source snapshots."""

import hashlib
import json

from app.schemas.github_projects import ProjectLearningPath, ProjectSnapshot


def canonical_digest(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def validate_learning_path(value: ProjectLearningPath, snapshot: ProjectSnapshot) -> None:
    # Revalidate even model_copy/model_construct values at the persistence boundary.
    value = ProjectLearningPath.model_validate_json(value.model_dump_json())
    snapshot = ProjectSnapshot.model_validate_json(snapshot.model_dump_json())
    if (
        value.status != "ready"
        or value.content is None
        or value.commit_sha != snapshot.commit_sha
        or value.snapshot_digest != snapshot.digest
        or canonical_digest(snapshot.model_dump(mode="json", exclude={"digest"})) != snapshot.digest
    ):
        raise ValueError("Learning path does not match its pinned snapshot")
    allowed = {item.reference_id for item in snapshot.references}
    if len(allowed) != len(snapshot.references) or any(
        item.reference_id
        != canonical_digest([snapshot.commit_sha, item.kind, item.path, item.text])
        for item in snapshot.references
    ):
        raise ValueError("Snapshot reference integrity failed")
    if any(
        not set(step.reference_ids) <= allowed
        or len(set(step.reference_ids)) != len(step.reference_ids)
        for step in value.content.steps
    ):
        raise ValueError("Learning path citations must identify pinned snapshot references")
