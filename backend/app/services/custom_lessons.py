"""Learner-requested lessons: request rules, background generation and server-checked answers.

Persistence goes through CustomLessonRepository (SQL implementation in app.db). Everything is
scoped to the requesting account (another account gets 404). Answer keys never leave the
repository. Generated code is never executed. No prompts, learner text or model output are
logged.
"""

import contextlib
import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Condition, Lock
from uuid import UUID

from app.core.ai_privacy import public_ai_question
from app.core.custom_lesson_settings import CustomLessonSettings
from app.core.errors import ApplicationError
from app.domain.clock import Clock
from app.repositories.custom_lessons import (
    CustomLessonRepository,
    LessonContent,
    RequestFields,
)
from app.schemas.custom_lessons import (
    AnswerCreate,
    AnswerResult,
    CustomLessonList,
    CustomLessonRequestCreate,
    CustomLessonRequestView,
    CustomLessonView,
    LanguageList,
    LanguageView,
)
from app.services.custom_lesson_generation import (
    CustomLessonGenerator,
    GeneratedLesson,
    GenerationDeclined,
    LessonDraft,
    LessonRequestData,
)

# Generated lessons are never run on Trace's server, so none is "server_verified".
LANGUAGES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("python", "Python", ("FastAPI", "Flask", "Django")),
    ("javascript", "JavaScript", ("Node + Express", "React", "Next.js")),
    ("typescript", "TypeScript", ("Node + Express", "React", "Next.js")),
    ("go", "Go", ("net/http", "Gin")),
    ("java", "Java", ("Spring Boot",)),
    ("csharp", "C#", ("ASP.NET Core",)),
    ("ruby", "Ruby", ("Rails",)),
    ("php", "PHP", ("Laravel",)),
    ("sql", "SQL", ("PostgreSQL", "SQLite", "MySQL")),
)

# Clearly harmful requests are refused before any provider call (the model also declines).
_UNSAFE = re.compile(
    r"\b(malware|ransomware|keylogger|botnet|ddos|phishing|credential stuffing|spyware|"
    r"steal(?:ing)? (?:passwords?|credentials|cookies|data)|hack(?:ing)? into|exploit kit|"
    r"bypass (?:paywall|licen[cs]e|drm)|bomb|weapon|porn|sexual)\b",
    re.IGNORECASE,
)


def _now(clock: Clock) -> datetime:
    return clock().astimezone(UTC)


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def check_request_text(body: CustomLessonRequestCreate) -> None:
    """Typed rejections with a rewrite hint, before anything is stored or sent."""
    for text in (body.topic, body.language, body.framework or ""):
        try:
            public_ai_question(text)
        except ValueError:
            raise ApplicationError(
                "custom_lesson_sensitive_input",
                "Remove passwords, keys and email addresses from your request, then try again.",
                422,
            ) from None
        if _UNSAFE.search(text):
            raise ApplicationError(
                "custom_lesson_policy_rejected",
                "Trace can't create lessons about this. Try a programming topic, for example "
                "'how FastAPI validates a request body'.",
                422,
            )


@dataclass(frozen=True)
class Owner:
    account_id: UUID


def _not_found(what: str) -> ApplicationError:
    return ApplicationError("not_found", f"{what} not found.", 404)


class CustomLessonService:
    def __init__(
        self,
        repository: CustomLessonRepository,
        settings: CustomLessonSettings,
        clock: Clock,
        *,
        available: bool,
    ) -> None:
        self.repository, self.settings, self.clock = repository, settings, clock
        self.available = available

    def create_request(
        self, owner: Owner, body: CustomLessonRequestCreate, key: UUID
    ) -> tuple[CustomLessonRequestView, bool]:
        """Returns (view, created). Same key + same body replays; same key + other body is 409."""
        if not self.available:
            raise ApplicationError(
                "custom_lessons_unavailable", "Creating lessons isn't available right now.", 503
            )
        check_request_text(body)
        fields = RequestFields(
            topic=body.topic,
            language=body.language,
            framework=body.framework,
            level=body.level,
            goal=body.goal,
            lesson_count=body.lesson_count,
            practice_styles=tuple(dict.fromkeys(body.practice_styles)),
        )
        outcome = self.repository.create_request(
            owner.account_id,
            str(key),
            _hash(body.model_dump(mode="json")),
            fields,
            _now(self.clock),
            per_minute=self.settings.requests_per_minute,
            per_day=self.settings.daily_requests_per_account,
        )
        if outcome.kind == "conflict":
            raise ApplicationError(
                "idempotency_conflict",
                "This request key was already used for another request.",
                409,
            )
        if outcome.kind == "rate_limited":
            raise ApplicationError(
                "custom_lesson_rate_limited",
                "You've asked for several lessons in a short time. Try again in about a minute.",
                429,
            )
        if outcome.kind == "quota":
            raise ApplicationError(
                "custom_lesson_quota_reached",
                "You've reached today's limit of "
                f"{self.settings.daily_requests_per_account} lesson requests. Try again tomorrow.",
                429,
            )
        assert outcome.view is not None
        return outcome.view, outcome.kind == "created"

    def get_request(self, owner: Owner, request_id: UUID) -> CustomLessonRequestView:
        view = self.repository.get_request(
            owner.account_id,
            request_id,
            _now(self.clock),
            timedelta(seconds=self.settings.stale_after_seconds),
        )
        if view is None:
            raise _not_found("Lesson request")
        return view

    def cancel_request(self, owner: Owner, request_id: UUID) -> CustomLessonRequestView:
        view = self.repository.cancel_request(owner.account_id, request_id, _now(self.clock))
        if view is None:
            raise _not_found("Lesson request")
        return view

    def recover_interrupted(self) -> int:
        return self.repository.recover_interrupted(_now(self.clock))

    def list_lessons(self, owner: Owner) -> CustomLessonList:
        return self.repository.list_lessons(owner.account_id)

    def get_lesson(self, owner: Owner, lesson_id: UUID) -> CustomLessonView:
        view = self.repository.get_lesson(owner.account_id, lesson_id)
        if view is None:
            raise _not_found("Lesson")
        return view

    def delete_lesson(self, owner: Owner, lesson_id: UUID) -> None:
        if not self.repository.delete_lesson(owner.account_id, lesson_id):
            raise _not_found("Lesson")

    def answer(
        self, owner: Owner, lesson_id: UUID, challenge_id: UUID, body: AnswerCreate, key: UUID
    ) -> AnswerResult:
        outcome = self.repository.answer(
            owner.account_id,
            lesson_id,
            challenge_id,
            str(key),
            _hash(body.model_dump(mode="json")),
            body.selected_option,
            body.text,
            _now(self.clock),
        )
        if outcome.kind == "not_found":
            raise _not_found("Challenge")
        if outcome.kind == "conflict":
            raise ApplicationError(
                "idempotency_conflict", "This answer key was already used for another answer.", 409
            )
        if outcome.kind == "invalid_option":
            raise ApplicationError("invalid_answer", "Choose one of the options.", 422)
        if outcome.kind == "missing_text":
            raise ApplicationError("invalid_answer", "Write your answer first.", 422)
        assert outcome.result is not None
        return outcome.result

    def languages(self) -> LanguageList:
        return LanguageList(
            generation_available=self.available,
            items=[
                LanguageView(
                    id=language_id,
                    label=label,
                    frameworks=list(frameworks),
                    verification="answer_key",
                    note="Multiple-choice answers are checked against an answer key on "
                    "Trace's server. Generated code is never run. "
                    "'Explain' questions are practice only.",
                )
                for language_id, label, frameworks in LANGUAGES
            ],
        )


def lesson_content(draft: LessonDraft) -> LessonContent:
    """Only the fields the app needs; answer keys kept for the server-side check."""
    challenges: list[dict[str, object]] = []
    for challenge in draft.challenges:
        options = challenge.kind != "explain"
        challenges.append(
            {
                "kind": challenge.kind,
                "prompt": challenge.prompt,
                "code": challenge.code or None,
                "options": list(challenge.options) if options else [],
                "hints": list(challenge.hints),
                "explanation": challenge.explanation,
                "verification_mode": challenge.verification_mode,
                "correct_option": challenge.correct_option if options else None,
                "model_answer": None if options else challenge.model_answer,
            }
        )
    return LessonContent(
        title=draft.title,
        objective=draft.objective,
        sections=[{"heading": s.heading, "body": s.body} for s in draft.sections],
        challenges=challenges,
    )


class CustomLessonRunner:
    """One background worker. Generation never blocks an HTTP request."""

    def __init__(
        self,
        repository: CustomLessonRepository,
        generator: CustomLessonGenerator,
        clock: Clock,
        logger: logging.Logger,
    ) -> None:
        self.repository, self.generator, self.clock, self.logger = (
            repository,
            generator,
            clock,
            logger,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="trace-custom-lessons"
        )
        self._lock = Lock()
        self._idle = Condition(self._lock)
        self._running = 0
        self._closed = False

    def submit(self, request_id: UUID) -> None:
        with self._lock:
            if self._closed:
                return
            self._running += 1
        try:
            self._executor.submit(self._run, request_id)
        except RuntimeError:
            self._finished()

    def _finished(self) -> None:
        with self._idle:
            self._running -= 1
            self._idle.notify_all()

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        with self._idle:
            return self._idle.wait_for(lambda: self._running == 0, timeout=timeout)

    def close(self, timeout: float = 30.0) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.wait_for_idle(timeout)

    def _run(self, request_id: UUID) -> None:
        try:
            self._generate(request_id)
        except Exception:
            # No content or exception text is logged.
            self.logger.warning("custom_lesson_job_failed")
            with contextlib.suppress(Exception):
                self.repository.finish(request_id, "failed", "provider_error", _now(self.clock))
        finally:
            self._finished()

    def _generate(self, request_id: UUID) -> None:
        job = self.repository.start_generation(request_id, _now(self.clock))
        if job is None:
            return
        fields = job.fields
        request = LessonRequestData(
            topic=fields.topic,
            language=fields.language,
            framework=fields.framework,
            level=fields.level,
            goal=fields.goal,
            practice_styles=fields.practice_styles,
        )
        titles: list[str] = []
        for position in range(1, fields.lesson_count + 1):
            if self._closed or self.repository.status(request_id) != "generating":
                return  # cancelled, or shutting down (restart recovery marks it interrupted)
            outcome = self.generator.generate(
                request,
                lesson_number=position,
                lesson_count=fields.lesson_count,
                previous_titles=titles,
                subject=f"custom-lessons:{job.account_id}",
            )
            if isinstance(outcome, GenerationDeclined):
                self.repository.finish(request_id, "rejected", outcome.reason, _now(self.clock))
                return
            if not isinstance(outcome, GeneratedLesson):
                self.repository.finish(request_id, "failed", outcome.code, _now(self.clock))
                return
            saved = self.repository.save_lesson(
                request_id, job, position, lesson_content(outcome.draft), _now(self.clock)
            )
            if not saved:
                return
            titles.append(outcome.draft.title)
        self.repository.finish(request_id, "ready", None, _now(self.clock))
