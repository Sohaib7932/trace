"""Reject unsupported claims before projecting trusted engineering observations."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.engineering_evidence import (
    AssistanceContext,
    Competency,
    EngineeringEvidenceBatch,
    EngineeringObservation,
    EvidenceCoverage,
    EvidenceQuery,
    HintEvidence,
    LessonPin,
    ObservedCheck,
    RetrievalEvidence,
    RetrievalQuestionPin,
    SourceReference,
    coverage_profile,
)

START = datetime(2026, 10, 1, tzinfo=UTC)
END = START + timedelta(days=1)
OWNER, SESSION = uuid4(), uuid4()


def reference(kind="attempt", **changes):
    return {"kind": kind, "record_id": uuid4(), **changes}


def lesson(**changes):
    return {
        "version_id": uuid4(),
        "lesson_id": "fastapi-payload-mismatch",
        "version": "1.0.0",
        "content_hash": "a" * 64,
        **changes,
    }


def assistance(**changes):
    return {"category": "unknown", "requested_before": [], "delivered_before": [], **changes}


def query(**changes):
    return {
        "owner_learner_id": OWNER,
        "session_id": SESSION,
        "start_at": START,
        "end_at": END,
        "as_of": END,
        "max_records": 20,
        **changes,
    }


def check(code="http_status", **changes):
    origin = (
        "asgi_http"
        if code in {"http_status", "api_response", "validation"}
        else "fresh_database_read"
        if code in {"row_count", "stored_values"}
        else "verifier"
    )
    return {
        "source": reference("verification_check"),
        "code": code,
        "matched": code != "execution",
        "origin": origin,
        **changes,
    }


def runtime_checks():
    return [
        check(code)
        for code in ("http_status", "api_response", "validation", "row_count", "stored_values")
    ]


def observation(event_type="prediction_submitted", **changes):
    competency, source, basis, outcome = {
        "prediction_submitted": (Competency.PREDICTION, "prediction", "direct", "success"),
        "modification_submitted": (Competency.MODIFICATION, "attempt", "direct", "unknown"),
        "verification_finished": (Competency.VERIFICATION, "verification_run", "direct", "success"),
        "debugging_recovery_observed": (
            Competency.DEBUGGING,
            "verification_run",
            "indirect",
            "success",
        ),
        "transfer_completed": (Competency.TRANSFER, "verification_run", "direct", "success"),
    }[event_type]
    data = {
        "id": uuid4(),
        "schema_version": "engineering-evidence-v1",
        "owner_learner_id": OWNER,
        "session_id": SESSION,
        "lesson": lesson(),
        "competency": competency,
        "event_type": event_type,
        "outcome": outcome,
        "basis": basis,
        "occurred_at": START + timedelta(hours=1),
        "source": reference(source),
        "related_sources": [reference("attempt")] if source == "verification_run" else [],
        "assistance": assistance(),
        "checks": runtime_checks() if source == "verification_run" else [],
    }
    if event_type == "debugging_recovery_observed":
        data["related_sources"].append(reference("verification_run"))
    if event_type == "transfer_completed":
        data["lesson"] = lesson(lesson_id="fastapi-nested-payload-transfer")
    return {**data, **changes}


def hint(event_type="hint_requested", **changes):
    return {
        "id": uuid4(),
        "schema_version": "engineering-evidence-v1",
        "owner_learner_id": OWNER,
        "session_id": SESSION,
        "lesson": lesson(),
        "event_type": event_type,
        "outcome": "requested" if event_type == "hint_requested" else "delivered",
        "occurred_at": START + timedelta(hours=1),
        "source": reference(
            "hint_operation" if event_type == "hint_requested" else "tutor_interaction"
        ),
        **changes,
    }


def retrieval(**changes):
    return {
        "id": uuid4(),
        "schema_version": "engineering-evidence-v1",
        "owner_learner_id": OWNER,
        "session_id": SESSION,
        "lesson": lesson(lesson_id="fastapi-nested-payload-transfer"),
        "event_type": "retrieval_answered",
        "outcome": "success",
        "occurred_at": START + timedelta(hours=1),
        "source": reference("retrieval_attempt"),
        "checkpoint": reference("retrieval_checkpoint"),
        "question": {"question_id": "shipping-contract-v1", "content_hash": "b" * 64},
        "assistance": assistance(),
        **changes,
    }


def batch_data(observations=(), hints=(), retrieval_events=(), **changes):
    records = (*observations, *hints, *retrieval_events)
    pin = records[0]["lesson"] if records else lesson()
    observed = frozenset(item["competency"] for item in observations)
    return {
        "query": query(**changes),
        "lesson": pin,
        "coverage": [
            item.model_dump() for item in coverage_profile(LessonPin.model_validate(pin), observed)
        ],
        "observations": list(observations),
        "hint_events": list(hints),
        "retrieval_events": list(retrieval_events),
    }


def batch(observations=(), hints=(), retrieval_events=(), **changes):
    return EngineeringEvidenceBatch.model_validate(
        batch_data(observations, hints, retrieval_events, **changes)
    )


def test_taxonomy_has_exact_six_stable_competencies_without_scores():
    assert tuple(item.value for item in Competency) == (
        "prediction",
        "investigation",
        "modification",
        "debugging",
        "verification",
        "transfer",
    )
    assert "score" not in EngineeringObservation.model_fields
    assert "reasoning" not in EngineeringObservation.model_fields


@pytest.mark.parametrize(
    "event_type",
    [
        "prediction_submitted",
        "modification_submitted",
        "verification_finished",
        "debugging_recovery_observed",
        "transfer_completed",
    ],
)
def test_supported_source_events_round_trip_without_raw_learner_or_evaluator_data(event_type):
    item = EngineeringObservation.model_validate(observation(event_type))
    assert EngineeringObservation.model_validate_json(item.model_dump_json()) == item
    encoded = item.model_dump_json()
    for private_field in ("expected", "observed", "reasoning", "explanation", "answer_key", "text"):
        assert f'"{private_field}":' not in encoded


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "schema_version",
        "owner_learner_id",
        "session_id",
        "lesson",
        "competency",
        "event_type",
        "outcome",
        "basis",
        "occurred_at",
        "source",
        "related_sources",
        "assistance",
        "checks",
    ],
)
def test_observations_require_explicit_source_values_not_default_ids_or_times(field):
    data = observation()
    del data[field]
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(data)


@pytest.mark.parametrize(
    "model,factory",
    [
        (EvidenceQuery, query),
        (LessonPin, lesson),
        (SourceReference, reference),
        (AssistanceContext, assistance),
        (ObservedCheck, check),
        (EngineeringObservation, observation),
        (HintEvidence, hint),
        (
            RetrievalQuestionPin,
            lambda: {"question_id": "report-contract-v1", "content_hash": "b" * 64},
        ),
    ],
)
def test_all_contracts_reject_unknown_fields(model, factory):
    data = factory()
    data["frontend_score"] = 100
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"competency": Competency.INVESTIGATION},
        {"competency": Competency.TRANSFER},
        {"source": reference("attempt")},
        {"basis": "indirect"},
        {"schema_version": "engineering-evidence-v2"},
        {"outcome": "unknown"},
        {"outcome": "unavailable"},
        {"event_type": "page_viewed"},
    ],
)
def test_prediction_cannot_be_relabelled_as_another_competency_or_inferred_claim(changes):
    data = observation()
    data.update(changes)
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(data)


@pytest.mark.parametrize("outcome", ["success", "failure", "unavailable"])
def test_modification_submission_cannot_retroactively_claim_correctness(outcome):
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(
            observation("modification_submitted", outcome=outcome)
        )


def test_prediction_failure_is_observed_failure_not_inferred_mastery():
    assert (
        EngineeringObservation.model_validate(observation(outcome="failure")).outcome == "failure"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"version": "1.1.0"},
        {"version": "v1.0.0"},
        {"version": "01.0.0"},
        {"lesson_id": "generated-candidate"},
        {"content_hash": "A" * 64},
        {"content_hash": "a" * 63},
        {"content_hash": "g" * 64},
    ],
)
def test_lesson_pin_rejects_unpublished_versions_and_malformed_digests(changes):
    with pytest.raises(ValidationError):
        LessonPin.model_validate(lesson(**changes))


@pytest.mark.parametrize("category", ["independent", "authored_hint_assisted"])
def test_uninstrumented_assistance_claims_remain_unavailable(category):
    with pytest.raises(ValidationError):
        AssistanceContext.model_validate(assistance(category=category))


def test_request_without_delivery_keeps_assistance_unknown():
    item = AssistanceContext.model_validate(
        assistance(requested_before=[reference("hint_operation")])
    )
    assert item.category == "unknown" and item.delivered_before == ()


def test_legacy_delivered_help_does_not_require_a_fabricated_reservation():
    item = AssistanceContext.model_validate(
        assistance(category="tutor_assisted", delivered_before=[reference("tutor_interaction")])
    )
    assert item.requested_before == () and len(item.delivered_before) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "tutor_assisted"},
        {"delivered_before": [reference("tutor_interaction")]},
        {"requested_before": [reference("tutor_interaction")]},
        {"category": "tutor_assisted", "delivered_before": [reference("hint_operation")]},
        {"requested_before": [reference("hint_operation") for _ in range(4)]},
    ],
)
def test_assistance_does_not_confuse_request_delivery_or_unknown_context(changes):
    with pytest.raises(ValidationError):
        AssistanceContext.model_validate(assistance(**changes))


@pytest.mark.parametrize(
    "field,kind",
    [("requested_before", "hint_operation"), ("delivered_before", "tutor_interaction")],
)
def test_assistance_rejects_duplicate_source_records(field, kind):
    ref = reference(kind)
    data = assistance(**{field: [ref, ref]})
    if field == "delivered_before":
        data["category"] = "tutor_assisted"
    with pytest.raises(ValidationError):
        AssistanceContext.model_validate(data)


@pytest.mark.parametrize(
    "code,origin",
    [
        ("http_status", "fresh_database_read"),
        ("api_response", "verifier"),
        ("validation", "server_lifecycle"),
        ("row_count", "asgi_http"),
        ("stored_values", "verifier"),
        ("execution", "asgi_http"),
    ],
)
def test_check_evidence_origin_cannot_be_relabelled(code, origin):
    with pytest.raises(ValidationError):
        ObservedCheck.model_validate(check(code, origin=origin))


@pytest.mark.parametrize("matched", [1, 0, "true", "false", None])
def test_check_matches_require_real_booleans(matched):
    with pytest.raises(ValidationError):
        ObservedCheck.model_validate(check(matched=matched))


def test_check_requires_actual_verification_check_reference():
    with pytest.raises(ValidationError):
        ObservedCheck.model_validate(check(source=reference("attempt")))


@pytest.mark.parametrize("origin", ["verifier", "server_lifecycle"])
def test_execution_failure_preserves_trusted_failure_source(origin):
    item = ObservedCheck.model_validate(check("execution", origin=origin))
    assert not item.matched
    with pytest.raises(ValidationError):
        ObservedCheck.model_validate(check("execution", origin=origin, matched=True))


def test_real_failed_verification_and_infrastructure_error_remain_distinct():
    checks = runtime_checks()
    checks[0]["matched"] = False
    failed = EngineeringObservation.model_validate(
        observation("verification_finished", outcome="failure", checks=checks)
    )
    error = EngineeringObservation.model_validate(
        observation("verification_finished", outcome="unavailable", checks=[check("execution")])
    )
    assert failed.outcome == "failure" and error.outcome == "unavailable"


@pytest.mark.parametrize(
    "changes",
    [
        {"checks": []},
        {"checks": [check()]},
        {"outcome": "unknown"},
        {"checks": [check("execution")]},
        {"related_sources": []},
        {"outcome": "failure"},
    ],
)
def test_runtime_success_requires_complete_consistent_checks_and_attempt_link(changes):
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(observation("verification_finished", **changes))


def test_runtime_success_cannot_hide_a_failed_check():
    checks = runtime_checks()
    checks[-1]["matched"] = False
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(observation("verification_finished", checks=checks))


@pytest.mark.parametrize("mutation", ["duplicate_code", "duplicate_source"])
def test_runtime_checks_cannot_duplicate_categories_or_source_records(mutation):
    checks = runtime_checks()
    if mutation == "duplicate_code":
        checks[-1] = check("http_status")
    else:
        checks[-1]["source"] = checks[0]["source"]
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(observation("verification_finished", checks=checks))


def test_nonruntime_action_cannot_claim_frontend_supplied_verification_results():
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(observation(checks=runtime_checks()))


@pytest.mark.parametrize(
    "changes",
    [
        {"basis": "direct"},
        {"related_sources": [reference("attempt")]},
        {"outcome": "failure"},
    ],
)
def test_recovery_observation_does_not_claim_direct_debugging_diagnosis(changes):
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(observation("debugging_recovery_observed", **changes))


def test_transfer_requires_tasks_pin_not_notes_completion():
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(observation("transfer_completed", lesson=lesson()))


@pytest.mark.parametrize(
    "changes",
    [
        {"question": None},
        {"checkpoint": reference("attempt")},
        {"question": {"question_id": "unknown-question", "content_hash": "b" * 64}},
        {"question": {"question_id": "shipping-contract-v1", "content_hash": "b"}},
    ],
)
def test_retrieval_answer_requires_exact_question_pin_and_checkpoint(changes):
    with pytest.raises(ValidationError):
        RetrievalEvidence.model_validate(retrieval(**changes))


def test_nonretrieval_observation_cannot_smuggle_a_question_pin():
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(
            observation(
                retrieval_question={"question_id": "shipping-contract-v1", "content_hash": "b" * 64}
            )
        )


@pytest.mark.parametrize(
    "event_type,outcome,kind,valid",
    [
        ("hint_requested", "requested", "hint_operation", True),
        ("hint_finalized", "delivered", "tutor_interaction", True),
        ("hint_finalized", "error", "tutor_interaction", True),
        ("hint_requested", "delivered", "hint_operation", False),
        ("hint_requested", "requested", "tutor_interaction", False),
        ("hint_finalized", "requested", "tutor_interaction", False),
        ("hint_finalized", "error", "hint_operation", False),
    ],
)
def test_hint_request_and_finalization_are_distinct_immutable_events(
    event_type, outcome, kind, valid
):
    data = hint(event_type, outcome=outcome, source=reference(kind))
    if valid:
        assert HintEvidence.model_validate(data).outcome == outcome
    else:
        with pytest.raises(ValidationError):
            HintEvidence.model_validate(data)


def test_empty_cohort_contains_no_fabricated_investigation_or_completion_evidence():
    result = batch()
    assert result.observations == result.hint_events == ()


@pytest.mark.parametrize("field", ["owner_learner_id", "session_id"])
@pytest.mark.parametrize("kind", ["observation", "hint"])
def test_batch_rejects_cross_owner_and_cross_session_evidence(field, kind):
    data = observation(**{field: uuid4()}) if kind == "observation" else hint(**{field: uuid4()})
    with pytest.raises(ValidationError):
        batch([data] if kind == "observation" else [], [data] if kind == "hint" else [])


def test_batch_rejects_mixed_lesson_pins_even_for_the_same_lesson_label():
    first, second = observation(), hint()
    with pytest.raises(ValidationError):
        batch([first], [second])


@pytest.mark.parametrize("mutation", ["id", "source_event"])
def test_batch_deduplicates_stable_identity_and_source_event(mutation):
    first = observation()
    second = deepcopy(first)
    if mutation == "source_event":
        second["id"] = uuid4()
    else:
        second["source"] = reference("prediction")
    with pytest.raises(ValidationError):
        batch([first, second])


def test_batch_combines_hint_and_action_count_in_one_explicit_bound():
    first = observation()
    help_event = hint(lesson=first["lesson"])
    with pytest.raises(ValidationError):
        batch([first], [help_event], max_records=1)
    assert len(batch([first], [help_event], max_records=2).hint_events) == 1


@pytest.mark.parametrize(
    "when,valid",
    [
        (START, True),
        (END - timedelta(microseconds=1), True),
        (START - timedelta(microseconds=1), False),
        (END, False),
    ],
)
def test_event_window_is_exact_start_inclusive_end_exclusive(when, valid):
    data = observation(occurred_at=when)
    if valid:
        assert batch([data]).observations[0].occurred_at == when
    else:
        with pytest.raises(ValidationError):
            batch([data])


@pytest.mark.parametrize(
    "changes",
    [
        {"end_at": START},
        {"end_at": START - timedelta(seconds=1)},
        {"as_of": END - timedelta(seconds=1)},
        {"max_records": 0},
        {"max_records": 10001},
        {"max_records": True},
        {"max_records": "20"},
        {"start_at": START.replace(tzinfo=None)},
    ],
)
def test_query_requires_explicit_safe_utc_bounds_and_strict_limits(changes):
    with pytest.raises(ValidationError):
        EvidenceQuery.model_validate(query(**changes))


def test_offset_instants_normalize_to_utc_without_server_timezone_policy():
    offset = timezone(timedelta(hours=5, minutes=30))
    data = observation(occurred_at=START.astimezone(offset))
    result = batch([data], start_at=START.astimezone(offset), end_at=END.astimezone(offset))
    assert result.observations[0].occurred_at.tzinfo == UTC
    assert result.query.start_at.tzinfo == UTC


def test_out_of_order_projection_does_not_rewrite_original_observations():
    first = observation(occurred_at=START + timedelta(hours=1))
    second = observation(
        "modification_submitted", lesson=first["lesson"], occurred_at=START + timedelta(hours=2)
    )
    result = batch([second, first])
    assert tuple(item.id for item in result.observations) == (second["id"], first["id"])
    assert result.observations[1].outcome == "success"
    with pytest.raises(ValidationError):
        result.observations[1].outcome = "failure"
    with pytest.raises(ValidationError):
        result.query.max_records = 100


def test_source_primary_reference_cannot_be_duplicated_as_supporting_provenance():
    data = observation()
    data["related_sources"] = [data["source"]]
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(data)


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_retrieval_round_trip_preserves_fact_without_competency_or_raw_answer(outcome):
    item = RetrievalEvidence.model_validate(retrieval(outcome=outcome))
    assert RetrievalEvidence.model_validate_json(item.model_dump_json()) == item
    assert item.assistance.category == "unknown"
    for field in (
        "competency",
        "basis",
        "checks",
        "reasoning",
        "selection",
        "expected",
        "observed",
        "answer_key",
        "score",
        "text",
    ):
        assert field not in item.model_dump()


@pytest.mark.parametrize("field", list(RetrievalEvidence.model_fields))
def test_retrieval_requires_original_identity_and_provenance_fields(field):
    data = retrieval()
    del data[field]
    with pytest.raises(ValidationError):
        RetrievalEvidence.model_validate(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"lesson": lesson()},
        {"source": reference("prediction")},
        {"checkpoint": reference("attempt")},
        {"outcome": "unavailable"},
        {"outcome": "unknown"},
        {"event_type": "prediction_submitted"},
        {"schema_version": "engineering-evidence-v2"},
        {"occurred_at": START.replace(tzinfo=None)},
        {"competency": Competency.PREDICTION},
        {"basis": "direct"},
        {"checks": runtime_checks()},
        {"related_sources": []},
        {"score": 1},
    ],
)
def test_retrieval_cannot_claim_unsupported_classification_or_source(changes):
    with pytest.raises(ValidationError):
        RetrievalEvidence.model_validate(retrieval(**changes))


@pytest.mark.parametrize(
    "help_context",
    [
        assistance(requested_before=[reference("hint_operation")]),
        assistance(category="tutor_assisted", delivered_before=[reference("tutor_interaction")]),
        assistance(category="independent"),
        assistance(category="authored_hint_assisted"),
    ],
)
def test_retrieval_cannot_reuse_earlier_task_help_or_invent_independence(help_context):
    with pytest.raises(ValidationError):
        RetrievalEvidence.model_validate(retrieval(assistance=help_context))


def test_recall_answer_cannot_be_relabelled_as_a_prediction_observation():
    data = observation()
    data.update(event_type="retrieval_answered", source=reference("retrieval_attempt"))
    with pytest.raises(ValidationError):
        EngineeringObservation.model_validate(data)


@pytest.mark.parametrize("field", ["owner_learner_id", "session_id", "lesson"])
def test_batch_rejects_cross_scope_auxiliary_retrieval(field):
    data = batch_data(retrieval_events=[retrieval()])
    data["retrieval_events"][0][field] = (
        lesson(lesson_id="fastapi-nested-payload-transfer") if field == "lesson" else uuid4()
    )
    with pytest.raises(ValidationError):
        EngineeringEvidenceBatch.model_validate(data)


@pytest.mark.parametrize("mutation", ["id", "source_event"])
def test_auxiliary_retrieval_is_idempotent_and_cannot_duplicate_evidence(mutation):
    first = retrieval()
    second = deepcopy(first)
    if mutation == "source_event":
        second["id"] = uuid4()
    else:
        second["source"] = reference("retrieval_attempt")
    with pytest.raises(ValidationError):
        batch(retrieval_events=[first, second])


@pytest.mark.parametrize("when", [START - timedelta(microseconds=1), END])
def test_auxiliary_retrieval_respects_the_same_half_open_utc_cohort(when):
    with pytest.raises(ValidationError):
        batch(retrieval_events=[retrieval(occurred_at=when)])


def test_hint_and_retrieval_records_share_event_bound_without_manufacturing_competence():
    answer = retrieval()
    help_event = hint(lesson=answer["lesson"])
    with pytest.raises(ValidationError):
        batch(hints=[help_event], retrieval_events=[answer], max_records=1)
    result = batch(hints=[help_event], retrieval_events=[answer], max_records=2)
    assert len(result.hint_events) == len(result.retrieval_events) == 1
    assert result.observations == ()
    assert not any(item.observed_in_window for item in result.coverage)


@pytest.mark.parametrize("family", ["fastapi-payload-mismatch", "fastapi-nested-payload-transfer"])
def test_empty_cohort_retains_lesson_and_explicit_capture_limits(family):
    pin = LessonPin.model_validate(lesson(lesson_id=family))
    data = batch_data()
    data.update(lesson=pin, coverage=coverage_profile(pin, frozenset()))
    data["query"]["max_records"] = 1
    result = EngineeringEvidenceBatch.model_validate(data)
    assert result.lesson == pin
    coverage = {item.competency: item for item in result.coverage}
    assert set(coverage) == set(Competency)
    assert not any(item.observed_in_window for item in result.coverage)
    assert coverage[Competency.PREDICTION].availability == "direct"
    assert coverage[Competency.INVESTIGATION].availability == "unavailable"
    assert coverage[Competency.INVESTIGATION].limitations == ("investigation_not_recorded",)
    assert coverage[Competency.MODIFICATION].availability == "partial"
    assert "code_patch_not_recorded" in coverage[Competency.MODIFICATION].limitations
    assert coverage[Competency.DEBUGGING].availability == "partial"
    assert "diagnosis_not_recorded" in coverage[Competency.DEBUGGING].limitations
    assert coverage[Competency.VERIFICATION].availability == "direct"
    transfer = coverage[Competency.TRANSFER]
    if family == "fastapi-payload-mismatch":
        assert transfer.availability == "unavailable"
        assert transfer.limitations == ("outgoing_transfer_not_recorded",)
    else:
        assert transfer.availability == "partial"
        assert transfer.limitations == ("exact_notes_parent_not_pinned",)


def test_runtime_error_presence_does_not_change_direct_support_into_a_success_claim():
    record = observation(
        "verification_finished", outcome="unavailable", checks=[check("execution")]
    )
    result = batch([record])
    descriptor = next(
        item for item in result.coverage if item.competency == Competency.VERIFICATION
    )
    assert descriptor.availability == "direct" and descriptor.observed_in_window
    assert result.observations[0].outcome == "unavailable"
    assert not any(item.observed_in_window for item in result.coverage if item != descriptor)


@pytest.mark.parametrize(
    "changes",
    [
        {"availability": "mastered"},
        {"availability": "unavailable", "observed_in_window": True},
        {"observed_in_window": 1},
        {"observed_in_window": "false"},
        {"limitations": ["learner_is_unskilled"]},
        {"limitations": ["selected_outcome_only", "selected_outcome_only"]},
        {
            "limitations": [
                "selected_outcome_only",
                "finite_mapping_only",
                "code_patch_not_recorded",
                "runtime_outcome_separate",
                "recovery_chronology_only",
            ]
        },
        {"score": 0},
    ],
)
def test_capture_metadata_is_strict_bounded_and_contains_no_profile_or_score(changes):
    data = {
        "competency": Competency.PREDICTION,
        "availability": "direct",
        "observed_in_window": False,
        "limitations": ["selected_outcome_only"],
        **changes,
    }
    with pytest.raises(ValidationError):
        EvidenceCoverage.model_validate(data)


@pytest.mark.parametrize("field", ["lesson", "coverage", "retrieval_events"])
def test_batch_requires_explicit_pin_coverage_and_auxiliary_collection_even_when_empty(field):
    data = batch_data()
    del data[field]
    with pytest.raises(ValidationError):
        EngineeringEvidenceBatch.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "duplicate", "capability", "limit", "presence", "invented_diagnosis"],
)
def test_batch_rejects_forged_instrumentation_metadata(mutation):
    data = batch_data()
    coverage = data["coverage"]
    if mutation == "missing":
        coverage.pop()
    elif mutation == "extra":
        coverage.append(deepcopy(coverage[0]))
    elif mutation == "duplicate":
        coverage[-1] = deepcopy(coverage[0])
    elif mutation == "capability":
        coverage[0]["availability"] = "partial"
    elif mutation == "limit":
        coverage[0]["limitations"] = []
    elif mutation == "presence":
        coverage[0]["observed_in_window"] = True
    elif mutation == "invented_diagnosis":
        coverage[3]["availability"] = "direct"
        coverage[3]["limitations"] = []
    with pytest.raises(ValidationError):
        EngineeringEvidenceBatch.model_validate(data)


def test_batch_cannot_hide_actual_event_presence_with_false_metadata():
    data = batch_data([observation()])
    data["coverage"][0]["observed_in_window"] = False
    with pytest.raises(ValidationError):
        EngineeringEvidenceBatch.model_validate(data)


def test_notes_and_tasks_coverage_cannot_be_substituted_for_an_empty_session():
    data = batch_data()
    tasks = LessonPin.model_validate(lesson(lesson_id="fastapi-nested-payload-transfer"))
    data["coverage"] = coverage_profile(tasks, frozenset())
    with pytest.raises(ValidationError):
        EngineeringEvidenceBatch.model_validate(data)


def test_coverage_is_immutable_and_its_descriptor_order_has_no_event_meaning():
    data = batch_data()
    data["coverage"].reverse()
    result = EngineeringEvidenceBatch.model_validate(data)
    assert {item.competency for item in result.coverage} == set(Competency)
    with pytest.raises(ValidationError):
        result.coverage[0].availability = "direct"


def test_coverage_profile_revalidates_constructed_pins_and_uninstrumented_claims():
    pin = LessonPin.model_construct(**lesson(version="9.0.0"))
    with pytest.raises(ValidationError):
        coverage_profile(pin, frozenset())
    valid = LessonPin.model_validate(lesson())
    with pytest.raises(ValueError):
        coverage_profile(valid, frozenset({"prediction"}))
    with pytest.raises(ValidationError):
        coverage_profile(valid, frozenset({Competency.INVESTIGATION}))
