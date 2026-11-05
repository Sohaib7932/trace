from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.leaderboard import LeaderboardSlice


class LeaderboardRepository(Protocol):
    def page(self, viewer: UUID, as_of: datetime, offset: int, limit: int) -> LeaderboardSlice: ...
