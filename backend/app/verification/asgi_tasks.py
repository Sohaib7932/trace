import json
from typing import Annotated, Literal
from uuid import UUID

import anyio
import httpx2
from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from app.domain.learning import LearningError
from app.domain.transfer import TASK_PRIORITY, TASK_TITLE, TaskObservation
from app.repositories.learning import LearningRepository
from app.services.tasks import TasksService


class TaskMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: Literal["low", "normal", "high"]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    metadata: TaskMetadata


class SavedTask(BaseModel):
    id: UUID
    title: str
    metadata: TaskMetadata


def create_tasks_app(repository: LearningRepository, run_id: UUID) -> FastAPI:
    app = FastAPI(title="Controlled task exercise", docs_url=None, openapi_url=None)

    def tasks_service() -> TasksService:
        return TasksService(repository, run_id)

    @app.post("/tasks", response_model=SavedTask, status_code=201)
    def save_task(
        task: TaskCreate, service: Annotated[TasksService, Depends(tasks_service)]
    ) -> SavedTask:
        saved = service.create(task.title, task.metadata.priority)
        return SavedTask(
            id=saved.id,
            title=saved.title,
            metadata=TaskMetadata.model_validate({"priority": saved.priority}),
        )

    return app


class AsgiTasksVerifier:
    def __init__(self, repository: LearningRepository, timeout_seconds: float) -> None:
        self.repository, self.timeout_seconds = repository, timeout_seconds

    def observe(self, run_id: UUID, mapping: str) -> TaskObservation:
        status, body = anyio.run(self._request, run_id, mapping)
        codes: tuple[str, ...] = ()
        response_id: str | None = None
        if isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, list):
                codes = tuple(
                    f"{item['type']}:{item['loc'][-1]}"
                    for item in detail
                    if isinstance(item, dict) and item.get("type") and item.get("loc")
                )
            if isinstance(body.get("id"), str):
                response_id = body["id"]
        try:
            with self.repository.read() as store:
                tasks = store.tasks(run_id)
        except LearningError:
            tasks = None
        return TaskObservation(status, json.dumps(body, sort_keys=True), codes, tasks, response_id)

    async def _request(self, run_id: UUID, mapping: str) -> tuple[int, object]:
        payload: dict[str, object] = {"title": TASK_TITLE}
        if mapping == "nested":
            payload["metadata"] = {"priority": TASK_PRIORITY}
        else:
            payload["priority"] = TASK_PRIORITY
        transport = httpx2.ASGITransport(
            app=create_tasks_app(self.repository, run_id), raise_app_exceptions=False
        )
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://controlled-exercise", timeout=self.timeout_seconds
        ) as client:
            with anyio.fail_after(self.timeout_seconds):
                response = await client.post("/tasks", json=payload)
        try:
            body: object = response.json()
        except ValueError:
            body = {"message": "The controlled task endpoint did not return JSON."}
        return response.status_code, body
