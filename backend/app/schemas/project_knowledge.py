"""Versioned read-only repository knowledge; V1 receipts remain unchanged."""

import hashlib
import re
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from app.core.ai_privacy import public_ai_question
from app.domain.lesson_spec.fields import Digest, Items, Value, VersionId
from app.schemas.github_projects import CommitSha, GitHubId


def repository_path(value: str) -> str:
    public_ai_question(value)
    if (
        not re.fullmatch(r"[A-Za-z0-9_./@()\[\] -]+", value)
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or len(value) > 500
    ):
        raise ValueError("Use a safe pinned repository path")
    return value


_SYMBOLIC_FIELD = (
    r"(?:[A-Za-z0-9_]+_)?(?:access_token|refresh_token|client_secret|api_key|secret_key|"
    r"password|service_role_key|aws_secret_access_key|aws_session_token|github_token)"
)
_ANNOTATION_ONLY = re.compile(
    rf"(?im)\b{_SYMBOLIC_FIELD}\s*:\s*(?:SecretStr|str|bytes)(?:\s*\|\s*None)?"
    r"(?=\s*(?:[,)]|$))"
)
_SYMBOLIC_CALL = re.compile(
    rf"(?im)^(\s*{_SYMBOLIC_FIELD}\s*=\s*)"
    r"[A-Za-z_][A-Za-z0-9_.]*\([A-Za-z0-9_., ()=*\[\]]*\)\s*$"
)


def untrusted_source(value: str) -> str:
    # A source file may reference a credential variable without containing its
    # value. Suppress only a value-free annotation or string-free symbolic call
    # for the privacy SCREEN, retaining the original source exactly. Literal
    # assignments, credential prefixes, emails and all other forms still fail.
    screened = _ANNOTATION_ONLY.sub("symbolic_field: str", value)
    screened = _SYMBOLIC_CALL.sub(
        lambda match: "symbolic_assignment = " + match.group(0)[len(match.group(1)) :], screened
    )
    public_ai_question(screened)
    if not value.strip() or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError("Use bounded plain UTF-8 source")
    return value


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Source timestamps require a timezone")
    return value


def metadata_text(value: str) -> str:
    public_ai_question(value)
    if not value.strip() or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError("Use nonblank source metadata without control characters")
    return value


MetadataText = Annotated[str, AfterValidator(metadata_text)]
type RepositoryPath = Annotated[
    str, Field(min_length=1, max_length=500), AfterValidator(repository_path)
]
type SourceText = Annotated[
    str, Field(min_length=1, max_length=1800), AfterValidator(untrusted_source)
]
type SourceTimestamp = Annotated[str, Field(max_length=50), AfterValidator(timestamp)]
type SourceCategory = Literal[
    "frontend",
    "backend",
    "api_schema",
    "database",
    "migration",
    "documentation",
    "source",
    "agent_log",
]


class RepositoryKnowledgeMetadata(Value):
    repository_id: GitHubId
    full_name: MetadataText = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=201)
    private: bool
    default_branch: MetadataText = Field(min_length=1, max_length=200)


class RepositoryTreeEntry(Value):
    path: RepositoryPath
    kind: Literal["file", "directory"]
    blob_sha: CommitSha
    size: int | None = Field(default=None, ge=0, le=2**40)
    category: SourceCategory
    content_included: bool = False


class AgentLogMetadata(Value):
    format: Literal["native_cohort"] = "native_cohort"
    session_id: MetadataText = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    entry_number: int = Field(ge=1, le=1000000)
    turn_id: MetadataText | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    timestamp: SourceTimestamp | None = None
    timestamp_source: Literal["hook.timestamp", "hook_capture_time_utc", "unknown"] = "unknown"
    model: MetadataText | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:/-]+$")
    correlation: Literal["same_pinned_snapshot_only"] = "same_pinned_snapshot_only"
    prompt_to_file_relationship: Literal["unproven"] = "unproven"


class RepositorySourceReference(Value):
    reference_id: Digest
    digest: Digest
    path: RepositoryPath
    line_start: int = Field(ge=1, le=1000000)
    line_end: int = Field(ge=1, le=1000000)
    text: SourceText = Field(repr=False)
    kind: Literal["source", "agent_prompt", "agent_response"] = "source"
    category: SourceCategory
    blob_sha: CommitSha
    agent: AgentLogMetadata | None = None

    @model_validator(mode="after")
    def exact_span_and_digest(self) -> Self:
        if self.line_end < self.line_start or self.line_end - self.line_start + 1 != len(
            self.text.splitlines()
        ):
            raise ValueError("Line range must exactly match the supplied source")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.digest:
            raise ValueError("Source digest does not match exact text")
        if (self.kind == "source") != (self.agent is None):
            raise ValueError("Native agent blocks require their source metadata")
        return self


class RepositoryCommit(Value):
    commit_sha: CommitSha
    title: Annotated[str, Field(min_length=1, max_length=300), AfterValidator(untrusted_source)]
    timestamp: SourceTimestamp | None = None
    changed_files: Items[RepositoryPath] = Field(default=(), max_length=75)
    changed_files_complete: bool = False


class RepositoryIngestionCoverage(Value):
    status: Literal["partial"] = "partial"
    tree_complete: bool
    history_complete: bool
    changed_files_complete: bool
    catalog_entries: int = Field(ge=0, le=240)
    fetched_files: int = Field(ge=0, le=18)
    omitted_files: int = Field(ge=0, le=1000000)
    reasons: Items[
        Literal[
            "excluded_path",
            "unsupported_type",
            "file_size",
            "invalid_content",
            "tree_budget",
            "catalog_budget",
            "file_budget",
            "source_budget",
            "history_budget",
            "changed_files_budget",
            "request_deadline_budget",
            "truncated_tree",
            "unsupported_agent_format",
        ]
    ] = Field(default=(), max_length=14)
    max_catalog_entries: Literal[240] = 240
    max_tree_requests: Literal[20] = 20
    max_fetched_files: Literal[18] = 18
    max_file_bytes: Literal[32768] = 32768
    max_references: Literal[40] = 40
    max_source_bytes: Literal[48000] = 48000
    max_history_commits: Literal[30] = 30
    max_changed_files: Literal[75] = 75
    max_artifact_bytes: Literal[98304] = 98304


class RepositoryKnowledgeSnapshot(Value):
    schema_version: Literal["project-repository-v2"] = "project-repository-v2"
    connection_id: VersionId
    commit_sha: CommitSha
    digest: Digest
    repository: RepositoryKnowledgeMetadata
    catalog: Items[RepositoryTreeEntry] = Field(max_length=240)
    references: Items[RepositorySourceReference] = Field(min_length=1, max_length=40)
    commits: Items[RepositoryCommit] = Field(default=(), max_length=30)
    coverage: RepositoryIngestionCoverage
    complete_repository: Literal[False] = False

    @model_validator(mode="after")
    def bounded_artifact(self) -> Self:
        if len(self.model_dump_json().encode()) > 98304:
            raise ValueError("Repository knowledge exceeds 96 KiB")
        if len({item.reference_id for item in self.references}) != len(self.references):
            raise ValueError("Reference identifiers must be unique")
        if len({item.path for item in self.catalog}) != len(self.catalog):
            raise ValueError("Catalog paths must be unique")
        return self
