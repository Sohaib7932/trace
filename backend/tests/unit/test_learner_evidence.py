"""Count authorized selected facts without inventing a profile or exposing private inputs."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.providers.fake_question_generator import FakeQuestionGenerator
from app.schemas.generation import GenerationRequest, LearnerEvidenceSummary
from app.schemas.generation_admission import AdmissionAccepted
from app.schemas.learner_evidence import LearnerEvidenceBatch
from app.services.challenge_content_admission import ChallengeContentAdmission
from app.services.learner_evidence import summarize_learner_evidence
from tests.generation_fixtures import request_data

OWNER = uuid4()
START = datetime(2026, 10, 1, tzinfo=UTC)
END = START + timedelta(days=1)


def fact(kind, **changes):
    data = {
        "id": uuid4(),
        "owner_learner_id": OWNER,
        "kind": kind,
        "occurred_at": START + timedelta(hours=1),
    }
    if kind in {"prediction", "retrieval_answer"}:
        data["correct"] = True
    elif kind == "hint":
        data.update(request_time_source="reservation", status="pending", completed_at=None)
    data.update(changes)
    return data


def batch_data(facts=(), **window):
    return {
        "window": {
            "owner_learner_id": OWNER,
            "start_at": START,
            "end_at": END,
            "as_of": END,
            "max_records": 20,
            **window,
        },
        "facts": list(facts),
    }


def batch(facts=(), **window):
    return LearnerEvidenceBatch.model_validate(batch_data(facts, **window))


def test_empty_selected_window_returns_only_existing_eight_zero_counts():
    result = summarize_learner_evidence(batch())
    assert isinstance(result, LearnerEvidenceSummary)
    assert result.model_dump() == {
        "prediction_count": 0,
        "correct_prediction_count": 0,
        "modification_attempt_count": 0,
        "hint_request_count": 0,
        "hints_delivered_count": 0,
        "retrieval_answer_count": 0,
        "correct_retrieval_answer_count": 0,
        "verification_error_count": 0,
    }


def test_all_eight_counts_preserve_pending_help_and_infrastructure_distinction():
    selected = batch(
        [
            fact("prediction"),
            fact("prediction", correct=False),
            fact("modification"),
            fact("hint"),
            fact("hint", status="delivered", completed_at=START + timedelta(hours=2)),
            fact("hint", status="error", completed_at=START + timedelta(hours=3)),
            fact("retrieval_answer"),
            fact("retrieval_answer", correct=False),
            fact("verification_error"),
        ]
    )
    result = summarize_learner_evidence(selected)
    assert result.model_dump() == {
        "prediction_count": 2,
        "correct_prediction_count": 1,
        "modification_attempt_count": 1,
        "hint_request_count": 3,
        "hints_delivered_count": 1,
        "retrieval_answer_count": 2,
        "correct_retrieval_answer_count": 1,
        "verification_error_count": 1,
    }
    assert "mastery" not in result.model_dump() and "learner_failure" not in result.model_dump()


def test_request_cohort_can_include_a_delivery_after_its_end_but_known_by_as_of():
    completion = END + timedelta(hours=1)
    selected = batch(
        [
            fact("hint", status="delivered", completed_at=completion),
        ],
        as_of=completion,
    )
    summary = summarize_learner_evidence(selected)
    assert summary.hint_request_count == summary.hints_delivered_count == 1


@pytest.mark.parametrize(
    "when,valid",
    [
        (START, True),
        (END - timedelta(microseconds=1), True),
        (START - timedelta(microseconds=1), False),
        (END, False),
        (END + timedelta(days=1), False),
    ],
)
def test_window_is_start_inclusive_end_exclusive(when, valid):
    data = batch_data([fact("modification", occurred_at=when)])
    if valid:
        assert (
            summarize_learner_evidence(
                LearnerEvidenceBatch.model_validate(data)
            ).modification_attempt_count
            == 1
        )
    else:
        with pytest.raises(ValidationError):
            LearnerEvidenceBatch.model_validate(data)


def test_utc_normalization_preserves_exact_instant_boundaries():
    offset = timezone(timedelta(hours=5, minutes=30))
    selected = batch(
        [fact("prediction", occurred_at=START.astimezone(offset))],
        start_at=START.astimezone(offset),
        end_at=END.astimezone(offset),
        as_of=END.astimezone(offset),
    )
    assert selected.window.start_at == START and selected.window.start_at.tzinfo == UTC
    assert selected.facts[0].occurred_at.tzinfo == UTC
    assert summarize_learner_evidence(selected).prediction_count == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"start_at": END},
        {"end_at": START},
        {"as_of": START},
        {"start_at": START.replace(tzinfo=None)},
        {"end_at": END.replace(tzinfo=None)},
        {"as_of": END.replace(tzinfo=None)},
        {"max_records": 0},
        {"max_records": 10001},
        {"max_records": True},
        {"max_records": 1.5},
    ],
)
def test_window_has_no_unbounded_or_ambiguous_configuration(changes):
    with pytest.raises(ValidationError):
        batch(**changes)


@pytest.mark.parametrize(
    "field", ["owner_learner_id", "start_at", "end_at", "as_of", "max_records"]
)
def test_every_window_policy_input_is_explicitly_required(field):
    data = batch_data()
    del data["window"][field]
    with pytest.raises(ValidationError):
        LearnerEvidenceBatch.model_validate(data)


@pytest.mark.parametrize("field", ["id", "owner_learner_id", "occurred_at", "request_time_source"])
def test_fact_identity_time_and_hint_provenance_have_no_generated_defaults(field):
    item = fact("hint")
    del item[field]
    with pytest.raises(ValidationError):
        batch([item])


def test_record_cap_rejects_overflow_without_silent_truncation():
    data = batch_data([fact("modification"), fact("modification")], max_records=1)
    with pytest.raises(ValidationError, match="explicit record limit"):
        LearnerEvidenceBatch.model_validate(data)


def test_cross_owner_facts_are_rejected_without_disclosing_either_identity():
    other = uuid4()
    with pytest.raises(ValidationError) as exc:
        batch([fact("prediction", owner_learner_id=other)])
    assert str(other) not in str(exc.value) and str(OWNER) not in str(exc.value)


@pytest.mark.parametrize(
    "kind", ["prediction", "modification", "hint", "retrieval_answer", "verification_error"]
)
def test_same_record_cannot_be_counted_twice_in_a_category(kind):
    item = fact(kind)
    with pytest.raises(ValidationError, match="only once"):
        batch([item, deepcopy(item)])


def test_hint_reservation_and_result_must_be_joined_before_aggregation():
    pending = fact("hint")
    delivered = {**pending, "status": "delivered", "completed_at": START + timedelta(hours=2)}
    with pytest.raises(ValidationError, match="only once"):
        batch([pending, delivered])


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "delivered"},
        {"status": "error"},
        {"completed_at": START + timedelta(hours=2)},
        {"status": "delivered", "completed_at": START},
        {"status": "delivered", "completed_at": END + timedelta(microseconds=1)},
        {"status": "delivered", "completed_at": END.replace(tzinfo=None)},
        {"request_time_source": "legacy_record"},
        {"request_time_source": "event_attempt_reference"},
    ],
)
def test_hint_fact_requires_real_request_time_and_outcome_known_by_cutoff(changes):
    with pytest.raises(ValidationError):
        batch([fact("hint", **changes)])


def test_delivery_at_as_of_is_known_and_pending_is_not_delivered():
    selected = batch(
        [
            fact("hint"),
            fact("hint", status="delivered", completed_at=END),
        ]
    )
    result = summarize_learner_evidence(selected)
    assert result.hint_request_count == 2 and result.hints_delivered_count == 1


@pytest.mark.parametrize("kind", ["verification_failed", "mastery", "misconception", "skill"])
def test_no_inferred_or_learner_failure_fact_is_accepted(kind):
    with pytest.raises(ValidationError):
        batch([fact(kind)])


@pytest.mark.parametrize("kind", ["prediction", "retrieval_answer"])
@pytest.mark.parametrize("correct", [1, 0, "true", None])
def test_correctness_is_an_explicit_strict_boolean_from_trusted_evaluation(kind, correct):
    with pytest.raises(ValidationError):
        batch([fact(kind, correct=correct)])


@pytest.mark.parametrize(
    "field",
    [
        "reasoning",
        "selected_answer",
        "expected_field",
        "private",
        "interests",
        "skill_score",
        "difficulty",
        "email",
        "access_token",
        "misconception_diagnosis",
    ],
)
def test_raw_text_private_configuration_and_profile_fields_are_not_admitted(field):
    with pytest.raises(ValidationError) as exc:
        batch([fact("prediction", **{field: "private-sentinel"})])
    assert "private-sentinel" not in str(exc.value)


def test_batch_and_window_reject_unknown_policy_or_profile_fields():
    for where in ("batch", "window"):
        data = batch_data()
        target = data if where == "batch" else data["window"]
        target["default_interest"] = "private-sentinel"
        with pytest.raises(ValidationError):
            LearnerEvidenceBatch.model_validate(data)


def test_frozen_models_and_forged_instances_cannot_bypass_aggregation_boundaries(capsys):
    selected = batch([fact("prediction")])
    with pytest.raises(ValidationError):
        selected.window.max_records = 10000
    with pytest.raises(ValidationError):
        selected.facts[0].correct = False
    forged = selected.model_copy(
        update={"facts": (selected.facts[0].model_copy(update={"correct": "private-sentinel"}),)}
    )
    with pytest.raises(ValidationError) as exc:
        summarize_learner_evidence(forged)
    assert "private-sentinel" not in str(exc.value) + capsys.readouterr().err


@pytest.mark.parametrize("family", ["notes-v1", "tasks-nested-v1"])
def test_existing_generation_and_admission_receive_counts_only(family):
    summary = summarize_learner_evidence(batch([fact("prediction"), fact("hint")]))
    data = request_data(family)
    data["learner_evidence"] = summary.model_dump()
    request = GenerationRequest.model_validate(data)
    completion = FakeQuestionGenerator().generate(request)
    admitted = ChallengeContentAdmission().admit(request, completion)
    assert isinstance(admitted, AdmissionAccepted) and admitted.release_eligible is False
    encoded = request.model_dump_json()
    assert str(OWNER) not in encoded and START.isoformat() not in encoded
    for private_key in (
        "owner_learner_id",
        "occurred_at",
        "completed_at",
        "fact_id",
        "start_at",
        "as_of",
    ):
        assert private_key not in encoded
