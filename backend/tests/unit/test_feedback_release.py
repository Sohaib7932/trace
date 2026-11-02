"""Immutable evaluation bindings and deterministic source/authorization fences."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.ai.providers.fake_evidence_feedback import FakeEvidenceFeedbackProvider
from app.domain.accounts import Account, Principal
from app.domain.learning import LearningError, NoteSnapshot, VerificationRun
from app.repositories.feedback_release import FeedbackReleaseRead
from app.schemas.evidence_feedback import FeedbackCompletion
from app.schemas.feedback_release import (
    FeedbackEvaluationEnvelope,
    FeedbackReleaseScope,
    FreshAuthorization,
    ReleasedFeedbackResult,
    SelectedRun,
    feedback_release_digest,
)
from app.services.evidence_feedback import EvidenceFeedbackService
from app.services.feedback_release import FeedbackReleaseService
from tests.feedback_fixtures import START, ReadOnlyRepository, at, feedback_source, identity
from tests.unit.test_engineering_evidence_sources import add_help
from tests.unit.test_evidence_feedback_policy import passing_notes, tasks


class Clock:
    def __init__(self):
        self.now = at(100)

    def __call__(self):
        return self.now


class Repository:
    def __init__(self, source):
        self.source, self.active, self.reads = source, 0, 0
        self.error = None
        self.identity = "a" * 64
        self.on_release = None
        self.deadline = None
        self.on_initial_exit = self.on_final_exit = None

    @contextmanager
    def read(self, principal, session_id, now):
        self.reads += 1
        if self.reads == 2 and self.on_release is not None:
            self.on_release()
        if self.error:
            raise LearningError(self.error, "Authorization is unavailable.")
        if principal.expires_at <= now or (self.deadline is not None and self.deadline <= now):
            raise LearningError("unauthenticated", "Authorization expired.")
        if (
            self.source.session.id != session_id
            or self.source.session.learner_id != principal.learner_id
        ):
            raise LearningError("not_found", "Session not found.")
        auth = FreshAuthorization(
            mode="account",
            learner_id=principal.learner_id,
            account_id=principal.account.id,
            credential_id=None,
            principal_expires_at=principal.expires_at,
            valid_until=self.deadline or principal.expires_at,
            identity_fingerprint=self.identity,
            observed_at=now,
        )
        self.active += 1
        try:
            # Model a transaction snapshot; no mutable source remains after exit.
            source = deepcopy(self.source)
            yield FeedbackReleaseRead(auth, source.session, source.lesson, source)
        finally:
            self.active -= 1
            hook = self.on_initial_exit if self.reads == 1 else self.on_final_exit
            if hook is not None:
                hook()


def setup(outcome=None):
    source = feedback_source()
    source.notes = lambda run_id: ()
    clock, repository = Clock(), Repository(source)
    principal = Principal(
        source.session.learner_id,
        at(1000),
        Account(identity("account"), START, "active", ("learner",)),
    )

    class Probe(FakeEvidenceFeedbackProvider):
        def explain(self, request):
            assert repository.active == 0
            return super().explain(request)

    provider = Probe(outcome)
    feedback = EvidenceFeedbackService(ReadOnlyRepository(source), provider, clock)
    service = FeedbackReleaseService(repository, feedback, clock)
    scope = FeedbackReleaseScope(allowed_modes=("account", "guest"), allow_terminal_reflection=True)
    return source, repository, principal, clock, provider, service, scope


def evaluate(context):
    source, _, principal, _, _, service, scope = context
    return service.evaluate(principal, source.session.id, scope=scope)


def test_exact_server_owned_envelope_and_release_bind_the_same_canonical_bundle():
    context = setup()
    source, repository, principal, clock, provider, _, _ = context
    result = evaluate(context)
    envelope = result.envelope
    assert repository.reads == 2 and repository.active == 0 and len(provider.calls) == 1
    assert result.reply.delivery == "mock" and envelope.availability == "evaluated"
    assert envelope.authorization.learner_id == principal.learner_id
    assert envelope.cutoff == clock() == result.released_at
    assert envelope.session.session_id == source.session.id
    assert envelope.plan.evidence == envelope.evidence
    assert envelope.evidence.query.max_records == 64
    assert envelope.cohort_fingerprint == feedback_release_digest(envelope.evidence)
    assert envelope.scope_fingerprint == feedback_release_digest(envelope.scope)
    assert envelope.selected_attempt.attempt_id == source.saved_attempts[0].id
    assert envelope.selected_run.run_id == source.saved_runs[0].id
    assert envelope.selected_run.status == "failed"
    assert ReleasedFeedbackResult.model_validate(result.model_dump()) == result


@pytest.mark.parametrize("selected", [None, "saved", "rejected"])
def test_preattempt_gate_never_extracts_or_calculates_accuracy_or_calls_provider(
    selected, monkeypatch
):
    context = setup()
    source, repository, _, _, provider, _, _ = context
    source.saved_attempts, source.saved_runs, source.saved_checks = [], [], []
    source.saved_prediction = (
        None if selected is None else replace(source.saved_prediction, selected_answer=selected)
    )
    monkeypatch.setattr(
        "app.services.feedback_release.EngineeringEvidenceService.extract",
        lambda *_: pytest.fail("A closed stage gate must not calculate prediction correctness"),
    )
    result = evaluate(context)
    assert result.envelope.availability == "not_ready" and result.reply is None
    assert result.envelope.evidence is result.envelope.plan is None
    assert repository.reads == 2 and not provider.calls


@pytest.mark.parametrize("disabled", ["mode", "terminal", "unsupported_version"])
def test_disabled_and_unapproved_paths_never_invoke_provider(disabled):
    context = list(setup())
    source = context[0]
    if disabled == "mode":
        context[6] = FeedbackReleaseScope.disabled()
    elif disabled == "terminal":
        source.session = replace(source.session, state="abandoned")
        context[6] = FeedbackReleaseScope(
            allowed_modes=("account",), allow_terminal_reflection=False
        )
    else:
        source.lesson = replace(source.lesson, version="1.1.0")
    result = evaluate(context)
    assert result.envelope.availability == "not_supported" and result.reply is None
    assert context[1].reads == 2 and not context[4].calls


@pytest.mark.parametrize("bad", ["digest", "public", "attempt_provenance", "runtime"])
def test_source_unavailability_is_fenced_and_has_no_conclusions_or_provider_call(bad):
    context = setup()
    source = context[0]
    if bad == "digest":
        source.lesson = replace(source.lesson, content_hash="0" * 64)
    elif bad == "public":
        source.lesson = replace(
            source.lesson, public_content={**source.lesson.public_content, "title": "changed"}
        )
    elif bad == "attempt_provenance":
        source.saved_attempts[0] = replace(source.saved_attempts[0], number=True)
    else:
        source.saved_checks[0] = replace(source.saved_checks[0], observed="not a status")
    result = evaluate(context)
    assert result.envelope.availability == "unavailable"
    assert result.reply.state == "unavailable" and result.reply.sections == ()
    assert result.reply.evidence_references == () and not context[4].calls
    assert context[1].reads == 2


@pytest.mark.parametrize(
    "outcome",
    [
        TimeoutError("fixture timeout"),
        RuntimeError("fixture exception"),
        FeedbackCompletion(status="success", source="test_fixture", text="{"),
        FeedbackCompletion(status="unavailable", source="none", text=None, error_code="disabled"),
    ],
)
def test_provider_failures_have_whole_policy_fallback_only_after_fresh_release(outcome):
    context = setup(outcome)
    result = evaluate(context)
    assert result.reply.delivery == "deterministic"
    assert result.reply.state == "supported" and result.reply.fallback_reason is not None
    assert len(context[4].calls) == 1 and context[1].reads == 2


@pytest.mark.parametrize(
    "outcome",
    [
        None,
        TimeoutError("fixture"),
        RuntimeError("fixture"),
        FeedbackCompletion(status="success", source="test_fixture", text="{"),
    ],
)
@pytest.mark.parametrize("code", ["unauthenticated", "forbidden", "not_found"])
def test_final_authorization_failure_overrides_every_provider_or_fallback_result(outcome, code):
    context = setup(outcome)
    context[1].on_release = lambda: setattr(context[1], "error", code)
    with pytest.raises(LearningError) as error:
        evaluate(context)
    assert error.value.code == code and len(context[4].calls) == 1


@pytest.mark.parametrize("path", ["pre_ready", "disabled", "unavailable"])
def test_no_provider_paths_still_require_final_current_authorization(path):
    context = list(setup())
    if path == "pre_ready":
        context[0].saved_attempts, context[0].saved_runs, context[0].saved_checks = [], [], []
    elif path == "disabled":
        context[6] = FeedbackReleaseScope.disabled()
    else:
        context[0].lesson = replace(context[0].lesson, content_hash="0" * 64)
    context[1].on_release = lambda: setattr(context[1], "error", "unauthenticated")
    with pytest.raises(LearningError) as error:
        evaluate(context)
    assert error.value.code == "unauthenticated" and not context[4].calls


@pytest.mark.parametrize(
    "mutation",
    [
        "session_owner",
        "session_pin",
        "lesson_hash",
        "terminal",
        "new_attempt",
        "pending_run",
        "run_finalized",
        "check_values",
        "runtime_row",
        "prediction",
        "private_reasoning",
        "identity",
    ],
)
def test_current_head_rejects_mutations_even_when_the_old_cutoff_hides_new_events(mutation):
    context = setup()
    source, repository, _, clock, provider, _, _ = context

    def mutate():
        clock.now = at(102)
        if mutation == "session_owner":
            source.session = replace(source.session, learner_id=identity("other-owner"))
        elif mutation == "session_pin":
            source.session = replace(source.session, lesson_version_id=identity("other-version"))
        elif mutation == "lesson_hash":
            source.lesson = replace(source.lesson, content_hash="f" * 64)
        elif mutation == "terminal":
            source.session = replace(source.session, state="abandoned")
        elif mutation == "new_attempt":
            source.saved_attempts.append(
                replace(
                    source.saved_attempts[0],
                    id=identity("new-attempt"),
                    number=2,
                    created_at=at(101),
                )
            )
        elif mutation == "pending_run":
            source.saved_runs.append(
                VerificationRun(
                    identity("pending"),
                    source.session.id,
                    source.saved_attempts[0].id,
                    "pending",
                    "pending-key",
                    at(101),
                )
            )
        elif mutation == "run_finalized":
            source.saved_runs[0] = replace(
                source.saved_runs[0], status="error", completed_at=at(101)
            )
        elif mutation == "check_values":
            source.saved_checks[0] = replace(
                source.saved_checks[0], expected="changed private expectation"
            )
        elif mutation == "runtime_row":
            source.notes = lambda _: (NoteSnapshot(identity("new-row"), "private", "payload"),)
        elif mutation == "prediction":
            source.saved_prediction = replace(source.saved_prediction, selected_answer="saved")
        elif mutation == "private_reasoning":
            source.saved_prediction = replace(
                source.saved_prediction, reasoning="changed raw source"
            )
        else:
            repository.identity = "b" * 64

    repository.on_release = mutate
    with pytest.raises(LearningError) as error:
        evaluate(context)
    assert error.value.code == ("not_found" if mutation == "session_owner" else "feedback_changed")
    assert len(provider.calls) == 1


def test_pending_hint_finalization_changes_source_head_even_outside_the_cutoff():
    context = setup()
    source, repository, _, clock, _, _, _ = context
    add_help(source, "pending")

    def mutate():
        clock.now = at(102)
        operation = source.saved_operations[0]
        source.saved_operations[0] = replace(operation, status="finalized", completed_at=at(101))
        from app.domain.learning import TutorInteraction

        source.saved_hints.append(
            TutorInteraction(
                operation.id,
                source.session.id,
                operation.attempt_id,
                operation.sequence,
                "PRIVATE_HINT_TEXT",
                "delivered",
                operation.idempotency_key,
                at(101),
            )
        )

    repository.on_release = mutate
    with pytest.raises(LearningError, match="Feedback changed"):
        evaluate(context)


def test_source_order_and_later_authorization_observation_do_not_false_invalidate():
    context = setup()
    source, repository, _, clock, _, _, _ = context
    passing_notes(source, retain_failure=True)

    def reorder():
        clock.now = at(101)
        source.saved_attempts.reverse()
        source.saved_runs.reverse()
        source.saved_checks.reverse()

    repository.on_release = reorder
    result = evaluate(context)
    assert result.reply.state == "supported" and result.released_at > result.envelope.cutoff
    assert result.released_authorization.observed_at == result.envelope.cutoff
    assert result.released_at == at(101)


@pytest.mark.parametrize("stage", ["initial", "final"])
@pytest.mark.parametrize(
    "outcome",
    [
        None,
        TimeoutError("fixture"),
        RuntimeError("fixture"),
        FeedbackCompletion(status="success", source="test_fixture", text="{"),
    ],
)
def test_known_authorization_deadline_cannot_expire_during_a_source_audit(stage, outcome):
    context = setup(outcome)
    repository, clock, provider = context[1], context[3], context[4]
    repository.deadline = at(101)

    def hook():
        clock.now = at(102)

    if stage == "initial":
        repository.on_initial_exit = hook
    else:
        repository.on_final_exit = hook
    with pytest.raises(LearningError) as error:
        evaluate(context)
    assert error.value.code == "unauthenticated"
    assert len(provider.calls) == (0 if stage == "initial" else 1)


@pytest.mark.parametrize("expire_during_validation", [False, True])
def test_known_deadline_is_checked_again_after_released_result_binding_validation(
    monkeypatch, expire_during_validation
):
    context = setup()
    repository, clock = context[1], context[3]
    repository.deadline = at(101)
    original = ReleasedFeedbackResult.model_validate

    def validate(*args, **kwargs):
        result = original(*args, **kwargs)
        if expire_during_validation:
            clock.now = at(102)
        return result

    monkeypatch.setattr(ReleasedFeedbackResult, "model_validate", validate)
    if expire_during_validation:
        with pytest.raises(LearningError) as error:
            evaluate(context)
        assert error.value.code == "unauthenticated"
    else:
        result = evaluate(context)
        assert result.released_at == at(100)
        assert result.released_authorization.valid_until == at(101)
    assert repository.active == 0 and repository.reads == 2
    assert len(context[4].calls) == 1


@pytest.mark.parametrize("pending", [False, True])
def test_unexecuted_or_pending_selected_attempt_does_not_invent_a_finished_result(pending):
    context = setup()
    source = context[0]
    source.saved_checks = []
    source.saved_runs = (
        [replace(source.saved_runs[0], status="pending", completed_at=None)] if pending else []
    )
    result = evaluate(context)
    assert result.reply.state == "partially_supported"
    assert (result.envelope.selected_run is not None) == pending
    if pending:
        assert result.envelope.selected_run.status == "pending"
    assert not any(
        item.claim_id.startswith("verification-")
        for section in result.reply.sections
        for item in section.items
    )


def test_record_budget_overflow_returns_only_a_release_authorized_unavailable_result():
    context = setup()
    source = context[0]
    original = source.saved_attempts[0]
    source.saved_attempts = [
        replace(
            original,
            id=identity(f"bounded-{number}"),
            number=number,
            idempotency_key=f"bounded-{number}",
            created_at=at(3 + number / 100),
        )
        for number in range(1, 66)
    ]
    source.saved_runs[0] = replace(source.saved_runs[0], attempt_id=source.saved_attempts[0].id)
    result = evaluate(context)
    assert result.envelope.availability == "unavailable"
    assert result.reply.sections == result.reply.evidence_references == ()
    assert context[1].reads == 2 and not context[4].calls


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_attempt",
        "missing_run",
        "wrong_attempt",
        "attempt_time",
        "run_id",
        "run_status",
        "run_time",
    ],
)
def test_selected_metadata_cannot_override_canonical_facts_even_with_recomputed_hash(mutation):
    result = evaluate(setup())
    body = result.envelope.model_dump(warnings=False)
    if mutation == "missing_attempt":
        body["selected_attempt"] = body["selected_run"] = None
    elif mutation == "missing_run":
        body["selected_run"] = None
    elif mutation == "wrong_attempt":
        body["selected_attempt"]["attempt_id"] = identity("unrelated-attempt")
    elif mutation == "attempt_time":
        body["selected_attempt"]["created_at"] = at(4)
    elif mutation == "run_id":
        body["selected_run"]["run_id"] = identity("unrelated-run")
    elif mutation == "run_status":
        body["selected_run"]["status"] = "passed"
    else:
        body["selected_run"]["completed_at"] = at(6)
    body["envelope_fingerprint"] = feedback_release_digest(
        {key: value for key, value in body.items() if key != "envelope_fingerprint"}
    )
    with pytest.raises(ValidationError):
        FeedbackEvaluationEnvelope.model_validate(body)


@pytest.mark.parametrize("mutation", ["wording", "state", "drop_claim", "citation"])
def test_rehashed_plans_cannot_authorize_claims_outside_the_existing_deterministic_policy(mutation):
    result = evaluate(setup())
    body = result.envelope.model_dump(warnings=False)
    plan = body["plan"]
    if mutation == "wording":
        plan["claims"][0]["wordings"][0]["text"] = "Unsupported mastery and private answer."
    elif mutation == "state":
        plan["state"] = "partially_supported"
    elif mutation == "drop_claim":
        plan["claims"] = plan["claims"][1:]
    else:
        plan["claims"][0]["evidence_ids"] = plan["claims"][1]["evidence_ids"]
    body["envelope_fingerprint"] = feedback_release_digest(
        {key: value for key, value in body.items() if key != "envelope_fingerprint"}
    )
    with pytest.raises(ValidationError):
        FeedbackEvaluationEnvelope.model_validate(body)


@pytest.mark.parametrize(
    "mutation", ["cutoff", "owner", "scope", "cohort", "source", "reply", "release"]
)
def test_forged_nested_or_copied_internal_results_fail_cross_binding_validation(mutation):
    result = evaluate(setup())
    envelope = result.envelope
    if mutation == "cutoff":
        envelope = envelope.model_copy(update={"cutoff": at(101)})
    elif mutation == "owner":
        envelope = envelope.model_copy(
            update={
                "authorization": envelope.authorization.model_copy(
                    update={"learner_id": identity("other")}
                )
            }
        )
    elif mutation == "scope":
        envelope = envelope.model_copy(update={"scope": FeedbackReleaseScope.disabled()})
    elif mutation == "cohort":
        envelope = envelope.model_copy(update={"cohort_fingerprint": "0" * 64})
    elif mutation == "source":
        envelope = envelope.model_copy(update={"source_fingerprint": "0" * 64})
    if mutation == "reply":
        item = result.reply.sections[0].items[0].model_copy(update={"text": "Invented competence."})
        section = result.reply.sections[0].model_copy(update={"items": (item,)})
        result = result.model_copy(
            update={
                "reply": result.reply.model_copy(
                    update={"sections": (section, *result.reply.sections[1:])}
                )
            }
        )
    elif mutation == "release":
        result = result.model_copy(update={"released_at": at(101)})
    result = result.model_copy(update={"envelope": envelope})
    with pytest.raises(ValidationError):
        ReleasedFeedbackResult.model_validate(result.model_dump(warnings=False))


@pytest.mark.parametrize("modes", [("account", "account"), ("unknown",)])
def test_scope_rejects_duplicate_or_unsupported_modes(modes):
    with pytest.raises(ValidationError):
        FeedbackReleaseScope(allowed_modes=modes, allow_terminal_reflection=False)


def test_fingerprint_encoding_is_canonical_and_never_accepts_opaque_values():
    shifted = at(3).astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert feedback_release_digest({"b": at(3), "a": UUID(int=1)}) == feedback_release_digest(
        {"a": UUID(int=1), "b": shifted}
    )
    with pytest.raises(ValueError):
        feedback_release_digest({"opaque": object()})
    with pytest.raises(ValueError):
        feedback_release_digest({1: "non-string key"})


def rehash(body, field):
    body[field] = feedback_release_digest(
        {key: value for key, value in body.items() if key != field}
    )
    return body


def gate_result(gate):
    context = list(setup())
    if gate == "not_ready":
        context[0].saved_attempts, context[0].saved_runs, context[0].saved_checks = [], [], []
    elif gate == "not_supported":
        context[6] = FeedbackReleaseScope.disabled()
    elif gate == "unavailable":
        context[0].lesson = replace(context[0].lesson, content_hash="0" * 64)
    return evaluate(context)


@pytest.mark.parametrize("mutation", ["expired", "beyond_principal", "mode", "both", "neither"])
def test_current_auth_observation_rejects_impossible_deadlines_and_mode_identity_pairs(mutation):
    body = evaluate(setup()).envelope.authorization.model_dump(warnings=False)
    if mutation == "expired":
        body["valid_until"] = body["observed_at"]
    elif mutation == "beyond_principal":
        body["valid_until"] = body["principal_expires_at"] + timedelta(seconds=1)
    elif mutation == "mode":
        body["mode"] = "guest"
    elif mutation == "both":
        body["credential_id"] = identity("foreign-credential")
    else:
        body["account_id"] = None
    with pytest.raises(ValidationError, match="unexpired|authentication mode"):
        FreshAuthorization.model_validate(body)


@pytest.mark.parametrize("mutation", ["pending_finished", "final_missing_time", "backdated_finish"])
def test_selected_run_cannot_forge_finalization_state_or_chronology(mutation):
    body = evaluate(setup()).envelope.selected_run.model_dump(warnings=False)
    if mutation == "pending_finished":
        body["status"] = "pending"
    elif mutation == "final_missing_time":
        body["completed_at"] = None
    else:
        body["completed_at"] = body["created_at"] - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="finalization|before it was created"):
        SelectedRun.model_validate(body)


@pytest.mark.parametrize(
    "mutation",
    [
        "lesson_pin",
        "public_pair",
        "missing_plan",
        "closed_plan",
        "closed_evidence",
        "no_cohort",
        "future_selected_attempt",
        "foreign_selected_run",
        "server_limit",
        "server_start",
        "server_as_of",
    ],
)
def test_rehashed_envelope_cannot_change_pins_gates_or_server_owned_evidence_scope(mutation):
    original = evaluate(setup())
    body = original.envelope.model_dump(warnings=False)
    if mutation == "lesson_pin":
        body["session"]["lesson_version_id"] = identity("unrelated-version")
    elif mutation == "public_pair":
        body["public_content"] = None
    elif mutation == "missing_plan":
        body["plan"] = None
    elif mutation == "closed_plan":
        closed = gate_result("not_supported").envelope.model_dump(warnings=False)
        closed["plan"] = body["plan"]
        body = closed
    elif mutation == "closed_evidence":
        body["availability"], body["plan"] = "not_ready", None
    elif mutation == "no_cohort":
        body = gate_result("not_ready").envelope.model_dump(warnings=False)
        body["cohort_fingerprint"] = "0" * 64
    elif mutation in {"future_selected_attempt", "foreign_selected_run"}:
        unsupported = gate_result("unavailable").envelope.model_dump(warnings=False)
        unsupported["selected_attempt"] = body["selected_attempt"]
        if mutation == "future_selected_attempt":
            unsupported["selected_attempt"]["created_at"] = unsupported["cutoff"]
        else:
            unsupported["selected_run"] = body["selected_run"]
            unsupported["selected_run"]["attempt_id"] = identity("another-attempt")
        body = unsupported
    else:
        field, value = {
            "server_limit": ("max_records", 63),
            "server_start": ("start_at", at(0.5)),
            "server_as_of": ("as_of", at(101)),
        }[mutation]
        body["evidence"]["query"][field] = value
        body["cohort_fingerprint"] = feedback_release_digest(body["evidence"])
    with pytest.raises(ValidationError) as error:
        FeedbackEvaluationEnvelope.model_validate(rehash(body, "envelope_fingerprint"))
    assert "envelope fingerprint does not match" not in str(error.value)


def test_unexecuted_cohort_cannot_be_relabelled_with_an_unobserved_passing_run():
    context = setup()
    original_run = context[0].saved_runs[0]
    context[0].saved_runs, context[0].saved_checks = [], []
    body = evaluate(context).envelope.model_dump(warnings=False)
    body["selected_run"] = {
        "run_id": original_run.id,
        "attempt_id": original_run.attempt_id,
        "status": "passed",
        "created_at": original_run.created_at,
        "completed_at": original_run.completed_at,
    }
    with pytest.raises(ValidationError, match="requires its canonical observation"):
        FeedbackEvaluationEnvelope.model_validate(rehash(body, "envelope_fingerprint"))


@pytest.mark.parametrize(
    "mutation",
    [
        "identity",
        "mode",
        "observed_before_cutoff",
        "decision_before_read",
        "expired_receipt",
        "missing_reply",
        "request_replay",
        "session_replay",
        "state",
        "source_reference",
        "wording",
    ],
)
def test_rehashed_release_receipts_cannot_replay_identity_or_override_canonical_claims(mutation):
    body = evaluate(setup()).model_dump(warnings=False)
    if mutation == "identity":
        body["released_authorization"]["identity_fingerprint"] = "b" * 64
    elif mutation == "mode":
        auth = body["released_authorization"]
        auth["mode"], auth["account_id"], auth["credential_id"] = "guest", None, identity("guest")
    elif mutation == "observed_before_cutoff":
        body["released_authorization"]["observed_at"] = at(99)
    elif mutation == "decision_before_read":
        body["released_at"] = at(99)
    elif mutation == "expired_receipt":
        body["released_at"] = body["released_authorization"]["valid_until"]
    elif mutation == "missing_reply":
        body["reply"] = None
    elif mutation == "request_replay":
        body["reply"]["request_id"] = identity("another-request")
    elif mutation == "session_replay":
        body["reply"]["session_id"] = identity("another-session")
    elif mutation == "state":
        body["reply"]["state"] = "partially_supported"
    elif mutation == "source_reference":
        body["reply"]["evidence_references"][0]["sources"][0]["record_id"] = identity(
            "foreign-record"
        )
    else:
        body["reply"]["sections"][0]["items"][0]["text"] = "An unsupported competence conclusion."
    with pytest.raises(ValidationError) as error:
        ReleasedFeedbackResult.model_validate(rehash(body, "release_fingerprint"))
    assert "Released result fingerprint does not match" not in str(error.value)


@pytest.mark.parametrize("gate", ["not_ready", "not_supported", "unavailable"])
def test_closed_or_unavailable_release_cannot_replay_a_previous_graded_reply(gate):
    closed = gate_result(gate).model_dump(warnings=False)
    reply = evaluate(setup()).reply.model_dump(warnings=False)
    reply["request_id"] = closed["envelope"]["request_id"]
    reply["session_id"] = closed["envelope"]["session"]["session_id"]
    closed["reply"] = reply
    with pytest.raises(
        ValidationError, match="cannot contain feedback|cannot produce feedback conclusions"
    ):
        ReleasedFeedbackResult.model_validate(rehash(closed, "release_fingerprint"))


@pytest.mark.parametrize(
    "corruption",
    ["version_mismatch", "tasks_private_binding", "missing_prediction", "foreign_prediction"],
)
def test_untrusted_definition_or_attempt_provenance_is_unavailable_before_provider(corruption):
    context = setup()
    source = context[0]
    if corruption == "version_mismatch":
        source.lesson = replace(source.lesson, id=identity("wrong-version"))
    elif corruption == "tasks_private_binding":
        tasks(source)
        source.lesson = replace(source.lesson, expected_field="flat")
    elif corruption == "missing_prediction":
        source.saved_prediction = None
    else:
        source.saved_prediction = replace(
            source.saved_prediction, session_id=identity("foreign-session")
        )
    result = evaluate(context)
    assert result.envelope.availability == result.reply.state == "unavailable"
    assert result.reply.sections == () and context[4].calls == []
    assert context[1].reads == 2 and context[1].active == 0


@pytest.mark.parametrize("code", ["unauthenticated", "forbidden", "not_found"])
def test_initial_extractor_authorization_errors_cannot_be_masked_as_safe_feedback(
    monkeypatch, code
):
    context = setup()

    def denied(*_):
        raise LearningError(code, "CONTROLLED_SOURCE_AUTH_FAILURE")

    monkeypatch.setattr("app.services.feedback_release.EngineeringEvidenceService.extract", denied)
    with pytest.raises(LearningError) as error:
        evaluate(context)
    assert error.value.code == code and context[4].calls == []
    assert context[1].active == 0


@pytest.mark.parametrize(
    "code",
    [
        "evidence_integrity",
        "evidence_limit",
        "dependency_unavailable",
        "unauthenticated",
        "forbidden",
        "not_found",
        "wrong_cohort",
    ],
)
def test_final_extractor_faults_or_wrong_server_cohort_never_release_old_feedback(
    monkeypatch, code
):
    from app.schemas.engineering_evidence import EngineeringEvidenceBatch
    from app.services.engineering_evidence import EngineeringEvidenceService

    context = setup()
    original = EngineeringEvidenceService.extract
    calls = 0

    def checked(service, query):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(service, query)
        if code != "wrong_cohort":
            message = (
                "Authorization or session access is unavailable."
                if code in {"unauthenticated", "forbidden", "not_found"}
                else "PRIVATE_FINAL_SOURCE_ERROR"
            )
            raise LearningError(code, message)
        batch = original(service, query)
        changed = batch.model_dump(warnings=False)
        changed["query"]["max_records"] = 63
        return EngineeringEvidenceBatch.model_validate(changed)

    monkeypatch.setattr(EngineeringEvidenceService, "extract", checked)
    with pytest.raises(LearningError) as error:
        evaluate(context)
    assert error.value.code == (
        code if code in {"unauthenticated", "forbidden", "not_found"} else "feedback_changed"
    )
    assert "PRIVATE_" not in str(error.value)
    assert len(context[4].calls) == 1 and context[1].active == 0


@pytest.mark.parametrize("revoked", [False, True])
def test_failed_selected_source_resolution_still_requires_final_current_authorization(
    monkeypatch, revoked
):
    context = setup()

    def missing(*_):
        raise ValueError("PRIVATE_SELECTED_SOURCE_FAILURE")

    monkeypatch.setattr("app.services.feedback_release._selected", missing)
    if revoked:
        context[1].on_release = lambda: setattr(context[1], "error", "unauthenticated")
        with pytest.raises(LearningError) as error:
            evaluate(context)
        assert error.value.code == "unauthenticated"
    else:
        result = evaluate(context)
        assert result.reply.state == "unavailable" and result.reply.sections == ()
        assert "PRIVATE_SELECTED_SOURCE_FAILURE" not in result.model_dump_json()
    assert context[4].calls == [] and context[1].reads == 2


@pytest.mark.parametrize("bad_id", [None, 123, "00000000-0000-4000-8000-000000000001"])
def test_untyped_session_selectors_fail_before_any_repository_or_provider_read(bad_id):
    context = setup()
    with pytest.raises(ValueError, match="must be a UUID"):
        context[5].evaluate(context[2], bad_id, scope=context[6])
    assert context[1].reads == 0 and context[4].calls == []


def test_extractor_cannot_acquire_a_write_transaction_from_the_borrowed_read_port(monkeypatch):
    context = setup()

    def write_attempt(service, _query):
        with service.repository.write():
            pytest.fail("The read-only feedback port cannot open a write scope")

    monkeypatch.setattr(
        "app.services.feedback_release.EngineeringEvidenceService.extract", write_attempt
    )
    with pytest.raises(AssertionError, match="read-only"):
        evaluate(context)
    assert context[1].active == 0 and context[4].calls == []


def test_source_head_bound_never_truncates_large_histories_into_valid_feedback():
    context = setup()
    source = context[0]
    original = source.saved_attempts[0]
    source.saved_attempts = [
        original,
        *[
            replace(
                original,
                id=identity(f"head-limit-{number}"),
                number=number,
                idempotency_key=f"head-limit-{number}",
                created_at=at(3 + number / 10000),
            )
            for number in range(2, 10002)
        ],
    ]
    with pytest.raises(LearningError) as error:
        evaluate(context)
    assert error.value.code == "evidence_limit"
    assert context[1].active == 0 and context[4].calls == []


def test_opaque_repository_rows_are_not_serialized_as_authoritative_evidence():
    context = setup()
    context[0].saved_prediction = SimpleNamespace(private="PRIVATE_OPAQUE_ROW_CANARY")
    with pytest.raises(ValueError, match="detached repository records"):
        evaluate(context)
    assert context[1].active == 0 and context[4].calls == []
