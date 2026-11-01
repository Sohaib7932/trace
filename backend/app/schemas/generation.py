"""Generation copy contracts, server briefs and untrusted transport completions.

These models neither define an exercise nor admit content for release. Slot,
variant and wording keys are bounded references supplied by a server-built brief;
checking generated references against that brief belongs to the admission layer.
"""

import re
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StrictInt, model_validator

from app.domain.lesson_spec.fields import Items, LocalId, Value, plain_text

MAX_GENERATED_CONTENT_BYTES = 16 * 1024
# Transport may capture an oversized or malformed response for later rejection.
# This separate capture ceiling is not the valid-content or raw admission limit.
MAX_COMPLETION_CAPTURE_BYTES = 64 * 1024


def educational_copy(value: str) -> str:
    """Plain-copy syntax guards, not semantic or template-aware admission."""
    plain_text(value)
    if "`" in value or "~~~" in value:
        raise ValueError("Code markup is not educational copy")
    patterns = (
        r"(?m)^(?: {4}|\t)\S",  # Indented Markdown code blocks.
        r"(?m)^\s*(?:from\s+\S+\s+import\b|import\s+\w|(?:async\s+)?def\s|class\s+\w)",
        r"(?m)^\s*(?:if|elif|for|while|with)\b[^\n]*:\s*(?:$|\S)",
        r"(?m)^\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*=(?!=)",
        r"\b(?:eval|exec|compile|__import__|open|print)\s*\(",
        r"\b[A-Za-z_]\w*\.[A-Za-z_]\w*\s*\(",
        r"(?im)^\s*(?:\$\s*)?(?:bash|sh|zsh|powershell(?:\.exe)?|pwsh|cmd(?:\.exe)?|curl|wget|sudo|rm|del|Remove-Item|Invoke-Expression)\b",
        r"\$\(|&&|\|\s*(?:bash|sh|powershell|pwsh)\b",
        r"(?i)\b(?:SELECT\s+\*\s+FROM|INSERT\s+INTO|DELETE\s+FROM|DROP\s+TABLE|CREATE\s+TABLE|ALTER\s+TABLE|UPDATE\s+\w+\s+SET)\b",
    )
    if any(re.search(pattern, value) for pattern in patterns):
        raise ValueError("Executable or query syntax is not educational copy")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Educational copy must be valid UTF-8") from exc
    return value


type ContractVersion = Literal["1.0.0"]
type TemplateFamily = Literal["notes-v1", "tasks-nested-v1"]
type CopyTitle = Annotated[
    str, Field(min_length=1, max_length=120), AfterValidator(educational_copy)
]
type CopyDescription = Annotated[
    str, Field(min_length=1, max_length=600), AfterValidator(educational_copy)
]
type CopyStatement = Annotated[
    str, Field(min_length=1, max_length=600), AfterValidator(educational_copy)
]
type CopyNarrative = Annotated[
    str, Field(min_length=1, max_length=2000), AfterValidator(educational_copy)
]
type CopyPrompt = Annotated[
    str, Field(min_length=1, max_length=1000), AfterValidator(educational_copy)
]
type CopyHint = Annotated[
    str, Field(min_length=1, max_length=500), AfterValidator(educational_copy)
]
type CopyFraming = Annotated[
    str, Field(min_length=1, max_length=1000), AfterValidator(educational_copy)
]
type EvidenceCount = Annotated[StrictInt, Field(ge=0, le=10000)]
type InstructionalFact = Literal[
    "request-receiver-contract",
    "validation-before-persistence",
    "independent-readback",
    "nested-receiver-shape",
]


class ObjectiveCopy(Value):
    slot_key: LocalId
    statement: CopyStatement


class MisconceptionCopy(Value):
    slot_key: LocalId
    statement: CopyStatement
    suggested_feedback: CopyStatement


class PredictionChoiceWording(Value):
    """Only wording references; outcome identities and meanings are server-owned."""

    rejected: LocalId
    saved: LocalId
    server_error: LocalId


class PredictionCopy(Value):
    prompt: CopyPrompt
    choice_wording: PredictionChoiceWording


class ProgressiveHints(Value):
    # Copy destinations corresponding to the existing three progressive levels.
    orient: CopyHint
    compare: CopyHint
    investigate_evidence: CopyHint


class ExplanationCopy(Value):
    concept: CopyFraming
    evidence: CopyFraming


class GeneratedChallengeContent(Value):
    """Educational copy only; never a LessonSpecV1 or a release decision.

    The 16 KiB check below bounds the parsed content's compact JSON encoding. It
    cannot detect duplicate JSON keys or count discarded wire whitespace. A later
    admission layer must check the original GenerationCompletion.raw_json first.
    """

    contract_version: ContractVersion
    title: CopyTitle
    description: CopyDescription
    context_variant: LocalId
    objectives: Items[ObjectiveCopy] = Field(min_length=1, max_length=3)
    scenario_narrative: CopyNarrative
    prediction: PredictionCopy
    investigation_prompt: CopyPrompt
    modification_instructions: CopyPrompt
    hints: ProgressiveHints = Field(repr=False)
    explanations: ExplanationCopy = Field(repr=False)
    misconceptions: Items[MisconceptionCopy] = Field(max_length=3, repr=False)

    @model_validator(mode="after")
    def bounded_copy(self) -> Self:
        for entries in (self.objectives, self.misconceptions):
            keys = [entry.slot_key for entry in entries]
            if len(keys) != len(set(keys)):
                raise ValueError("Copy destination slots must be unique within each collection")
        if len(self.model_dump_json().encode("utf-8")) > MAX_GENERATED_CONTENT_BYTES:
            raise ValueError("Generated content exceeds 16384 UTF-8 bytes")
        return self


class ApprovedWordingOption(Value):
    key: LocalId
    label: CopyHint


class ApprovedPredictionWording(Value):
    rejected: Items[ApprovedWordingOption] = Field(min_length=1, max_length=8)
    saved: Items[ApprovedWordingOption] = Field(min_length=1, max_length=8)
    server_error: Items[ApprovedWordingOption] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        for options in (self.rejected, self.saved, self.server_error):
            keys = [option.key for option in options]
            if len(keys) != len(set(keys)):
                raise ValueError("Wording keys must be unique within each outcome slot")
        return self


class LearnerEvidenceSummary(Value):
    """Minimized factual counts from a bounded server-selected history window."""

    prediction_count: EvidenceCount
    correct_prediction_count: EvidenceCount
    modification_attempt_count: EvidenceCount
    hint_request_count: EvidenceCount
    hints_delivered_count: EvidenceCount
    retrieval_answer_count: EvidenceCount
    correct_retrieval_answer_count: EvidenceCount
    verification_error_count: EvidenceCount

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if (
            self.correct_prediction_count > self.prediction_count
            or self.hints_delivered_count > self.hint_request_count
            or self.correct_retrieval_answer_count > self.retrieval_answer_count
        ):
            raise ValueError("Successful or delivered counts cannot exceed their source counts")
        return self


class GenerationRequest(Value):
    """Internal server-built brief, not a user instruction or lesson definition.

    Reference keys do not create capabilities. A later trusted builder must source
    them and their wording labels from approved template data, never client input.
    """

    contract_version: ContractVersion
    template_family: TemplateFamily
    permitted_narrative_variants: Items[LocalId] = Field(min_length=1, max_length=8)
    requested_objective_slots: Items[LocalId] = Field(min_length=1, max_length=3)
    requested_misconception_slots: Items[LocalId] = Field(max_length=3)
    approved_prediction_wording: ApprovedPredictionWording
    allowed_instructional_facts: Items[InstructionalFact] = Field(min_length=1, max_length=4)
    learner_evidence: LearnerEvidenceSummary | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def consistent_brief(self) -> Self:
        for keys in (
            self.permitted_narrative_variants,
            self.requested_objective_slots,
            self.requested_misconception_slots,
            self.allowed_instructional_facts,
        ):
            if len(keys) != len(set(keys)):
                raise ValueError("Brief references must be unique within each collection")
        if (
            self.template_family == "notes-v1"
            and "nested-receiver-shape" in self.allowed_instructional_facts
        ):
            raise ValueError("The notes template does not provide a nested receiving schema")
        return self


type TransportIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$"),
    AfterValidator(plain_text),
]
type CompletionStatus = Literal[
    "success",
    "refusal",
    "truncated",
    "timeout",
    "rate_limited",
    "unavailable",
    "transport_error",
]


class ProviderMetadata(Value):
    provider_id: TransportIdentifier
    request_id: TransportIdentifier | None


class ModelMetadata(Value):
    requested_model_id: TransportIdentifier | None
    returned_model_id: TransportIdentifier | None


class TransportMetadata(Value):
    """Filled by a transport adapter, never parsed from model-generated claims."""

    source: Literal["transport"]
    provider: ProviderMetadata
    model: ModelMetadata


def captured_text(value: str) -> str:
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise ValueError("Captured output must be valid UTF-8") from exc
    if size > MAX_COMPLETION_CAPTURE_BYTES:
        raise ValueError("Captured output exceeds 65536 UTF-8 bytes")
    return value


class GenerationCompletion(Value):
    """Transport result, not validated content. Raw text is preserved verbatim.

    Success means text was returned, not that it is JSON or fits the generation
    contract. Refusals and failures need not have output; truncation may retain a
    prefix. Never route raw_json directly to a learner or log it implicitly.
    """

    status: CompletionStatus
    raw_json: Annotated[str, AfterValidator(captured_text)] | None = Field(repr=False)
    transport: TransportMetadata

    @model_validator(mode="after")
    def success_has_output(self) -> Self:
        if self.status == "success" and (self.raw_json is None or not self.raw_json.strip()):
            raise ValueError("Successful transport completion must contain output text")
        return self
