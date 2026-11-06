"""Offline injected HTTP only: one POST, bounded reads and no secret/content output."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr

from scripts import accept_deployed_ai as cli
from scripts.ai_acceptance_evidence import EvidenceBaseline, EvidenceError, VerifiedEvidence
from scripts.operator_http import OperatorHTTP

TOKEN = "eyJsynthetic.fixture.signature"
PRIVATE = "private-learner-output-canary"


class Evidence:
    def __init__(self, *, fail=None):
        self.fail, self.closed, self.prepared = False, False, None
        self.fail = fail

    def prepare(self, owner, key, digest):
        if self.fail:
            raise EvidenceError(self.fail)
        self.prepared = EvidenceBaseline(owner, key, digest, 0, frozenset())
        return self.prepared

    def verify(self, baseline, request_id, lesson_id, count):
        assert baseline is self.prepared and count == 3
        return VerifiedEvidence(input_tokens=100, output_tokens=200)

    def close(self):
        self.closed = True


def fixture(*, states=("ready",), available=True, failure=None, extra_answer=False):
    owner, request_id, lesson_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC).isoformat()
    body = cli.synthetic_request().model_dump(mode="json")
    job = {
        "id": str(request_id),
        "status": states[0],
        "error_code": None,
        "message": None,
        "topic": body["topic"],
        "language": "Python",
        "framework": None,
        "level": "beginner",
        "lesson_count": 1,
        "lessons_ready": 1,
        "lesson_ids": [str(lesson_id)],
        "created_at": now,
        "updated_at": now,
        "completed_at": now,
    }
    lesson = {
        "id": str(lesson_id),
        "request_id": str(request_id),
        "position": 1,
        "title": PRIVATE,
        "objective": PRIVATE,
        "language": "Python",
        "level": "beginner",
        "created_at": now,
        "challenge_count": 3,
        "completed_challenges": 0,
        "sections": [{"heading": "Example", "body": PRIVATE}],
        "next_lesson_id": None,
        "challenges": [
            {
                "id": str(uuid4()),
                "position": i,
                "kind": "multiple_choice",
                "prompt": PRIVATE,
                "code": None,
                "options": ["one", "two"],
                "hints": [PRIVATE],
                "verification_mode": "answer_key",
                "attempts": 0,
                "answered_correctly": None,
                "explanation": None,
            }
            for i in range(1, 4)
        ],
    }
    if extra_answer:
        lesson["challenges"][0]["correct_option"] = 1
    calls = []
    polls = [0]

    def handle(request):
        calls.append(request)
        path = request.url.path
        if path == "/api/v1/account/me":
            return httpx2.Response(
                200, json={"user_id": str(owner), "status": "active", "roles": ["learner"]}
            )
        if path.endswith("/languages"):
            return httpx2.Response(200, json={"items": [], "generation_available": available})
        if request.method == "POST":
            if failure:
                raise httpx2.ReadTimeout("private-token-or-response-canary")
            return httpx2.Response(202, json=job)
        if "/requests/" in path:
            polls[0] += 1
            return httpx2.Response(
                200, json={**job, "status": states[min(polls[0], len(states) - 1)]}
            )
        return httpx2.Response(200, json=lesson)

    client = OperatorHTTP(SecretStr(TOKEN), transport=httpx2.MockTransport(handle))
    return client, calls, Evidence(), (owner, request_id, lesson_id), body


def apply(key):
    return [
        "--apply",
        "--confirm-free-tier-project",
        "--confirm-server-call-cap-one",
        "--idempotency-key",
        str(key),
    ]


def test_default_is_offline_without_reading_credentials_database_or_constructing_clients(
    capsys, monkeypatch
):
    monkeypatch.setenv("TRACE_OPERATOR_ACCESS_TOKEN", "private-token-canary")

    def forbidden():
        raise AssertionError("No default external work")

    assert cli.main([], http_factory=forbidden, evidence_factory=forbidden) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "dry_run" and report["generation_post_attempted"] is False
    assert "private-token-canary" not in captured.out + captured.err


@pytest.mark.parametrize(
    "args",
    [
        ["--apply"],
        ["--apply", "--confirm-free-tier-project"],
        ["--apply", "--confirm-server-call-cap-one"],
        ["--apply", "--confirm-free-tier-project", "--confirm-server-call-cap-one"],
    ],
)
def test_apply_requires_all_explicit_preconditions_before_any_factory(args, capsys):
    def forbidden():
        raise AssertionError("No unapproved external work")

    assert cli.main(args, http_factory=forbidden, evidence_factory=forbidden) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "explicit_preconditions_required"


def test_success_posts_fixed_synthetic_job_once_and_only_emits_validated_metadata(capsys):
    client, calls, evidence, identities, body = fixture(states=("queued", "generating", "ready"))
    key = uuid4()
    assert (
        cli.main(
            apply(key),
            http_factory=lambda: client,
            evidence_factory=lambda: evidence,
            pause=lambda _: None,
        )
        == 0
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    posts = [call for call in calls if call.method == "POST"]
    assert len(posts) == 1 and posts[0].headers["idempotency-key"] == str(key)
    assert json.loads(posts[0].content) == body
    assert report["status"] == "verified" and report["evidence"]["provider_attempts"] == 1
    assert report["billing_verified"] is False and report["evidence"]["billing_verified"] is False
    assert report["evidence"]["returned_model_id"] == "not_retained"
    assert report["server_one_call_cap"] == "operator_attested_not_remotely_observed"
    assert evidence.closed
    for secret in (TOKEN, PRIVATE, str(key), *(str(value) for value in identities), body["topic"]):
        assert secret not in captured.out + captured.err


@pytest.mark.parametrize(
    "failure", ["competing_work", "existing_operation", "evidence_unavailable"]
)
def test_unprovable_baseline_never_dispatches_generation(failure, capsys):
    client, calls, _, _, _ = fixture()
    evidence = Evidence(fail=failure)
    assert (
        cli.main(apply(uuid4()), http_factory=lambda: client, evidence_factory=lambda: evidence)
        == 1
    )
    assert not any(call.method == "POST" for call in calls)
    assert json.loads(capsys.readouterr().out)["reason"] == failure


def test_provider_unavailable_never_dispatches_or_fabricates_lesson(capsys):
    client, calls, evidence, _, _ = fixture(available=False)
    assert (
        cli.main(apply(uuid4()), http_factory=lambda: client, evidence_factory=lambda: evidence)
        == 1
    )
    assert not any(call.method == "POST" for call in calls)
    assert json.loads(capsys.readouterr().out)["reason"] == "provider_unavailable"


def test_ambiguous_post_timeout_is_not_retried_or_echoed(capsys):
    client, calls, evidence, _, _ = fixture(failure=True)
    assert (
        cli.main(apply(uuid4()), http_factory=lambda: client, evidence_factory=lambda: evidence)
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert len([call for call in calls if call.method == "POST"]) == 1
    assert report["status"] == "unverified" and report["outcome_unknown"] is True
    assert "private-token-or-response-canary" not in json.dumps(report)


def test_poll_limit_is_bounded_and_never_creates_a_second_job(capsys):
    client, calls, evidence, _, _ = fixture(states=("generating",))
    assert (
        cli.main(
            apply(uuid4()),
            http_factory=lambda: client,
            evidence_factory=lambda: evidence,
            pause=lambda _: None,
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["reason"] == "poll_deadline" and report["outcome_unknown"] is True
    assert len([call for call in calls if call.method == "POST"]) == 1
    assert len([call for call in calls if "/requests/" in call.url.path]) == 24


@pytest.mark.parametrize("state", ["failed", "cancelled", "rejected"])
def test_terminal_nonready_state_never_claims_live_success(state, capsys):
    client, calls, evidence, _, _ = fixture(states=(state,))
    assert (
        cli.main(apply(uuid4()), http_factory=lambda: client, evidence_factory=lambda: evidence)
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "unverified" and report["job_state"] == state
    assert "evidence" not in report and len([call for call in calls if call.method == "POST"]) == 1


def test_unexpected_answer_key_in_learner_readback_rejects_without_echo(capsys):
    client, _, evidence, _, _ = fixture(extra_answer=True)
    assert (
        cli.main(apply(uuid4()), http_factory=lambda: client, evidence_factory=lambda: evidence)
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "unverified" and "evidence" not in report
    assert PRIVATE not in json.dumps(report) and "correct_option" not in json.dumps(report)


def test_cli_argument_errors_never_echo_accidentally_pasted_credentials(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--api-key=private-cli-canary"])
    output = capsys.readouterr()
    assert "private-cli-canary" not in output.out + output.err
