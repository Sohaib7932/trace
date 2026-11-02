"""Short, consistent authorization/evidence reads for feedback release only."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.accounts import Principal
from app.domain.learning import LearningSession, LessonVersion
from app.repositories.learning import LearningStore
from app.schemas.feedback_release import FreshAuthorization


@dataclass(frozen=True)
class FeedbackReleaseRead:
    """The learning port is borrowed only while its repository context is open."""

    auth: FreshAuthorization
    session: LearningSession
    lesson: LessonVersion
    learning: LearningStore


class FeedbackReleaseRepository(Protocol):
    def read(
        self, principal: Principal, session_id: UUID, now: datetime
    ) -> AbstractContextManager[FeedbackReleaseRead]: ...
