import base64
import binascii
import hashlib
import json
import re
from datetime import datetime
from uuid import UUID

from app.core.errors import ApplicationError
from app.domain.accounts import Account
from app.domain.clock import Clock, as_utc, utc_now
from app.repositories.leaderboard import LeaderboardRepository
from app.schemas.leaderboard import LeaderboardEntry, LeaderboardMe, LeaderboardResponse

_CURSOR = re.compile(r"[A-Za-z0-9_-]{1,512}\Z")
_MAX_OFFSET = 1_000_000_000


def board_identifier(user_id: UUID) -> str:
    """Separate this read-only pseudonym from account, learner and provider identifiers."""
    return hashlib.sha256(b"trace:leaderboard:v1\0" + user_id.bytes).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Duplicate cursor field")
    return value


def _decode_cursor(cursor: str, now: datetime) -> tuple[datetime, int]:
    try:
        if not _CURSOR.fullmatch(cursor):
            raise ValueError("Invalid cursor encoding")
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {"as_of", "offset"}:
            raise ValueError("Invalid cursor fields")
        offset, stamp = data["offset"], data["as_of"]
        if type(offset) is not int or not 0 <= offset <= _MAX_OFFSET or not isinstance(stamp, str):
            raise ValueError("Invalid cursor values")
        at = as_utc(datetime.fromisoformat(stamp))
        if at > now:
            raise ValueError("Future cursor")
        return at, offset
    except (ValueError, TypeError, binascii.Error, OverflowError, RecursionError):
        raise ApplicationError("validation_error", "Invalid leaderboard cursor.", 422) from None


def _encode_cursor(at: datetime, offset: int) -> str:
    raw = json.dumps({"as_of": at.isoformat(), "offset": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class LeaderboardService:
    def __init__(self, repository: LeaderboardRepository, clock: Clock = utc_now) -> None:
        self.repository, self.clock = repository, clock

    def page(self, account: Account, cursor: str | None, limit: int) -> LeaderboardResponse:
        account.require_role("learner")
        if not 1 <= limit <= 50:
            raise ApplicationError("validation_error", "Invalid leaderboard page size.", 422)
        now = as_utc(self.clock())
        at, offset = _decode_cursor(cursor, now) if cursor is not None else (now, 0)
        board = self.repository.page(account.id, at, offset, limit)
        return LeaderboardResponse(
            entries=[
                LeaderboardEntry(
                    rank=row.rank,
                    user_id=board_identifier(row.user_id),
                    display_name=None,
                    avatar_id=None,
                    avatar_url=None,
                    verified_count=row.verified_count,
                    is_me=row.user_id == account.id,
                )
                for row in board.entries
            ],
            next_cursor=_encode_cursor(at, offset + len(board.entries)) if board.has_more else None,
            me=LeaderboardMe(rank=board.me.rank, verified_count=board.me.verified_count)
            if board.me is not None
            else None,
            generated_at=at,
        )
