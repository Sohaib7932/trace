"""Internal source-version receipts; never an expanded public response contract."""

import hashlib
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.domain.lesson_spec.fields import Digest, Items, Value
from app.schemas.support import SupportResponse
from app.support.versioning import ApprovedSupportPassageVersion


class VersionedSupportAnswer(Value):
    model_config = ConfigDict(revalidate_instances="always")

    response: SupportResponse = Field(repr=False)
    manifest_sha256: Digest | None = None
    passages: Items[ApprovedSupportPassageVersion] = Field(default=(), max_length=3)
    retrieval_profile: Literal["lexical", "semantic", "hybrid"] = "lexical"
    index_sha256: Digest | None = None

    @field_validator("response", mode="before")
    @classmethod
    def recheck_response(cls, value: object) -> object:
        if isinstance(value, SupportResponse):
            return value.model_dump(mode="json", warnings=False)
        return value

    @model_validator(mode="after")
    def exact_references(self) -> "VersionedSupportAnswer":
        if (self.retrieval_profile == "lexical") != (self.index_sha256 is None):
            raise ValueError("Vector receipts require a pinned index; lexical receipts do not")
        if self.manifest_sha256 is None:
            if self.passages or self.index_sha256:
                raise ValueError("Version receipts require a manifest")
            return self
        if self.response.status != "answered" or len(self.passages) != len(
            self.response.references
        ):
            raise ValueError("A receipt records only an actually constructed answer")
        for reference, version in zip(self.response.references, self.passages, strict=True):
            if (reference.source_id, reference.passage_id) != (
                version.source_id,
                version.passage_id,
            ) or hashlib.sha256(
                reference.quote.encode("utf-8")
            ).hexdigest() != version.passage_sha256:
                raise ValueError("Receipt versions must match response references")
        return self

    def safe_receipt(self) -> dict[str, object] | None:
        """Allowlisted public source metadata; no question, answer, identity or raw text."""
        if self.manifest_sha256 is None:
            return None
        receipt: dict[str, object] = {
            "schema_version": "support-answer-receipt-v1",
            "manifest_sha256": self.manifest_sha256,
            "passages": [item.model_dump(mode="json") for item in self.passages],
        }
        if self.index_sha256 is not None:
            receipt.update(retrieval_profile=self.retrieval_profile, index_sha256=self.index_sha256)
        return receipt
