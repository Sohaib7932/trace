from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db import models as m
from app.db.session import Database
from app.domain.leaderboard import LeaderboardSlice, RankedLearner
from app.domain.learning import LearningError

_CHECK_CODES = ("http_status", "api_response", "validation", "row_count", "stored_values")


class SqlLeaderboardRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def page(self, viewer: UUID, as_of: datetime, offset: int, limit: int) -> LeaderboardSlice:
        # Reuse the persisted verification evidence; never create a score/completion ledger.
        checked_runs = (
            select(m.VerificationCheck.run_id)
            .where(
                m.VerificationCheck.matched.is_(True), m.VerificationCheck.code.in_(_CHECK_CODES)
            )
            .group_by(m.VerificationCheck.run_id)
            .having(func.count() == len(_CHECK_CODES))
        )
        passed = (
            select(m.VerificationRun.id)
            .where(
                m.VerificationRun.session_id == m.LearningSession.id,
                m.VerificationRun.status == "passed",
                m.VerificationRun.completed_at <= as_of,
                m.VerificationRun.id.in_(checked_runs),
            )
            .exists()
        )
        problems = (
            select(m.LearningSession.learner_id, m.LessonVersion.lesson_id)
            .join(m.LessonVersion, m.LessonVersion.id == m.LearningSession.lesson_version_id)
            .where(
                m.LearningSession.state == "completed",
                m.LearningSession.completed_at <= as_of,
                passed,
            )
            .distinct()
            .cte("verified_problems")
        )
        counts = (
            select(problems.c.learner_id, func.count().label("verified_count"))
            .group_by(problems.c.learner_id)
            .cte("verified_counts")
        )
        ranked = (
            select(
                m.User.id.label("user_id"),
                counts.c.verified_count,
                # The deterministic secondary order belongs outside RANK so ties stay tied.
                func.rank().over(order_by=counts.c.verified_count.desc()).label("rank"),
            )
            .join(m.AccountLearner, m.AccountLearner.user_id == m.User.id)
            .join(counts, counts.c.learner_id == m.AccountLearner.learner_id)
            .where(
                m.User.status == "active",
                m.User.created_at <= as_of,
                m.AccountLearner.created_at <= as_of,
                select(m.UserRole.user_id)
                .where(m.UserRole.user_id == m.User.id, m.UserRole.role == "learner")
                .exists(),
            )
            .cte("ranked_learners")
        )
        try:
            # Page and off-page viewer position must describe the same database snapshot.
            with self.database.consistent_read() as session:
                rows = session.execute(
                    select(ranked)
                    .order_by(ranked.c.verified_count.desc(), ranked.c.user_id)
                    .offset(offset)
                    .limit(limit + 1)
                ).all()
                me = session.execute(select(ranked).where(ranked.c.user_id == viewer)).one_or_none()
                return LeaderboardSlice(
                    tuple(
                        RankedLearner(row.user_id, row.rank, row.verified_count)
                        for row in rows[:limit]
                    ),
                    RankedLearner(me.user_id, me.rank, me.verified_count)
                    if me is not None
                    else None,
                    len(rows) > limit,
                )
        except SQLAlchemyError:
            raise LearningError(
                "dependency_unavailable", "The leaderboard database is unavailable."
            ) from None
