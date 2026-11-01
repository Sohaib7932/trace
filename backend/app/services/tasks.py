from uuid import UUID

from app.domain.transfer import TaskSnapshot
from app.repositories.exercise import ExerciseRepository


class TasksService:
    def __init__(self, repository: ExerciseRepository, run_id: UUID) -> None:
        self.repository, self.run_id = repository, run_id

    def create(self, title: str, priority: str) -> TaskSnapshot:
        with self.repository.write() as store:
            return store.add_task(self.run_id, title, priority)
