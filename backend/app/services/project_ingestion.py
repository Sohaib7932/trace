"""Deterministic, bounded repository inspection through a read-only provider port.

No repository content is executed, treated as instructions or accepted as a
learner result. V1 snapshot models and historical digest rules are untouched.
"""

import hashlib
import json
import re
from collections import deque
from typing import Any

from pydantic import ValidationError

from app.ai.github_projects import GitHubProjectClient
from app.core.ai_privacy import public_ai_question
from app.core.errors import ApplicationError
from app.core.github_errors import unavailable
from app.schemas.github_projects import ConnectionView
from app.schemas.project_knowledge import (
    AgentLogMetadata,
    RepositoryCommit,
    RepositoryIngestionCoverage,
    RepositoryKnowledgeMetadata,
    RepositoryKnowledgeSnapshot,
    RepositorySourceReference,
    RepositoryTreeEntry,
    SourceCategory,
    repository_path,
    untrusted_source,
)

MAX_TREE_CALLS = 20
MAX_CATALOG = 240
MAX_FILES = 18
MAX_REFERENCES = 40
MAX_SOURCE_BYTES = 48000
MAX_TREE_ENTRIES = 2000
_SHA = re.compile(r"^[0-9a-f]{40}$")
_EXCLUDED_DIRECTORIES = {
    "node_modules",
    "vendor",
    "bower_components",
    "__pycache__",
    ".git",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "out",
    "coverage",
    "htmlcov",
    "target",
    "bin",
    "obj",
    "generated",
    "__generated__",
    "playwright-report",
    "test-results",
    ".turbo",
    ".cache",
    "site-packages",
    "secrets",
    "credentials",
    "private_keys",
}
_SOURCE_EXTENSIONS = {
    "py",
    "ts",
    "tsx",
    "js",
    "jsx",
    "mjs",
    "cjs",
    "md",
    "mdx",
    "rst",
    "txt",
    "json",
    "sql",
    "toml",
    "yaml",
    "yml",
    "go",
    "rs",
    "java",
    "kt",
    "cs",
    "rb",
    "php",
    "vue",
    "svelte",
    "html",
    "css",
    "scss",
    "sh",
}


def canonical_digest(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def knowledge_digest(snapshot: RepositoryKnowledgeSnapshot) -> str:
    return canonical_digest(snapshot.model_dump(mode="json", exclude={"digest"}))


def safe_repository_path(path: str, *, directory: bool = False) -> bool:
    """Allow code named token/password; exclude actual secret storage and generated paths."""
    try:
        repository_path(path)
    except ValueError:
        return False
    parts = path.lower().split("/")
    if parts[0] == ".claude-logs":
        return len(parts) == 1 if directory else len(parts) == 2 and parts[-1].endswith(".md")
    if any(part in _EXCLUDED_DIRECTORIES or part.startswith(".") for part in parts):
        return False
    name = parts[-1]
    if (
        name.startswith((".env", "env."))
        or name.endswith((".env", ".pem", ".key", ".p12", ".pfx", ".crt", ".cer"))
        or re.search(r"(?:^|[._-])(?:credentials?|secrets?|private[_-]?key)(?:[._-]|$)", name)
        or name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"}
        or name.endswith((".min.js", ".min.css", ".map", ".generated.ts", ".generated.py", ".d.ts"))
    ):
        return False
    return (
        directory
        or name.rsplit(".", 1)[-1] in _SOURCE_EXTENSIONS
        or name in {"dockerfile", "makefile", "procfile"}
    )


def source_category(path: str) -> SourceCategory:
    parts = path.lower().split("/")
    name = parts[-1]
    if parts[0] == ".claude-logs":
        return "agent_log"
    if any(part in {"migrations", "alembic", "shared_versions", "versions"} for part in parts):
        return "migration"
    if any(part in {"schemas", "routers", "routes", "api"} for part in parts) or "schema" in name:
        return "api_schema"
    if (
        any(part in {"db", "database", "models", "repositories"} for part in parts)
        or "model" in name
    ):
        return "database"
    if name.endswith((".md", ".mdx", ".rst")) or "docs" in parts:
        return "documentation"
    if (
        parts[0] in {"frontend", "client", "web", "src"}
        or any(part in {"components", "pages"} for part in parts)
        or name.endswith((".tsx", ".jsx", ".vue", ".svelte"))
    ):
        return "frontend"
    if any(part in {"backend", "server", "services", "app"} for part in parts):
        return "backend"
    return "source"


def _priority(path: str) -> tuple[int, str]:
    lower = path.lower()
    # Auth walkthroughs need both frontend and backend, never just first N filenames.
    relevance = 0 if re.search(r"auth|session|login|identity|supabase|jwt|oauth", lower) else 1
    if lower.startswith(("tests/", "test/")) or "/tests/" in lower:
        relevance += 2
    return relevance, lower


def _directory_priority(path: str) -> tuple[int, int, str]:
    parts = path.lower().split("/")
    # Rank the actual directory, not every descendant of "app". Otherwise a
    # broad AI/domain subtree can consume the budget before API routes or
    # migration definitions are visited in an ordinary monorepo.
    if path == "" or any(re.search(r"auth|login|identity", part) for part in parts):
        rank = 0
    elif len(parts) == 1 and parts[0] in {"backend", "frontend", "src", "server", "client", "app"}:
        rank = 1
    elif (
        parts[-1]
        in {
            "src",
            "api",
            "routes",
            "routers",
            "core",
            "schemas",
            "db",
            "models",
            "lib",
            "components",
            "app",
            "pages",
            "alembic",
            "migrations",
            "shared_versions",
            "versions",
        }
        or re.fullmatch(r"v[0-9]{1,2}", parts[-1]) is not None
    ):
        rank = 2
    elif parts[0] in {".claude-logs", "docs"}:
        rank = 3
    else:
        rank = 4
    return rank, len(parts), path


def _reference(
    sha: str,
    blob: str,
    path: str,
    text: str,
    start: int,
    *,
    kind: str = "source",
    agent: AgentLogMetadata | None = None,
) -> RepositorySourceReference:
    payload = {
        "digest": hashlib.sha256(text.encode()).hexdigest(),
        "path": path,
        "line_start": start,
        "line_end": start + len(text.splitlines()) - 1,
        "text": text,
        "kind": kind,
        "category": source_category(path),
        "blob_sha": blob,
        "agent": agent.model_dump(mode="json") if agent is not None else None,
    }
    return RepositorySourceReference.model_validate(
        {"reference_id": canonical_digest([sha, payload]), **payload}
    )


def _source_chunks(
    sha: str, blob: str, path: str, content: str
) -> tuple[RepositorySourceReference, ...]:
    # Validate the entire file before selecting excerpts: no prefix-only secret check.
    untrusted_source(content)
    if re.search(
        r"(?im)^\s*(?:#|//|/\*)?\s*(?:@generated|code generated|do not edit|auto-generated)",
        content[:1000],
    ):
        return ()
    lines = content.splitlines()
    groups: list[tuple[int, str]] = []
    buffered: list[str] = []
    start, length = 1, 0
    for number, line in enumerate(lines, start=1):
        if len(line) > 1800:
            if buffered:
                groups.append((start, "\n".join(buffered)))
                buffered, length = [], 0
            start = number + 1
            continue
        if buffered and (length + len(line) + 1 > 1600 or len(buffered) >= 35):
            groups.append((start, "\n".join(buffered)))
            buffered, length, start = [], 0, number
        if not buffered:
            start = number
        buffered.append(line)
        length += len(line) + 1
    if buffered:
        groups.append((start, "\n".join(buffered)))
    # Four excerpts/file, selected deterministically for architecture relevance.
    ranked = sorted(
        groups,
        key=lambda item: (
            -len(
                re.findall(
                    r"(?i)\b(?:auth|token|session|jwt|oauth|supabase|login|route|router|schema|class|def|export|fetch)\b",
                    item[1],
                )
            ),
            item[0],
        ),
    )[:4]
    return tuple(
        _reference(sha, blob, path, text, line) for line, text in sorted(ranked) if text.strip()
    )


def _fit_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep an honest partial receipt instead of exceeding durable payload bounds."""
    # Leave room for the digest key; account for Unicode JSON byte size exactly.
    while len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) > 98150:
        catalog = payload["catalog"]
        references = payload["references"]
        included = {reference["path"] for reference in references}
        removable = [index for index, entry in enumerate(catalog) if entry["path"] not in included]
        if removable:
            catalog.pop(removable[-1])
            reason = "catalog_budget"
            payload["coverage"]["tree_complete"] = False
        elif len(references) > 1:
            references.pop()
            reason = "source_budget"
        elif catalog:
            catalog.pop()
            reason = "catalog_budget"
            payload["coverage"]["tree_complete"] = False
        elif payload["commits"]:
            payload["commits"].pop()
            reason = "history_budget"
            payload["coverage"]["history_complete"] = False
        else:
            raise unavailable()
        payload["coverage"]["catalog_entries"] = len(catalog)
        payload["coverage"]["reasons"] = sorted(set(payload["coverage"]["reasons"]) | {reason})
    included = {reference["path"] for reference in payload["references"]}
    for entry in payload["catalog"]:
        entry["content_included"] = entry["path"] in included
    return payload


def _metadata_json(value: str) -> Any:
    try:
        return json.loads(value)
    except ValueError:
        raise ValueError("Malformed native log metadata") from None


def agent_log_references(
    sha: str, blob: str, path: str, content: str
) -> tuple[RepositorySourceReference, ...]:
    """Only native counted prompt/final bodies; optional metadata is source attribution."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    marker = re.compile(
        r"(?m)^\[CLAUDE_LOG_ENTRY type=(PROMPT|RESPONSE) num=(\d+) session=([A-Za-z0-9_-]+)\]\n"
    )
    matches = list(marker.finditer(normalized))
    found: list[RepositorySourceReference] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        metadata, separator, tail = normalized[match.end() : end].partition("\n\n")
        fields = dict(line.split(": ", 1) for line in metadata.splitlines() if ": " in line)
        length_text = fields.get("chars", "")
        if not separator or not re.fullmatch(r"[0-9]{1,6}", length_text):
            continue
        length = int(length_text)
        if not 0 < length <= 1800 or len(tail) < length or tail[length:].strip():
            continue
        body = tail[:length]
        if re.search(
            r"(?i)<(?:analysis|system|developer|tool)|"
            r"\b(?:hidden reasoning|internal reasoning|tool result)\b",
            body,
        ):
            continue
        try:
            # Only explicit native fields, never frontmatter author/email/cwd.
            attributed: dict[str, Any] = {
                "session_id": match.group(3),
                "entry_number": int(match.group(2)),
            }
            for key in ("turn_id", "model", "timestamp_source"):
                if key in fields:
                    attributed[key] = _metadata_json(fields[key])
            if "timestamp" in fields:
                attributed["timestamp"] = fields["timestamp"]
            agent = AgentLogMetadata.model_validate(attributed)
            body_offset = match.end() + len(metadata) + 2
            start = normalized.count("\n", 0, body_offset) + 1
            found.append(
                _reference(
                    sha,
                    blob,
                    path,
                    body,
                    start,
                    kind="agent_prompt" if match.group(1) == "PROMPT" else "agent_response",
                    agent=agent,
                )
            )
        except (ValueError, ValidationError):
            continue
        if len(found) >= 8:
            break
    return tuple(found)


def _budget(client: GitHubProjectClient) -> bool:
    return client.remaining_seconds() > 1.5


def _committed_date(commit: dict[str, Any]) -> str | None:
    details = commit.get("commit")
    identity = details.get("committer") if isinstance(details, dict) else None
    value = identity.get("date") if isinstance(identity, dict) else None
    return value if isinstance(value, str) else None


def ingest(
    client: GitHubProjectClient, connection: ConnectionView, sha: str
) -> RepositoryKnowledgeSnapshot:
    """Read the pinned tree and bounded history; callers own fresh authorization/persistence."""
    if _SHA.fullmatch(sha) is None:
        raise ApplicationError("invalid_request", "Use an exact commit SHA.", 422)
    token = client.repository_token(connection.installation_id, connection.repository_id)
    metadata = client.repository(token, connection.full_name)
    if (
        metadata.get("id") != connection.repository_id
        or type(metadata.get("id")) is not int
        or metadata.get("full_name") != connection.full_name
        or type(metadata.get("private")) is not bool
    ):
        raise unavailable()
    try:
        repository = RepositoryKnowledgeMetadata(
            repository_id=connection.repository_id,
            full_name=connection.full_name,
            private=metadata["private"],
            default_branch=metadata["default_branch"],
        )
    except (KeyError, ValidationError):
        raise unavailable() from None
    first = client.commit_page(token, connection.full_name, sha, 1)
    detail = first.get("commit")
    root_tree = detail.get("tree") if isinstance(detail, dict) else None
    tree_sha = root_tree.get("sha") if isinstance(root_tree, dict) else None
    if not isinstance(tree_sha, str) or _SHA.fullmatch(tree_sha) is None:
        raise unavailable()
    reasons: set[str] = set()
    queue = deque([("", tree_sha)])
    catalog: list[RepositoryTreeEntry] = []
    omitted, calls, entries_seen = 0, 0, 0
    while queue and calls < MAX_TREE_CALLS and len(catalog) < MAX_CATALOG:
        if not _budget(client):
            reasons.add("request_deadline_budget")
            break
        queued = sorted(queue, key=lambda item: _directory_priority(item[0]))
        queue = deque(queued)
        prefix, current_sha = queue.popleft()
        result = client.tree(token, connection.full_name, current_sha)
        calls += 1
        if result.get("truncated"):
            reasons.add("truncated_tree")
        rows = result.get("tree")
        if not isinstance(rows, list):
            raise unavailable()
        for entry in sorted(
            rows,
            key=lambda item: (
                _priority(str(item.get("path", ""))) if isinstance(item, dict) else (9, "")
            ),
        ):
            entries_seen += 1
            if entries_seen > MAX_TREE_ENTRIES:
                reasons.add("catalog_budget")
                break
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise unavailable()
            name = entry["path"]
            if "/" in name or name in {".", ".."}:
                raise unavailable()
            path = f"{prefix}/{name}" if prefix else name
            directory = entry.get("type") == "tree" and entry.get("mode") == "040000"
            if not safe_repository_path(path, directory=directory):
                omitted += 1
                reasons.add("excluded_path")
                continue
            if not directory and (
                entry.get("type") != "blob" or entry.get("mode") not in {"100644", "100755"}
            ):
                omitted += 1
                reasons.add("unsupported_type")
                continue
            blob = entry.get("sha")
            if not isinstance(blob, str) or _SHA.fullmatch(blob) is None:
                raise unavailable()
            size = entry.get("size")
            if size is not None and (type(size) is not int or not 0 <= size <= 2**40):
                raise unavailable()
            if len(catalog) >= MAX_CATALOG:
                reasons.add("catalog_budget")
                break
            catalog.append(
                RepositoryTreeEntry(
                    path=path,
                    kind="directory" if directory else "file",
                    blob_sha=blob,
                    size=size,
                    category=source_category(path),
                )
            )
            if directory:
                queue.append((path, blob))
        if entries_seen > MAX_TREE_ENTRIES:
            break
    if queue:
        reasons.add("tree_budget")
    if len(catalog) >= MAX_CATALOG:
        reasons.add("catalog_budget")
    # Round-robin categories, architecture/auth files first within each category.
    buckets: dict[str, list[RepositoryTreeEntry]] = {}
    for entry in sorted(catalog, key=lambda entry: _priority(entry.path)):
        if entry.kind == "file":
            buckets.setdefault(entry.category, []).append(entry)
    selected: list[RepositoryTreeEntry] = []
    categories = (
        "frontend",
        "backend",
        "api_schema",
        "database",
        "migration",
        "documentation",
        "source",
        "agent_log",
    )
    while len(selected) < MAX_FILES and any(buckets.values()):
        for category in categories:
            if buckets.get(category) and len(selected) < MAX_FILES:
                selected.append(buckets[category].pop(0))
    if any(buckets.values()):
        reasons.add("file_budget")
    refs: list[RepositorySourceReference] = []
    included: set[str] = set()
    fetched, source_bytes = 0, 0
    for entry in selected:
        if not _budget(client):
            reasons.add("request_deadline_budget")
            break
        if entry.size is not None and entry.size > 32768:
            omitted += 1
            reasons.add("file_size")
            continue
        try:
            content = client.content(
                token, connection.full_name, entry.path, sha, blob_sha=entry.blob_sha
            )
        except ApplicationError as error:
            if error.code != "github_file_omitted":
                raise
            omitted += 1
            reasons.add("file_size")
            continue
        fetched += 1
        try:
            if len(content.encode()) > 32768:
                omitted += 1
                reasons.add("file_size")
                continue
            if entry.category == "agent_log":
                public_ai_question(content)
            else:
                untrusted_source(content)
            chunks = (
                agent_log_references(sha, entry.blob_sha, entry.path, content)
                if entry.category == "agent_log"
                else _source_chunks(sha, entry.blob_sha, entry.path, content)
            )
        except ValueError:
            omitted += 1
            reasons.add("invalid_content")
            continue
        if not chunks:
            omitted += 1
            reasons.add(
                "unsupported_agent_format" if entry.category == "agent_log" else "invalid_content"
            )
        for chunk in chunks:
            size = len(chunk.text.encode())
            if len(refs) >= MAX_REFERENCES or source_bytes + size > MAX_SOURCE_BYTES:
                reasons.add("source_budget")
                break
            refs.append(chunk)
            included.add(entry.path)
            source_bytes += size
    # Follow explicit numeric pages. Missing pages/errors abort, never fake completeness.
    changed: list[str] = []
    changed_complete = False
    page = first
    for number in range(1, 4):
        if number > 1:
            if not _budget(client):
                reasons.add("request_deadline_budget")
                break
            page = client.commit_page(token, connection.full_name, sha, number)
        files = page.get("files")
        if not isinstance(files, list):
            raise unavailable()
        for file in files:
            if not isinstance(file, dict) or not isinstance(file.get("filename"), str):
                raise unavailable()
            if safe_repository_path(file["filename"]):
                changed.append(file["filename"])
        if len(files) < 25:
            changed_complete = True
            break
    if not changed_complete:
        reasons.add("changed_files_budget")
    commits: list[RepositoryCommit] = []
    history_complete = False
    for number in range(1, 4):
        if not _budget(client):
            reasons.add("request_deadline_budget")
            break
        rows = client.history_page(token, connection.full_name, sha, number)
        for row in rows:
            details = row.get("commit")
            message = details.get("message") if isinstance(details, dict) else None
            if not isinstance(row.get("sha"), str) or _SHA.fullmatch(row["sha"]) is None:
                raise unavailable()
            if not isinstance(message, str):
                raise unavailable()
            try:
                public_ai_question(message)
                commits.append(
                    RepositoryCommit(
                        commit_sha=row["sha"],
                        title=message.split("\n", 1)[0][:300],
                        timestamp=_committed_date(row),
                        changed_files=tuple(dict.fromkeys(changed)) if row["sha"] == sha else (),
                        changed_files_complete=changed_complete if row["sha"] == sha else False,
                    )
                )
            except ValueError:
                reasons.add("invalid_content")
        if len(rows) < 10:
            history_complete = True
            break
    if not history_complete:
        reasons.add("history_budget")
    if not refs:
        raise ApplicationError("github_no_safe_sources", "No safe source excerpts found.", 422)
    catalog = [
        entry.model_copy(update={"content_included": entry.path in included}) for entry in catalog
    ]
    payload = {
        "schema_version": "project-repository-v2",
        "connection_id": connection.id,
        "commit_sha": sha,
        "repository": repository.model_dump(mode="json"),
        "catalog": [entry.model_dump(mode="json") for entry in catalog],
        "references": [item.model_dump(mode="json") for item in refs],
        "commits": [item.model_dump(mode="json") for item in commits],
        "coverage": RepositoryIngestionCoverage.model_validate(
            {
                "tree_complete": not queue
                and not reasons.intersection(
                    {"tree_budget", "catalog_budget", "truncated_tree", "request_deadline_budget"}
                ),
                "history_complete": history_complete,
                "changed_files_complete": changed_complete,
                "catalog_entries": len(catalog),
                "fetched_files": fetched,
                "omitted_files": omitted,
                "reasons": sorted(reasons),
            }
        ).model_dump(mode="json"),
        "complete_repository": False,
    }
    try:
        payload = _fit_artifact(payload)
        return RepositoryKnowledgeSnapshot.model_validate(
            {**payload, "digest": canonical_digest(payload)}
        )
    except ValueError:
        raise unavailable() from None
