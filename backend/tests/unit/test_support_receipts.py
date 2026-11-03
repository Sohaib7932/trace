"""Receipt construction rejects forged quotes and bypassed response models."""

import pytest
from pydantic import ValidationError

from app.schemas.support import SupportReference, SupportResponse
from app.support.receipts import VersionedSupportAnswer
from tests.unit.test_support_versioning import sources


def answer():
    snapshot = sources().snapshot()
    source = snapshot.sources[0]
    passage = source.document.passages[0]
    response = SupportResponse(
        status="answered",
        message="Relevant approved documentation is quoted below.",
        source="ai",
        references=(
            SupportReference(
                source_id=source.document.source_id,
                source_name=source.document.title,
                passage_id=passage.passage_id,
                quote=passage.text,
            ),
        ),
    )
    return VersionedSupportAnswer(
        response=response,
        manifest_sha256=snapshot.manifest_sha256,
        passages=(source.passages[0],),
    )


def test_receipt_is_exact_but_does_not_log_approved_text_or_question():
    result = answer()
    receipt = result.safe_receipt()
    assert receipt["manifest_sha256"] == result.manifest_sha256
    assert set(receipt) == {"schema_version", "manifest_sha256", "passages"}
    assert "quote" not in receipt["passages"][0]
    assert "text" not in receipt["passages"][0]


def test_changed_quote_cannot_be_attested_with_a_valid_source_identifier():
    result = answer()
    reference = result.response.references[0].model_copy(
        update={"quote": "Different approved text"}
    )
    response = result.response.model_copy(update={"references": (reference,)})
    with pytest.raises(ValidationError):
        VersionedSupportAnswer(
            response=response, manifest_sha256=result.manifest_sha256, passages=result.passages
        )


def test_bypassed_response_validation_is_not_trusted_by_receipt_constructor():
    result = answer()
    forged = result.response.model_copy(update={"source": "private-secret-provider"})
    with pytest.raises(ValidationError):
        VersionedSupportAnswer(
            response=forged, manifest_sha256=result.manifest_sha256, passages=result.passages
        )


def test_bypassed_top_level_copy_is_rechecked_at_reuse():
    result = answer()
    forged = result.model_copy(update={"manifest_sha256": None})
    with pytest.raises(ValidationError):
        VersionedSupportAnswer.model_validate(forged)


def test_unversioned_fixture_and_unavailable_answers_cannot_claim_a_version_receipt():
    result = answer()
    fixture = VersionedSupportAnswer(response=result.response)
    assert fixture.safe_receipt() is None
    unavailable = SupportResponse(
        status="unavailable",
        message="Customer support is currently unavailable.",
        source="unavailable",
    )
    with pytest.raises(ValidationError):
        VersionedSupportAnswer(
            response=unavailable, manifest_sha256=result.manifest_sha256, passages=result.passages
        )
