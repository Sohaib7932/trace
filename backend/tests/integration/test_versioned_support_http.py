"""Public contract stays stable while release receipts bind exact approved versions."""

import io
import json
import logging

from app.core.logging import JsonFormatter
from tests.integration.test_live_ai_http import api as api  # noqa: F401
from tests.integration.test_live_ai_http import support


def capture_receipts(api):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    api.app.state.logger.addHandler(handler)
    return stream


def receipts(stream):
    return [
        event
        for line in stream.getvalue().splitlines()
        if (event := json.loads(line))["event"] == "support_answer_released"
    ]


def test_answer_release_is_traceable_to_exact_version_without_logging_question_or_quote(api):
    stream = capture_receipts(api)
    response = support(api)
    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    (event,) = receipts(stream)
    assert event["request_id"] == response.headers["X-Request-ID"]
    receipt = event["support_provenance"]
    snapshot = api.knowledge.snapshot()
    assert receipt["manifest_sha256"] == snapshot.manifest_sha256
    (version,) = receipt["passages"]
    (reference,) = response.json()["references"]
    assert version["revision"] == api.state.package.revision
    assert (version["source_id"], version["passage_id"]) == (
        reference["source_id"],
        reference["passage_id"],
    )
    serialized = json.dumps(event)
    assert reference["quote"] not in serialized
    assert "How does password recovery work?" not in serialized
    assert str(api.signer.subject) not in serialized
    assert "reviewed_by" not in serialized
    assert set(reference) == {"source_id", "source_name", "passage_id", "quote"}


def test_identical_text_under_new_revision_cannot_release_a_stale_provider_selection(api):
    stream = capture_receipts(api)
    previous = api.knowledge.snapshot()

    def revise():
        api.state.package = api.state.package.model_copy(update={"revision": "1.0.1"})

    api.provider.callback = revise
    response = support(api)
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert not response.json()["references"]
    assert api.knowledge.snapshot().manifest_sha256 != previous.manifest_sha256
    assert not receipts(stream)


def test_source_revocation_during_provider_work_blocks_release_and_receipt(api):
    stream = capture_receipts(api)

    def revoke():
        api.state.package = api.state.package.model_copy(
            update={"revoked_source_ids": ("registration-authentication",)}
        )

    api.provider.callback = revoke
    response = support(api)
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert not response.json()["references"]
    assert not api.knowledge.available
    assert not receipts(stream)
