from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.accounts import Account
from app.domain.learning import LearningError
from app.schemas.candidate_lifecycle import CandidateEvent, CandidateHistory, CandidateSnapshot
from app.schemas.candidate_validation import (
    CHECK_CODES,
    CandidateValidationCode,
    RuntimeEvidenceCheck,
    RuntimeProfileEvidence,
    RuntimeValidationReport,
)
from app.services.candidate_lifecycle import CandidateLifecycleService
from app.services.candidate_validation import CandidateValidationService
from tests.lifecycle_fixtures import NOW, admin, inputs


class MemoryStore:
    def __init__(self):
        self.rows = {}

    def get(self, candidate_id):
        return self.rows.get(candidate_id)

    def by_creation_key(self, key):
        return next((h for h in self.rows.values() if h.snapshot.creation_key == key), None)

    def insert(self, snapshot, event):
        if snapshot.id in self.rows:
            raise LearningError("conflict", "Identity already reserved.")
        self.rows[snapshot.id] = CandidateHistory(snapshot=snapshot, events=(event,))

    def append(self, event, expected_revision):
        history = self.rows[event.candidate_id]
        if history.revision != expected_revision:
            raise LearningError("conflict", "Stale revision.")
        self.rows[event.candidate_id] = CandidateHistory(
            snapshot=history.snapshot, events=history.events + (event,)
        )


class MemoryRepository:
    def __init__(self):
        self.store = MemoryStore()
        self.writing = False

    @contextmanager
    def read(self):
        yield self.store

    @contextmanager
    def write(self):
        assert not self.writing
        self.writing = True
        try:
            yield self.store
        finally:
            self.writing = False


def service(validator=None):
    repo = MemoryRepository()
    return CandidateLifecycleService(
        repo, validator or CandidateValidationService(), lambda: NOW
    ), repo


@pytest.mark.parametrize("family", ["notes-v1", "tasks-nested-v1"])
def test_composed_snapshot_preserves_separate_inputs_hashes_and_unreleased_state(family):
    lifecycle, repo = service()
    case = inputs(family)
    history = lifecycle.create(**case)
    snapshot = history.snapshot
    assert history.state == "composed" and history.review_status == "pending"
    assert snapshot.created_at == NOW and not snapshot.release_eligible
    assert snapshot.source_blueprint == case["blueprint"].reference()
    candidate, request, accepted, blueprint, identity, _ = snapshot.context()
    assert request == case["request"] and accepted.status == "accepted"
    assert identity == case["identity"] and blueprint == case["blueprint"]
    assert snapshot.definition_json.encode() == candidate.canonical_definition_bytes
    assert not hasattr(snapshot, "raw_json") and not hasattr(snapshot, "prompt")
    assert "raw_json" not in snapshot.model_dump_json()
    assert lifecycle.create(**case) == history
    assert len(repo.store.rows) == 1


def test_creation_key_conflicts_on_changed_request_or_origin():
    lifecycle, _ = service()
    case = inputs()
    lifecycle.create(**case)
    case["generation_origin"] = "provider"
    with pytest.raises(LearningError, match="Creation key"):
        lifecycle.create(**case)


def test_unadmitted_content_creates_no_candidate():
    lifecycle, repo = service()
    case = inputs()
    case["completion"] = case["completion"].model_copy(update={"raw_json": '{"unknown":true}'})
    with pytest.raises(LearningError, match="not admitted"):
        lifecycle.create(**case)
    assert not repo.store.rows


def test_gate_runs_outside_write_and_unavailable_retry_is_explicit_idempotent():
    lifecycle, repo = service()
    original = lifecycle.validator

    class CheckedGate:
        calls = 0

        def validate(self, *args, **kwargs):
            assert not repo.writing
            self.calls += 1
            return original.validate(*args, **kwargs)

    gate = CheckedGate()
    lifecycle.validator = gate
    history = lifecycle.create(**inputs())
    key = str(uuid4())
    event = lifecycle.validate(history.snapshot.id, key=key, expected_revision=0)
    assert (
        event.state == "validation_unavailable" and event.validation.code == "runtime_unavailable"
    )
    assert lifecycle.validate(history.snapshot.id, key=key, expected_revision=0) == event
    assert gate.calls == 1
    retried = lifecycle.validate(history.snapshot.id, key=str(uuid4()), expected_revision=1)
    assert retried.revision == 2 and retried.state == "validation_unavailable"
    assert gate.calls == 2


@pytest.mark.parametrize("field", ["request_sha256", "admitted_sha256", "composition_sha256"])
def test_provenance_digest_tampering_is_rejected(field):
    lifecycle, _ = service()
    snapshot = lifecycle.create(**inputs()).snapshot
    data = snapshot.model_dump(mode="json")
    data[field] = "f" * 64
    with pytest.raises(ValidationError):
        CandidateSnapshot.model_validate_json(__import__("json").dumps(data))


@pytest.mark.parametrize(
    "changes",
    [
        {"release_eligible": True},
        {"created_at": "2026-11-01T00:00:00"},
        {"raw_json": "not permitted"},
        {"generation_origin": "untrusted"},
    ],
)
def test_snapshot_schema_rejects_unsafe_claims_and_naive_timestamps(changes):
    lifecycle, _ = service()
    data = lifecycle.create(**inputs()).snapshot.model_dump(mode="json")
    data.update(changes)
    with pytest.raises(ValidationError):
        CandidateSnapshot.model_validate_json(__import__("json").dumps(data))


@pytest.mark.parametrize("action", ["human_review", "production_approval", "reject"])
def test_no_human_action_before_technical_validation(action):
    lifecycle, _ = service()
    history = lifecycle.create(**inputs())
    with pytest.raises(LearningError):
        lifecycle.decide(
            history.snapshot.id,
            account=admin(),
            action=action,
            reason="Review.",
            key=str(uuid4()),
            expected_revision=0,
        )


def test_nonadmin_and_disabled_admin_cannot_review():
    lifecycle, _ = service()
    history = lifecycle.create(**inputs())
    for account in [
        Account(uuid4(), NOW, "active", ("learner",)),
        Account(uuid4(), NOW, "disabled", ("admin",)),
    ]:
        with pytest.raises(LearningError, match="required role"):
            lifecycle.decide(
                history.snapshot.id,
                account=account,
                action="human_review",
                reason="Review.",
                key=str(uuid4()),
                expected_revision=0,
            )


def test_same_operation_key_with_different_action_context_is_conflict():
    lifecycle, _ = service()
    history = lifecycle.create(**inputs())
    key = str(uuid4())
    lifecycle.validate(history.snapshot.id, key=key, expected_revision=0)
    with pytest.raises(LearningError, match="another candidate action"):
        lifecycle.validate(history.snapshot.id, key=key, expected_revision=1)


def test_stale_expected_revision_cannot_append_a_new_validation():
    lifecycle, _ = service()
    history = lifecycle.create(**inputs())
    lifecycle.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)
    with pytest.raises(LearningError, match="revision"):
        lifecycle.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)


def test_storage_identity_is_bound_to_the_reserved_version_identity():
    lifecycle, _ = service()
    snapshot = lifecycle.create(**inputs()).snapshot
    data = snapshot.model_dump(mode="json")
    data["id"] = str(uuid4())
    with pytest.raises(ValidationError, match="storage identity"):
        CandidateSnapshot.model_validate_json(__import__("json").dumps(data))


def test_forged_history_cannot_jump_from_composed_to_production_approved():
    lifecycle, _ = service()
    history = lifecycle.create(**inputs()).snapshot
    first = lifecycle.get(history.id).events[0]
    forged = first.model_copy(
        update={
            "action": "production_approval",
            "state": "production_approved",
            "revision": 1,
            "previous_state": "composed",
            "actor_id": str(uuid4()),
            "reviewed_blueprint_sha256": history.source_blueprint.content_sha256,
        }
    )
    with pytest.raises(ValidationError, match="invalid transition"):
        CandidateHistory(snapshot=history, events=(first, forged))


def test_history_cannot_precede_candidate_creation_timestamp():
    lifecycle, _ = service()
    history = lifecycle.create(**inputs())
    earlier = history.events[0].model_copy(update={"created_at": NOW - timedelta(seconds=1)})
    with pytest.raises(ValidationError, match="chronological"):
        CandidateHistory(snapshot=history.snapshot, events=(earlier,))


def test_forged_validation_receipt_is_revalidated_and_never_appended():
    lifecycle, _ = service()
    history = lifecycle.create(**inputs())
    original = lifecycle.validator

    class ForgedGate:
        def validate(self, *args, **kwargs):
            return original.validate(*args, **kwargs).model_copy(update={"release_eligible": True})

    lifecycle.validator = ForgedGate()
    with pytest.raises(ValidationError):
        lifecycle.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)
    assert lifecycle.get(history.snapshot.id).state == "composed"


def test_valid_receipt_for_another_identity_cannot_be_attached():
    lifecycle, _ = service()
    history = lifecycle.create(**inputs())
    original = lifecycle.validator

    class OtherIdentity:
        def validate(self, *args, **kwargs):
            result = original.validate(*args, **kwargs)
            return result.model_copy(
                update={
                    "identity": result.identity.model_copy(update={"version_id": str(uuid4())}),
                }
            )

    lifecycle.validator = OtherIdentity()
    with pytest.raises(LearningError, match="another candidate"):
        lifecycle.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)
    assert lifecycle.get(history.snapshot.id).revision == 0


@pytest.mark.parametrize(
    "field", ["definition_json", "blueprint_json", "request_json", "admitted_json"]
)
def test_noncanonical_or_nonexact_stored_snapshots_are_rejected(field):
    lifecycle, _ = service()
    snapshot = lifecycle.create(**inputs()).snapshot
    data = snapshot.model_dump(mode="json")
    data[field] = " " + data[field]
    with pytest.raises(ValidationError):
        CandidateSnapshot.model_validate_json(__import__("json").dumps(data))


class PassingRuntime:
    """Only runtime evidence is mocked; the real candidate gate still binds all inputs."""

    def validate(self, definition):
        return RuntimeValidationReport(
            status="passed",
            code=None,
            performed=True,
            completed=True,
            profiles=tuple(
                RuntimeProfileEvidence(
                    profile=profile,
                    evaluation_matched=True,
                    checks=tuple(
                        RuntimeEvidenceCheck(code=code, passed=True) for code in sorted(CHECK_CODES)
                    ),
                )
                for profile in ("baseline", "repair")
            ),
        )


def validated_history(origin="mock"):
    lifecycle, repo = service(CandidateValidationService(PassingRuntime()))
    history = lifecycle.create(**inputs(generation_origin=origin))
    lifecycle.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)
    return lifecycle, repo, lifecycle.get(history.snapshot.id)


def reviewed_history(origin="mock"):
    lifecycle, repo, history = validated_history(origin)
    actor = admin()
    lifecycle.decide(
        history.snapshot.id,
        account=actor,
        action="human_review",
        reason="Explicit candidate review.",
        key=str(uuid4()),
        expected_revision=1,
    )
    return lifecycle, repo, lifecycle.get(history.snapshot.id), actor


def approval_event(history, actor, *, digest=None):
    return CandidateEvent(
        id=str(uuid4()),
        candidate_id=history.snapshot.id,
        revision=3,
        operation_key=str(uuid4()),
        command_sha256="a" * 64,
        action="production_approval",
        previous_state="human_reviewed",
        state="production_approved",
        created_at=NOW,
        actor_id=str(actor.id),
        reason="Simulated explicit approval; never publication.",
        reviewed_blueprint_sha256=digest or history.snapshot.source_blueprint.content_sha256,
    )


@pytest.mark.parametrize("destination", ["source_blueprint", "composition_metadata"])
def test_serialized_source_reference_forgery_cannot_rebind_an_existing_definition(destination):
    lifecycle, _ = service()
    data = lifecycle.create(**inputs()).snapshot.model_dump(mode="json")
    reference = (
        data["source_blueprint"]
        if destination == "source_blueprint"
        else data["metadata"]["blueprint"]
    )
    reference["content_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="source blueprint"):
        CandidateSnapshot.model_validate_json(__import__("json").dumps(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("lesson_id", "fastapi-payload-mismatch"),
        ("version", "9.9.9"),
    ],
)
def test_reserved_identity_cannot_be_changed_independently_of_immutable_definition(field, value):
    lifecycle, _ = service()
    data = lifecycle.create(**inputs()).snapshot.model_dump(mode="json")
    data["identity"][field] = value
    with pytest.raises(ValidationError, match="immutable definition"):
        CandidateSnapshot.model_validate_json(__import__("json").dumps(data))


@pytest.mark.parametrize(
    "malformation", ["missing_validation", "receipt_on_creation", "wrong_outcome_state"]
)
def test_validation_audit_event_cannot_omit_or_misrepresent_its_actual_receipt(malformation):
    _, _, history = validated_history()
    if malformation == "receipt_on_creation":
        data = history.events[0].model_dump(mode="json")
        data["validation"] = history.events[1].validation.model_dump(mode="json")
    else:
        data = history.events[1].model_dump(mode="json")
        if malformation == "missing_validation":
            data["validation"] = None
        else:
            data["state"] = "validation_unavailable"
    with pytest.raises(ValidationError, match="gate receipt|actual gate result"):
        CandidateEvent.model_validate_json(__import__("json").dumps(data))


@pytest.mark.parametrize("action", ["human_review", "production_approval", "reject"])
def test_human_audit_decision_cannot_hide_its_administrator_identity(action):
    lifecycle, _, history, actor = reviewed_history("provider")
    if action == "reject":
        event = lifecycle.decide(
            history.snapshot.id,
            account=actor,
            action="reject",
            reason="Explicit rejection.",
            key=str(uuid4()),
            expected_revision=2,
        )
    else:
        event = (
            approval_event(history, actor) if action == "production_approval" else history.events[2]
        )
    data = event.model_dump(mode="json")
    data.update(action=action, actor_id=None)
    with pytest.raises(ValidationError, match="identified administrator"):
        CandidateEvent.model_validate_json(__import__("json").dumps(data))


@pytest.mark.parametrize("index", [0, 1])
def test_system_generated_events_cannot_be_relabelled_as_human_decisions(index):
    _, _, history = validated_history()
    data = history.events[index].model_dump(mode="json")
    data["actor_id"] = str(uuid4())
    with pytest.raises(ValidationError, match="System lifecycle"):
        CandidateEvent.model_validate_json(__import__("json").dumps(data))


@pytest.mark.parametrize(
    "misplacement", ["approval_without_attestation", "review_with_attestation"]
)
def test_blueprint_review_attestation_is_bound_to_the_separate_approval_action(misplacement):
    _, _, history, actor = reviewed_history("provider")
    event = (
        approval_event(history, actor)
        if misplacement == "approval_without_attestation"
        else history.events[2]
    )
    data = event.model_dump(mode="json")
    data["reviewed_blueprint_sha256"] = (
        None
        if misplacement == "approval_without_attestation"
        else history.snapshot.source_blueprint.content_sha256
    )
    with pytest.raises(ValidationError, match="source review attestation"):
        CandidateEvent.model_validate_json(__import__("json").dumps(data))


@pytest.mark.parametrize(
    "corruption", ["other_candidate", "revision_gap", "wrong_predecessor", "backdated_result"]
)
def test_imported_history_cannot_splice_foreign_reordered_or_backdated_events(corruption):
    _, _, history = validated_history()
    created, validated = history.events
    if corruption == "other_candidate":
        validated = validated.model_copy(update={"candidate_id": str(uuid4())})
    elif corruption == "revision_gap":
        validated = validated.model_copy(update={"revision": 5})
    elif corruption == "wrong_predecessor":
        validated = validated.model_copy(update={"previous_state": "validation_unavailable"})
    else:
        created = created.model_copy(update={"created_at": NOW + timedelta(seconds=2)})
        validated = validated.model_copy(update={"created_at": NOW + timedelta(seconds=1)})
    with pytest.raises(ValidationError, match="identity-bound|chain|chronological"):
        CandidateHistory(snapshot=history.snapshot, events=(created, validated))


@pytest.mark.parametrize("forgery", ["other_identity", "other_digest"])
def test_history_receipt_cannot_belong_to_another_candidate_even_with_a_valid_state_chain(forgery):
    _, _, history = validated_history()
    created, validated = history.events
    receipt = validated.validation
    receipt = receipt.model_copy(
        update=(
            {"identity": receipt.identity.model_copy(update={"version_id": str(uuid4())})}
            if forgery == "other_identity"
            else {"content_sha256": "f" * 64}
        )
    )
    with pytest.raises(ValidationError, match="another immutable candidate"):
        CandidateHistory(
            snapshot=history.snapshot,
            events=(created, validated.model_copy(update={"validation": receipt})),
        )


@pytest.mark.parametrize("origin,digest", [("mock", None), ("provider", "f" * 64)])
def test_history_rejects_approval_of_mock_content_or_a_different_source_digest(origin, digest):
    _, _, history, actor = reviewed_history(origin)
    assert history.review_status == "reviewed" and history.release_eligible is False
    forged = approval_event(history, actor, digest=digest)
    with pytest.raises(ValidationError, match="exact non-mock source attestation"):
        CandidateHistory(snapshot=history.snapshot, events=history.events + (forged,))


def test_human_review_does_not_allow_a_wrong_source_approval_attestation():
    lifecycle, _, history, actor = reviewed_history("provider")
    with pytest.raises(LearningError, match="exact source blueprint"):
        lifecycle.decide(
            history.snapshot.id,
            account=actor,
            action="production_approval",
            reason="Wrong source.",
            key=str(uuid4()),
            expected_revision=2,
            reviewed_blueprint_sha256="f" * 64,
        )
    assert lifecycle.get(history.snapshot.id).review_status == "reviewed"


@pytest.mark.parametrize("review_first", [False, True])
def test_explicit_human_rejection_preserves_prior_receipts_and_never_releases(review_first):
    lifecycle, _, history = validated_history()
    actor = admin()
    if review_first:
        lifecycle.decide(
            history.snapshot.id,
            account=actor,
            action="human_review",
            reason="Review.",
            key=str(uuid4()),
            expected_revision=1,
        )
        history = lifecycle.get(history.snapshot.id)
    rejection = lifecycle.decide(
        history.snapshot.id,
        account=actor,
        action="reject",
        reason="Requires revised educational content.",
        key=str(uuid4()),
        expected_revision=history.revision,
    )
    result = lifecycle.get(history.snapshot.id)
    assert result.events[:-1] == history.events
    assert result.state == result.review_status == "rejected"
    assert rejection.actor_id == str(actor.id) and result.release_eligible is False


def test_actual_gate_failure_is_a_durable_technical_rejection_not_human_approval():
    class FailedRuntime:
        def validate(self, definition):
            return RuntimeValidationReport(
                status="failed",
                code=CandidateValidationCode.RUNTIME_EXECUTION_FAILED,
                performed=False,
                completed=False,
            )

    lifecycle, _ = service(CandidateValidationService(FailedRuntime()))
    history = lifecycle.create(**inputs())
    event = lifecycle.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)
    assert event.state == "rejected" and event.validation.status == "runtime_failed"
    assert event.actor_id is None and lifecycle.get(history.snapshot.id).review_status == "rejected"


def test_missing_candidate_cannot_be_returned_or_validated_as_a_success():
    lifecycle, _ = service()
    with pytest.raises(LearningError, match="Candidate not found") as exc:
        lifecycle.get(str(uuid4()))
    assert exc.value.code == "not_found"


def test_missing_storage_during_gate_work_cannot_create_an_orphan_finalization():
    lifecycle, repo = service()
    history = lifecycle.create(**inputs())
    original = lifecycle.validator

    class StorageDisappeared:
        def validate(self, *args, **kwargs):
            receipt = original.validate(*args, **kwargs)
            repo.store.rows.pop(
                history.snapshot.id
            )  # Injected store failure, not real database deletion.
            return receipt

    lifecycle.validator = StorageDisappeared()
    with pytest.raises(LearningError, match="Candidate not found"):
        lifecycle.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)
    assert not repo.store.rows


def test_exact_validation_retry_winning_during_gate_work_returns_its_original_receipt():
    lifecycle, _ = service()
    history = lifecycle.create(**inputs())
    original = lifecycle.validator
    key = str(uuid4())
    winner = []

    class ConcurrentWinner:
        def validate(self, *args, **kwargs):
            receipt = original.validate(*args, **kwargs)
            lifecycle.validator = original
            winner.append(lifecycle.validate(history.snapshot.id, key=key, expected_revision=0))
            return receipt

    lifecycle.validator = ConcurrentWinner()
    returned = lifecycle.validate(history.snapshot.id, key=key, expected_revision=0)
    assert returned == winner[0] and len(lifecycle.get(history.snapshot.id).events) == 2


@pytest.mark.parametrize("action", ["created", "validation"])
def test_human_decision_operation_cannot_forge_system_lifecycle_actions(action):
    lifecycle, _, history = validated_history()
    with pytest.raises(LearningError, match="explicit human review"):
        lifecycle.decide(
            history.snapshot.id,
            account=admin(),
            action=action,
            reason="Not a human decision.",
            key=str(uuid4()),
            expected_revision=1,
        )
