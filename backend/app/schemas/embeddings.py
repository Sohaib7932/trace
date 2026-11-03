"""Internal provider-neutral embeddings, separate from generative completions."""

import hashlib
import math
import struct
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from app.domain.lesson_spec.fields import Digest, Items, Value
from app.support.versioning import canonical_digest

EMBEDDING_MODEL = "gemini-embedding-001"
DIMENSIONS = 768
type EmbeddingPurpose = Literal["document", "query"]
type EmbeddingErrorCode = Literal[
    "disabled",
    "configuration_missing",
    "invalid_request",
    "invalid_response",
    "timeout",
    "authentication_error",
    "rate_limited",
    "budget_exhausted",
    "transport_error",
    "request_too_large",
    "response_too_large",
    "concurrency_limit",
    "accounting_unavailable",
]
type Nonnegative = Annotated[StrictInt, Field(ge=0)]


class EmbeddingProfile(Value):
    schema_version: Literal["embedding-space-v1"] = "embedding-space-v1"
    provider_id: Literal["gemini"] = "gemini"
    model_id: Literal["gemini-embedding-001"] = "gemini-embedding-001"
    dimensions: Literal[768] = 768
    document_task: Literal["RETRIEVAL_DOCUMENT"] = "RETRIEVAL_DOCUMENT"
    query_task: Literal["RETRIEVAL_QUERY"] = "RETRIEVAL_QUERY"
    document_renderer: Literal["title-plus-passage-v1"] = "title-plus-passage-v1"
    query_renderer: Literal["exact-question-v1"] = "exact-question-v1"
    normalization: Literal["finite-l2-f32-v1"] = "finite-l2-f32-v1"
    api_profile: Literal["gemini-developer-v1beta-standard-v1"] = (
        "gemini-developer-v1beta-standard-v1"
    )

    @property
    def space_sha256(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_vector(values: tuple[float, ...]) -> tuple[float, ...]:
    """Normalize before float32 storage; reject booleans/nonfinite/zero/wrong dimensions."""
    if len(values) != DIMENSIONS or any(
        type(value) not in {int, float} or not math.isfinite(value) for value in values
    ):
        raise ValueError("Invalid embedding vector")
    scale = max(abs(value) for value in values)
    if scale == 0:
        raise ValueError("Zero embeddings are invalid")
    scaled = tuple(value / scale for value in values)
    norm = math.sqrt(math.fsum(value * value for value in scaled))
    return tuple(struct.unpack("!f", struct.pack("!f", value / norm))[0] for value in scaled)


def vector_digest(values: tuple[float, ...]) -> str:
    return hashlib.sha256(struct.pack(f"!{len(values)}f", *values)).hexdigest()


class UnitEmbedding(Value):
    values: Items[float] = Field(min_length=768, max_length=768, repr=False)
    vector_sha256: Digest

    @model_validator(mode="after")
    def normalized_integrity(self) -> Self:
        if (
            any(not math.isfinite(value) for value in self.values)
            or not math.isclose(
                math.fsum(value * value for value in self.values), 1.0, abs_tol=1e-5
            )
            or any(
                value != struct.unpack("!f", struct.pack("!f", value))[0] for value in self.values
            )
            or vector_digest(self.values) != self.vector_sha256
        ):
            raise ValueError("Vector values, normalization and digest must agree")
        return self

    @classmethod
    def from_raw(cls, values: tuple[float, ...]) -> "UnitEmbedding":
        normalized = normalized_vector(values)
        return cls(values=normalized, vector_sha256=vector_digest(normalized))


class EmbeddingRequest(Value):
    profile: EmbeddingProfile = Field(default_factory=EmbeddingProfile)
    purpose: EmbeddingPurpose
    texts: Items[str] = Field(min_length=1, max_length=100, repr=False)
    connect_timeout_seconds: float = Field(gt=0, le=10)
    response_timeout_seconds: float = Field(gt=0, le=30)
    max_response_bytes: int = Field(ge=4096, le=4194304)

    @model_validator(mode="after")
    def bounded_text(self) -> Self:
        for text in self.texts:
            if not text.strip() or len(text.encode("utf-8")) > 2000 or "\x00" in text:
                raise ValueError("Embedding inputs must be bounded nonblank UTF-8 text")
        if len(self.model_dump_json().encode("utf-8")) > 65536:
            raise ValueError("Embedding request exceeds its byte budget")
        return self


class EmbeddingTransportResult(Value):
    vectors: Items[Items[float]] = Field(min_length=1, max_length=100, repr=False)
    input_tokens: Nonnegative | None = None
    observed_provider_revision: str | None = Field(default=None, max_length=120)


class EmbeddingBatchResult(Value):
    status: Literal["success", "unavailable"]
    profile: EmbeddingProfile = Field(default_factory=EmbeddingProfile)
    purpose: EmbeddingPurpose
    input_sha256: Items[Digest] = Field(max_length=100)
    vectors: Items[UnitEmbedding] = Field(default=(), max_length=100, repr=False)
    source: Literal["ai", "test_fixture", "unavailable"]
    error_code: EmbeddingErrorCode | None = None
    input_tokens: Nonnegative | None = None
    observed_provider_revision: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        if self.status == "success":
            if (
                not self.input_sha256
                or len(self.vectors) != len(self.input_sha256)
                or self.error_code is not None
                or self.source == "unavailable"
            ):
                raise ValueError("Successful embeddings require exact input/vector correspondence")
        elif self.vectors or self.source != "unavailable" or self.error_code is None:
            raise ValueError("Unavailable embeddings cannot supply vectors")
        return self


class EmbeddingUsage(Value):
    attempts: Nonnegative
    input_items: Nonnegative
    reserved_input_token_estimate: Nonnegative
    observed_input_tokens: Nonnegative
    missing_usage_count: Nonnegative
    successful_batches: Nonnegative
    in_flight: Nonnegative
    closed: bool


class EmbeddingIndexMetadata(Value):
    schema_version: Literal["embedding-index-v1"] = "embedding-index-v1"
    profile: EmbeddingProfile = Field(default_factory=EmbeddingProfile)
    created_at: AwareDatetime
    adapter_version: Literal["google-genai-2-34-standard-embedding-v1"] = (
        "google-genai-2-34-standard-embedding-v1"
    )
    observed_provider_revision: str | None = Field(default=None, max_length=120)
    source: Literal["ai", "test_fixture"]
    scope: Literal["benchmark", "production_candidate"] = "benchmark"

    @model_validator(mode="after")
    def fixture_scope(self) -> Self:
        if self.source == "test_fixture" and self.scope != "benchmark":
            raise ValueError("Mock vector artifacts cannot become production candidates")
        return self
