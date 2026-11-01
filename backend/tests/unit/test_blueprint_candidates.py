"""New candidate definitions are checked against actual legacy source facts, not fixtures."""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from app.blueprints.candidates import (
    BLUEPRINT_CANDIDATE_VERSION,
    EVIDENCE_CATEGORIES,
    BlueprintCandidate,
    candidate_version_id,
    notes_blueprint_candidate,
    tasks_blueprint_candidate,
)
from app.domain.learning import NOTE_CONTENT, NOTE_TITLE
from app.domain.lesson_spec import initial_learner_projection, validate_lesson_spec
from app.domain.lesson_spec.canonical import canonical_bytes, verify_digest
from app.domain.lesson_spec.fields import RetrievalCheckpoint, TransferCheckpoint
from app.domain.lesson_spec.templates import NOTES, TASKS
from app.domain.retrieval import QUESTIONS, RETRIEVAL_DAYS
from app.domain.transfer import TASK_PRIORITY, TASK_TITLE
from app.services.catalog import PUBLIC_CONTENT, TRANSFER_CONTENT, lesson_hash, transfer_hash
from app.verification.asgi_notes import NoteCreate
from app.verification.asgi_tasks import TaskCreate

FACTORIES = (notes_blueprint_candidate, tasks_blueprint_candidate)


@pytest.mark.parametrize("factory", FACTORIES)
def test_complete_candidate_validates_and_canonical_digest_roundtrips(factory):
    candidate = factory()
    definition = candidate.definition
    assert verify_digest(definition)
    assert validate_lesson_spec(canonical_bytes(definition)) == definition
    assert factory() == candidate
    assert candidate.trusted_blueprint().reference().content_sha256 == definition.content_sha256


@pytest.mark.parametrize("factory", FACTORIES)
def test_independent_review_json_is_the_exact_complete_authored_candidate(factory):
    candidate = factory()
    path = (
        Path(__file__).resolve().parents[3]
        / "docs/architecture/blueprint-candidates"
        / f"{candidate.template_family}.json"
    )
    snapshot = validate_lesson_spec(path.read_bytes())
    assert verify_digest(snapshot)
    assert canonical_bytes(snapshot) == canonical_bytes(candidate.definition)


@pytest.mark.parametrize("factory", FACTORIES)
def test_candidate_identity_is_proposed_version_not_legacy_identity(factory):
    definition = factory().definition
    assert definition.version == BLUEPRINT_CANDIDATE_VERSION == "1.1.0"
    assert definition.version_id == str(
        uuid5(NAMESPACE_URL, f"trace:blueprint-candidate:{definition.lesson_id}:1.1.0")
    )
    assert candidate_version_id(definition.lesson_id) == definition.version_id


@pytest.mark.parametrize("factory", FACTORIES)
def test_candidate_envelope_does_not_grant_review_approval_or_release(factory):
    candidate = factory()
    assert candidate.review_status == "pending"
    assert candidate.production_approved is candidate.release_eligible is False
    for field, value in [
        ("review_status", "approved"),
        ("production_approved", True),
        ("release_eligible", True),
    ]:
        with pytest.raises(ValidationError):
            setattr(candidate, field, value)
        data = candidate.model_dump()
        data[field] = value
        with pytest.raises(ValidationError):
            BlueprintCandidate.model_validate(data)


def test_notes_pins_complete_finalized_tasks_identity_version_and_digest():
    notes, tasks = notes_blueprint_candidate(), tasks_blueprint_candidate()
    transfer = notes.definition.checkpoints[4]
    assert isinstance(transfer, TransferCheckpoint)
    assert transfer.target_version == tasks.trusted_blueprint().reference()
    assert notes.definition.version_id != tasks.definition.version_id
    assert tasks.definition.entry_mode == "transfer_only"
    assert len(tasks.definition.checkpoints) == 4


def test_retrieval_uses_existing_questions_answers_and_one_seven_day_schedule():
    definition = notes_blueprint_candidate().definition
    retrieval = [cp for cp in definition.checkpoints if isinstance(cp, RetrievalCheckpoint)]
    assert tuple(cp.schedule.delay_days for cp in retrieval) == RETRIEVAL_DAYS == (1, 7)
    for checkpoint, question in zip(retrieval, QUESTIONS, strict=True):
        assert checkpoint.question.id == question.id
        assert checkpoint.question.prompt == question.prompt
        assert checkpoint.question.schema_code == question.schema_code
        assert checkpoint.question.payload == json.loads(question.payload)
        assert tuple(option.label for option in checkpoint.question.options) == question.options
        rule = definition.private.evaluation.rules[checkpoint.evaluation_rule_id]
        assert rule.answer == question.answer
        feedback = next(item for item in definition.explanations if item.id == rule.explanation_id)
        assert feedback.text == question.explanation
        assert feedback.release_event == "retrieval_response_saved"
        assert checkpoint.schedule.anchor_checkpoint_id == definition.checkpoints[4].id


@pytest.mark.parametrize(
    "factory,template", [(notes_blueprint_candidate, NOTES), (tasks_blueprint_candidate, TASKS)]
)
def test_private_expectations_match_supported_runtime_template_facts(factory, template):
    definition = factory().definition
    private = definition.private
    assert private.runtime_binding.template_id == factory().template_family
    assert private.runtime_binding.revision == "1.0.0"
    fixture = private.verification.fixture
    assert fixture.id == template.fixture_id and fixture.initial_mapping == template.initial
    assert fixture.input_values == definition.scenario.input_values
    baseline, repair = (
        private.verification.profiles.initial_failure,
        private.verification.profiles.repair,
    )
    assert baseline.http_status == 422 and baseline.row_count == 0
    assert baseline.validation_codes == template.validation_codes
    assert repair.http_status == 201 and repair.row_count == 1
    assert repair.response_shape == template.response_shape and repair.validation_codes == ()
    assert repair.stored_values == fixture.input_values
    assert repair.require_response_row_identity_match is True
    assert baseline.require_response_row_identity_match is False
    for profile in (baseline, repair):
        assert profile.required_checks == EVIDENCE_CATEGORIES
    assert definition.tutor_policy.mode == "authored_only"
    assert definition.tutor_policy.max_requests_per_core_session == 3
    artifacts = {artifact.id: artifact.content for artifact in definition.scenario.artifacts}
    assert artifacts == {
        "request-builder": template.request_source,
        "receiver-schema": template.receiver_source,
    }


def test_candidate_inputs_match_actual_verifier_constants_and_receiving_models():
    notes, tasks = notes_blueprint_candidate().definition, tasks_blueprint_candidate().definition
    assert notes.scenario.input_values.model_dump() == {
        "title": NOTE_TITLE,
        "content": NOTE_CONTENT,
    }
    assert tasks.scenario.input_values.model_dump() == {
        "title": TASK_TITLE,
        "priority": TASK_PRIORITY,
    }
    assert (
        NoteCreate.model_validate({"title": NOTE_TITLE, "content": NOTE_CONTENT}).content
        == NOTE_CONTENT
    )
    assert (
        TaskCreate.model_validate(
            {"title": TASK_TITLE, "metadata": {"priority": TASK_PRIORITY}}
        ).metadata.priority
        == TASK_PRIORITY
    )
    for model, payload, expected in [
        (
            NoteCreate,
            {"title": NOTE_TITLE, "body": NOTE_CONTENT},
            {"missing:content", "extra_forbidden:body"},
        ),
        (
            TaskCreate,
            {"title": TASK_TITLE, "priority": TASK_PRIORITY},
            {"missing:metadata", "extra_forbidden:priority"},
        ),
    ]:
        with pytest.raises(ValidationError) as exc:
            model.model_validate(payload)
        assert {f"{item['type']}:{item['loc'][-1]}" for item in exc.value.errors()} == expected
    assert NoteCreate.model_fields["title"].metadata[0].min_length == 1
    assert NoteCreate.model_fields["title"].metadata[1].max_length == 200
    assert NoteCreate.model_fields["content"].metadata[1].max_length == 2000
    assert TaskCreate.model_fields["title"].metadata[1].max_length == 200


@pytest.mark.parametrize("factory", FACTORIES)
def test_initial_projection_excludes_answer_rules_future_explanations_and_digest(factory):
    projection = initial_learner_projection(factory().definition).model_dump(mode="json")
    assert not set(projection) & {
        "private",
        "content_sha256",
        "hints",
        "explanations",
        "checkpoints",
    }
    encoded = json.dumps(projection)
    assert "correct_value" not in encoded and "required_checks" not in encoded


def test_blueprint_work_does_not_change_legacy_content_hashes():
    # Published hashes have their own legacy algorithm and must not become V1 digests.
    before = (lesson_hash(PUBLIC_CONTENT, "content", "rejected"), transfer_hash(TRANSFER_CONTENT))
    notes_blueprint_candidate()
    tasks_blueprint_candidate()
    after = (lesson_hash(PUBLIC_CONTENT, "content", "rejected"), transfer_hash(TRANSFER_CONTENT))
    assert after == before
    assert before[0] != notes_blueprint_candidate().definition.content_sha256


@pytest.mark.parametrize("change", ["family", "digest", "runtime", "target"])
def test_tampered_candidate_envelope_fails_strict_validation(change):
    original = notes_blueprint_candidate()
    data = original.definition.model_dump(mode="json")
    family = original.template_family
    if change == "family":
        family = "tasks-nested-v1"
    elif change == "digest":
        data["content_sha256"] = "f" * 64
    elif change == "runtime":
        data["private"]["runtime_binding"]["revision"] = "9.0.0"
    else:
        data["checkpoints"][4]["target_version"]["version_id"] = data["version_id"]
    with pytest.raises(ValueError):
        BlueprintCandidate(template_family=family, definition=validate_lesson_spec(data))
