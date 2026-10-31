from uuid import UUID

from app.domain.learning import NoteSnapshot
from app.repositories.learning import LearningRepository


class NotesService:
    def __init__(self, repository: LearningRepository, run_id: UUID) -> None:
        self.repository, self.run_id = repository, run_id

    def create(self, title: str, content: str) -> NoteSnapshot:
        with self.repository.write() as store:
            return store.add_note(self.run_id, title, content)
