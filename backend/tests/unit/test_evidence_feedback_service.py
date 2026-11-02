"""Read-only feedback authorization, source failures and whole-response fallback."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.ai.providers.fake_evidence_feedback import FakeEvidenceFeedbackProvider
from app.domain.accounts import Account
from app.domain.learning import Credential, LearningError
from app.schemas.evidence_feedback import FeedbackCompletion
from app.services.evidence_feedback import EvidenceFeedbackService
from app.services.evidence_feedback_validation import render_feedback
from tests.feedback_fixtures import (
    START,
    ReadOnlyRepository,
    at,
    feedback_principal,
    feedback_query,
    feedback_request,
    feedback_source,
    identity,
)

PRIVATE = "SIMULATED_PRIVATE_BACKEND_DETAIL"


class MutableClock:
    def __init__(self):
        self.now = at(100)

    def __call__(self):
        return self.now


def setup(provider=None, repository=None):
    source = feedback_source()
    repository = repository or ReadOnlyRepository(source)
    provider = provider or FakeEvidenceFeedbackProvider()
    clock = MutableClock()
    return source, repository, provider, clock, EvidenceFeedbackService(repository, provider, clock)


def assert_same_authorized_content(reply, expected):
    assert reply.state == expected.state
    assert reply.request_id == expected.request_id
    assert reply.session_id == expected.session_id
    assert reply.lesson == expected.lesson
    assert reply.sections == expected.sections
    assert reply.evidence_references == expected.evidence_references
    assert reply.lesson_references == expected.lesson_references
    assert reply.coverage_references == expected.coverage_references


def assert_unavailable(reply, reason):
    assert reply.state == "unavailable" and reply.delivery == "unavailable"
    assert reply.fallback_reason == reason and reply.lesson is None
    assert reply.sections == reply.evidence_references == reply.lesson_references == ()
    assert reply.coverage_references == () and reply.notice
    assert PRIVATE not in reply.model_dump_json()


def test_real_extractor_and_policy_are_read_only_and_retry_is_idempotent():
    source, repository, provider, _, service = setup()
    query = feedback_query(source)
    principal = feedback_principal(source)
    original = service.feedback(principal, query)
    assert original.delivery == "mock" and original.fallback_reason is None
    assert service.feedback(principal, query) == original
    assert len(provider.calls) == 2 and repository.reads == 4
    assert provider.calls[0] == provider.calls[1]
    assert provider.calls[0] is not provider.calls[1]
    with pytest.raises(AssertionError, match="write transaction"):
        repository.write()


@pytest.mark.parametrize(
    "kind", ["expired", "exact_expiry", "naive_expiry", "missing_id", "wrong_id", "malformed"]
)
def test_invalid_authorization_never_reads_history_or_invokes_provider(kind):
    source, repository, provider, clock, service = setup()
    principal = feedback_principal(source)
    if kind == "expired":
        principal = replace(principal, expires_at=clock.now - timedelta(seconds=1))
    elif kind == "exact_expiry":
        principal = replace(principal, expires_at=clock.now)
    elif kind == "naive_expiry":
        principal = replace(principal, expires_at=clock.now.replace(tzinfo=None))
    elif kind == "missing_id":
        principal = replace(principal, learner_id=None)
    elif kind == "wrong_id":
        principal = replace(principal, learner_id="forged")
    else:
        principal = object()
    with pytest.raises(LearningError) as caught:
        service.feedback(principal, feedback_query(source))
    assert caught.value.code == "unauthenticated"
    assert repository.reads == 0 and provider.calls == []


@pytest.mark.parametrize("kind", ["foreign", "revoked", "expired", "naive", "malformed"])
def test_credential_must_belong_to_learner_and_remain_active(kind):
    source, repository, provider, clock, service = setup()
    credential = Credential(identity("credential"), source.session.learner_id, at(200), None)
    if kind == "foreign":
        credential = replace(credential, learner_id=identity("other-owner"))
    elif kind == "revoked":
        credential = replace(credential, revoked_at=at(1))
    elif kind == "expired":
        credential = replace(credential, expires_at=clock.now)
    elif kind == "naive":
        credential = replace(credential, expires_at=clock.now.replace(tzinfo=None))
    else:
        credential = object()
    principal = replace(feedback_principal(source), credential=credential)
    with pytest.raises(LearningError) as caught:
        service.feedback(principal, feedback_query(source))
    assert caught.value.code == "unauthenticated"
    assert repository.reads == 0 and provider.calls == []


@pytest.mark.parametrize(
    "status,code",
    [
        ("disabled", "forbidden"),
        ("deleted", "forbidden"),
        ("pending", "forbidden"),
        ("", "forbidden"),
        (None, "unauthenticated"),
        (False, "unauthenticated"),
    ],
)
def test_inactive_or_malformed_accounts_cannot_request_feedback(status, code):
    source, repository, provider, _, service = setup()
    account = Account(identity("account"), START, status, ("learner",))
    principal = replace(feedback_principal(source), account=account)
    with pytest.raises(LearningError) as caught:
        service.feedback(principal, feedback_query(source))
    assert caught.value.code == code
    assert repository.reads == 0 and provider.calls == []


def test_malformed_account_principal_is_rejected_without_raw_attribute_exception():
    source, repository, provider, _, service = setup()
    principal = replace(feedback_principal(source), account=object())
    with pytest.raises(LearningError) as caught:
        service.feedback(principal, feedback_query(source))
    assert caught.value.code in {"unauthenticated", "forbidden"}
    assert repository.reads == 0 and provider.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"max_records": True},
        {"max_records": 65},
        {"max_records": "4"},
        {"start_at": at(101)},
        {"end_at": at(100).replace(tzinfo=None)},
    ],
)
def test_forged_query_model_copy_is_revalidated_before_any_repository_read(changes):
    source, repository, provider, _, service = setup()
    query = feedback_query(source).model_copy(update=changes)
    with pytest.raises(ValidationError):
        service.feedback(feedback_principal(source), query)
    assert repository.reads == 0 and provider.calls == []


@pytest.mark.parametrize("kind", ["owner", "session"])
def test_cross_owner_and_unknown_sessions_propagate_not_found_without_provider(kind):
    source, _, provider, _, service = setup()
    principal, query = feedback_principal(source), feedback_query(source)
    if kind == "owner":
        principal = replace(principal, learner_id=identity("foreign-owner"))
    else:
        query = query.model_copy(update={"session_id": identity("missing-session")})
    with pytest.raises(LearningError) as caught:
        service.feedback(principal, query)
    assert caught.value.code == "not_found" and provider.calls == []


class FailingRepository:
    def __init__(self, source, code):
        self.source, self.code, self.reads = source, code, 0

    @contextmanager
    def read(self):
        self.reads += 1
        raise LearningError(self.code, PRIVATE)
        yield self.source

    def write(self):
        raise AssertionError("Feedback must never write")


@pytest.mark.parametrize(
    "code,reason",
    [
        ("dependency_unavailable", "source_unavailable"),
        ("evidence_integrity", "source_invalid"),
        ("evidence_limit", "context_limit"),
        ("conflict", "source_invalid"),
    ],
)
def test_source_read_failures_abstain_without_conclusions_or_private_details(code, reason):
    source = feedback_source()
    provider = FakeEvidenceFeedbackProvider()
    repository = FailingRepository(source, code)
    service = EvidenceFeedbackService(repository, provider, lambda: at(100))
    reply = service.feedback(feedback_principal(source), feedback_query(source))
    assert_unavailable(reply, reason)
    assert provider.calls == []


def test_real_extractor_limit_becomes_explicit_context_limit_abstention():
    source, _, provider, _, service = setup()
    reply = service.feedback(feedback_principal(source), feedback_query(source, max_records=1))
    assert_unavailable(reply, "context_limit")
    assert provider.calls == []


class PublicReadStore:
    def __init__(self, source, mutation):
        self.source, self.mutation = source, mutation

    def owned_session(self, owner, session_id):
        original = self.source.owned_session(owner, session_id)
        if self.mutation == "missing":
            return None
        if self.mutation == "foreign_owner":
            return replace(original, learner_id=identity("foreign-owner"))
        if self.mutation == "foreign_session":
            return replace(original, id=identity("foreign-session"))
        if self.mutation == "version_id":
            return replace(original, lesson_version_id=identity("wrong-version"))
        return original

    def version_by_id(self, version_id):
        original = self.source.version_by_id(version_id)
        if self.mutation == "content":
            return replace(
                original, public_content={**original.public_content, "scenario": PRIVATE}
            )
        if self.mutation == "digest":
            return replace(original, content_hash="f" * 64)
        if self.mutation == "version":
            return replace(original, version="9.0.0")
        if self.mutation == "lesson_id":
            return replace(original, lesson_id="forged-lesson")
        if self.mutation == "row_identity":
            return replace(original, id=identity("wrong-row"))
        return original


class ChangingPublicRepository(ReadOnlyRepository):
    def __init__(self, source, mutation):
        super().__init__(source)
        self.mutation = mutation

    @contextmanager
    def read(self):
        self.reads += 1
        yield self.store if self.reads == 1 else PublicReadStore(self.store, self.mutation)


@pytest.mark.parametrize(
    "mutation", ["content", "digest", "version", "lesson_id", "row_identity", "version_id"]
)
def test_public_lesson_is_reread_with_exact_pin_and_catalog_content(mutation):
    source = feedback_source()
    provider = FakeEvidenceFeedbackProvider()
    service = EvidenceFeedbackService(
        ChangingPublicRepository(source, mutation), provider, lambda: at(100)
    )
    reply = service.feedback(feedback_principal(source), feedback_query(source))
    assert_unavailable(reply, "source_invalid")
    assert provider.calls == []


@pytest.mark.parametrize("mutation", ["missing", "foreign_owner", "foreign_session"])
def test_second_public_read_cannot_cross_owner_or_session_scope(mutation):
    source = feedback_source()
    provider = FakeEvidenceFeedbackProvider()
    service = EvidenceFeedbackService(
        ChangingPublicRepository(source, mutation), provider, lambda: at(100)
    )
    if mutation == "missing":
        with pytest.raises(LearningError) as caught:
            service.feedback(feedback_principal(source), feedback_query(source))
        assert caught.value.code == "not_found"
    else:
        # A trusted adapter returning a foreign identity is source corruption,
        # rather than an ordinary absent row. Neither case reaches the provider.
        reply = service.feedback(feedback_principal(source), feedback_query(source))
        assert_unavailable(reply, "source_invalid")
    assert provider.calls == []


@pytest.mark.parametrize(
    "outcome,reason",
    [
        (TimeoutError(PRIVATE), "provider_timeout"),
        (RuntimeError(PRIVATE), "provider_exception"),
        (
            FeedbackCompletion(
                status="unavailable", text=None, source="none", error_code="disabled"
            ),
            "disabled",
        ),
        (
            FeedbackCompletion(status="refusal", text=None, source="test_fixture"),
            "provider_unavailable",
        ),
        (
            FeedbackCompletion(
                status="truncated", text='{"private":"' + PRIVATE, source="test_fixture"
            ),
            "provider_unavailable",
        ),
        (
            FeedbackCompletion(
                status="rate_limited", text=None, source="none", error_code="rate_limited"
            ),
            "provider_unavailable",
        ),
        (
            FeedbackCompletion(status="timeout", text=None, source="none", error_code="timeout"),
            "provider_timeout",
        ),
        (
            FeedbackCompletion(
                status="transport_error", text=None, source="none", error_code="transport_error"
            ),
            "provider_unavailable",
        ),
    ],
)
def test_provider_failures_render_a_whole_deterministic_response_with_original_citations(
    outcome, reason
):
    source, _, provider, _, service = setup(FakeEvidenceFeedbackProvider(outcome))
    expected = render_feedback(feedback_request(source))
    reply = service.feedback(feedback_principal(source), feedback_query(source))
    assert reply.delivery == "deterministic" and reply.fallback_reason == reason
    assert_same_authorized_content(reply, expected)
    assert len(provider.calls) == 1 and PRIVATE not in reply.model_dump_json()


@pytest.mark.parametrize(
    "completion",
    [
        FeedbackCompletion.model_construct(status="success", text=None, source="test_fixture"),
        FeedbackCompletion.model_construct(status="success", text="{}", source="ai"),
        FeedbackCompletion.model_construct(
            status="unavailable", text=None, source="none", error_code=PRIVATE
        ),
        FeedbackCompletion.model_construct(
            status="success", text="x" * 65537, source="test_fixture"
        ),
        FeedbackCompletion(status="success", text="not JSON " + PRIVATE, source="test_fixture"),
    ],
)
def test_malformed_completion_cannot_leave_provider_conclusions_in_fallback(completion):
    source, _, _, _, service = setup(FakeEvidenceFeedbackProvider(completion))
    expected = render_feedback(feedback_request(source))
    reply = service.feedback(feedback_principal(source), feedback_query(source))
    assert reply.fallback_reason == "invalid_output" and reply.delivery == "deterministic"
    assert_same_authorized_content(reply, expected)
    assert PRIVATE not in reply.model_dump_json()


@pytest.mark.parametrize("returned", [None, PRIVATE, object()])
def test_provider_returning_a_noncompletion_object_cannot_leak_its_value(returned):
    class InvalidProvider:
        def explain(self, request):
            return returned

    source, _, _, _, service = setup(InvalidProvider())
    expected = render_feedback(feedback_request(source))
    reply = service.feedback(feedback_principal(source), feedback_query(source))
    assert reply.fallback_reason == "invalid_output" and reply.delivery == "deterministic"
    assert_same_authorized_content(reply, expected)
    assert PRIVATE not in reply.model_dump_json()


@pytest.mark.parametrize("provider_fails", [False, True])
def test_expired_authorization_during_provider_call_never_returns_feedback(provider_fails):
    clock = MutableClock()

    class ExpiringProvider:
        def explain(self, request):
            clock.now = at(101)
            if provider_fails:
                raise TimeoutError(PRIVATE)
            return FakeEvidenceFeedbackProvider().explain(request)

    source = feedback_source()
    principal = replace(feedback_principal(source), expires_at=at(101))
    service = EvidenceFeedbackService(ReadOnlyRepository(source), ExpiringProvider(), clock)
    with pytest.raises(LearningError) as caught:
        service.feedback(principal, feedback_query(source))
    assert caught.value.code == "unauthenticated"


def test_provider_mutation_of_its_detached_request_cannot_change_authorized_text_or_refs():
    class MutatingProvider:
        def explain(self, request):
            object.__setattr__(request.claims[0].wordings[0], "text", PRIVATE)
            return FakeEvidenceFeedbackProvider().explain(request)

    source, _, _, _, service = setup(MutatingProvider())
    expected = render_feedback(feedback_request(source))
    reply = service.feedback(feedback_principal(source), feedback_query(source))
    assert reply.delivery == "mock"
    assert_same_authorized_content(reply, expected)
    assert PRIVATE not in reply.model_dump_json()


def test_provider_mutation_of_citations_forces_entire_original_policy_fallback():
    class MutatingProvider:
        def explain(self, request):
            fact = next(claim for claim in request.claims if claim.evidence_ids)
            object.__setattr__(fact, "evidence_ids", (identity("invented-evidence"),))
            return FakeEvidenceFeedbackProvider().explain(request)

    source, _, _, _, service = setup(MutatingProvider())
    expected = render_feedback(feedback_request(source))
    reply = service.feedback(feedback_principal(source), feedback_query(source))
    assert reply.delivery == "deterministic"
    assert reply.fallback_reason in {"invalid_output", "provider_exception"}
    assert_same_authorized_content(reply, expected)


def test_missing_activity_returns_insufficient_evidence_without_provider_or_competence_claim():
    source, _, provider, _, service = setup(
        FakeEvidenceFeedbackProvider(AssertionError("Must not run"))
    )
    source.saved_prediction = None
    source.saved_attempts = []
    source.saved_runs = []
    source.saved_checks = []
    source.session = replace(source.session, state="awaiting_prediction")
    reply = service.feedback(feedback_principal(source), feedback_query(source))
    assert reply.state == "insufficient_evidence" and reply.delivery == "deterministic"
    assert reply.fallback_reason is None and provider.calls == []
    assert reply.evidence_references == ()
    assert all(
        statement.role != "fact" for section in reply.sections for statement in section.items
    )
    assert sum(section.kind == "next" for section in reply.sections) == 1
