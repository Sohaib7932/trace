"""Durable offline candidate review, not publication or learner assignment."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.db import models as m
from app.db.candidates import SqlCandidateRepository
from app.domain.learning import LearningError
from app.services.candidate_lifecycle import CandidateLifecycleService
from app.services.candidate_validation import CandidateValidationService
from app.verification.candidate_runtime import IsolatedCandidateRuntime
from tests.lifecycle_fixtures import NOW, admin, inputs


def lifecycle(database, runtime=True):
    return CandidateLifecycleService(
        SqlCandidateRepository(database),
        CandidateValidationService(IsolatedCandidateRuntime() if runtime else None),
        lambda: NOW,
    )


def persisted_admin(database):
    account = admin()
    with database.session() as session, session.begin():
        session.add(m.User(id=account.id, status="active", created_at=NOW, updated_at=NOW))
        session.flush()
        session.add(m.UserRole(user_id=account.id, role="admin"))
    return account


@pytest.mark.parametrize("family", ["notes-v1", "tasks-nested-v1"])
def test_actual_gate_receipt_persisted_separately_without_learner_records(database, family):
    service = lifecycle(database)
    case = inputs(family)
    created = service.create(**case)
    event = service.validate(created.snapshot.id, key=str(uuid4()), expected_revision=0)
    assert event.state == "validated" and event.validation.status == "validated"
    assert event.validation.runtime_verification_completed
    assert len(event.validation.runtime_evidence) == 2
    for profile in event.validation.runtime_evidence:
        assert len(profile.checks) == 5 and all(check.passed for check in profile.checks)
    reloaded = lifecycle(database).get(created.snapshot.id)
    assert reloaded.events == created.events + (event,)
    assert reloaded.state == "validated" and reloaded.review_status == "pending"
    assert reloaded.release_eligible is False
    with database.session() as session:
        for model in [
            m.Learner,
            m.LearningSession,
            m.Attempt,
            m.VerificationRun,
            m.RetrievalCheckpoint,
        ]:
            assert session.scalars(select(model)).all() == []


def test_duplicate_create_and_generation_request_identity_conflicts(database):
    service = lifecycle(database, runtime=False)
    case = inputs()
    history = service.create(**case)
    assert service.create(**case) == history
    other = inputs()
    other["generation_request_id"] = case["generation_request_id"]
    with pytest.raises(LearningError, match="immutable history"):
        service.create(**other)
    with database.session() as session:
        assert len(session.scalars(select(m.GeneratedCandidate)).all()) == 1
        assert len(session.scalars(select(m.CandidateLifecycleEvent)).all()) == 1


def test_unavailable_validation_retries_with_new_key_and_keeps_original_receipt(database):
    service = lifecycle(database, runtime=False)
    history = service.create(**inputs())
    key = str(uuid4())
    failed = service.validate(history.snapshot.id, key=key, expected_revision=0)
    assert failed.state == "validation_unavailable"
    service.validator = CandidateValidationService(IsolatedCandidateRuntime())
    assert service.validate(history.snapshot.id, key=key, expected_revision=0) == failed
    passed = service.validate(history.snapshot.id, key=str(uuid4()), expected_revision=1)
    assert passed.state == "validated" and passed.revision == 2
    assert service.get(history.snapshot.id).events[1] == failed


def test_review_and_approval_are_explicit_admin_steps_with_no_release(database):
    # This simulates a FUTURE trusted provider boundary in a disposable database.
    # No real provider or production approval is exercised by this test.
    service = lifecycle(database)
    actor = persisted_admin(database)
    history = service.create(**inputs(generation_origin="provider"))
    candidate_id = history.snapshot.id
    service.validate(candidate_id, key=str(uuid4()), expected_revision=0)
    review_key = str(uuid4())
    reviewed = service.decide(
        candidate_id,
        account=actor,
        action="human_review",
        reason="Explicit review.",
        key=review_key,
        expected_revision=1,
    )
    assert (
        service.decide(
            candidate_id,
            account=actor,
            action="human_review",
            reason="Explicit review.",
            key=review_key,
            expected_revision=1,
        )
        == reviewed
    )
    with pytest.raises(LearningError, match="exact source"):
        service.decide(
            candidate_id,
            account=actor,
            action="production_approval",
            reason="Approval.",
            key=str(uuid4()),
            expected_revision=2,
            reviewed_blueprint_sha256="f" * 64,
        )
    approved = service.decide(
        candidate_id,
        account=actor,
        action="production_approval",
        reason="Explicit approval.",
        key=str(uuid4()),
        expected_revision=2,
        reviewed_blueprint_sha256=history.snapshot.source_blueprint.content_sha256,
    )
    assert approved.state == "production_approved" and approved.release_eligible is False
    assert service.get(candidate_id).review_status == "approved"
    with database.session() as session:
        assert session.scalars(select(m.LessonVersion)).all() == []
        assert session.scalars(select(m.LearningSession)).all() == []


def test_mock_origin_cannot_be_promoted_even_after_human_review(database):
    service = lifecycle(database)
    actor = persisted_admin(database)
    history = service.create(**inputs())
    cid = history.snapshot.id
    service.validate(cid, key=str(uuid4()), expected_revision=0)
    service.decide(
        cid,
        account=actor,
        action="human_review",
        reason="Review.",
        key=str(uuid4()),
        expected_revision=1,
    )
    with pytest.raises(LearningError, match="Mock generation"):
        service.decide(
            cid,
            account=actor,
            action="production_approval",
            reason="Approval.",
            key=str(uuid4()),
            expected_revision=2,
            reviewed_blueprint_sha256=history.snapshot.source_blueprint.content_sha256,
        )
    assert service.get(cid).state == "human_reviewed"


@pytest.mark.parametrize(
    "provider",
    ["mock", "fake", "unconfigured", "fake-question-generator-test-fixture", "mock-script"],
)
def test_fixture_transport_cannot_attest_provider_origin(database, provider):
    service = lifecycle(database, runtime=False)
    case = inputs(generation_origin="provider")
    transport = case["completion"].transport.model_copy(
        update={
            "provider": case["completion"].transport.provider.model_copy(
                update={"provider_id": provider}
            ),
        }
    )
    case["completion"] = case["completion"].model_copy(update={"transport": transport})
    with pytest.raises(LearningError, match="Fixture transport"):
        service.create(**case)


def test_database_rechecks_admin_role_instead_of_trusting_forged_account_object(database):
    service = lifecycle(database)
    account = persisted_admin(database)
    history = service.create(**inputs())
    service.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0)
    with database.session() as session, session.begin():
        session.execute(delete(m.UserRole).where(m.UserRole.user_id == account.id))
    with pytest.raises(LearningError, match="active administrator"):
        service.decide(
            history.snapshot.id,
            account=account,
            action="human_review",
            reason="Review.",
            key=str(uuid4()),
            expected_revision=1,
        )


def test_concurrent_create_exact_retries_return_one_history(database):
    case = inputs()
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=5)
        return lifecycle(database, runtime=False).create(**case).snapshot.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: create(), range(2))) == [case["identity"].version_id] * 2
    with database.session() as session:
        assert len(session.scalars(select(m.GeneratedCandidate)).all()) == 1


def test_concurrent_validation_compare_and_swap_preserves_one_event(database):
    service = lifecycle(database, runtime=False)
    history = service.create(**inputs())
    barrier = Barrier(2)
    original = service.validator

    class BlockingGate:
        def validate(self, *args, **kwargs):
            barrier.wait(timeout=5)
            return original.validate(*args, **kwargs)

    def run():
        local = lifecycle(database, runtime=False)
        local.validator = BlockingGate()
        try:
            return local.validate(history.snapshot.id, key=str(uuid4()), expected_revision=0).state
        except LearningError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: run(), range(2))) == [
            "conflict",
            "validation_unavailable",
        ]
    assert len(service.get(history.snapshot.id).events) == 2


@pytest.mark.parametrize("model", [m.GeneratedCandidate, m.CandidateLifecycleEvent])
def test_candidate_history_is_append_only_in_sql(database, model):
    service = lifecycle(database, runtime=False)
    service.create(**inputs())
    for statement in [delete(model), update(model).values(release_eligible=False)]:
        with (
            pytest.raises(IntegrityError, match="history preserved"),
            database.session() as session,
            session.begin(),
        ):
            session.execute(statement)


def test_validation_receipt_cannot_be_supplied_or_forged_by_a_caller(database):
    service = lifecycle(database, runtime=False)
    history = service.create(**inputs())
    with pytest.raises(TypeError):
        service.validate(
            history.snapshot.id,
            key=str(uuid4()),
            expected_revision=0,
            receipt={"status": "validated"},
        )
    assert service.get(history.snapshot.id).state == "composed"


def test_corrupt_event_payload_disagreement_fails_closed_on_read(database):
    service = lifecycle(database, runtime=False)
    history = service.create(**inputs())
    with database.session() as session, session.begin():
        session.add(
            m.CandidateLifecycleEvent(
                id=uuid4(),
                candidate_id=UUID(history.snapshot.id),
                revision=1,
                operation_key=uuid4(),
                action="validation",
                previous_state="composed",
                state="validation_unavailable",
                actor_id=None,
                created_at=NOW,
                payload=history.events[0].model_dump(mode="json"),
                release_eligible=False,
            )
        )
    with pytest.raises(LearningError, match="event integrity"):
        service.get(history.snapshot.id)
