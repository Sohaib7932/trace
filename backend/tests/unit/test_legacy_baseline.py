"""Frozen legacy values and the complete domain transition matrix."""

from itertools import product

import pytest

from app.domain.learning import LearningError, SessionState, transition
from app.domain.retrieval import QUESTIONS
from app.services.catalog import PUBLIC_CONTENT, TRANSFER_CONTENT, lesson_hash, transfer_hash

LESSON_HASHES = {
    "fastapi-payload-mismatch": (
        "c3231631019829efe5cd1882b361cf22b8bdcdd51caca2a67a60dd73b326707e"
    ),
    "fastapi-nested-payload-transfer": (
        "c4aefadd5f468da2505db0d14cd4d12bdc1f707282d241a10118cae39c49db0d"
    ),
}
QUESTION_HASHES = {
    "shipping-contract-v1": "da5d78e3b8be1ecdbb0ceb676b76410a95d43fb129e83dbb464e4383a5fffffc",
    "report-contract-v1": "434e8c383810cea431f30bd605c3601cc5dcb68c81acb77d6fd1c864600ff9ef",
}


def test_legacy_lesson_hashes_are_literal_compatibility_fixtures() -> None:
    assert (
        lesson_hash(PUBLIC_CONTENT, "content", "rejected")
        == LESSON_HASHES["fastapi-payload-mismatch"]
    )
    assert transfer_hash(TRANSFER_CONTENT) == LESSON_HASHES["fastapi-nested-payload-transfer"]


def test_legacy_retrieval_questions_keep_their_ids_and_literal_hashes() -> None:
    assert {question.id: question.content_hash for question in QUESTIONS} == QUESTION_HASHES


@pytest.mark.parametrize("source,target", list(product(SessionState, repeat=2)))
@pytest.mark.parametrize("verified", [False, True])
def test_every_legacy_domain_transition(source, target, verified) -> None:
    ordinary = {
        ("awaiting_prediction", "ready_for_attempt"),
        ("ready_for_attempt", "verification_pending"),
        ("verification_pending", "needs_revision"),
        ("needs_revision", "verification_pending"),
    }
    allowed = (
        (source, target) in ordinary
        or (source == "verification_pending" and target == "completed" and verified)
        or (source not in {"completed", "abandoned"} and target == "abandoned")
    )
    if allowed:
        assert transition(source, target, verified=verified) == target.value
    else:
        with pytest.raises(LearningError, match="current state|observed verification"):
            transition(source, target, verified=verified)
