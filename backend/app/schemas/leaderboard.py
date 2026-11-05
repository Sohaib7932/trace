from datetime import datetime

from pydantic import Field

from app.schemas.learning import Contract


class LeaderboardEntry(Contract):
    rank: int = Field(ge=1, description="Competition rank: equal counts share ranks 1, 1, 3.")
    user_id: str = Field(description="Stable opaque board identifier, not an account identifier.")
    display_name: None = Field(description="No public profile is currently stored.")
    avatar_id: None
    avatar_url: None
    verified_count: int = Field(ge=1, description="Distinct server-verified canonical problems.")
    is_me: bool


class LeaderboardMe(Contract):
    rank: int = Field(ge=1)
    verified_count: int = Field(ge=1)


class LeaderboardResponse(Contract):
    entries: list[LeaderboardEntry]
    next_cursor: str | None = Field(description="Opaque continuation, or null at the end.")
    me: LeaderboardMe | None = Field(description="Viewer's position; null for zero completions.")
    generated_at: datetime = Field(description="UTC cutoff retained throughout this pagination.")
