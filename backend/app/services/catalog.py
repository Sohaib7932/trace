import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.learning import LearningError, LessonVersion
from app.repositories.learning import LearningRepository

LESSON_ID = "fastapi-payload-mismatch"
LESSON_VERSION = "1.0.0"
PUBLIC_CONTENT = {
    "title": "Follow the note: from form to database",
    "objective": (
        "Trace a form value through an outgoing request and the receiving "
        "schema, then verify a real save."
    ),
    "scenario": (
        "The notes form says a note was submitted, but nothing is saved. "
        "Inspect the request builder and the receiving FastAPI schema. "
        "Predict the outcome before changing the outgoing mapping."
    ),
    "outgoing_code": (
        'payload = {\n    "title": note.title,\n    "body": note.content,\n}\n'
        'response = client.post("/notes", json=payload)'
    ),
    "schema_code": (
        "from pydantic import BaseModel, ConfigDict\n\nclass "
        "NoteCreate(BaseModel):\n    model_config = "
        'ConfigDict(extra="forbid")\n    title: str\n    content: str'
    ),
}


def lesson_hash(public_content: dict[str, str], expected_field: str, prediction_answer: str) -> str:
    payload = {
        "public_content": public_content,
        "expected_field": expected_field,
        "prediction_answer": prediction_answer,
        "adapter": "notes-v1",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def seed_first_lesson(repository: LearningRepository) -> LessonVersion:
    digest = lesson_hash(PUBLIC_CONTENT, "content", "rejected")
    with repository.write() as store:
        existing = store.version(LESSON_ID, LESSON_VERSION)
        if existing:
            if existing.content_hash != digest:
                raise LearningError(
                    "conflict", "Published lesson content differs; publish a new version."
                )
            return existing
        version = LessonVersion(
            uuid4(),
            LESSON_ID,
            LESSON_VERSION,
            dict(PUBLIC_CONTENT),
            "content",
            "rejected",
            digest,
            datetime.now(UTC),
        )
        store.publish(version)
        return version


class CatalogService:
    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def retrieve(self, lesson_id: str, version: str | None = None) -> LessonVersion:
        with self.repository.read() as store:
            result = store.version(lesson_id, version)
            if result is None:
                raise LearningError("not_found", "Lesson not found.")
            return result
