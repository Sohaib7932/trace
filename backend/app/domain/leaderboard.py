from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RankedLearner:
    user_id: UUID
    rank: int
    verified_count: int


@dataclass(frozen=True)
class LeaderboardSlice:
    entries: tuple[RankedLearner, ...]
    me: RankedLearner | None
    has_more: bool
