"""Isolated execution of the two existing trusted ASGI exercise families.

Each profile receives a new in-memory SQLite database with only two exercise
tables. Existing FastAPI apps, services, ASGI adapters and deterministic evaluators
perform the request and independent committed-state readback. No application
Settings, learner repository, migration, history row or generated code is used.

The baseline intentionally evaluates as a failed learner correction; candidate
validation expects that rejection, then separately expects a successful repair.
Reports contain only category outcomes, never private observed/expected values.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import count
from threading import RLock
from types import TracebackType
from typing import Literal, Self
from uuid import UUID

from sqlalchemy import Column, MetaData, String, Table, Uuid, create_engine, insert, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from app.domain.learning import (
    NOTE_CONTENT,
    NOTE_TITLE,
    LearningError,
    NoteSnapshot,
    Observation,
    evaluate,
    response_matches_fixture,
)
from app.domain.lesson_spec import LessonSpecV1, validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes, verify_digest
from app.domain.lesson_spec.templates import NOTES, TASKS
from app.domain.transfer import (
    TaskObservation,
    TaskSnapshot,
    evaluate_transfer,
    response_matches_task,
    task_values_match,
)
from app.repositories.exercise import ExerciseStore
from app.schemas.candidate_validation import (
    CandidateValidationCode,
    RuntimeEvidenceCheck,
    RuntimeProfileEvidence,
    RuntimeValidationReport,
)
from app.verification.asgi_notes import AsgiNotesVerifier
from app.verification.asgi_tasks import AsgiTasksVerifier

_METADATA = MetaData()
_NOTES = Table(
    "validation_notes",
    _METADATA,
    Column("id", Uuid, primary_key=True),
    Column("run_id", Uuid, nullable=False, unique=True),
    Column("title", String(200), nullable=False),
    Column("content", String(2000), nullable=False),
)
_TASKS = Table(
    "validation_tasks",
    _METADATA,
    Column("id", Uuid, primary_key=True),
    Column("run_id", Uuid, nullable=False, unique=True),
    Column("title", String(200), nullable=False),
    Column("priority", String(16), nullable=False),
)
_RUN_ID = UUID(int=1)


class _ExerciseStore:
    def __init__(self, connection: Connection, identities: Iterator[int]) -> None:
        self.connection, self.identities = connection, identities

    def add_note(self, run_id: UUID, title: str, content: str) -> NoteSnapshot:
        row_id = UUID(int=next(self.identities))
        self.connection.execute(
            insert(_NOTES).values(id=row_id, run_id=run_id, title=title, content=content)
        )
        return NoteSnapshot(row_id, title, content)

    def notes(self, run_id: UUID) -> tuple[NoteSnapshot, ...]:
        return tuple(
            NoteSnapshot(row.id, row.title, row.content)
            for row in self.connection.execute(select(_NOTES).where(_NOTES.c.run_id == run_id))
        )

    def add_task(self, run_id: UUID, title: str, priority: str) -> TaskSnapshot:
        row_id = UUID(int=next(self.identities))
        self.connection.execute(
            insert(_TASKS).values(id=row_id, run_id=run_id, title=title, priority=priority)
        )
        return TaskSnapshot(row_id, title, priority)

    def tasks(self, run_id: UUID) -> tuple[TaskSnapshot, ...]:
        return tuple(
            TaskSnapshot(row.id, row.title, row.priority)
            for row in self.connection.execute(select(_TASKS).where(_TASKS.c.run_id == run_id))
        )


class _ExerciseDatabase:
    """A disposable storage adapter, with no configurable path or learner methods."""

    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False, "autocommit": False},
            hide_parameters=True,
        )
        self._lock = RLock()
        self._identities = count(2)
        try:
            _METADATA.create_all(self.engine)
        except Exception:
            self.engine.dispose()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.engine.dispose()

    @contextmanager
    def read(self) -> Iterator[ExerciseStore]:
        try:
            with self._lock, self.engine.connect() as connection:
                yield _ExerciseStore(connection, self._identities)
        except SQLAlchemyError:
            raise LearningError(
                "dependency_unavailable", "Exercise storage is unavailable."
            ) from None

    @contextmanager
    def write(self) -> Iterator[ExerciseStore]:
        try:
            with self._lock, self.engine.begin() as connection:
                yield _ExerciseStore(connection, self._identities)
        except SQLAlchemyError:
            raise LearningError(
                "dependency_unavailable", "Exercise storage is unavailable."
            ) from None


def _baseline_response(raw: str, expected_codes: tuple[str, ...]) -> bool:
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        return False
    if not isinstance(body, dict) or not isinstance(body.get("detail"), list):
        return False
    codes = []
    for detail in body["detail"]:
        if not isinstance(detail, dict):
            return False
        kind, location = detail.get("type"), detail.get("loc")
        if not isinstance(kind, str) or not isinstance(location, list) or len(location) != 2:
            return False
        if location[0] != "body" or not isinstance(location[1], str):
            return False
        codes.append(f"{kind}:{location[1]}")
    return len(codes) == len(expected_codes) and set(codes) == set(expected_codes)


def _evidence(
    observed: Observation | TaskObservation,
    profile: Literal["baseline", "repair"],
) -> RuntimeProfileEvidence:
    rows = observed.notes if isinstance(observed, Observation) else observed.tasks
    if isinstance(observed, Observation):
        template, note_rows = NOTES, observed.notes
        evaluation = evaluate(
            template.initial if profile == "baseline" else template.correct,
            template.correct,
            observed,
        )
        response_matches = response_matches_fixture(observed)
        values_match = bool(
            note_rows is not None
            and len(note_rows) == 1
            and note_rows[0].title == NOTE_TITLE
            and note_rows[0].content == NOTE_CONTENT
            and str(note_rows[0].id) == observed.response_note_id
        )
        response_id = observed.response_note_id
    else:
        template = TASKS
        evaluation = evaluate_transfer(
            template.initial if profile == "baseline" else template.correct,
            template.correct,
            observed,
        )
        response_matches = response_matches_task(observed)
        values_match = task_values_match(observed)
        response_id = observed.response_task_id
    if profile == "baseline":
        valid_codes = len(observed.validation_codes) == len(template.validation_codes) and set(
            observed.validation_codes
        ) == set(template.validation_codes)
        response_matches = _baseline_response(observed.response_json, template.validation_codes)
        row_count = rows is not None and len(rows) == 0
        values_match = row_count and response_id is None
        status_matches, validation_matches = observed.http_status == 422, valid_codes
        evaluation_matches = evaluation.status == "failed"
    else:
        status_matches = observed.http_status == 201
        validation_matches = status_matches and not observed.validation_codes
        row_count = rows is not None and len(rows) == 1
        evaluation_matches = evaluation.status == "passed"
    return RuntimeProfileEvidence(
        profile=profile,
        evaluation_matched=evaluation_matches,
        checks=(
            RuntimeEvidenceCheck(code="http_status", passed=status_matches),
            RuntimeEvidenceCheck(code="api_response", passed=response_matches),
            RuntimeEvidenceCheck(code="validation", passed=validation_matches),
            RuntimeEvidenceCheck(code="row_count", passed=row_count),
            RuntimeEvidenceCheck(code="stored_values", passed=values_match),
        ),
    )


def _incomplete(
    code: CandidateValidationCode,
    performed: bool,
    profiles: list[RuntimeProfileEvidence],
    *,
    unavailable: bool = False,
) -> RuntimeValidationReport:
    return RuntimeValidationReport(
        status="unavailable" if unavailable else "failed",
        code=code,
        performed=performed,
        completed=False,
        profiles=tuple(profiles),
    )


class IsolatedCandidateRuntime:
    """Execute trusted initial and repaired mappings; never execute source strings."""

    def validate(self, definition: LessonSpecV1) -> RuntimeValidationReport:
        try:
            checked = validate_lesson_spec(canonical_bytes(definition))
            if not verify_digest(checked):
                return _incomplete(
                    CandidateValidationCode.RUNTIME_REPORT_INVALID, False, [], unavailable=True
                )
        except (TypeError, ValueError):
            return _incomplete(
                CandidateValidationCode.RUNTIME_REPORT_INVALID, False, [], unavailable=True
            )
        notes = checked.private.runtime_binding.template_id == "notes-v1"
        template = NOTES if notes else TASKS
        profiles: list[RuntimeProfileEvidence] = []
        performed = False
        plans: tuple[tuple[Literal["baseline", "repair"], str], ...] = (
            ("baseline", template.initial),
            ("repair", template.correct),
        )
        for profile, mapping in plans:
            try:
                # Separate databases prevent the baseline or a prior candidate's
                # data from affecting the repair observation or another call.
                with _ExerciseDatabase() as repository:
                    timeout = checked.private.verification.timeout_seconds
                    verifier = (
                        AsgiNotesVerifier(repository, timeout)
                        if notes
                        else AsgiTasksVerifier(repository, timeout)
                    )
                    performed = True
                    observed = verifier.observe(_RUN_ID, mapping)
                if not isinstance(observed, Observation if notes else TaskObservation):
                    return _incomplete(
                        CandidateValidationCode.RUNTIME_REPORT_INVALID,
                        performed,
                        profiles,
                        unavailable=True,
                    )
                rows = observed.notes if isinstance(observed, Observation) else observed.tasks
                if observed.http_status is None or rows is None:
                    return _incomplete(
                        CandidateValidationCode.RUNTIME_UNAVAILABLE,
                        performed,
                        profiles,
                        unavailable=True,
                    )
                if observed.http_status >= 500:
                    return _incomplete(
                        CandidateValidationCode.RUNTIME_EXECUTION_FAILED, performed, profiles
                    )
                profiles.append(_evidence(observed, profile))
            except TimeoutError:
                return _incomplete(
                    CandidateValidationCode.RUNTIME_TIMEOUT, performed, profiles, unavailable=True
                )
            except (SQLAlchemyError, OSError, ImportError):
                return _incomplete(
                    CandidateValidationCode.RUNTIME_UNAVAILABLE,
                    performed,
                    profiles,
                    unavailable=True,
                )
            except LearningError as exc:
                unavailable = exc.code == "dependency_unavailable"
                return _incomplete(
                    CandidateValidationCode.RUNTIME_UNAVAILABLE
                    if unavailable
                    else CandidateValidationCode.RUNTIME_EXCEPTION,
                    performed,
                    profiles,
                    unavailable=unavailable,
                )
            except Exception:
                return _incomplete(CandidateValidationCode.RUNTIME_EXCEPTION, performed, profiles)
        passed = all(
            item.evaluation_matched and all(check.passed for check in item.checks)
            for item in profiles
        )
        return RuntimeValidationReport(
            status="passed" if passed else "failed",
            code=None if passed else CandidateValidationCode.RUNTIME_EVIDENCE_FAILED,
            performed=performed,
            completed=True,
            profiles=tuple(profiles),
        )
