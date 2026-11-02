"""Real SQLite changes cannot escape the feedback release authorization fence."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from app.ai.providers.fake import FakeTutorProvider
from app.ai.providers.fake_evidence_feedback import FakeEvidenceFeedbackProvider
from app.db import models as m
from app.db.accounts import SqlAccountRepository
from app.db.feedback_release import SqlFeedbackReleaseRepository
from app.db.learning import SqlLearningRepository
from app.domain.accounts import Principal, VerifiedIdentity
from app.domain.learning import LearningError
from app.schemas.evidence_feedback import FeedbackCompletion
from app.schemas.feedback_release import FeedbackReleaseScope
from app.services.accounts import AccountService
from app.services.catalog import LESSON_ID, seed_first_lesson
from app.services.evidence_feedback import EvidenceFeedbackService
from app.services.feedback_release import FeedbackReleaseService
from app.services.identity import credential_digest
from app.services.learning import LearningService
from app.services.verification import VerificationService
from app.verification.asgi_notes import AsgiNotesVerifier
from tests.integration.test_tutor_transactions import BlockingTutor

OUTCOMES = ("mock", "timeout", "exception", "malformed", "disabled")


class ReleaseClock:
    def __init__(self):
        self.now = datetime.now(UTC) + timedelta(seconds=1)

    def __call__(self):
        return self.now

    def advance(self, seconds=1):
        self.now += timedelta(seconds=seconds)


class BlockingFeedback(FakeEvidenceFeedbackProvider):
    def __init__(self, outcome="mock"):
        super().__init__()
        self.outcome = outcome
        self.entered, self.release = Event(), Event()
        self.requests = []

    def explain(self, request):
        self.requests.append(request)
        self.entered.set()
        if not self.release.wait(10):
            raise TimeoutError("Controlled feedback fixture deadline")
        if self.outcome == "timeout":
            raise TimeoutError("Controlled feedback fixture timeout")
        if self.outcome == "exception":
            raise RuntimeError("CONTROLLED_PRIVATE_PROVIDER_EXCEPTION")
        if self.outcome == "malformed":
            return FeedbackCompletion(status="success", text="not JSON", source="test_fixture")
        if self.outcome == "disabled":
            return FeedbackCompletion(
                status="unavailable", text=None, source="none", error_code="disabled"
            )
        return super().explain(request)


class BlockingVerifier:
    def __init__(self, repository, unavailable=False):
        self.real = AsgiNotesVerifier(repository, 5)
        self.unavailable = unavailable
        self.entered, self.release = Event(), Event()

    def observe(self, run_id, field):
        self.entered.set()
        if not self.release.wait(10):
            raise TimeoutError("Controlled verification fixture deadline")
        if self.unavailable:
            raise RuntimeError("Controlled runtime dependency failure")
        return self.real.observe(run_id, field)


def explicit_test_scope():
    # Proposed test audience only; this does not approve or activate production feedback.
    return FeedbackReleaseScope(
        schema_version="feedback-release-scope-v1",
        allowed_modes=("account", "guest"),
        allow_terminal_reflection=False,
    )


def create_context(database, *, mode="guest", phase="failed"):
    clock = ReleaseClock()
    repository = SqlLearningRepository(database)
    seed_first_lesson(repository)
    accounts = AccountService(SqlAccountRepository(database), clock)
    raw = "controlled-release-guest-" + str(uuid4())
    if mode == "account":
        account = accounts.bootstrap(
            VerifiedIdentity(
                "https://controlled-issuer.invalid", str(uuid4()), clock() + timedelta(hours=1)
            )
        )
        owner = accounts.learner(account)
        principal = Principal(owner, clock() + timedelta(hours=1), account=account)
    else:
        with repository.write() as store:
            credential = store.create_identity(credential_digest(raw), clock() + timedelta(hours=1))
        owner = credential.learner_id
        principal = Principal(owner, credential.expires_at, credential=credential)
    learning = LearningService(repository, FakeTutorProvider(), clock)
    verification = VerificationService(repository, AsgiNotesVerifier(repository, 5), 5, clock=clock)
    session = learning.create_session(owner, LESSON_ID, "1.0.0", str(uuid4()))
    clock.advance()
    learning.predict(owner, session.id, "saved", "Controlled prediction.", str(uuid4()))
    submitted = None
    if phase != "prediction":
        clock.advance()
        submitted = learning.attempt(owner, session.id, "body", "Controlled attempt.", str(uuid4()))
        if phase == "failed":
            clock.advance()
            assert (
                verification.verify(owner, session.id, submitted.id, str(uuid4())).status
                == "failed"
            )
    clock.advance()
    return SimpleNamespace(
        database=database,
        clock=clock,
        repository=repository,
        accounts=accounts,
        raw=raw,
        owner=owner,
        principal=principal,
        learning=learning,
        verification=verification,
        session=session,
        submitted=submitted,
    )


def release_service(context, provider, repository=None):
    return FeedbackReleaseService(
        repository or SqlFeedbackReleaseRepository(context.database),
        EvidenceFeedbackService(context.repository, provider, context.clock),
        context.clock,
    )


def mutate_authorization(context, change):
    if change == "principal_expired":
        context.clock.now = context.principal.expires_at
    elif change == "claimed":
        account = context.accounts.bootstrap(
            VerifiedIdentity(
                "https://controlled-claim.invalid",
                str(uuid4()),
                context.clock() + timedelta(hours=1),
            )
        )
        assert context.accounts.claim(account, context.raw, str(uuid4())) == context.owner
    else:
        with context.database.session() as db, db.begin():
            if change == "disabled":
                db.execute(
                    update(m.User)
                    .where(m.User.id == context.principal.account.id)
                    .values(status="disabled")
                )
            elif change == "role_removed":
                db.execute(
                    delete(m.UserRole).where(
                        m.UserRole.user_id == context.principal.account.id,
                        m.UserRole.role == "learner",
                    )
                )
            elif change == "revoked":
                db.execute(
                    update(m.LearnerCredential)
                    .where(m.LearnerCredential.id == context.principal.credential.id)
                    .values(revoked_at=context.clock())
                )
            elif change == "expired":
                db.execute(
                    update(m.LearnerCredential)
                    .where(m.LearnerCredential.id == context.principal.credential.id)
                    .values(expires_at=context.clock())
                )
            else:
                raise AssertionError("Unknown controlled authorization mutation")


AUTH_CHANGES = (
    ("account", "disabled", "forbidden"),
    ("account", "role_removed", "forbidden"),
    ("guest", "revoked", "unauthenticated"),
    ("guest", "expired", "unauthenticated"),
    ("guest", "claimed", "unauthenticated"),
    ("guest", "principal_expired", "unauthenticated"),
    ("account", "principal_expired", "unauthenticated"),
)


@pytest.mark.parametrize("outcome", OUTCOMES)
@pytest.mark.parametrize(("mode", "change", "code"), AUTH_CHANGES)
def test_current_authorization_overrules_every_provider_outcome(
    database, outcome, mode, change, code
):
    context = create_context(database, mode=mode)
    provider = BlockingFeedback(outcome)
    service = release_service(context, provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            service.evaluate, context.principal, context.session.id, scope=explicit_test_scope()
        )
        try:
            assert provider.entered.wait(5)
            context.clock.advance()
            mutate_authorization(context, change)
        finally:
            provider.release.set()
        with pytest.raises(LearningError) as error:
            future.result(timeout=5)
    assert error.value.code == code
    assert len(provider.requests) == 1


@pytest.mark.parametrize(("mode", "change", "code"), AUTH_CHANGES)
def test_initial_current_authorization_failure_never_invokes_provider(database, mode, change, code):
    context = create_context(database, mode=mode)
    mutate_authorization(context, change)
    provider = BlockingFeedback()
    with pytest.raises(LearningError) as error:
        release_service(context, provider).evaluate(
            context.principal, context.session.id, scope=explicit_test_scope()
        )
    assert error.value.code == code and provider.requests == []


@pytest.mark.parametrize("outcome", OUTCOMES)
@pytest.mark.parametrize(
    "change", ("new_attempt", "new_run", "hint_request", "abandoned", "completed")
)
def test_post_cutoff_source_changes_reject_every_provider_outcome(database, outcome, change):
    context = create_context(database, phase="submitted" if change == "new_run" else "failed")
    provider = BlockingFeedback(outcome)
    service = release_service(context, provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            service.evaluate, context.principal, context.session.id, scope=explicit_test_scope()
        )
        try:
            assert provider.entered.wait(5)
            cutoff = provider.requests[0].evidence.query.as_of
            context.clock.advance()
            assert context.clock() > cutoff
            if change == "new_attempt":
                added = context.learning.attempt(
                    context.owner, context.session.id, "body", "", str(uuid4())
                )
                assert added.id not in {
                    o.source.record_id for o in provider.requests[0].evidence.observations
                }
            elif change == "new_run":
                run, _, _ = context.verification._reserve(
                    context.owner, context.session.id, context.submitted.id, str(uuid4())
                )
                assert run.status == "pending" and run.created_at > cutoff
            elif change == "hint_request":
                operation, _ = context.learning._reserve_hint(
                    context.owner, context.session.id, None, str(uuid4()), None
                )
                assert operation.status == "pending" and operation.created_at > cutoff
            elif change == "abandoned":
                assert (
                    context.learning.abandon(context.owner, context.session.id).state == "abandoned"
                )
            else:
                added = context.learning.attempt(
                    context.owner, context.session.id, "content", "", str(uuid4())
                )
                context.clock.advance()
                assert (
                    context.verification.verify(
                        context.owner, context.session.id, added.id, str(uuid4())
                    ).status
                    == "passed"
                )
        finally:
            provider.release.set()
        with pytest.raises(LearningError) as error:
            future.result(timeout=5)
    assert error.value.code == "feedback_changed"
    assert len(provider.requests) == 1


@pytest.mark.parametrize("outcome", OUTCOMES)
@pytest.mark.parametrize("runtime_status", ("failed", "error"))
def test_verification_finalization_after_cutoff_rejects_unchanged_window(
    database, outcome, runtime_status
):
    context = create_context(database, phase="submitted")
    verifier = BlockingVerifier(context.repository, unavailable=runtime_status == "error")
    verification = VerificationService(context.repository, verifier, 5, clock=context.clock)
    provider = BlockingFeedback(outcome)
    service = release_service(context, provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        verifying = pool.submit(
            verification.verify,
            context.owner,
            context.session.id,
            context.submitted.id,
            str(uuid4()),
        )
        try:
            assert verifier.entered.wait(5)
            context.clock.advance()
            future = pool.submit(
                service.evaluate, context.principal, context.session.id, scope=explicit_test_scope()
            )
            assert provider.entered.wait(5)
            cutoff = provider.requests[0].evidence.query.as_of
            context.clock.advance()
            verifier.release.set()
            finished = verifying.result(timeout=5)
            assert finished.status == runtime_status and finished.completed_at > cutoff
            if runtime_status == "error":
                assert (
                    context.learning.progress(context.owner, context.session.id).session.state
                    == "verification_pending"
                )
        finally:
            verifier.release.set()
            provider.release.set()
        with pytest.raises(LearningError) as error:
            future.result(timeout=5)
    assert error.value.code == "feedback_changed"


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_tutor_finalization_after_cutoff_rejects_unchanged_window(database, outcome):
    context = create_context(database)
    tutor = BlockingTutor()
    learning = LearningService(context.repository, tutor, context.clock)
    provider = BlockingFeedback(outcome)
    service = release_service(context, provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tutoring = pool.submit(learning.hint, context.owner, context.session.id, None, str(uuid4()))
        try:
            assert tutor.entered.wait(5)
            context.clock.advance()
            future = pool.submit(
                service.evaluate, context.principal, context.session.id, scope=explicit_test_scope()
            )
            assert provider.entered.wait(5)
            cutoff = provider.requests[0].evidence.query.as_of
            context.clock.advance()
            tutor.release.set()
            delivered = tutoring.result(timeout=5)
            assert delivered.status == "delivered" and delivered.created_at > cutoff
        finally:
            tutor.release.set()
            provider.release.set()
        with pytest.raises(LearningError) as error:
            future.result(timeout=5)
    assert error.value.code == "feedback_changed"


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_unrelated_write_commits_during_provider_and_valid_result_is_released(database, outcome):
    context = create_context(database)
    provider = BlockingFeedback(outcome)
    service = release_service(context, provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            service.evaluate, context.principal, context.session.id, scope=explicit_test_scope()
        )
        try:
            assert provider.entered.wait(5)
            with context.repository.write() as store:
                unrelated = store.create_identity(
                    credential_digest("controlled unrelated guest"),
                    context.clock() + timedelta(hours=1),
                )
            with database.session() as db:
                assert (
                    db.scalar(select(m.Learner.id).where(m.Learner.id == unrelated.learner_id))
                    is not None
                )
        finally:
            provider.release.set()
        result = future.result(timeout=5)
    assert result.reply is not None
    assert result.reply.delivery == ("mock" if outcome == "mock" else "deterministic")
    assert len(provider.requests) == 1


@pytest.mark.parametrize("path", ("not_ready", "source_unavailable"))
def test_no_provider_path_still_requires_current_release_authorization(database, monkeypatch, path):
    context = create_context(database, phase="prediction" if path == "not_ready" else "submitted")
    provider = BlockingFeedback()
    repository = SqlFeedbackReleaseRepository(database)

    class RevokeBeforeRelease:
        reads = 0

        @contextmanager
        def read(self, principal, session_id, now):
            self.reads += 1
            if self.reads == 2:
                mutate_authorization(context, "revoked")
            with repository.read(principal, session_id, now) as captured:
                yield captured

    if path == "source_unavailable":

        def unavailable(*_):
            raise LearningError("dependency_unavailable", "Controlled private source failure")

        monkeypatch.setattr(
            "app.services.engineering_evidence.EngineeringEvidenceService.extract", unavailable
        )
    with pytest.raises(LearningError) as error:
        release_service(context, provider, RevokeBeforeRelease()).evaluate(
            context.principal, context.session.id, scope=explicit_test_scope()
        )
    assert error.value.code == "unauthenticated" and provider.requests == []
