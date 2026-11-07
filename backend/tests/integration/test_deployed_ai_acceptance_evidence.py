"""Read-only acceptance proof against disposable actual ledger/lesson persistence."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import event, select, update

from app.ai.accounting import AllowancePolicy, ProviderAttempt, ProviderUsage
from app.core.ai_settings import GEMINI_MODEL
from app.db.accounting import SqlAIControls
from app.db.custom_lesson_models import CustomLessonRow
from app.db.custom_lessons import SqlCustomLessonRepository
from app.db.models import User, UserRole
from app.repositories.custom_lessons import LessonContent, RequestFields
from app.services.custom_lessons import _hash
from scripts.accept_deployed_ai import synthetic_request
from scripts.ai_acceptance_evidence import EvidenceError, SqlAcceptanceEvidence


@pytest.fixture
def scope(database):
    now, owner, key = datetime.now(UTC), uuid4(), uuid4()
    with database.session() as session, session.begin():
        session.add(User(id=owner, status="active", created_at=now, updated_at=now))
        session.flush()
        session.add(UserRole(user_id=owner, role="learner"))
    policy = AllowancePolicy(scope="disposable-acceptance")
    return dict(
        database=database,
        now=now,
        owner=owner,
        key=key,
        policy=policy,
        reader=SqlAcceptanceEvidence(database, policy),
        repository=SqlCustomLessonRepository(database),
        controls=SqlAIControls(database),
    )


def prepare(scope):
    body = synthetic_request().model_dump(mode="json")
    return scope["reader"].prepare(scope["owner"], scope["key"], _hash(body))


def create_job(scope, *, key=None, digest=None, complete=True):
    body = synthetic_request()
    outcome = scope["repository"].create_request(
        scope["owner"],
        str(key or scope["key"]),
        digest or _hash(body.model_dump(mode="json")),
        RequestFields(
            body.topic,
            body.language,
            body.framework,
            body.level,
            body.goal,
            1,
            tuple(body.practice_styles),
        ),
        scope["now"],
        per_minute=5,
        per_day=10,
    )
    assert outcome.kind == "created"
    request_id = outcome.view.id
    if not complete:
        return request_id, None
    job = scope["repository"].start_generation(request_id, scope["now"])
    content = LessonContent(
        "private-generated-title-canary",
        "private-objective-canary",
        [{"heading": "Example", "body": "private-passage-canary"}],
        [
            dict(
                kind="multiple_choice",
                prompt="private-prompt-canary",
                code=None,
                options=["one", "two"],
                hints=["private-hint-canary"],
                explanation="private-answer-canary",
                verification_mode="answer_key",
                correct_option=1,
                model_answer=None,
            )
            for _ in range(3)
        ],
    )
    assert scope["repository"].save_lesson(request_id, job, 1, content, scope["now"])
    scope["repository"].finish(request_id, "ready", None, scope["now"])
    with scope["database"].session() as session:
        lesson_id = session.scalar(
            select(CustomLessonRow.id).where(CustomLessonRow.request_id == request_id)
        )
    return request_id, lesson_id


def record_attempt(
    scope,
    *,
    model=GEMINI_MODEL,
    status="success",
    cost=0,
    input_tokens=10,
    output_tokens=20,
    pending=False,
):
    identity = uuid4()
    attempt = ProviderAttempt(
        id=identity,
        capability="generation",
        model_id=model,
        subject_hash=sha256(("custom-lessons:" + str(scope["owner"])).encode()).hexdigest(),
        estimated_input_bytes=1000,
        item_count=1,
    )
    scope["controls"].reserve(scope["policy"], attempt)
    if not pending:
        scope["controls"].finish(
            identity,
            ProviderUsage(
                status=status,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                accounted_cost_microusd=cost,
            ),
        )
    return identity


def verify(scope, baseline, job):
    return scope["reader"].verify(baseline, job[0], job[1], 3)


def test_exact_single_job_and_successful_live_ledger_produce_only_safe_metadata(scope):
    baseline = prepare(scope)
    job = create_job(scope)
    record_attempt(scope)
    proof = verify(scope, baseline, job)
    raw = proof.model_dump_json()
    assert proof.provider_attempts == 1 and proof.recorded_cost_microusd == 0
    assert proof.requested_model_id == GEMINI_MODEL and proof.billing_verified is False
    for private in (
        str(scope["owner"]),
        str(scope["key"]),
        str(job[0]),
        str(job[1]),
        "subject_hash",
        "private-generated",
        "private-passage",
        "private-prompt",
        "private-answer",
    ):
        assert private not in raw
    assert str(scope["owner"]) not in repr(baseline) and str(scope["key"]) not in repr(baseline)


def test_successful_http_content_without_any_durable_ai_attempt_is_not_live_proof(scope):
    baseline = prepare(scope)
    job = create_job(scope)
    with pytest.raises(EvidenceError, match="unavailable") as error:
        verify(scope, baseline, job)
    assert error.value.code == "competing_work"


@pytest.mark.parametrize(
    "change",
    [
        {"status": "refusal"},
        {"status": "truncated"},
        {"status": "timeout"},
        {"status": "error"},
        {"model": "gemini-3.5-flash-lite"},
        {"cost": 1},
        {"pending": True},
    ],
)
def test_failed_pending_wrong_model_or_nonzero_cost_cannot_be_verified(scope, change):
    baseline = prepare(scope)
    job = create_job(scope)
    record_attempt(scope, **change)
    with pytest.raises(EvidenceError) as error:
        verify(scope, baseline, job)
    assert error.value.code == "provider_unverified"


@pytest.mark.parametrize("field", ["cost", "input_tokens", "output_tokens"])
def test_unknown_usage_stays_unknown_and_never_becomes_a_zero_cost_claim(scope, field):
    baseline = prepare(scope)
    job = create_job(scope)
    record_attempt(scope, **{field: None})
    with pytest.raises(EvidenceError) as error:
        verify(scope, baseline, job)
    assert error.value.code == "usage_unknown"


def test_preexisting_active_job_blocks_before_any_new_operation(scope):
    create_job(scope, complete=False)
    with pytest.raises(EvidenceError) as error:
        scope["reader"].prepare(scope["owner"], uuid4(), "bounded-hash")
    assert error.value.code == "competing_work"


def test_an_existing_idempotency_key_is_not_resubmitted_for_fresh_proof(scope):
    create_job(scope)
    with pytest.raises(EvidenceError) as error:
        prepare(scope)
    assert error.value.code == "existing_operation"


def test_preexisting_unfinalized_provider_work_blocks_acceptance(scope):
    record_attempt(scope, pending=True)
    with pytest.raises(EvidenceError) as error:
        prepare(scope)
    assert error.value.code == "competing_work"


def test_competing_account_job_invalidates_the_attribution_window(scope):
    baseline = prepare(scope)
    job = create_job(scope)
    create_job(scope, key=uuid4(), complete=False)
    record_attempt(scope)
    with pytest.raises(EvidenceError) as error:
        verify(scope, baseline, job)
    assert error.value.code == "competing_work"


def test_multiple_new_provider_attempts_are_not_reported_as_one(scope):
    baseline = prepare(scope)
    job = create_job(scope)
    record_attempt(scope)
    record_attempt(scope)
    with pytest.raises(EvidenceError) as error:
        verify(scope, baseline, job)
    assert error.value.code == "competing_work"


def test_wrong_request_hash_and_revoked_owner_fail_closed(scope):
    baseline = prepare(scope)
    job = create_job(scope, digest="different-body-hash")
    record_attempt(scope)
    with pytest.raises(EvidenceError) as error:
        verify(scope, baseline, job)
    assert error.value.code == "request_mismatch"
    with scope["database"].session() as session, session.begin():
        session.execute(update(User).where(User.id == scope["owner"]).values(status="disabled"))
    with pytest.raises(EvidenceError) as error:
        verify(scope, baseline, job)
    assert error.value.code == "identity_changed"


def test_reader_uses_explicit_metadata_columns_and_never_issues_writes(scope):
    baseline = prepare(scope)
    job = create_job(scope)
    record_attempt(scope)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(scope["database"].engine, "before_cursor_execute", capture)
    try:
        verify(scope, baseline, job)
    finally:
        event.remove(scope["database"].engine, "before_cursor_execute", capture)
    assert statements and all(
        statement.lstrip().upper().startswith("SELECT") for statement in statements
    )
    combined = " ".join(statements).lower()
    for private_column in (
        ".topic",
        ".framework",
        ".sections",
        ".prompt",
        ".options",
        ".hints",
        ".correct_option",
        ".model_answer",
    ):
        assert private_column not in combined


def test_existing_successful_history_does_not_replace_or_confuse_the_new_attempt(scope):
    record_attempt(scope, model="gemini-3.5-flash-lite")
    baseline = prepare(scope)
    job = create_job(scope)
    record_attempt(scope)
    proof = verify(scope, baseline, job)
    assert proof.provider_attempts == 1 and proof.requested_model_id == GEMINI_MODEL


def test_reported_zero_tokens_are_distinct_from_missing_usage(scope):
    baseline = prepare(scope)
    job = create_job(scope)
    record_attempt(scope, input_tokens=0, output_tokens=0)
    proof = verify(scope, baseline, job)
    assert proof.input_tokens == 0 and proof.output_tokens == 0


def test_operator_policy_mismatch_blocks_before_generation(scope):
    record_attempt(scope)
    changed = AllowancePolicy(scope=scope["policy"].scope, max_attempts=21)
    reader = SqlAcceptanceEvidence(scope["database"], changed)
    with pytest.raises(EvidenceError) as error:
        reader.prepare(scope["owner"], scope["key"], "bounded-hash")
    assert error.value.code == "evidence_configuration_required"
