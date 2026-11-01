"""Real trusted ASGI requests with exercise-only SQLite, no learner records."""

import json
import socket
from dataclasses import replace
from uuid import UUID

import httpx2
import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.exc import OperationalError

from app.db.learning import SqlLearningStore
from app.db.session import Database
from app.domain.learning import NOTE_CONTENT, NOTE_TITLE, LearningError, NoteSnapshot
from app.domain.lesson_spec import validate_lesson_spec
from app.domain.lesson_spec.templates import NOTES, TASKS
from app.domain.transfer import TASK_PRIORITY, TASK_TITLE, TaskSnapshot
from app.schemas.candidate_validation import CHECK_CODES
from app.services.candidate_validation import CandidateValidationService
from app.services.verification import VerificationService
from app.verification import candidate_runtime as runtime_module
from app.verification.asgi_notes import AsgiNotesVerifier
from app.verification.asgi_tasks import AsgiTasksVerifier
from app.verification.candidate_runtime import IsolatedCandidateRuntime
from tests.candidate_validation_fixtures import validation_case
from tests.composition_fixtures import FAMILIES, test_definition


def adapter(family):
    return AsgiNotesVerifier if family == "notes-v1" else AsgiTasksVerifier


@pytest.mark.parametrize("family", FAMILIES)
def test_full_candidate_gate_uses_real_runtime_and_still_forbids_release(family):
    case = validation_case(family)
    result = CandidateValidationService(IsolatedCandidateRuntime()).validate(**case)
    assert result.status == "validated" and result.code is None
    assert result.runtime_verification_performed is True
    assert result.runtime_verification_completed is True
    assert all(stage.status == "passed" for stage in result.stages)
    assert result.release_eligible is False and case["candidate"].release_eligible is False
    assert case["candidate"].state == "composed_unverified"
    assert not hasattr(result, "published")


@pytest.mark.parametrize("family", FAMILIES)
def test_real_existing_apps_evaluators_and_five_categories_validate_both_profiles(family):
    definition = test_definition(family)
    report = IsolatedCandidateRuntime().validate(definition)
    assert report.status == "passed" and report.code is None
    assert report.performed is True and report.completed is True
    assert [item.profile for item in report.profiles] == ["baseline", "repair"]
    for profile in report.profiles:
        assert profile.evaluation_matched is True
        assert {check.code for check in profile.checks} == CHECK_CODES
        assert all(check.passed for check in profile.checks)
    serialized = report.model_dump_json()
    assert (
        not {"response_json", "notes", "tasks", "expected", "observed", "rules"}
        & json.loads(serialized).keys()
    )
    for private_value in [NOTE_TITLE, NOTE_CONTENT, TASK_TITLE, TASK_PRIORITY]:
        assert private_value not in serialized


@pytest.mark.parametrize("family", FAMILIES)
def test_runtime_has_no_app_database_or_history_and_needs_no_network(family, monkeypatch, tmp_path):
    definition = test_definition(family)
    sentinel = tmp_path / "protected-application.db"
    sentinel.write_bytes(b"Protected application database sentinel")
    before = sentinel.read_bytes(), sentinel.stat().st_mtime_ns
    monkeypatch.setenv("TRACE_DATABASE_URL", f"sqlite+pysqlite:///{sentinel}")
    seen_tables = []
    original_enter = runtime_module._ExerciseDatabase.__enter__

    def entered(resource):
        assert resource.engine.url.database == ":memory:"
        seen_tables.append(set(inspect(resource.engine).get_table_names()))
        assert not any(
            hasattr(resource, name)
            for name in ["add_session", "add_attempt", "add_checkpoint", "add_prediction"]
        )
        return original_enter(resource)

    def forbidden(*args, **kwargs):
        pytest.fail("Candidate runtime attempted application/history storage or network I/O")

    monkeypatch.setattr(runtime_module._ExerciseDatabase, "__enter__", entered)
    for owner, name in [
        (Database, "__init__"),
        (VerificationService, "verify"),
        (SqlLearningStore, "add_session"),
        (SqlLearningStore, "add_prediction"),
        (SqlLearningStore, "add_attempt"),
        (SqlLearningStore, "add_hint"),
        (SqlLearningStore, "add_checkpoint"),
        (SqlLearningStore, "add_retrieval_attempt"),
        (SqlLearningStore, "add_event"),
        (SqlLearningStore, "set_state"),
        (httpx2.HTTPTransport, "handle_request"),
        (httpx2.AsyncHTTPTransport, "handle_async_request"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
    ]:
        monkeypatch.setattr(owner, name, forbidden)
    report = IsolatedCandidateRuntime().validate(definition)
    assert report.status == "passed"
    assert seen_tables == [{"validation_notes", "validation_tasks"}] * 2
    assert (sentinel.read_bytes(), sentinel.stat().st_mtime_ns) == before


@pytest.mark.parametrize("family", FAMILIES)
def test_profiles_and_calls_have_fresh_databases_and_deterministic_outcomes(family, monkeypatch):
    original_exit = runtime_module._ExerciseDatabase.__exit__
    engines, counts = [], []

    def exiting(resource, *args):
        engines.append(resource.engine)
        with resource.engine.connect() as connection:
            counts.append(
                (
                    len(connection.execute(select(runtime_module._NOTES)).all()),
                    len(connection.execute(select(runtime_module._TASKS)).all()),
                )
            )
        return original_exit(resource, *args)

    monkeypatch.setattr(runtime_module._ExerciseDatabase, "__exit__", exiting)
    runtime, definition = IsolatedCandidateRuntime(), test_definition(family)
    first, second = runtime.validate(definition), runtime.validate(definition)
    assert first.status == second.status == "passed" and first == second
    assert len({id(engine) for engine in engines}) == 4
    expected_repair = (1, 0) if family == "notes-v1" else (0, 1)
    assert counts == [(0, 0), expected_repair] * 2
    for engine in engines:
        # dispose() replaced the pool: reconnecting creates a fresh empty database.
        assert inspect(engine).get_table_names() == []
        engine.dispose()


@pytest.mark.parametrize("family", FAMILIES)
def test_fresh_readback_occurs_after_a_distinct_committed_write_context(family, monkeypatch):
    write_name, read_name = ("add_note", "notes") if family == "notes-v1" else ("add_task", "tasks")
    original_write = getattr(runtime_module._ExerciseStore, write_name)
    original_read = getattr(runtime_module._ExerciseStore, read_name)
    writers, reads = [], []

    def writing(store, *args):
        writers.append(store.connection)
        return original_write(store, *args)

    def reading(store, *args):
        assert all(writer is not store.connection and writer.closed for writer in writers)
        reads.append(store.connection)
        return original_read(store, *args)

    monkeypatch.setattr(runtime_module._ExerciseStore, write_name, writing)
    monkeypatch.setattr(runtime_module._ExerciseStore, read_name, reading)
    assert IsolatedCandidateRuntime().validate(test_definition(family)).status == "passed"
    assert len(writers) == 1 and len(reads) == 2


def corrupt(observed, profile, category, family):
    notes = family == "notes-v1"
    rows_name, id_name = ("notes", "response_note_id") if notes else ("tasks", "response_task_id")
    if category == "http_status":
        return replace(observed, http_status=200)
    if category == "api_response":
        return replace(observed, response_json='{"private-sentinel":"invalid-response"}')
    if category == "validation":
        return replace(observed, validation_codes=("unsupported:private-sentinel",))
    if category == "row_count":
        if profile == "repair":
            rows = ()
        else:
            row = (
                NoteSnapshot(UUID(int=9), NOTE_TITLE, NOTE_CONTENT)
                if notes
                else TaskSnapshot(UUID(int=9), TASK_TITLE, TASK_PRIORITY)
            )
            rows = (row,)
        return replace(observed, **{rows_name: rows})
    if profile == "baseline":
        return replace(observed, **{id_name: str(UUID(int=9))})
    rows = getattr(observed, rows_name)
    return replace(observed, **{rows_name: (replace(rows[0], title="Incorrect stored fixture"),)})


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("profile", ["baseline", "repair"])
@pytest.mark.parametrize("category", sorted(CHECK_CODES))
def test_each_required_evidence_category_can_independently_reject_runtime(
    family, profile, category, monkeypatch
):
    kind = adapter(family)
    original = kind.observe
    template = NOTES if family == "notes-v1" else TASKS

    def modified(instance, run_id, mapping):
        observed = original(instance, run_id, mapping)
        selected = mapping == (template.initial if profile == "baseline" else template.correct)
        return corrupt(observed, profile, category, family) if selected else observed

    monkeypatch.setattr(kind, "observe", modified)
    report = IsolatedCandidateRuntime().validate(test_definition(family))
    assert report.status == "failed" and report.code == "runtime_evidence_failed"
    assert report.performed is True and report.completed is True
    result = next(item for item in report.profiles if item.profile == profile)
    assert next(check for check in result.checks if check.code == category).passed is False
    assert "private-sentinel" not in report.model_dump_json()


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("field", ["http_status", "readback"])
def test_missing_observation_is_unavailable_not_invented_zero_rows(family, field, monkeypatch):
    kind, original = adapter(family), adapter(family).observe

    def missing(instance, run_id, mapping):
        observed = original(instance, run_id, mapping)
        name = (
            "http_status"
            if field == "http_status"
            else "notes"
            if family == "notes-v1"
            else "tasks"
        )
        return replace(observed, **{name: None})

    monkeypatch.setattr(kind, "observe", missing)
    report = IsolatedCandidateRuntime().validate(test_definition(family))
    assert report.status == "unavailable" and report.code == "runtime_unavailable"
    assert report.performed is True and report.completed is False and report.profiles == ()


@pytest.mark.parametrize("family", FAMILIES)
def test_actual_repository_read_failure_remains_unavailable(family, monkeypatch):
    name = "notes" if family == "notes-v1" else "tasks"

    def unavailable(*args):
        raise LearningError("dependency_unavailable", "Private readback failure")

    monkeypatch.setattr(runtime_module._ExerciseStore, name, unavailable)
    report = IsolatedCandidateRuntime().validate(test_definition(family))
    assert report.status == "unavailable" and report.code == "runtime_unavailable"
    assert report.performed is True and report.completed is False and report.profiles == ()
    assert "Private" not in report.model_dump_json()


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "failure,code,status",
    [
        (TimeoutError, "runtime_timeout", "unavailable"),
        (RuntimeError, "runtime_exception", "failed"),
    ],
)
def test_timeout_and_exception_are_deterministic_failures_without_sleeping(
    family, failure, code, status, monkeypatch
):
    def failing(*args):
        raise failure("Private exception details must not escape")

    monkeypatch.setattr(adapter(family), "observe", failing)
    report = IsolatedCandidateRuntime().validate(test_definition(family))
    assert report.status == status and report.code == code
    assert report.performed is True and report.completed is False and report.profiles == ()
    assert "Private" not in report.model_dump_json()


@pytest.mark.parametrize("family", FAMILIES)
def test_actual_asgi_application_exception_is_not_a_candidate_success(family, monkeypatch):
    module = __import__(adapter(family).__module__, fromlist=["unused"])
    name = "create_notes_app" if family == "notes-v1" else "create_tasks_app"
    original = getattr(module, name)

    def broken(*args):
        app = original(*args)

        @app.middleware("http")
        async def fail(request, call_next):
            raise RuntimeError("Private application exception")

        return app

    monkeypatch.setattr(module, name, broken)
    report = IsolatedCandidateRuntime().validate(test_definition(family))
    assert report.status == "failed" and report.code == "runtime_execution_failed"
    assert report.performed is True and report.completed is False
    assert "Private" not in report.model_dump_json()


def test_unavailable_storage_setup_does_not_claim_runtime_execution(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError("Private storage path", {}, None)

    monkeypatch.setattr(runtime_module, "create_engine", unavailable)
    report = IsolatedCandidateRuntime().validate(test_definition())
    assert report.status == "unavailable" and report.code == "runtime_unavailable"
    assert report.performed is False and report.completed is False and not report.profiles
    assert "Private" not in report.model_dump_json()


@pytest.mark.parametrize("family", FAMILIES)
def test_unavailable_adapter_constructor_does_not_claim_an_observation(family, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ImportError("Private adapter initialization failure")

    monkeypatch.setattr(adapter(family), "__init__", unavailable)
    report = IsolatedCandidateRuntime().validate(test_definition(family))
    assert report.status == "unavailable" and report.code == "runtime_unavailable"
    assert report.performed is False and report.completed is False and report.profiles == ()
    assert "Private" not in report.model_dump_json()


@pytest.mark.parametrize("family", FAMILIES)
def test_missing_observation_object_cannot_be_counted_as_runtime_evidence(family, monkeypatch):
    monkeypatch.setattr(adapter(family), "observe", lambda *args: None)
    report = IsolatedCandidateRuntime().validate(test_definition(family))
    assert report.status == "unavailable" and report.code == "runtime_report_invalid"
    assert report.performed is True and report.completed is False and report.profiles == ()


def test_partial_database_setup_failure_disposes_its_engine(monkeypatch):
    original = runtime_module.create_engine
    disposed = []

    def created(*args, **kwargs):
        engine = original(*args, **kwargs)
        event.listen(engine, "engine_disposed", lambda resource: disposed.append(resource))
        return engine

    def unavailable(*args, **kwargs):
        raise OperationalError("Private table setup", {}, None)

    monkeypatch.setattr(runtime_module, "create_engine", created)
    monkeypatch.setattr(runtime_module._METADATA, "create_all", unavailable)
    report = IsolatedCandidateRuntime().validate(test_definition())
    assert report.status == "unavailable" and report.performed is False
    assert len(disposed) == 1


def test_stale_or_invalid_definition_is_rejected_before_any_runtime(monkeypatch):
    data = test_definition().model_dump(mode="json")
    data["title"] = "Changed content with a stale digest"
    stale = validate_lesson_spec(data)

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid definition reached disposable runtime setup")

    monkeypatch.setattr(runtime_module, "_ExerciseDatabase", forbidden)
    for value in [stale, None, {}, "not a definition"]:
        report = IsolatedCandidateRuntime().validate(value)
        assert report.status == "unavailable" and report.code == "runtime_report_invalid"
        assert report.performed is False and report.completed is False
