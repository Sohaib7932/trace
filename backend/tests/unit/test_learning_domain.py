import json
from dataclasses import replace
from uuid import uuid4

import pytest

from app.domain.learning import (
    NOTE_CONTENT,
    NOTE_TITLE,
    LearningError,
    NoteSnapshot,
    Observation,
    SessionState,
    evaluate,
    transition,
)


@pytest.mark.parametrize(
    "source,target",
    [
        ("awaiting_prediction", SessionState.READY_FOR_ATTEMPT),
        ("ready_for_attempt", SessionState.VERIFICATION_PENDING),
        ("verification_pending", SessionState.NEEDS_REVISION),
        ("needs_revision", SessionState.VERIFICATION_PENDING),
    ],
)
def test_valid_transition_sequence(source, target) -> None:
    assert transition(source, target) == target.value


@pytest.mark.parametrize(
    "state", ["awaiting_prediction", "ready_for_attempt", "verification_pending", "needs_revision"]
)
def test_unfinished_session_can_be_abandoned(state) -> None:
    assert transition(state, SessionState.ABANDONED) == "abandoned"


def test_invalid_or_unverified_completion_is_rejected() -> None:
    with pytest.raises(LearningError):
        transition("awaiting_prediction", SessionState.COMPLETED)
    with pytest.raises(LearningError):
        transition("verification_pending", SessionState.COMPLETED)
    assert transition("verification_pending", SessionState.COMPLETED, verified=True) == "completed"


def test_evaluator_requires_http_and_exact_independent_readback() -> None:
    note = NoteSnapshot(uuid4(), NOTE_TITLE, NOTE_CONTENT)
    success = Observation(
        201,
        json.dumps({"id": str(note.id), "title": NOTE_TITLE, "content": NOTE_CONTENT}),
        (),
        (note,),
        str(note.id),
    )
    assert evaluate("content", "content", success).status == "passed"
    for contradictory in [
        replace(success, notes=()),
        replace(success, notes=None),
        replace(success, response_note_id=str(uuid4())),
        replace(success, notes=(replace(note, content="wrong"),)),
        replace(success, http_status=500),
        replace(success, http_status=None),
        replace(success, response_json="not-json"),
        replace(success, response_json="[]"),
        replace(
            success,
            response_json=json.dumps(
                {"id": str(note.id), "title": "wrong", "content": NOTE_CONTENT}
            ),
        ),
        replace(success, validation_codes=("unexpected:validation",)),
    ]:
        assert evaluate("content", "content", contradictory).status == "error"
    assert evaluate("body", "content", success).status == "error"
    rejected = Observation(422, "{}", ("missing:content", "extra_forbidden:body"), (), None)
    assert evaluate("body", "content", rejected).status == "failed"
    assert evaluate("body", "content", replace(rejected, validation_codes=())).status == "error"
