"""Owned, freshly authorized tutor context; provider work happens outside database reads."""

import hashlib
import json
import re
from collections.abc import Callable
from typing import cast
from uuid import UUID

from app.ai.lesson_assistant import LessonAssistant
from app.core.errors import ApplicationError
from app.domain.accounts import Principal
from app.domain.clock import Clock, utc_now
from app.domain.learning import LearningError
from app.repositories.feedback_release import FeedbackReleaseRepository
from app.schemas.lesson_assistant import (
    LessonAssistantReply,
    LessonAssistantRequest,
    LessonStage,
    SupportedLesson,
    VisibleEvidence,
)
from app.services.catalog import (
    LESSON_ID,
    PUBLIC_CONTENT,
    TRANSFER_CONTENT,
    lesson_hash,
    transfer_hash,
)
from app.services.lesson_assistant import LessonAssistantService, build_lesson_assistant_request
from app.services.tutor_guidance import stage_guidance

# Authored from the actual FastAPI/Pydantic exercise contracts and trusted verification
# implementation. These are production help text, not promoted mock-provider fixtures.
GUIDANCE = {
    "request-contract": (
        "A request must match the receiving schema's field names and JSON structure. "
        "Compare the outgoing request with that contract before changing the mapping."
    ),
    "validation-order": (
        "FastAPI validates the incoming request against its declared Pydantic model before "
        "running the route. A validation failure can stop the save operation before "
        "a database write."
    ),
    "extra-fields": (
        "With extra='forbid', a receiving Pydantic model rejects keys that are not declared "
        "in that model. Intended values must also appear under the right keys and at the "
        "right JSON level."
    ),
    "json-levels": (
        "Pydantic compares each value at the JSON level declared by the schema. Check where "
        "each object begins and ends; a value appearing elsewhere does not satisfy that "
        "receiving contract."
    ),
    "verification": (
        "Use the saved verification checks to distinguish HTTP and validation behavior from "
        "an independently observed database result. A submitted change alone does not prove "
        "a successful save."
    ),
    "evidence-limits": (
        "Trace records predictions, mapping-change attempts, hints and trusted verification "
        "results. Those records do not establish how you investigated the issue or whether "
        "you worked without external help."
    ),
}
_SECRET = re.compile(
    r"-----BEGIN .*PRIVATE KEY|\b(?:AIza[\w-]{20,}|sk-[\w-]{20,}|ghp_[\w]{20,})|"
    r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}|"
    r"\b(?:password|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S{6,}",
    re.I,
)


class LessonTutoringService:
    def __init__(
        self,
        repository: FeedbackReleaseRepository,
        assistant_factory: Callable[[dict[str, str], str], LessonAssistant],
        clock: Clock = utc_now,
    ) -> None:
        self.repository, self.assistant_factory, self.clock = repository, assistant_factory, clock

    def _capture(
        self,
        owner: Principal,
        session_id: UUID,
        question: str,
        *,
        include_visible_context: bool = False,
    ) -> tuple[str, LessonAssistantRequest, dict[str, str]]:
        # Reuse C1's database-authoritative account/role/ownership/expiry checks.
        with self.repository.read(owner, session_id, self.clock()) as read:
            if read.auth.mode != "account":
                raise LearningError("unauthenticated", "Sign in to use the lesson tutor.")
            if read.session.state == "abandoned":
                raise LearningError("conflict", "The tutor is unavailable for this session.")
            lesson = read.lesson
            expected = PUBLIC_CONTENT if lesson.lesson_id == LESSON_ID else TRANSFER_CONTENT
            expected_hash = (
                lesson_hash(PUBLIC_CONTENT, "content", "rejected")
                if lesson.lesson_id == LESSON_ID
                else transfer_hash(TRANSFER_CONTENT)
            )
            if (
                lesson.version != "1.0.0"
                or lesson.lesson_id not in {LESSON_ID, "fastapi-nested-payload-transfer"}
                or lesson.public_content != expected
                or lesson.content_hash != expected_hash
            ):
                raise LearningError("conflict", "This pinned lesson is not supported by the tutor.")
            stages: dict[str, LessonStage] = {
                "awaiting_prediction": "predict",
                "ready_for_attempt": "modify",
                "verification_pending": "verify",
                "needs_revision": "modify",
                "completed": "verify",
            }
            lesson_id = cast(SupportedLesson, lesson.lesson_id)
            stage = stages[read.session.state]
            choices = dict(GUIDANCE, objective=lesson.public_content["objective"])
            choices.update(stage_guidance(lesson_id, stage))
            attempts = read.learning.attempts(session_id)
            attempt_numbers = {attempt.id: attempt.number for attempt in attempts}
            runs = read.learning.runs(session_id)
            latest_order = max(
                ((attempt_numbers.get(run.attempt_id, 0), run.created_at) for run in runs),
                default=None,
            )
            latest_runs = [
                run
                for run in runs
                if (attempt_numbers.get(run.attempt_id, 0), run.created_at) == latest_order
            ]
            # Attempt numbers establish action order even when timestamps tie.
            # Conflicting outcomes tied within one attempt cannot establish a
            # latest result; omit that claim instead of ordering random UUIDs.
            latest = latest_runs[0] if len({run.status for run in latest_runs}) == 1 else None
            if latest and latest.status == "failed":
                choices["observed-failure"] = (
                    "The latest saved verification failed. Inspect that run's visible checks "
                    "before revising the outgoing request. This observation does not establish "
                    "why you chose your change."
                )
            elif latest and latest.status == "passed":
                choices["observed-success"] = (
                    "The latest saved verification passed. Review its stored checks for the "
                    "exact evidence; the tutor does not independently grade your change or "
                    "complete the lesson."
                )
            facts = {
                "authorization": read.auth.identity_fingerprint,
                "session": str(read.session.id),
                "state": read.session.state,
                "lesson": str(lesson.id),
                "hash": lesson.content_hash,
                "runs": [(str(run.id), run.status, str(run.completed_at)) for run in runs],
                "attempts": [str(item.id) for item in attempts],
                "hints": [(str(item.id), item.status) for item in read.learning.hints(session_id)],
            }
            signature = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
            visible_attempt = None
            evidence: tuple[VisibleEvidence, ...] = ()
            if include_visible_context:
                selected = max(attempts, key=lambda item: item.number, default=None)
                if selected is not None:
                    visible_attempt = (
                        f"Saved submission: {selected.change_type}; selected field/shape: "
                        f"{selected.field_name}. A submission alone does not establish correctness."
                    )
                if latest is not None and latest.status in {"passed", "failed"}:
                    # Reuse the existing learner-visible evidence categories, never
                    # serialize expected/observed payloads or private evaluator data.
                    checks = read.learning.checks(latest.id)
                    if len(checks) == 5 and len({item.code for item in checks}) == 5:
                        evidence = tuple(
                            VisibleEvidence.model_validate(
                                {
                                    "category": item.code,
                                    "feedback": "The saved check matched its trusted expectation."
                                    if item.matched
                                    else "The saved check did not match its trusted expectation.",
                                }
                            )
                            for item in sorted(checks, key=lambda item: item.code)
                        )
            request = build_lesson_assistant_request(
                lesson_id=lesson_id,
                stage=stage,
                public_content=lesson.public_content,
                question=question,
                visible_attempt=visible_attempt,
                evidence=evidence,
            )
            return signature, request, choices

    def answer(self, owner: Principal, session_id: UUID, question: str) -> LessonAssistantReply:
        before, request, choices = self._capture(owner, session_id, question)
        if _SECRET.search(question):
            raise ApplicationError(
                "invalid_request", "Remove passwords, keys and tokens from the question.", 422
            )
        subject = (
            "tutor:" + hashlib.sha256(str(owner.account.id).encode()).hexdigest()
            if owner.account
            else "invalid"
        )
        assistant = LessonAssistantService(self.assistant_factory(choices, subject))
        # No repository read/write transaction is open during the provider call.
        reply = assistant.answer(request)
        after, _, _ = self._capture(owner, session_id, question)
        if before != after:
            raise LearningError("conflict", "Saved work changed. Refresh progress and ask again.")
        return reply
