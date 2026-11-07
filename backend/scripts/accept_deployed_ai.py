"""Offline-first operator acceptance of one fixed synthetic deployed lesson job.

Apply mode is a future explicitly authorized mutation, not a provider probe by
import or default invocation. No credentials, user IDs, prompts or model answers
are written to the report. A successful HTTP reply alone never proves live AI.
"""

import json
import time
from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import UUID

from app.core.ai_activation import SafeArgumentParser
from app.schemas.custom_lessons import (
    CustomLessonRequestCreate,
    CustomLessonRequestView,
    CustomLessonView,
    LanguageList,
)
from app.services.custom_lessons import _hash
from scripts.ai_acceptance_evidence import (
    EvidenceBaseline,
    EvidenceError,
    VerifiedEvidence,
    from_environment,
)


class OperatorPort(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        idempotency_key: UUID | None = None,
    ) -> object: ...
    def remaining_seconds(self) -> float: ...
    def close(self) -> None: ...


class EvidencePort(Protocol):
    def prepare(self, owner: UUID, key: UUID, body_hash: str) -> EvidenceBaseline: ...
    def verify(
        self, baseline: EvidenceBaseline, request_id: UUID, lesson_id: UUID, challenge_count: int
    ) -> VerifiedEvidence: ...
    def close(self) -> None: ...


def synthetic_request() -> CustomLessonRequestCreate:
    return CustomLessonRequestCreate(
        topic="Understand how Python lists preserve insertion order",
        language="Python",
        level="beginner",
        goal="understand",
        lesson_count=1,
        practice_styles=["multiple_choice"],
    )


def _http_from_environment() -> OperatorPort:
    from scripts.operator_http import OperatorHTTP

    return OperatorHTTP.from_environment()


def _accept(
    http: OperatorPort,
    evidence: EvidencePort,
    key: UUID,
    report: dict[str, object],
    pause: Callable[[float], None],
) -> None:
    account = http.request("GET", "/api/v1/account/me")
    if (
        not isinstance(account, dict)
        or account.get("status") != "active"
        or not isinstance(account.get("roles"), list)
        or "learner" not in account.get("roles", [])
    ):
        raise EvidenceError("identity_changed")
    owner = UUID(str(account.get("user_id")))
    languages = LanguageList.model_validate(http.request("GET", "/api/v1/custom-lessons/languages"))
    if not languages.generation_available:
        report.update(status="unverified", reason="provider_unavailable")
        return
    request = synthetic_request()
    body = request.model_dump(mode="json")
    baseline = evidence.prepare(owner, key, _hash(body))
    report["generation_post_attempted"] = True
    # EXACTLY one POST. No retry, token refresh or new key on an ambiguous reply.
    job = CustomLessonRequestView.model_validate(
        http.request("POST", "/api/v1/custom-lessons/requests", body=body, idempotency_key=key)
    )
    if (job.topic, job.language, job.framework, job.level, job.lesson_count) != (
        request.topic,
        request.language,
        request.framework,
        request.level,
        1,
    ):
        raise EvidenceError("request_mismatch")
    request_id = job.id
    polls = 0
    while job.status in {"queued", "generating"}:
        if polls >= 24 or http.remaining_seconds() <= 2:
            report.update(
                status="unverified",
                reason="poll_deadline",
                job_state=job.status,
                outcome_unknown=True,
            )
            return
        pause(min(1.0, http.remaining_seconds()))
        job = CustomLessonRequestView.model_validate(
            http.request("GET", f"/api/v1/custom-lessons/requests/{request_id}")
        )
        if job.id != request_id:
            raise EvidenceError("request_mismatch")
        polls += 1
    report["job_state"] = job.status
    if job.status != "ready":
        report.update(status="unverified", reason="generation_not_ready")
        return
    if job.lessons_ready != 1 or len(job.lesson_ids) != 1:
        raise EvidenceError("request_mismatch")
    lesson = CustomLessonView.model_validate(
        http.request("GET", f"/api/v1/custom-lessons/{job.lesson_ids[0]}")
    )
    if (
        lesson.id != job.lesson_ids[0]
        or lesson.request_id != request_id
        or lesson.next_lesson_id is not None
        or lesson.challenge_count != len(lesson.challenges)
        or not 3 <= lesson.challenge_count <= 5
    ):
        raise EvidenceError("request_mismatch")
    report["http_readback"] = True
    proof = evidence.verify(baseline, request_id, lesson.id, lesson.challenge_count)
    report["evidence"] = VerifiedEvidence.model_validate(proof.model_dump()).model_dump(mode="json")
    report.update(
        status="verified",
        reason="unique_job_and_durable_provider_success",
        lesson_count=1,
        challenge_count=lesson.challenge_count,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    http_factory: Callable[[], OperatorPort] = _http_from_environment,
    evidence_factory: Callable[[], EvidencePort] = from_environment,
    pause: Callable[[float], None] = time.sleep,
) -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-free-tier-project", action="store_true")
    parser.add_argument("--confirm-server-call-cap-one", action="store_true")
    parser.add_argument("--idempotency-key", type=UUID)
    args = parser.parse_args(argv)
    report: dict[str, object] = {
        "status": "dry_run",
        "generation_post_attempted": False,
        "billing_verified": False,
        "live_acceptance_executed": False,
        "outcome_unknown": False,
    }
    if not args.apply:
        report["requires"] = [
            "explicit_future_apply_authorization",
            "free_tier_project_confirmation",
            "running_server_one_call_cap_confirmation",
            "stable_idempotency_key",
            "private_operator_token",
            "explicit_production_postgresql_evidence",
        ]
        print(json.dumps(report, sort_keys=True))
        return 0
    if not (
        args.confirm_free_tier_project and args.confirm_server_call_cap_one and args.idempotency_key
    ):
        report.update(status="blocked", reason="explicit_preconditions_required")
        print(json.dumps(report, sort_keys=True))
        return 2
    http, evidence = None, None
    try:
        http = http_factory()
        evidence = evidence_factory()
        report["live_acceptance_executed"] = True
        report["server_one_call_cap"] = "operator_attested_not_remotely_observed"
        _accept(http, evidence, args.idempotency_key, report, pause)
    except EvidenceError as exc:
        report.update(status="unverified", reason=exc.code)
    except Exception as exc:
        # Includes network/auth/schema failures. Never echo a token, response,
        # URL, account identifier, provider error or exception representation.
        report.update(
            status="unverified",
            reason="acceptance_unavailable",
            outcome_unknown=getattr(exc, "outcome_unknown", False) is True,
        )
    finally:
        for resource in (http, evidence):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    report.update(status="unverified", reason="cleanup_unavailable")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
