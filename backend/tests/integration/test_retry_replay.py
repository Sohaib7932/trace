from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_notes_verifier
from app.db.learning import SqlLearningRepository
from app.db.session import Database
from app.domain.learning import VerificationRun
from tests.integration.test_learning import attempt, predict, start, verify


def test_final_error_replay_is_stable_while_another_retry_is_pending(
    learner: TestClient, database: Database, learning_app: FastAPI
) -> None:
    class Broken:
        def observe(self, run_id, field):
            raise RuntimeError("test interruption")

    learning_app.dependency_overrides[get_notes_verifier] = lambda: Broken()
    session = start(learner)
    predict(learner, session)
    submitted = attempt(learner, session, "content")
    original_key = str(uuid4())
    original = verify(learner, session, submitted["id"], original_key).json()
    assert original["status"] == "error"
    with SqlLearningRepository(database).write() as store:
        store.add_run(
            VerificationRun(
                uuid4(),
                UUID(session),
                UUID(submitted["id"]),
                "pending",
                str(uuid4()),
                datetime.now(UTC),
            )
        )
    replay = verify(learner, session, submitted["id"], original_key)
    assert replay.status_code == 200 and replay.json() == original
