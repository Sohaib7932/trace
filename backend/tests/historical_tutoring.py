"""Test-only compatibility for exercising current handlers on pre-reservation schemas.

Historical schemas have real immutable TutorInteraction rows but no operation
table. Keep only the new transient reservation port in memory while all original
HTTP validation, tutor interaction writes, events and database readbacks stay real.
Running application code has no missing-table fallback.
"""

from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

from app.db.learning import SqlLearningStore


@contextmanager
def historical_hint_operations():
    operations = {}

    def list_operations(store, session_id):
        return sorted(
            (operation for operation in operations.values() if operation.session_id == session_id),
            key=lambda operation: operation.sequence,
        )

    def add_operation(store, operation):
        if operation.id in operations or any(
            saved.session_id == operation.session_id
            and (
                saved.sequence == operation.sequence
                or saved.idempotency_key == operation.idempotency_key
            )
            for saved in operations.values()
        ):
            raise AssertionError("Historical operation fixture received duplicate identity")
        operations[operation.id] = operation

    def finish_operation(store, operation_id, at):
        operation = operations[operation_id]
        assert operation.status == "pending"
        operations[operation_id] = replace(operation, status="finalized", completed_at=at)

    with (
        patch.object(SqlLearningStore, "hint_operations", list_operations),
        patch.object(SqlLearningStore, "add_hint_operation", add_operation),
        patch.object(SqlLearningStore, "finish_hint_operation", finish_operation),
    ):
        yield
