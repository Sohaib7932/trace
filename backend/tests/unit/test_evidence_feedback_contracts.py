"""Internal feedback boundaries reject invented authority and broken provenance."""

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from app.schemas.engineering_evidence import (
    Competency,
    EngineeringEvidenceBatch,
    LessonPin,
    coverage_profile,
)
from app.schemas.evidence_feedback import (
    POLICY_VERSION,
    SCHEMA_VERSION,
    SELECTION_VERSION,
    EvidenceReference,
    FeedbackChoice,
    FeedbackClaim,
    FeedbackCompletion,
    FeedbackQuery,
    FeedbackReply,
    FeedbackRequest,
    FeedbackSection,
    FeedbackSelection,
    FeedbackStatement,
    FeedbackWording,
    LessonReference,
)
from app.services.catalog import LESSON_ID, PUBLIC_CONTENT, lesson_hash

START = datetime(2026, 10, 1, tzinfo=UTC)
END = START + timedelta(days=1)


def identity(name):
    return uuid5(NAMESPACE_URL, f"trace:feedback-contract-fixture:{name}")


def pin(**changes):
    return {
        "version_id": identity("version"),
        "lesson_id": LESSON_ID,
        "version": "1.0.0",
        "content_hash": lesson_hash(PUBLIC_CONTENT, "content", "rejected"),
        **changes,
    }


def query(**changes):
    return {
        "request_id": identity("request"),
        "session_id": identity("session"),
        "start_at": START,
        "end_at": END,
        "as_of": END,
        "max_records": 64,
        **changes,
    }


def source(kind="prediction", name="prediction"):
    return {"kind": kind, "record_id": identity(name)}


def evidence():
    lesson = LessonPin.model_validate(pin())
    return EngineeringEvidenceBatch.model_validate(
        {
            "query": {
                "owner_learner_id": identity("owner"),
                "session_id": identity("session"),
                "start_at": START,
                "end_at": END,
                "as_of": END,
                "max_records": 64,
            },
            "lesson": lesson,
            "coverage": coverage_profile(lesson, frozenset({Competency.PREDICTION})),
            "observations": [
                {
                    "id": identity("prediction-evidence"),
                    "schema_version": "engineering-evidence-v1",
                    "owner_learner_id": identity("owner"),
                    "session_id": identity("session"),
                    "lesson": lesson,
                    "competency": Competency.PREDICTION,
                    "event_type": "prediction_submitted",
                    "outcome": "failure",
                    "basis": "direct",
                    "occurred_at": START + timedelta(seconds=1),
                    "source": source(),
                    "related_sources": [],
                    "assistance": {
                        "category": "unknown",
                        "requested_before": [],
                        "delivered_before": [],
                    },
                    "checks": [],
                }
            ],
            "hint_events": [],
            "retrieval_events": [],
        }
    )


def lesson_reference(field="schema_code", **changes):
    text = PUBLIC_CONTENT[field]
    return {
        "reference_id": field,
        "lesson": pin(),
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        **changes,
    }


def wording(**changes):
    return {
        "wording_id": "plain",
        "text": "Your recorded prediction differs from the observed result.",
        **changes,
    }


def fact(**changes):
    return {
        "claim_id": "prediction-discrepancy",
        "section": "needs_improvement",
        "role": "fact",
        "competency": Competency.PREDICTION,
        "evidence_ids": [identity("prediction-evidence")],
        "lesson_reference_ids": [],
        "coverage_refs": [Competency.PREDICTION],
        "wordings": [wording()],
        **changes,
    }


def limitation(**changes):
    return {
        "claim_id": "investigation-unknown",
        "section": "why",
        "role": "limitation",
        "competency": Competency.INVESTIGATION,
        "evidence_ids": [],
        "lesson_reference_ids": [],
        "coverage_refs": [Competency.INVESTIGATION],
        "wordings": [wording(text="Investigation activity is not recorded.")],
        **changes,
    }


def next_step(**changes):
    return {
        "claim_id": "inspect-receiving-contract",
        "section": "next",
        "role": "next_step",
        "competency": None,
        "evidence_ids": [],
        "lesson_reference_ids": ["schema_code"],
        "coverage_refs": [],
        "wordings": [wording(text="Compare the outgoing mapping with the receiving schema.")],
        **changes,
    }


def request(**changes):
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "request_id": identity("request"),
        "evidence": evidence(),
        "focus": source(),
        "state": "partially_supported",
        "lesson_references": [lesson_reference(field) for field in PUBLIC_CONTENT],
        "claims": [fact(), limitation(), next_step()],
        **changes,
    }


def choice(claim=None, **changes):
    claim = claim or fact()
    return {
        "claim_id": claim["claim_id"],
        "wording_id": "plain",
        "evidence_ids": claim["evidence_ids"],
        "lesson_reference_ids": claim["lesson_reference_ids"],
        "coverage_refs": claim["coverage_refs"],
        **changes,
    }


def selection(**changes):
    return {
        "schema_version": SELECTION_VERSION,
        "policy_version": POLICY_VERSION,
        "request_id": identity("request"),
        "lesson": pin(),
        "state": "partially_supported",
        "choices": [choice(item) for item in request()["claims"]],
        **changes,
    }


def statement(claim=None, **changes):
    claim = claim or fact()
    return {
        "claim_id": claim["claim_id"],
        "role": claim["role"],
        "text": claim["wordings"][0]["text"],
        "evidence_ids": claim["evidence_ids"],
        "lesson_reference_ids": claim["lesson_reference_ids"],
        "coverage_refs": claim["coverage_refs"],
        **changes,
    }


def reply(**changes):
    batch = evidence()
    ref = lesson_reference()
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "request_id": identity("request"),
        "session_id": identity("session"),
        "lesson": pin(),
        "state": "partially_supported",
        "delivery": "deterministic",
        "fallback_reason": "disabled",
        "notice": None,
        "sections": [
            {"kind": "needs_improvement", "items": [statement()]},
            {"kind": "why", "items": [statement(limitation())]},
            {"kind": "next", "items": [statement(next_step())]},
        ],
        "evidence_references": [
            {"evidence_id": identity("prediction-evidence"), "sources": [source()]}
        ],
        "lesson_references": [
            {"reference_id": ref["reference_id"], "lesson": ref["lesson"], "sha256": ref["sha256"]}
        ],
        "coverage_references": [
            c
            for c in batch.coverage
            if c.competency in {Competency.PREDICTION, Competency.INVESTIGATION}
        ],
        **changes,
    }


def unavailable(**changes):
    return reply(
        state="unavailable",
        delivery="unavailable",
        lesson=None,
        fallback_reason="source_unavailable",
        notice="Recorded evidence is temporarily unavailable.",
        sections=[],
        evidence_references=[],
        lesson_references=[],
        coverage_references=[],
        **changes,
    )


def test_valid_feedback_is_frozen_versioned_and_uses_existing_canonical_evidence():
    checked = FeedbackRequest.model_validate(request())
    assert isinstance(checked.evidence, EngineeringEvidenceBatch)
    assert checked.evidence.lesson == LessonPin.model_validate(pin())
    assert checked.evidence.query.owner_learner_id == identity("owner")
    # Canonical evidence is an internal typed Python envelope; provider wire
    # output is the separate selection schema and does not receive raw history.
    assert FeedbackRequest.model_validate(checked.model_dump(warnings=False)) == checked
    assert (
        FeedbackSelection.model_validate_json(
            FeedbackSelection.model_validate(selection()).model_dump_json()
        )
        .choices[0]
        .claim_id
        == "prediction-discrepancy"
    )
    with pytest.raises(ValidationError):
        checked.state = "supported"
    assert "raw_history" not in FeedbackRequest.model_fields


@pytest.mark.parametrize(
    "field", ["owner_learner_id", "competency", "correct", "verification", "evidence", "claims"]
)
def test_untrusted_query_cannot_supply_trusted_authority(field):
    with pytest.raises(ValidationError):
        FeedbackQuery.model_validate(query(**{field: "invented"}))


@pytest.mark.parametrize("limit", [0, 65, True, 1.0, "12"])
def test_query_limits_are_strict_and_bounded(limit):
    with pytest.raises(ValidationError):
        FeedbackQuery.model_validate(query(max_records=limit))


@pytest.mark.parametrize(
    "changes",
    [
        {"end_at": START},
        {"start_at": END},
        {"as_of": START},
        {"start_at": START.replace(tzinfo=None)},
        {"end_at": END.replace(tzinfo=None)},
        {"as_of": END.replace(tzinfo=None)},
    ],
)
def test_query_rejects_ambiguous_or_reversed_time_cohorts(changes):
    with pytest.raises(ValidationError):
        FeedbackQuery.model_validate(query(**changes))


def test_query_normalizes_aware_offsets_without_using_host_timezone():
    offset = timezone(timedelta(hours=5, minutes=30))
    checked = FeedbackQuery.model_validate(
        query(
            start_at=START.astimezone(offset),
            end_at=END.astimezone(offset),
            as_of=END.astimezone(offset),
        )
    )
    assert checked.start_at == START and checked.start_at.tzinfo == UTC


@pytest.mark.parametrize("field", list(PUBLIC_CONTENT))
def test_lesson_fields_bind_exact_utf8_bytes_and_preserve_pinned_source(field):
    checked = LessonReference.model_validate(lesson_reference(field))
    assert checked.text == PUBLIC_CONTENT[field]
    assert hashlib.sha256(checked.text.encode()).hexdigest() == checked.sha256
    with pytest.raises(ValidationError):
        LessonReference.model_validate(lesson_reference(field, text=checked.text + "\r\n"))


@pytest.mark.parametrize(
    "changes",
    [
        {"reference_id": "answer_key"},
        {"reference_id": "private_evaluator"},
        {"reference_id": "../../private"},
        {"sha256": "f" * 64},
        {"sha256": "not-a-hash"},
        {"text": ""},
        {"text": "x" * 2401},
        {"text": "\ud800"},
    ],
)
def test_lesson_reference_rejects_private_fields_paths_and_unbound_text(changes):
    with pytest.raises(ValidationError):
        LessonReference.model_validate(lesson_reference(**changes))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "x" * 601,
        "<script>bad</script>",
        "https://outside.example/help",
        "javascript:bad",
        "bad\x00copy",
        "\ud800",
    ],
)
def test_server_wording_has_plain_utf8_and_size_boundaries(text):
    with pytest.raises(ValidationError):
        FeedbackWording.model_validate(wording(text=text))


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_ids": []},
        {"evidence_ids": [identity("e"), identity("e")]},
        {"lesson_reference_ids": ["schema_code", "schema_code"]},
        {"coverage_refs": [Competency.PREDICTION, Competency.PREDICTION]},
        {"wordings": [wording(), wording()]},
        {"wordings": []},
        {"section": "demonstrated", "role": "limitation"},
        {"section": "needs_improvement", "role": "next_step"},
        {"section": "why", "role": "next_step"},
        {"section": "next", "role": "fact"},
    ],
)
def test_claim_shape_requires_evidence_and_consistent_sections(changes):
    with pytest.raises(ValidationError):
        FeedbackClaim.model_validate(fact(**changes))


def test_limitations_are_not_relabelled_as_failed_competency_or_unsupported_facts():
    checked = FeedbackClaim.model_validate(limitation())
    assert checked.role == "limitation" and checked.evidence_ids == ()
    assert checked.coverage_refs == (Competency.INVESTIGATION,)
    with pytest.raises(ValidationError):
        FeedbackClaim.model_validate(limitation(role="fact"))
    with pytest.raises(ValidationError):
        FeedbackClaim.model_validate(next_step(lesson_reference_ids=[]))


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "evidence-feedback-v2"},
        {"policy_version": "unapproved"},
        {"state": "mastered"},
        {"state": "unavailable"},
        {"focus": source(name="foreign")},
        {"focus": source(kind="verification_check", name="foreign")},
        {"lesson_references": []},
        {"claims": []},
    ],
)
def test_request_rejects_wrong_version_authority_and_missing_policy_inputs(changes):
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(request(**changes))


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "policy_version",
        "request_id",
        "evidence",
        "focus",
        "state",
        "lesson_references",
        "claims",
    ],
)
def test_request_identity_and_policy_context_are_required(field):
    data = request()
    del data[field]
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_lesson", "wrong_pin", "unknown_evidence", "duplicate_claim", "no_next", "two_next"],
)
def test_request_references_are_complete_unique_and_bound_to_canonical_batch(mutation):
    data = request()
    if mutation == "duplicate_lesson":
        data["lesson_references"][-1] = deepcopy(data["lesson_references"][0])
    elif mutation == "wrong_pin":
        data["lesson_references"][0]["lesson"]["version_id"] = identity("foreign-version")
    elif mutation == "unknown_evidence":
        data["claims"][0]["evidence_ids"] = [identity("foreign-evidence")]
    elif mutation == "duplicate_claim":
        data["claims"].append(deepcopy(data["claims"][0]))
    elif mutation == "no_next":
        data["claims"] = data["claims"][:-1]
    elif mutation == "two_next":
        data["claims"].append(next_step(claim_id="second-next"))
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(data)


def test_request_deeply_revalidates_constructed_nested_python_models():
    batch = evidence()
    forged = batch.model_copy(
        update={"lesson": batch.lesson.model_copy(update={"version": "9.0.0"})}
    )
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(request(evidence=forged))
    bad_claim = FeedbackClaim.model_construct(**fact(evidence_ids=[]))
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(request(claims=[bad_claim, next_step()]))
    ref = LessonReference.model_validate(lesson_reference())
    bad_ref = ref.model_copy(update={"text": "tampered"})
    refs = request()["lesson_references"]
    refs[-1] = bad_ref
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(request(lesson_references=refs))


def test_request_has_independent_record_and_encoded_payload_limits():
    data = evidence().model_dump()
    first = data["observations"][0]
    data["query"]["max_records"] = 65
    data["observations"] = [
        {**first, "id": identity(f"e-{i}"), "source": source(name=f"p-{i}")} for i in range(65)
    ]
    oversized = EngineeringEvidenceBatch.model_validate(data)
    with pytest.raises(ValidationError, match="at most 64"):
        FeedbackRequest.model_validate(request(evidence=oversized, focus=None))
    claims = [
        fact(
            claim_id=f"fact-{i}",
            wordings=[wording(text="🧪" * 600), wording(wording_id="concise", text="🧪" * 600)],
        )
        for i in range(15)
    ]
    claims.append(
        next_step(
            wordings=[wording(text="🧪" * 600), wording(wording_id="concise", text="🧪" * 600)]
        )
    )
    with pytest.raises(ValidationError, match="65536 UTF-8"):
        FeedbackRequest.model_validate(request(claims=claims))


@pytest.mark.parametrize(
    "field",
    [
        "text",
        "explanation",
        "score",
        "correct",
        "verification",
        "answer_key",
        "private_evaluator",
        "competency",
        "document_path",
        "url",
    ],
)
def test_model_output_cannot_introduce_prose_or_authoritative_fields(field):
    data = selection(**{field: "injected"})
    with pytest.raises(ValidationError):
        FeedbackSelection.model_validate(data)
    data = choice(**{field: "injected"})
    with pytest.raises(ValidationError):
        FeedbackChoice.model_validate(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": SCHEMA_VERSION},
        {"policy_version": "wrong-policy"},
        {"state": "competent"},
        {"choices": [choice(), choice()]},
        {"choices": [choice(claim_id=f"c-{i}") for i in range(17)]},
    ],
)
def test_selection_requires_exact_protocol_and_unique_bounded_claims(changes):
    with pytest.raises(ValidationError):
        FeedbackSelection.model_validate(selection(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"wording_id": "invented"},
        {"evidence_ids": [identity("e"), identity("e")]},
        {"lesson_reference_ids": ["schema_code", "schema_code"]},
        {"coverage_refs": [Competency.DEBUGGING, Competency.DEBUGGING]},
        {"evidence_ids": [identity(str(i)) for i in range(9)]},
    ],
)
def test_selection_choices_cannot_duplicate_or_expand_reference_sets(changes):
    with pytest.raises(ValidationError):
        FeedbackChoice.model_validate(choice(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"text": None},
        {"text": "   "},
        {"source": "none"},
        {"source": "ai"},
        {"error_code": "timeout"},
        {"text": "x" * 65537},
        {"text": "🧪" * 16385},
        {"text": "\ud800"},
    ],
)
def test_successful_completion_is_bounded_fixture_transport_not_validated_authority(changes):
    with pytest.raises(ValidationError):
        FeedbackCompletion.model_validate(
            {"status": "success", "text": "{}", "source": "test_fixture", **changes}
        )


@pytest.mark.parametrize(
    "status", ["refusal", "truncated", "timeout", "rate_limited", "unavailable", "transport_error"]
)
def test_provider_failures_preserve_status_without_fabricating_feedback(status):
    completed = FeedbackCompletion(status=status, text=None, source="none")
    assert completed.status == status and completed.text is None
    assert "text" not in repr(completed)


def test_structured_reply_retains_citations_without_raw_history_or_private_values():
    rendered = FeedbackReply.model_validate(reply())
    assert FeedbackReply.model_validate_json(rendered.model_dump_json()) == rendered
    encoded = rendered.model_dump_json()
    for forbidden in [
        "owner_learner_id",
        "reasoning",
        "expected_field",
        "prediction_answer",
        '"score":',
    ]:
        assert forbidden not in encoded
    assert rendered.evidence_references[0].sources[0].record_id == identity("prediction")
    with pytest.raises(ValidationError):
        rendered.state = "supported"


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "v2"},
        {"policy_version": "other"},
        {"lesson": None},
        {"delivery": "unavailable"},
        {"delivery": "mock", "fallback_reason": "disabled"},
        {"fallback_reason": "source_invalid"},
        {
            "lesson_references": [
                {"reference_id": "schema_code", "lesson": pin(version="2.0.0"), "sha256": "a" * 64}
            ]
        },
    ],
)
def test_reply_version_state_and_delivery_must_be_consistent(changes):
    with pytest.raises(ValidationError):
        FeedbackReply.model_validate(reply(**changes))


@pytest.mark.parametrize(
    "mutation",
    [
        "evidence",
        "lesson",
        "coverage",
        "duplicate_section",
        "duplicate_claim",
        "wrong_pin",
        "duplicate_evidence",
        "duplicate_lesson",
        "duplicate_coverage",
    ],
)
def test_reply_cannot_drop_supporting_references_or_mix_pinned_lessons(mutation):
    data = reply()
    if mutation in {"evidence", "lesson", "coverage"}:
        data[
            {
                "evidence": "evidence_references",
                "lesson": "lesson_references",
                "coverage": "coverage_references",
            }[mutation]
        ] = []
    elif mutation == "duplicate_section":
        data["sections"].append(deepcopy(data["sections"][0]))
    elif mutation == "duplicate_claim":
        data["sections"][1]["items"][0]["claim_id"] = data["sections"][0]["items"][0]["claim_id"]
    elif mutation == "wrong_pin":
        data["lesson_references"][0]["lesson"]["version_id"] = identity("wrong-pin")
    else:
        key = {
            "duplicate_evidence": "evidence_references",
            "duplicate_lesson": "lesson_references",
            "duplicate_coverage": "coverage_references",
        }[mutation]
        data[key].append(deepcopy(data[key][0]))
    with pytest.raises(ValidationError):
        FeedbackReply.model_validate(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "fact", "evidence_ids": []},
        {"role": "next_step", "lesson_reference_ids": []},
        {"evidence_ids": [identity("e"), identity("e")]},
        {"text": "Read https://outside.example"},
    ],
)
def test_rendered_statements_preserve_plain_text_and_role_grounding(changes):
    with pytest.raises(ValidationError):
        FeedbackStatement.model_validate(statement(**changes))


@pytest.mark.parametrize(
    "kind,items",
    [
        ("next", []),
        ("next", [statement()]),
        ("next", [statement(next_step()), statement(next_step(claim_id="another"))]),
        ("why", [statement(next_step())]),
        ("demonstrated", [statement(limitation())]),
        ("needs_improvement", [statement(limitation())]),
    ],
)
def test_sections_cannot_turn_abstention_into_demonstrated_or_failed_ability(kind, items):
    with pytest.raises(ValidationError):
        FeedbackSection.model_validate({"kind": kind, "items": items})


@pytest.mark.parametrize(
    "changes",
    [
        {"notice": None},
        {"delivery": "mock"},
        {"fallback_reason": "provider_timeout"},
        {"fallback_reason": None},
        {"sections": reply()["sections"]},
        {"evidence_references": reply()["evidence_references"]},
        {"lesson_references": reply()["lesson_references"]},
        {"coverage_references": reply()["coverage_references"]},
    ],
)
def test_unavailable_feedback_cannot_retain_conclusions_from_untrusted_sources(changes):
    data = unavailable()
    data.update(changes)
    with pytest.raises(ValidationError):
        FeedbackReply.model_validate(data)


def test_unavailable_reply_abstains_and_deterministic_feedback_can_skip_provider():
    checked = FeedbackReply.model_validate(unavailable())
    assert checked.lesson is None and checked.sections == ()
    deterministic = FeedbackReply.model_validate(reply(fallback_reason=None))
    assert deterministic.delivery == "deterministic"
    accepted = FeedbackReply.model_validate(reply(delivery="mock", fallback_reason=None))
    assert accepted.delivery == "mock"


def test_evidence_reference_requires_unique_original_source_records():
    with pytest.raises(ValidationError):
        EvidenceReference(evidence_id=identity("e"), sources=())
    with pytest.raises(ValidationError):
        EvidenceReference.model_validate(
            {"evidence_id": identity("e"), "sources": [source(), source()]}
        )
