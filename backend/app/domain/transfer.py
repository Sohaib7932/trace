import json
from dataclasses import dataclass
from uuid import UUID

from app.domain.learning import Evaluation

TRANSFER_ID = "fastapi-nested-payload-transfer"
TASK_TITLE = "Prepare the product demo"
TASK_PRIORITY = "high"


@dataclass(frozen=True)
class TaskSnapshot:
    id: UUID
    title: str
    priority: str


@dataclass(frozen=True)
class TaskObservation:
    http_status: int | None
    response_json: str
    validation_codes: tuple[str, ...]
    tasks: tuple[TaskSnapshot, ...] | None
    response_task_id: str | None


def response_matches_task(observed: TaskObservation) -> bool:
    try:
        body = json.loads(observed.response_json)
    except (ValueError, TypeError):
        return False
    return (
        observed.http_status == 201
        and not observed.validation_codes
        and observed.response_task_id is not None
        and isinstance(body, dict)
        and body.get("id") == observed.response_task_id
        and body.get("title") == TASK_TITLE
        and body.get("metadata") == {"priority": TASK_PRIORITY}
    )


def task_values_match(observed: TaskObservation) -> bool:
    rows = observed.tasks
    return bool(
        rows is not None
        and len(rows) == 1
        and rows[0].title == TASK_TITLE
        and rows[0].priority == TASK_PRIORITY
        and str(rows[0].id) == observed.response_task_id
    )


def evaluate_transfer(mapping: str, expected: str, observed: TaskObservation) -> Evaluation:
    if observed.http_status is None or observed.tasks is None or observed.http_status >= 500:
        return Evaluation(
            "error", "Task verification was unavailable. This is not a learner mistake."
        )
    if (
        mapping != expected
        and observed.http_status == 422
        and not observed.tasks
        and {"missing:metadata", "extra_forbidden:priority"} <= set(observed.validation_codes)
    ):
        return Evaluation(
            "failed",
            (
                "The information is present at the wrong level. The nested schema "
                "rejected the flat request; no task was saved."
            ),
        )
    if mapping == expected and response_matches_task(observed) and task_values_match(observed):
        return Evaluation(
            "passed",
            (
                "The nested request matches the receiving contract. A fresh read "
                "confirmed the committed task and priority."
            ),
        )
    return Evaluation(
        "error",
        (
            "Task response and fresh database evidence are inconsistent. No "
            "learner grade was assigned."
        ),
    )
