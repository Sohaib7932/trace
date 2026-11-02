"""Strict output contracts and public-only digests are not authorization tokens."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.feedback_release import FeedbackReleaseScope
from app.schemas.lesson_assistant import PublicLessonContent
from app.schemas.public_feedback import (
    LESSON_LABELS,
    NOTICE_DETERMINISTIC,
    NOTICE_INSUFFICIENT,
    NOTICE_MOCK,
    NOTICE_NOT_READY,
    NOTICE_NOT_SUPPORTED,
    NOTICE_UNAVAILABLE,
    FeedbackVisibilityPolicy,
    PublicEvidenceCitation,
    PublicFeedbackReply,
    PublicFeedbackSection,
    PublicFeedbackStatement,
    PublicLessonCitation,
    PublicLessonIdentity,
    PublicVerificationCheck,
)
from app.services.catalog import PUBLIC_CONTENT, TRANSFER_CONTENT, lesson_hash, transfer_hash

SESSION_ID = UUID("00000000-0000-4000-8000-000000000042")
AT = datetime(2035, 1, 1, tzinfo=UTC)
NOTES_PUBLIC_DIGEST = "d8dbd297b96f22d6459dd41b81264a79ccaae802db2c8d5fe73d63392a8df9b7"
TASKS_PUBLIC_DIGEST = "c389d477ca0053a02c627cea1c12c88b11e6625ef675002fbf2727188edd6daf"


def policy_data():
    return {
        "scope": FeedbackReleaseScope(
            allowed_modes=("account",), allow_terminal_reflection=False
        ).model_dump(),
        "include_recall": False,
        "next_action_ids": (),
        "allow_mock_delivery": False,
        "approval_reference": "proposed-test-policy-only",
    }


def public_lesson():
    return {
        "lesson_id": "fastapi-payload-mismatch",
        "version": "1.0.0",
        "public_content_sha256": NOTES_PUBLIC_DIGEST,
    }


def evidence(alias="e1"):
    return {
        "alias": alias,
        "description": "Your submitted attempt",
        "occurred_at": AT,
        "checks": (),
    }


def lesson_citation(alias="l1"):
    return {
        "alias": alias,
        "lesson": public_lesson(),
        "field": "outgoing_code",
        "label": "Outgoing request builder",
        "sha256": hashlib.sha256(PUBLIC_CONTENT["outgoing_code"].encode("utf-8")).hexdigest(),
    }


def reply_data():
    return {
        "availability": "available",
        "feedback_state": "supported",
        "delivery_state": "deterministic",
        "session_id": SESSION_ID,
        "lesson": public_lesson(),
        "as_of": AT + timedelta(seconds=10),
        "sections": (
            {
                "kind": "demonstrated",
                "items": (
                    {
                        "role": "observation",
                        "text": "Your finite mapping submission is recorded.",
                        "evidence_aliases": ("e1",),
                        "lesson_aliases": ("l1",),
                    },
                ),
            },
        ),
        "evidence_citations": (evidence(),),
        "lesson_citations": (lesson_citation(),),
        "notice": NOTICE_DETERMINISTIC,
    }


def closed_data(availability="not_ready"):
    return {
        "availability": availability,
        "feedback_state": "unavailable" if availability == "unavailable" else None,
        "delivery_state": "unavailable",
        "session_id": SESSION_ID,
        "lesson": None,
        "as_of": None,
        "sections": (),
        "evidence_citations": (),
        "lesson_citations": (),
        "notice": {
            "not_ready": NOTICE_NOT_READY,
            "not_supported": NOTICE_NOT_SUPPORTED,
            "unavailable": NOTICE_UNAVAILABLE,
        }[availability],
    }


def test_disabled_policy_has_no_silently_approved_audience_or_guidance():
    policy = FeedbackVisibilityPolicy.disabled()
    assert policy.scope.allowed_modes == ()
    assert policy.scope.allow_terminal_reflection is False
    assert policy.include_recall is policy.allow_mock_delivery is False
    assert policy.next_action_ids == () and policy.approval_reference is None
    assert policy.policy_version == "evidence-feedback-visibility-v1"
    with pytest.raises(ValidationError):
        FeedbackVisibilityPolicy()


@pytest.mark.parametrize("field", list(policy_data()))
def test_policy_requires_each_explicit_configuration_field(field):
    body = policy_data()
    del body[field]
    with pytest.raises(ValidationError):
        FeedbackVisibilityPolicy.model_validate(body)


@pytest.mark.parametrize("enabled", ["audience", "terminal", "next_action", "mock"])
def test_unapproved_paths_cannot_activate_without_a_server_policy_reference(enabled):
    body = FeedbackVisibilityPolicy.disabled().model_dump()
    if enabled == "audience":
        body["scope"]["allowed_modes"] = ("guest",)
    elif enabled == "terminal":
        body["scope"]["allow_terminal_reflection"] = True
    elif enabled == "next_action":
        body["next_action_ids"] = ("compare-receiving-contract",)
    else:
        body["allow_mock_delivery"] = True
    with pytest.raises(ValidationError):
        FeedbackVisibilityPolicy.model_validate(body)


@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_recall_stays_unapproved_and_false_is_not_coerced(value):
    body = policy_data()
    body["include_recall"] = value
    with pytest.raises(ValidationError):
        FeedbackVisibilityPolicy.model_validate(body)


@pytest.mark.parametrize("value", [0, 1, "true", "false", None])
def test_mock_permission_is_a_strict_explicit_boolean(value):
    body = policy_data()
    body["allow_mock_delivery"] = value
    with pytest.raises(ValidationError):
        FeedbackVisibilityPolicy.model_validate(body)


@pytest.mark.parametrize(
    "ids",
    [("repair-mapping",), ("reveal-answer",), ("compare-receiving-contract",) * 2],
)
def test_next_action_vocabulary_is_finite_and_cannot_duplicate(ids):
    body = policy_data()
    body["next_action_ids"] = ids
    with pytest.raises(ValidationError):
        FeedbackVisibilityPolicy.model_validate(body)


@pytest.mark.parametrize(
    "field", ["schema_version", "account_id", "rate_limit", "provider_id", "raw_credentials"]
)
def test_policy_rejects_unknown_client_style_configuration_and_hides_input(field):
    body = policy_data()
    body[field] = "CONTROLLED_PRIVATE_CANARY"
    with pytest.raises(ValidationError) as error:
        FeedbackVisibilityPolicy.model_validate(body)
    assert "CONTROLLED_PRIVATE_CANARY" not in str(error.value)


def test_policy_refreshes_a_forged_nested_scope_before_accepting_it():
    body = policy_data()
    body["scope"] = FeedbackReleaseScope.disabled().model_copy(
        update={"allowed_modes": ("untrusted-mode",)}
    )
    with pytest.raises(ValidationError):
        FeedbackVisibilityPolicy.model_validate(body)


def test_output_values_are_frozen_and_serialize_without_provenance_or_diagnostics():
    reply = PublicFeedbackReply.model_validate(reply_data())
    assert reply.schema_version == "evidence-feedback-public-v1"
    assert reply.policy_version == "evidence-feedback-visibility-v1"
    assert isinstance(reply.sections, tuple)
    with pytest.raises(ValidationError):
        reply.feedback_state = "unavailable"
    with pytest.raises(ValidationError):
        reply.sections[0].items[0].text = "Mutated text"
    serialized = reply.model_dump_json()
    assert PublicFeedbackReply.model_validate_json(serialized) == reply
    assert set(reply.evidence_citations[0].model_dump()) == {
        "alias",
        "description",
        "occurred_at",
        "checks",
    }
    assert set(reply.lesson.model_dump()) == {"lesson_id", "version", "public_content_sha256"}


@pytest.mark.parametrize("value", ["true", 1])
def test_forged_typed_nested_check_cannot_bypass_strict_boolean_validation(value):
    body = reply_data()
    body["evidence_citations"][0].update(
        description="Your runtime verification", checks=({"code": "http_status", "matched": False},)
    )
    reply = PublicFeedbackReply.model_validate(body)
    citation = reply.evidence_citations[0]
    forged_check = citation.checks[0].model_copy(update={"matched": value})
    forged_citation = citation.model_copy(update={"checks": (forged_check,)})
    forged = reply.model_copy(update={"evidence_citations": (forged_citation,)})
    with pytest.raises(ValidationError):
        PublicFeedbackReply.model_validate(forged)


@pytest.mark.parametrize("mutation", ["text", "alias"])
def test_forged_typed_statement_is_freshly_validated_in_an_existing_typed_reply(mutation):
    reply = PublicFeedbackReply.model_validate(reply_data())
    statement = reply.sections[0].items[0]
    changes = {"text": "x" * 601} if mutation == "text" else {"evidence_aliases": ("e2",)}
    forged_statement = statement.model_copy(update=changes)
    forged_section = reply.sections[0].model_copy(update={"items": (forged_statement,)})
    forged = reply.model_copy(update={"sections": (forged_section,)})
    with pytest.raises(ValidationError):
        PublicFeedbackReply.model_validate(forged)


def test_existing_typed_policy_cannot_drop_the_reference_authorizing_its_explicit_scope():
    policy = FeedbackVisibilityPolicy.model_validate(policy_data())
    with pytest.raises(ValidationError):
        FeedbackVisibilityPolicy.model_validate(
            policy.model_copy(update={"approval_reference": None})
        )


@pytest.mark.parametrize(
    "field",
    [
        "account_id",
        "owner_learner_id",
        "source",
        "record_id",
        "evidence_id",
        "version_id",
        "content_hash",
        "fallback_reason",
        "provider_id",
        "model_id",
        "expected",
        "observed",
        "private_evaluator",
        "hint_text",
    ],
)
def test_public_reply_rejects_private_internal_fields(field):
    body = reply_data()
    body[field] = "CONTROLLED_PRIVATE_CANARY"
    with pytest.raises(ValidationError) as error:
        PublicFeedbackReply.model_validate(body)
    assert "CONTROLLED_PRIVATE_CANARY" not in str(error.value)


@pytest.mark.parametrize("availability", ["not_ready", "not_supported", "unavailable"])
def test_closed_states_have_no_evaluated_lesson_cutoff_or_citations(availability):
    reply = PublicFeedbackReply.model_validate(closed_data(availability))
    assert reply.lesson is reply.as_of is None
    assert reply.sections == reply.evidence_citations == reply.lesson_citations == ()
    assert reply.delivery_state == "unavailable"
    assert reply.feedback_state == ("unavailable" if availability == "unavailable" else None)


@pytest.mark.parametrize("availability", ["not_ready", "not_supported", "unavailable"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("feedback_state", "supported"),
        ("delivery_state", "deterministic"),
        ("lesson", public_lesson()),
        ("as_of", AT),
        ("sections", reply_data()["sections"]),
        ("evidence_citations", (evidence(),)),
        ("lesson_citations", (lesson_citation(),)),
        ("notice", NOTICE_DETERMINISTIC),
    ],
)
def test_closed_response_cannot_smuggle_evaluated_data(availability, field, value):
    body = closed_data(availability)
    body[field] = value
    with pytest.raises(ValidationError):
        PublicFeedbackReply.model_validate(body)


@pytest.mark.parametrize("state", ["supported", "partially_supported"])
@pytest.mark.parametrize("delivery", ["deterministic", "mock"])
def test_available_grounding_and_delivery_are_distinct_valid_dimensions(state, delivery):
    body = reply_data()
    body.update(feedback_state=state, delivery_state=delivery)
    body["notice"] = NOTICE_MOCK if delivery == "mock" else NOTICE_DETERMINISTIC
    reply = PublicFeedbackReply.model_validate(body)
    assert (reply.feedback_state, reply.delivery_state) == (state, delivery)


def test_insufficient_evidence_can_explicitly_abstain_without_observation_claims():
    body = reply_data()
    body.update(
        feedback_state="insufficient_evidence",
        sections=(),
        evidence_citations=(),
        lesson_citations=(),
        notice=NOTICE_INSUFFICIENT,
    )
    reply = PublicFeedbackReply.model_validate(body)
    assert reply.availability == "available" and reply.feedback_state == "insufficient_evidence"


@pytest.mark.parametrize("state", ["supported", "partially_supported"])
def test_neutral_limitations_alone_cannot_keep_supported_grounding(state):
    body = reply_data()
    body.update(feedback_state=state, evidence_citations=(), lesson_citations=())
    body["sections"] = (
        {
            "kind": "why",
            "items": (
                {
                    "role": "limitation",
                    "text": "Investigation actions are not recorded.",
                    "evidence_aliases": (),
                    "lesson_aliases": (),
                },
            ),
        },
    )
    with pytest.raises(ValidationError):
        PublicFeedbackReply.model_validate(body)


@pytest.mark.parametrize("section", ["demonstrated", "needs_improvement"])
def test_neutral_unknowns_cannot_be_presented_as_demonstrations_or_mistakes(section):
    observed = PublicFeedbackStatement.model_validate(reply_data()["sections"][0]["items"][0])
    unknown = PublicFeedbackStatement(
        role="limitation",
        text="Investigation ability is unknown because investigation actions are not recorded.",
        evidence_aliases=(),
        lesson_aliases=(),
    )
    with pytest.raises(ValidationError):
        PublicFeedbackSection(kind=section, items=(observed, unknown))


def test_repeating_a_public_section_cannot_duplicate_the_presented_conclusions():
    body = reply_data()
    body["sections"] = body["sections"] * 2
    with pytest.raises(ValidationError):
        PublicFeedbackReply.model_validate(body)


@pytest.mark.parametrize(("first_count", "accepted"), [(8, True), (9, False)])
def test_total_statement_limit_bounds_the_reply_across_individually_valid_sections(
    first_count, accepted
):
    body = reply_data()
    observed = body["sections"][0]["items"][0]
    body["sections"] = (
        {"kind": "demonstrated", "items": tuple(dict(observed) for _ in range(first_count))},
        {"kind": "why", "items": tuple(dict(observed) for _ in range(8))},
    )
    if accepted:
        reply = PublicFeedbackReply.model_validate(body)
        assert sum(len(section.items) for section in reply.sections) == 16
    else:
        with pytest.raises(ValidationError):
            PublicFeedbackReply.model_validate(body)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "evidence-feedback-v1"),
        ("policy_version", "evidence-feedback-policy-v1"),
        ("availability", "ready"),
        ("feedback_state", "passed"),
        ("feedback_state", None),
        ("feedback_state", "unavailable"),
        ("delivery_state", "live"),
        ("delivery_state", "unavailable"),
        ("lesson", None),
        ("as_of", None),
        ("as_of", AT.replace(tzinfo=None)),
        ("notice", "provider_timeout"),
        ("notice", NOTICE_NOT_READY),
    ],
)
def test_available_reply_rejects_incoherent_or_internal_states(field, value):
    body = reply_data()
    body[field] = value
    with pytest.raises(ValidationError):
        PublicFeedbackReply.model_validate(body)


@pytest.mark.parametrize("alias", ["e0", "e01", "e65", "l1", "verification_run", str(SESSION_ID)])
def test_evidence_aliases_cannot_be_source_identifiers_or_other_namespaces(alias):
    with pytest.raises(ValidationError):
        PublicEvidenceCitation.model_validate({**evidence(), "alias": alias})


@pytest.mark.parametrize("alias", ["l0", "l01", "l6", "e1", "outgoing_code", str(SESSION_ID)])
def test_lesson_aliases_are_bounded_response_local_names(alias):
    with pytest.raises(ValidationError):
        PublicLessonCitation.model_validate({**lesson_citation(), "alias": alias})


@pytest.mark.parametrize("kind", ["duplicate", "dangling", "unused", "gap", "statement_duplicate"])
@pytest.mark.parametrize("namespace", ["evidence", "lesson"])
def test_alias_graph_rejects_duplicate_missing_and_orphaned_citations(kind, namespace):
    body = reply_data()
    citations = f"{namespace}_citations"
    aliases = f"{namespace}_aliases"
    prefix = "e" if namespace == "evidence" else "l"
    ref = evidence if namespace == "evidence" else lesson_citation
    item = body["sections"][0]["items"][0]
    if kind == "duplicate":
        body[citations] = (ref(), ref())
    elif kind == "dangling":
        item[aliases] = (f"{prefix}2",)
    elif kind == "unused":
        body[citations] = (ref(), ref(f"{prefix}2"))
    elif kind == "gap":
        body[citations] = (ref(f"{prefix}2"),)
        item[aliases] = (f"{prefix}2",)
    else:
        item[aliases] = (f"{prefix}1", f"{prefix}1")
    with pytest.raises(ValidationError):
        PublicFeedbackReply.model_validate(body)


def test_all_five_verification_categories_expose_only_actual_boolean_matches():
    categories = ("http_status", "api_response", "validation", "row_count", "stored_values")
    citation = PublicEvidenceCitation.model_validate(
        {
            **evidence(),
            "description": "Your runtime verification",
            "checks": tuple(
                {"code": code, "matched": index % 2 == 0} for index, code in enumerate(categories)
            ),
        }
    )
    assert tuple(check.code for check in citation.checks) == categories
    assert all(set(check.model_dump()) == {"code", "matched"} for check in citation.checks)


@pytest.mark.parametrize("value", [AT.isoformat(), AT.replace(tzinfo=None), 0, True, None])
def test_python_citation_timestamps_remain_strict_and_aware(value):
    with pytest.raises(ValidationError):
        PublicEvidenceCitation.model_validate({**evidence(), "occurred_at": value})


@pytest.mark.parametrize("code", ["execution", "sql_rows", "HTTP 422", "expected", "passed"])
def test_internal_or_arbitrary_check_categories_are_rejected(code):
    with pytest.raises(ValidationError):
        PublicVerificationCheck(code=code, matched=False)


@pytest.mark.parametrize("value", [0, 1, "true", "false", None])
def test_verification_matches_do_not_coerce_status_codes_or_strings(value):
    with pytest.raises(ValidationError):
        PublicVerificationCheck(code="http_status", matched=value)


@pytest.mark.parametrize("field", ["expected", "observed", "source", "record_id", "response_json"])
def test_verification_output_cannot_add_private_runtime_fields(field):
    with pytest.raises(ValidationError):
        PublicVerificationCheck.model_validate(
            {"code": "http_status", "matched": False, field: "CANARY"}
        )


def test_verification_categories_cannot_repeat_or_attach_to_an_unrelated_action():
    check = {"code": "http_status", "matched": False}
    for description, checks in [
        ("Your runtime verification", (check, check)),
        ("Your submitted attempt", (check,)),
    ]:
        with pytest.raises(ValidationError):
            PublicEvidenceCitation.model_validate(
                {**evidence(), "description": description, "checks": checks}
            )


def test_friendly_evidence_and_lesson_labels_are_read_only_allowlists():
    with pytest.raises(TypeError):
        LESSON_LABELS["outgoing_code"] = "private source path"
    for description in ("verification_run", "source-record", "private/path.py"):
        with pytest.raises(ValidationError):
            PublicEvidenceCitation.model_validate({**evidence(), "description": description})
    for field, label in LESSON_LABELS.items():
        citation = {
            **lesson_citation(),
            "field": field,
            "label": label,
            "sha256": hashlib.sha256(PUBLIC_CONTENT[field].encode("utf-8")).hexdigest(),
        }
        assert PublicLessonCitation.model_validate(citation).label == label
    with pytest.raises(ValidationError):
        PublicLessonCitation.model_validate({**lesson_citation(), "label": "Receiving schema"})


@pytest.mark.parametrize(
    "field", ["version_id", "content_hash", "expected_field", "prediction_answer"]
)
def test_public_lesson_identity_rejects_internal_definition_siblings(field):
    with pytest.raises(ValidationError):
        PublicLessonIdentity.model_validate({**public_lesson(), field: "PRIVATE_CANARY"})


def test_lesson_citations_must_match_the_response_public_pin_and_digest():
    for field, value in [
        ("lesson_id", "fastapi-nested-payload-transfer"),
        ("public_content_sha256", "0" * 64),
    ]:
        body = reply_data()
        body["lesson_citations"][0]["lesson"][field] = value
        with pytest.raises(ValidationError):
            PublicFeedbackReply.model_validate(body)


@pytest.mark.parametrize(
    "text", ["", " " * 2, "x" * 601, "<script>private()</script>", "https://private.invalid"]
)
def test_statement_text_is_bounded_plain_content_without_arbitrary_links(text):
    with pytest.raises(ValidationError):
        PublicFeedbackStatement(
            role="observation",
            text=text,
            evidence_aliases=("e1",),
            lesson_aliases=(),
        )


def test_observations_and_next_actions_retain_complete_required_support():
    for role in ("observation", "next_action"):
        with pytest.raises(ValidationError):
            PublicFeedbackStatement(
                role=role, text="A statement.", evidence_aliases=(), lesson_aliases=()
            )
    statement = PublicFeedbackStatement(
        role="next_action",
        text="Compare the approved code and schema.",
        evidence_aliases=(),
        lesson_aliases=("l1",),
    )
    with pytest.raises(ValidationError):
        PublicFeedbackSection(kind="why", items=(statement,))
    with pytest.raises(ValidationError):
        PublicFeedbackSection(kind="next", items=(statement, statement))


@pytest.mark.parametrize(
    ("content", "expected", "legacy"),
    [
        (PUBLIC_CONTENT, NOTES_PUBLIC_DIGEST, lesson_hash(PUBLIC_CONTENT, "content", "rejected")),
        (TRANSFER_CONTENT, TASKS_PUBLIC_DIGEST, transfer_hash(TRANSFER_CONTENT)),
    ],
)
def test_actual_notes_and_tasks_public_digests_are_stable_and_exclude_private_wrappers(
    content, expected, legacy
):
    from app.services.public_feedback_projection import public_content_sha256

    public = PublicLessonContent.model_validate(content)
    assert public_content_sha256(public) == expected != legacy
    reversed_fields = dict(reversed(tuple(content.items())))
    assert public_content_sha256(PublicLessonContent.model_validate(reversed_fields)) == expected
    for private in ("expected_field", "prediction_answer", "adapter", "version_id"):
        with pytest.raises(ValidationError):
            PublicLessonContent.model_validate({**content, private: "PRIVATE_CANARY"})


def test_public_digest_preserves_utf8_newlines_and_exact_public_bytes():
    from app.services.public_feedback_projection import public_content_sha256

    body = {
        "title": "Café 🧠",
        "objective": "Trace the contract.",
        "scenario": "Line one.\nLine two.",
        "outgoing_code": "payload = {}\n",
        "schema_code": "class Input: pass\n",
    }
    public = PublicLessonContent.model_validate(body)
    assert (
        public_content_sha256(public)
        == "087a0e45abe4b3e226b7cf29bde816784f1769e74b408f133ac4f0942b3643c3"
    )
    assert public_content_sha256(
        PublicLessonContent.model_validate(dict(reversed(tuple(body.items()))))
    ) == public_content_sha256(public)
    for changed in (
        {**body, "scenario": "Line one.\r\nLine two."},
        {**body, "title": "Cafe\u0301 🧠"},
        {**body, "outgoing_code": "payload = {}"},
    ):
        assert public_content_sha256(
            PublicLessonContent.model_validate(changed)
        ) != public_content_sha256(public)
