from typing import Protocol
from uuid import UUID

from app.domain.learning import Observation
from app.domain.transfer import TaskObservation


class NotesVerifier(Protocol):
    def observe(self, run_id: UUID, field_name: str) -> Observation: ...


class TasksVerifier(Protocol):
    def observe(self, run_id: UUID, mapping: str) -> TaskObservation: ...
