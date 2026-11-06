"""Invalid support context fails before worker admission or any provider call."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.dependencies import get_support_operations
from app.db import knowledge_models as k
from tests.integration.test_knowledge_admin_http import admin_api as admin_api  # noqa: F401
from tests.integration.test_knowledge_archive import archive as archive  # noqa: F401
from tests.integration.test_live_ai_http import api as api  # noqa: F401


@pytest.mark.parametrize(
    "body",
    [
        {"question": "Why is token: none displayed?"},
        {
            "question": "What about that warning?",
            "history": [{"role": "user", "text": "Why is token: none displayed?"}],
        },
        {
            "question": "What about that warning?",
            "history": [
                {"role": "user", "text": "token:"},
                {"role": "assistant", "text": "A placeholder is displayed."},
            ],
        },
    ],
)
def test_invalid_composed_question_is_422_before_worker_admission(api, body):
    execute = AsyncMock(side_effect=AssertionError("No worker should be admitted"))
    api.app.dependency_overrides[get_support_operations] = lambda: SimpleNamespace(
        execute_account=execute
    )
    response = api.client.post("/api/v1/support/ask", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"] == []
    assert response.headers["cache-control"] == "no-store"
    assert body["question"] not in response.text
    assert "token:" not in response.text and "A placeholder" not in response.text
    execute.assert_not_awaited()
    assert not api.provider.calls


def test_valid_support_question_still_uses_existing_grounded_pipeline(api):
    response = api.client.post(
        "/api/v1/support/ask", json={"question": "How does password recovery work?"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["references"]
    assert len(api.provider.calls) == 1


@pytest.mark.parametrize("field", ["title", "passage"])
def test_admin_source_credentials_are_rejected_without_echo_or_persistence(admin_api, field):
    # Synthetic canary only; no real credential is ever loaded or submitted.
    synthetic = "AIza" + "A" * 35
    document = admin_api.archive.package.documents[0].model_dump(mode="json")
    if field == "title":
        document["title"] = synthetic
    else:
        document["passages"][0]["text"] = synthetic
    response = admin_api.client.post(
        "/api/v1/admin/knowledge/revisions",
        headers={"Authorization": "Bearer " + admin_api.signer.token()},
        json={"document": document, "revision": "2.0.0", "operation_key": str(uuid4())},
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "validation_error"
    assert synthetic not in response.text
    with admin_api.archive.database.session() as session:
        assert session.scalar(select(func.count()).select_from(k.KnowledgeRevisionRow)) == 0
