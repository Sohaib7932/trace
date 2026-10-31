import json
from typing import Annotated
from uuid import UUID

import anyio
import httpx2
from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from app.domain.learning import NOTE_CONTENT, NOTE_TITLE, LearningError, Observation
from app.repositories.learning import LearningRepository
from app.services.notes import NotesService


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2000)


class SavedNote(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    content: str


def create_notes_app(repository: LearningRepository, run_id: UUID) -> FastAPI:
    """Private real FastAPI route: normal validation, dependency and committed service write."""
    app = FastAPI(title="Controlled notes exercise", docs_url=None, openapi_url=None)

    def notes_service() -> NotesService:
        return NotesService(repository, run_id)

    @app.post("/notes", response_model=SavedNote, status_code=201)
    def save_note(
        note: NoteCreate, service: Annotated[NotesService, Depends(notes_service)]
    ) -> SavedNote:
        return SavedNote.model_validate(service.create(note.title, note.content))

    return app


class AsgiNotesVerifier:
    def __init__(self, repository: LearningRepository, timeout_seconds: float) -> None:
        self.repository, self.timeout_seconds = repository, timeout_seconds

    def observe(self, run_id: UUID, field_name: str) -> Observation:
        # Called from the public synchronous endpoint's worker, never a public TCP self-call.
        status, body = anyio.run(self._request, run_id, field_name)
        codes: tuple[str, ...] = ()
        response_id: str | None = None
        if isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, list):
                codes = tuple(
                    f"{item['type']}:{item['loc'][-1]}"
                    for item in detail
                    if isinstance(item, dict) and item.get("loc") and item.get("type")
                )
            if isinstance(body.get("id"), str):
                response_id = body["id"]
        # A distinct repository context creates a new SQLAlchemy session/transaction.
        # Failed readback is unavailable evidence, NEVER an invented zero-row observation.
        try:
            with self.repository.read() as store:
                notes = store.notes(run_id)
        except LearningError:
            notes = None
        return Observation(status, json.dumps(body, sort_keys=True), codes, notes, response_id)

    async def _request(self, run_id: UUID, field_name: str) -> tuple[int, object]:
        app = create_notes_app(self.repository, run_id)
        transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://controlled-exercise", timeout=self.timeout_seconds
        ) as client:
            with anyio.fail_after(self.timeout_seconds):
                response = await client.post(
                    "/notes", json={"title": NOTE_TITLE, field_name: NOTE_CONTENT}
                )
        try:
            body: object = response.json()
        except ValueError:
            body = {"message": "The controlled notes endpoint did not return JSON."}
        return response.status_code, body
