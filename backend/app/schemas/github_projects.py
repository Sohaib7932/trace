"""Bounded private Project Learning contracts; no code execution or grading."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StrictInt

from app.core.ai_privacy import public_ai_question
from app.domain.lesson_spec.fields import Digest, Items, Value, VersionId, plain_text
from app.schemas.conversation_tutor import explanatory_text

type GitHubId = Annotated[StrictInt, Field(gt=0, le=2**63 - 1)]
type CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
type ProjectText = Annotated[
    str,
    Field(min_length=1, max_length=1000),
    AfterValidator(plain_text),
    AfterValidator(public_ai_question),
]


def ungraded_explanation(value: str) -> str:
    explanatory_text(value)
    if re.search(
        r"\b(?:you|the learner) (?:have |has |are |is )?"
        r"(?:mastered|demonstrated|competent|proficient|an? expert)\b|"
        r"\b(?:your|learner(?:'s)?) (?:competency |mastery )?(?:score|grade|rating)\b",
        value,
        re.I,
    ):
        raise ValueError("Project suggestions cannot assess learner competence")
    return value


type ProjectExplanation = Annotated[ProjectText, AfterValidator(ungraded_explanation)]


class InstallationStart(Value):
    installation_url: str
    authorization_url: str
    state: str = Field(repr=False)
    expires_at: datetime


class InstallationComplete(Value):
    installation_id: GitHubId
    state: str = Field(min_length=1, max_length=2000, repr=False)
    code: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_.-]+$", repr=False)


class InstallationView(Value):
    installation_id: GitHubId
    repository_selection: Literal["selected"] = "selected"
    authorization_expires_at: datetime | None = None
    status: Literal["authorized", "reauthorization_required", "disconnected"] = (
        "reauthorization_required"
    )


class RepositoryChoice(Value):
    installation_id: GitHubId
    repository_id: GitHubId


class RepositoryView(Value):
    repository_id: GitHubId
    full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=201)
    private: bool


class ConnectionView(RepositoryView):
    id: VersionId
    installation_id: GitHubId
    status: Literal["connected", "disconnected"] = "connected"


class SnapshotCreate(Value):
    commit_sha: CommitSha


class ProjectReference(Value):
    reference_id: Digest
    kind: Literal[
        "commit", "changed_file", "pull_request", "source", "agent_prompt", "agent_response"
    ]
    path: str = Field(min_length=1, max_length=500)
    text: ProjectText = Field(repr=False)


class ProjectSnapshot(Value):
    schema_version: Literal["project-snapshot-v1"] = "project-snapshot-v1"
    connection_id: VersionId
    commit_sha: CommitSha
    digest: Digest
    references: Items[ProjectReference] = Field(max_length=40)
    omitted_files: int = Field(ge=0)
    complete_repository: Literal[False] = False


class ProjectLearningStep(Value):
    title: ProjectExplanation
    explanation: ProjectExplanation
    question: ProjectExplanation
    reference_ids: Items[Digest] = Field(min_length=1, max_length=4)


class ProjectLearningContent(Value):
    schema_version: Literal["project-learning-v1"] = "project-learning-v1"
    title: ProjectExplanation
    steps: Items[ProjectLearningStep] = Field(min_length=1, max_length=5)


class ProjectLearningPath(Value):
    status: Literal["ready", "unavailable"]
    content: ProjectLearningContent | None = None
    snapshot_digest: Digest
    commit_sha: CommitSha
    source: Literal["ai", "test_fixture", "none"] = "none"
    grading: Literal["ungraded"] = "ungraded"
    execution_status: Literal["not_executed"] = "not_executed"
    can_complete_lesson: Literal[False] = False
