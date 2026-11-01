"""The narrow storage boundary needed by trusted exercise apps and verifiers.

Learner repositories structurally satisfy this port; isolated candidate storage
can implement it without acquiring any learner-history operations.
"""

from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from app.domain.learning import NoteSnapshot
from app.domain.transfer import TaskSnapshot


class ExerciseStore(Protocol):
    def add_note(self, run_id: UUID, title: str, content: str) -> NoteSnapshot: ...

    def notes(self, run_id: UUID) -> tuple[NoteSnapshot, ...]: ...

    def add_task(self, run_id: UUID, title: str, priority: str) -> TaskSnapshot: ...

    def tasks(self, run_id: UUID) -> tuple[TaskSnapshot, ...]: ...


class ExerciseRepository(Protocol):
    def read(self) -> AbstractContextManager[ExerciseStore]: ...

    def write(self) -> AbstractContextManager[ExerciseStore]: ...
