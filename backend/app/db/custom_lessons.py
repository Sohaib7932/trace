"""SQL persistence for learner-requested lessons. Every query is scoped to the owning account.

Answer keys (correct_option, model_answer) are read only to check an answer; no view built
here ever contains them.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.custom_lesson_models import (
    CustomChallengeAnswerRow,
    CustomChallengeRow,
    CustomLessonRequestRow,
    CustomLessonRow,
)
from app.db.session import Database
from app.repositories.custom_lessons import (
    AnswerOutcome,
    CreateOutcome,
    GenerationJob,
    LessonContent,
    RequestFields,
)
from app.schemas.custom_lessons import (
    AnswerResult,
    ChallengeView,
    CustomLessonList,
    CustomLessonRequestView,
    CustomLessonSummary,
    CustomLessonView,
    Section,
)

ACTIVE = ("queued", "generating")

# Learner-facing messages per stored error code (no provider or model detail).
MESSAGES = {
    "provider_rate_limited": "The AI service is busy right now. Try again in a minute.",
    "quota_exhausted": "Today's AI allowance for Trace is used up. Try again later.",
    "provider_timeout": "The AI service took too long to answer. Try again.",
    "provider_unavailable": "The AI service isn't available right now. Try again later.",
    "provider_error": "The AI service couldn't create this lesson. Try again.",
    "invalid_output": "The draft didn't pass Trace's checks, so it wasn't saved. Try again.",
    "interrupted": "Creating this lesson was interrupted. Try again.",
    "off_topic": "This doesn't look like a programming topic. "
    "Describe code or a concept you want to learn.",
    "unsafe": "Trace can't create lessons about this. Try a different programming topic.",
    "unclear": "The request was too vague to teach. "
    "Add the language and what you want to practise.",
}


def message_for(code: str | None) -> str | None:
    if code is None:
        return None
    # Validation codes (answer_leak, invalid_python, ...) share one learner-facing message.
    return MESSAGES.get(code, MESSAGES["invalid_output"])


class SqlCustomLessonRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ---------- requests ----------
    def create_request(
        self,
        account_id: UUID,
        key: str,
        digest: str,
        fields: RequestFields,
        now: datetime,
        *,
        per_minute: int,
        per_day: int,
    ) -> CreateOutcome:
        with self.database.session() as session, session.begin():
            existing = session.scalar(
                select(CustomLessonRequestRow).where(
                    CustomLessonRequestRow.account_id == account_id,
                    CustomLessonRequestRow.idempotency_key == key,
                )
            )
            if existing is not None:
                if existing.request_hash != digest:
                    return CreateOutcome("conflict")
                return CreateOutcome("replayed", self._view(session, existing))
            if self._count_since(session, account_id, now - timedelta(minutes=1)) >= per_minute:
                return CreateOutcome("rate_limited")
            if self._count_since(session, account_id, now - timedelta(days=1)) >= per_day:
                return CreateOutcome("quota")
            row = CustomLessonRequestRow(
                account_id=account_id,
                idempotency_key=key,
                request_hash=digest,
                status="queued",
                error_code=None,
                topic=fields.topic,
                language=fields.language,
                framework=fields.framework,
                level=fields.level,
                goal=fields.goal,
                lesson_count=fields.lesson_count,
                practice_styles=list(fields.practice_styles),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                return CreateOutcome("conflict")
            return CreateOutcome("created", self._view(session, row))

    @staticmethod
    def _count_since(session: Session, account_id: UUID, since: datetime) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(CustomLessonRequestRow)
                .where(
                    CustomLessonRequestRow.account_id == account_id,
                    CustomLessonRequestRow.created_at > since,
                )
            )
            or 0
        )

    def get_request(
        self, account_id: UUID, request_id: UUID, now: datetime, stale_after: timedelta
    ) -> CustomLessonRequestView | None:
        with self.database.session() as session, session.begin():
            row = session.get(CustomLessonRequestRow, request_id)
            if row is None or row.account_id != account_id:
                return None
            if row.status in ACTIVE and row.updated_at < now - stale_after:
                row.status, row.error_code = "failed", "interrupted"
                row.updated_at = row.completed_at = now
            return self._view(session, row)

    def cancel_request(
        self, account_id: UUID, request_id: UUID, now: datetime
    ) -> CustomLessonRequestView | None:
        with self.database.session() as session, session.begin():
            row = session.get(CustomLessonRequestRow, request_id)
            if row is None or row.account_id != account_id:
                return None
            if row.status in ACTIVE:
                row.status, row.error_code = "cancelled", None
                row.updated_at = row.completed_at = now
            return self._view(session, row)

    def recover_interrupted(self, now: datetime) -> int:
        """Nothing can be running at startup. Tolerates a database not yet at head."""
        try:
            with self.database.session() as session, session.begin():
                result = session.execute(
                    update(CustomLessonRequestRow)
                    .where(CustomLessonRequestRow.status.in_(ACTIVE))
                    .values(
                        status="failed", error_code="interrupted", updated_at=now, completed_at=now
                    )
                )
                return int(getattr(result, "rowcount", 0) or 0)
        except SQLAlchemyError:
            return 0

    def _view(self, session: Session, row: CustomLessonRequestRow) -> CustomLessonRequestView:
        lesson_ids = list(
            session.scalars(
                select(CustomLessonRow.id)
                .where(CustomLessonRow.request_id == row.id)
                .order_by(CustomLessonRow.position)
            )
        )
        return CustomLessonRequestView.model_validate(
            {
                "id": row.id,
                "status": row.status,
                "error_code": row.error_code,
                "message": message_for(row.error_code),
                "topic": row.topic,
                "language": row.language,
                "framework": row.framework,
                "level": row.level,
                "lesson_count": row.lesson_count,
                "lessons_ready": len(lesson_ids),
                "lesson_ids": lesson_ids,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "completed_at": row.completed_at,
            }
        )

    # ---------- generation job ----------
    def start_generation(self, request_id: UUID, now: datetime) -> GenerationJob | None:
        with self.database.session() as session, session.begin():
            row = session.get(CustomLessonRequestRow, request_id)
            if row is None or row.status != "queued":
                return None
            row.status, row.updated_at = "generating", now
            return GenerationJob(
                row.account_id,
                RequestFields(
                    topic=row.topic,
                    language=row.language,
                    framework=row.framework,
                    level=row.level,
                    goal=row.goal,
                    lesson_count=row.lesson_count,
                    practice_styles=tuple(row.practice_styles),
                ),
            )

    def status(self, request_id: UUID) -> str | None:
        with self.database.session() as session:
            return session.scalar(
                select(CustomLessonRequestRow.status).where(CustomLessonRequestRow.id == request_id)
            )

    def finish(self, request_id: UUID, status: str, code: str | None, now: datetime) -> None:
        with self.database.session() as session, session.begin():
            session.execute(
                update(CustomLessonRequestRow)
                .where(
                    CustomLessonRequestRow.id == request_id,
                    CustomLessonRequestRow.status.in_(ACTIVE),
                )
                .values(status=status, error_code=code, updated_at=now, completed_at=now)
            )

    def save_lesson(
        self,
        request_id: UUID,
        job: GenerationJob,
        position: int,
        content: LessonContent,
        now: datetime,
    ) -> bool:
        """Stores one validated lesson unless the request was cancelled meanwhile."""
        with self.database.session() as session, session.begin():
            current = session.get(CustomLessonRequestRow, request_id)
            if current is None or current.status != "generating":
                return False
            lesson = CustomLessonRow(
                request_id=request_id,
                account_id=job.account_id,
                position=position,
                title=content.title[:120],
                objective=content.objective,
                language=job.fields.language,
                level=job.fields.level,
                sections=content.sections,
                created_at=now,
            )
            session.add(lesson)
            session.flush()
            for index, challenge in enumerate(content.challenges, start=1):
                session.add(CustomChallengeRow(lesson_id=lesson.id, position=index, **challenge))
            current.updated_at = now
            return True

    # ---------- lessons ----------
    def list_lessons(self, account_id: UUID) -> CustomLessonList:
        with self.database.session() as session:
            rows = session.scalars(
                select(CustomLessonRow)
                .where(CustomLessonRow.account_id == account_id)
                .order_by(CustomLessonRow.created_at.desc(), CustomLessonRow.position)
            ).all()
            return CustomLessonList(items=[self._summary(session, account_id, row) for row in rows])

    def get_lesson(self, account_id: UUID, lesson_id: UUID) -> CustomLessonView | None:
        with self.database.session() as session:
            row = session.get(CustomLessonRow, lesson_id)
            if row is None or row.account_id != account_id:
                return None
            answers = self._answers(session, account_id, row.id)
            challenges = session.scalars(
                select(CustomChallengeRow)
                .where(CustomChallengeRow.lesson_id == row.id)
                .order_by(CustomChallengeRow.position)
            ).all()
            next_id = session.scalar(
                select(CustomLessonRow.id).where(
                    CustomLessonRow.request_id == row.request_id,
                    CustomLessonRow.position == row.position + 1,
                )
            )
            summary = self._summary(session, account_id, row)
            return CustomLessonView(
                **summary.model_dump(),
                sections=[Section(**section) for section in row.sections],
                challenges=[self._challenge(c, answers.get(c.id, [])) for c in challenges],
                next_lesson_id=next_id,
            )

    def delete_lesson(self, account_id: UUID, lesson_id: UUID) -> bool:
        with self.database.session() as session, session.begin():
            row = session.get(CustomLessonRow, lesson_id)
            if row is None or row.account_id != account_id:
                return False
            challenge_ids = select(CustomChallengeRow.id).where(
                CustomChallengeRow.lesson_id == row.id
            )
            session.execute(
                delete(CustomChallengeAnswerRow).where(
                    CustomChallengeAnswerRow.challenge_id.in_(challenge_ids)
                )
            )
            session.execute(
                delete(CustomChallengeRow).where(CustomChallengeRow.lesson_id == row.id)
            )
            session.delete(row)
            return True

    @staticmethod
    def _answers(
        session: Session, account_id: UUID, lesson_id: UUID
    ) -> dict[UUID, list[bool | None]]:
        rows = session.execute(
            select(CustomChallengeAnswerRow.challenge_id, CustomChallengeAnswerRow.correct)
            .join(
                CustomChallengeRow, CustomChallengeRow.id == CustomChallengeAnswerRow.challenge_id
            )
            .where(
                CustomChallengeRow.lesson_id == lesson_id,
                CustomChallengeAnswerRow.account_id == account_id,
            )
            .order_by(CustomChallengeAnswerRow.created_at)
        ).all()
        found: dict[UUID, list[bool | None]] = {}
        for challenge_id, correct in rows:
            found.setdefault(challenge_id, []).append(correct)
        return found

    @staticmethod
    def _correctness(mode: str, results: list[bool | None]) -> bool | None:
        """answer_key: True once answered correctly, False if only wrong so far.
        practice_only and unanswered: None (no automatic check)."""
        if mode != "answer_key" or not results:
            return None
        return any(result is True for result in results)

    @staticmethod
    def _done(results: list[bool | None]) -> bool:
        return any(result is not False for result in results)

    def _summary(
        self, session: Session, account_id: UUID, row: CustomLessonRow
    ) -> CustomLessonSummary:
        answers = self._answers(session, account_id, row.id)
        count = (
            session.scalar(
                select(func.count())
                .select_from(CustomChallengeRow)
                .where(CustomChallengeRow.lesson_id == row.id)
            )
            or 0
        )
        return CustomLessonSummary.model_validate(
            {
                "id": row.id,
                "request_id": row.request_id,
                "position": row.position,
                "title": row.title,
                "objective": row.objective,
                "language": row.language,
                "level": row.level,
                "created_at": row.created_at,
                "challenge_count": count,
                "completed_challenges": sum(1 for r in answers.values() if self._done(r)),
            }
        )

    def _challenge(self, row: CustomChallengeRow, results: list[bool | None]) -> ChallengeView:
        # Never includes correct_option or model_answer.
        return ChallengeView.model_validate(
            {
                "id": row.id,
                "position": row.position,
                "kind": row.kind,
                "prompt": row.prompt,
                "code": row.code,
                "options": list(row.options),
                "hints": list(row.hints),
                "verification_mode": row.verification_mode,
                "attempts": len(results),
                "answered_correctly": self._correctness(row.verification_mode, results),
                "explanation": row.explanation if results else None,
            }
        )

    # ---------- answers (checked here; keys never leave the server) ----------
    def answer(
        self,
        account_id: UUID,
        lesson_id: UUID,
        challenge_id: UUID,
        key: str,
        digest: str,
        selected_option: int | None,
        text: str | None,
        now: datetime,
    ) -> AnswerOutcome:
        with self.database.session() as session, session.begin():
            lesson = session.get(CustomLessonRow, lesson_id)
            challenge = session.get(CustomChallengeRow, challenge_id)
            if (
                lesson is None
                or lesson.account_id != account_id
                or challenge is None
                or challenge.lesson_id != lesson.id
            ):
                return AnswerOutcome("not_found")
            previous = session.scalar(
                select(CustomChallengeAnswerRow).where(
                    CustomChallengeAnswerRow.challenge_id == challenge.id,
                    CustomChallengeAnswerRow.account_id == account_id,
                    CustomChallengeAnswerRow.idempotency_key == key,
                )
            )
            correct: bool | None
            if previous is not None:
                if previous.request_hash != digest:
                    return AnswerOutcome("conflict")
                correct = previous.correct
            else:
                if challenge.verification_mode == "answer_key":
                    if selected_option is None or selected_option >= len(challenge.options):
                        return AnswerOutcome("invalid_option")
                    correct = selected_option == challenge.correct_option
                else:
                    if not text:
                        return AnswerOutcome("missing_text")
                    correct = None
                session.add(
                    CustomChallengeAnswerRow(
                        challenge_id=challenge.id,
                        account_id=account_id,
                        idempotency_key=key,
                        request_hash=digest,
                        correct=correct,
                        created_at=now,
                    )
                )
                session.flush()
            attempts = (
                session.scalar(
                    select(func.count())
                    .select_from(CustomChallengeAnswerRow)
                    .where(
                        CustomChallengeAnswerRow.challenge_id == challenge.id,
                        CustomChallengeAnswerRow.account_id == account_id,
                    )
                )
                or 0
            )
            practice = challenge.verification_mode == "practice_only"
            return AnswerOutcome(
                "ok",
                AnswerResult.model_validate(
                    {
                        "challenge_id": challenge.id,
                        "verification_mode": challenge.verification_mode,
                        "correct": correct,
                        "explanation": challenge.explanation,
                        "model_answer": challenge.model_answer if practice else None,
                        "attempts": attempts,
                    }
                ),
            )
