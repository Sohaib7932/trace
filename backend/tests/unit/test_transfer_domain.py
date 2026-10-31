import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.domain.clock import as_utc
from app.domain.retrieval import (
    QUESTIONS,
    RetrievalCheckpoint,
    checkpoint_status,
    due_at,
    question_for,
)
from app.domain.transfer import (
    TASK_PRIORITY,
    TASK_TITLE,
    TaskObservation,
    TaskSnapshot,
    evaluate_transfer,
)


def observation() -> TaskObservation:
    task = TaskSnapshot(uuid4(), TASK_TITLE, TASK_PRIORITY)
    return TaskObservation(
        201,
        json.dumps(
            {"id": str(task.id), "title": task.title, "metadata": {"priority": task.priority}}
        ),
        (),
        (task,),
        str(task.id),
    )


def test_transfer_success_requires_matching_http_body_and_fresh_row() -> None:
    observed = observation()
    assert evaluate_transfer("nested", "nested", observed).status == "passed"
    flat = replace(
        observed,
        http_status=422,
        response_json='{"detail":[]}',
        validation_codes=("missing:metadata", "extra_forbidden:priority"),
        tasks=(),
        response_task_id=None,
    )
    assert evaluate_transfer("flat", "nested", flat).status == "failed"
    assert evaluate_transfer("nested", "nested", flat).status == "error"
    assert evaluate_transfer("flat", "nested", observed).status == "error"


@pytest.mark.parametrize(
    "change",
    [
        "no_status",
        "no_rows",
        "server_error",
        "no_id",
        "wrong_id",
        "empty_rows",
        "wrong_priority",
        "wrong_title",
        "extra_row",
        "malformed_body",
        "wrong_response_title",
        "wrong_response_metadata",
        "validation_codes",
        "body_not_object",
    ],
)
def test_inconsistent_transfer_evidence_is_never_success(change: str) -> None:
    observed = observation()
    task = observed.tasks[0]
    values = {
        "no_status": {"http_status": None},
        "no_rows": {"tasks": None},
        "server_error": {"http_status": 500},
        "no_id": {"response_task_id": None},
        "wrong_id": {"response_task_id": str(uuid4())},
        "empty_rows": {"tasks": ()},
        "wrong_priority": {"tasks": (replace(task, priority="low"),)},
        "wrong_title": {"tasks": (replace(task, title="Different task"),)},
        "extra_row": {"tasks": (task, task)},
        "malformed_body": {"response_json": "not JSON"},
        "wrong_response_title": {
            "response_json": json.dumps(
                {"id": str(task.id), "title": "Wrong", "metadata": {"priority": "high"}}
            )
        },
        "wrong_response_metadata": {
            "response_json": json.dumps(
                {"id": str(task.id), "title": TASK_TITLE, "metadata": {"priority": "low"}}
            )
        },
        "validation_codes": {"validation_codes": ("missing:metadata",)},
        "body_not_object": {"response_json": "[]"},
    }
    assert (
        evaluate_transfer("nested", "nested", replace(observed, **values[change])).status == "error"
    )


def test_utc_due_boundaries_dst_offsets_and_question_version_identity() -> None:
    # Completion before a fall-back change is converted to UTC before adding durations.
    local = datetime(2026, 11, 1, 1, 30, tzinfo=timezone(timedelta(hours=-4)))
    initial = as_utc(local)
    assert due_at(local, 1) == initial + timedelta(hours=24)
    assert due_at(local, 2) == initial + timedelta(hours=168)
    after_fallback = datetime(2026, 11, 2, 0, 30, tzinfo=timezone(timedelta(hours=-5)))
    checkpoint = RetrievalCheckpoint(
        uuid4(), uuid4(), 1, QUESTIONS[0].id, QUESTIONS[0].content_hash, due_at(local, 1), initial
    )
    assert checkpoint_status(checkpoint, after_fallback) == "due"
    assert (
        checkpoint_status(checkpoint, checkpoint.due_at - timedelta(microseconds=1)) == "upcoming"
    )
    assert (
        checkpoint_status(replace(checkpoint, completed_at=checkpoint.due_at), checkpoint.due_at)
        == "completed"
    )
    assert question_for(checkpoint) is QUESTIONS[0]
    with pytest.raises(ValueError, match="new version"):
        question_for(replace(checkpoint, question_hash="tampered"))
    with pytest.raises(ValueError, match="aware"):
        due_at(datetime(2026, 11, 1), 1)
    assert initial.tzinfo is UTC
