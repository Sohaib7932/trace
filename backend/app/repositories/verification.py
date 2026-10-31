from typing import Protocol
from uuid import UUID

from app.domain.learning import Observation


class NotesVerifier(Protocol):
    def observe(self, run_id: UUID, field_name: str) -> Observation: ...
