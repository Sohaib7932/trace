import json
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.learning import VerificationCheck
from app.domain.transfer import (
    TASK_PRIORITY,
    TASK_TITLE,
    TaskObservation,
    response_matches_task,
    task_values_match,
)
from app.repositories.learning import LearningStore


def task_checks(
    store: LearningStore, run_id: UUID, observed: TaskObservation | None, at: datetime
) -> None:
    if observed is None:
        store.add_check(
            VerificationCheck(
                uuid4(),
                run_id,
                "execution",
                False,
                "completed task request and fresh read",
                "dependency_or_execution_failure",
                "verifier",
                at,
            )
        )
        return
    rows = observed.tasks
    stored = (
        json.dumps(
            [{"id": str(t.id), "title": t.title, "priority": t.priority} for t in rows],
            sort_keys=True,
        )
        if rows is not None
        else "unavailable"
    )
    definitions = [
        ("http_status", observed.http_status == 201, "201", str(observed.http_status), "asgi_http"),
        (
            "api_response",
            response_matches_task(observed),
            "validated nested task response",
            observed.response_json,
            "asgi_http",
        ),
        (
            "validation",
            observed.http_status == 201 and not observed.validation_codes,
            "request accepted by nested receiving schema",
            json.dumps(observed.validation_codes),
            "asgi_http",
        ),
        (
            "row_count",
            rows is not None and len(rows) == 1,
            "1",
            str(len(rows)) if rows is not None else "unavailable",
            "fresh_database_read",
        ),
        (
            "stored_values",
            task_values_match(observed),
            json.dumps({"title": TASK_TITLE, "priority": TASK_PRIORITY}, sort_keys=True),
            stored,
            "fresh_database_read",
        ),
    ]
    for code, matched, expected, actual, source in definitions:
        store.add_check(
            VerificationCheck(uuid4(), run_id, code, matched, expected, actual, source, at)
        )
