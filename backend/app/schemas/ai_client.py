"""Transport-only metadata and bounded results; never learner correctness claims."""

from typing import Annotated, Literal

from pydantic import Field, StrictInt

from app.domain.lesson_spec.fields import Value
from app.schemas.generation import CompletionStatus, TransportIdentifier, captured_text

type Capability = Literal["generation", "tutor", "support"]
type Count = Annotated[StrictInt, Field(ge=0, le=1_000_000_000)]
type ClientErrorCode = Literal[
    "disabled",
    "configuration_missing",
    "timeout",
    "authentication_error",
    "rate_limited",
    "transient_error",
    "invalid_request",
    "budget_exhausted",
    "request_too_large",
    "response_too_large",
    "token_limit",
    "invalid_response",
    "transport_error",
]


class ClientCompletion(Value):
    status: CompletionStatus
    text: str | None = Field(default=None, repr=False)
    provider_id: TransportIdentifier
    requested_model_id: TransportIdentifier | None = None
    returned_model_id: TransportIdentifier | None = None
    request_id: TransportIdentifier | None = None
    source: Literal["test_fixture", "ai"] = "test_fixture"
    error_code: ClientErrorCode | None = None


class TransportRequest(Value):
    capability: Capability
    instructions: str = Field(min_length=1, max_length=12000, repr=False)
    data_json: str = Field(min_length=2, max_length=65536, repr=False)
    output_schema_json: str | None = Field(default=None, max_length=65536, repr=False)
    requested_model_id: TransportIdentifier | None
    max_input_tokens: Count
    max_output_tokens: Count
    max_response_bytes: Count
    connect_timeout_seconds: float
    response_timeout_seconds: float


class TransportCompletion(Value):
    status: Literal["success", "refusal", "truncated"] = "success"
    text: str | None = Field(default=None, repr=False)
    returned_model_id: TransportIdentifier | None = None
    request_id: TransportIdentifier | None = None
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    cost_microusd: Count | None = None

    def checked_text(self) -> str | None:
        return captured_text(self.text) if self.text is not None else None


class UsageRecord(Value):
    capability: Capability
    model_id: TransportIdentifier | None
    attempts: Count
    input_tokens: Count
    output_tokens: Count
    accounted_cost_microusd: Count
    missing_usage_count: Count
