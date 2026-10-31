import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.domain.clock import as_utc

RETRIEVAL_DAYS = (1, 7)


@dataclass(frozen=True)
class RetrievalQuestion:
    id: str
    title: str
    prompt: str
    payload: str
    schema_code: str
    options: tuple[str, str, str]
    answer: str
    explanation: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.__dict__, sort_keys=True).encode()).hexdigest()


QUESTIONS = (
    RetrievalQuestion(
        "shipping-contract-v1",
        "Recall the shipment contract",
        (
            "The shipment request contains all the intended values but is "
            "rejected. Which diagnosis fits the receiving contract?"
        ),
        '{"reference":"PKG-42","zone":"east"}',
        (
            "class Destination(BaseModel):\n    zone: str\n\nclass "
            "ShipmentCreate(BaseModel):\n    reference: str\n    destination: "
            "Destination"
        ),
        (
            "Any request containing zone must be accepted.",
            "The zone value is at a different JSON level than the schema expects.",
            "A rejected request proves that the database is down.",
        ),
        "b",
        (
            "Values and structure both matter. The receiving contract places "
            "zone inside destination; a flat zone does not satisfy that "
            "nested object."
        ),
    ),
    RetrievalQuestion(
        "report-contract-v1",
        "Recall the report mapping",
        (
            "A report form provides name and format. Which mapping change "
            "preserves the information and satisfies the contract?"
        ),
        '{"name":"Weekly digest","format":"csv"}',
        (
            'class Output(BaseModel):\n    format: Literal["csv", "json"]\n\n'
            "class ReportCreate(BaseModel):\n    name: str\n    output: Output"
        ),
        (
            "Place format inside an output object and retain name at the root.",
            "Rename format to body and keep it at the root.",
            "Send the unchanged JSON as a string instead of an object.",
        ),
        "a",
        (
            "Trace each value into its receiving location. The contract "
            "expects output.format, while name remains at the root. A rename "
            "or string conversion does not supply that object."
        ),
    ),
)


@dataclass(frozen=True)
class RetrievalCheckpoint:
    id: UUID
    transfer_session_id: UUID
    ordinal: int
    question_id: str
    question_hash: str
    due_at: datetime
    created_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True)
class RetrievalAttempt:
    id: UUID
    checkpoint_id: UUID
    number: int
    selection: str
    reasoning: str
    correct: bool
    feedback: str
    idempotency_key: str
    created_at: datetime


def due_at(completed: datetime, ordinal: int) -> datetime:
    return as_utc(completed) + timedelta(days=RETRIEVAL_DAYS[ordinal - 1])


def checkpoint_status(checkpoint: RetrievalCheckpoint, now: datetime) -> str:
    if checkpoint.completed_at is not None:
        return "completed"
    return "due" if as_utc(now) >= checkpoint.due_at else "upcoming"


def question_for(checkpoint: RetrievalCheckpoint) -> RetrievalQuestion:
    question = next(q for q in QUESTIONS if q.id == checkpoint.question_id)
    if question.content_hash != checkpoint.question_hash:
        raise ValueError("A published retrieval question changed without a new version")
    return question
