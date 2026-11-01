"""Ordered, fail-closed admission of untrusted educational copy; no release path.

The Phase 2.1 model already applies copy restrictions in Stage D. Those failures
remain contract rejections; Stage F repeats the same guards after references.
This component establishes syntax and reference consistency, not semantic truth,
absence of indirect answer leaks, technical correctness or execution safety.
"""

import json
import math
from collections.abc import Iterator

from pydantic import ValidationError

from app.domain.generation_copy import (
    EXPLANATION_SLOTS,
    HINT_SLOTS,
    PREDICTION_SLOTS,
    TEMPLATE_COPY_SLOTS,
)
from app.schemas.generation import (
    MAX_GENERATED_CONTENT_BYTES,
    GeneratedChallengeContent,
    GenerationCompletion,
    GenerationRequest,
    educational_copy,
)
from app.schemas.generation_admission import (
    AdmissionAccepted,
    AdmissionFailureCode,
    AdmissionRejected,
    AdmissionResult,
    AdmissionStage,
)

MAX_ADMISSION_JSON_DEPTH = 32


class _JSONRejection(ValueError):
    def __init__(self, code: AdmissionFailureCode) -> None:
        self.code = code


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _JSONRejection(AdmissionFailureCode.DUPLICATE_JSON_PROPERTY)
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise _JSONRejection(AdmissionFailureCode.NON_STANDARD_JSON_NUMBER)


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise _JSONRejection(AdmissionFailureCode.NON_STANDARD_JSON_NUMBER)
    return result


def _json_tree(document: object) -> None:
    # Iteration avoids a second recursive walk over attacker-controlled nesting.
    pending: list[tuple[object, int]] = [(document, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > MAX_ADMISSION_JSON_DEPTH:
            raise _JSONRejection(AdmissionFailureCode.JSON_DEPTH_EXCEEDED)
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeError as exc:
                raise _JSONRejection(AdmissionFailureCode.INVALID_UTF8) from exc
        elif isinstance(value, dict):
            pending.extend((key, depth + 1) for key in value)
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)


def _reject(code: AdmissionFailureCode) -> AdmissionRejected:
    # Only constant diagnostics cross this boundary. Never use an exception's
    # message, submitted property name, reference, prompt or generated text.
    stage: AdmissionStage
    match code:
        case AdmissionFailureCode.COMPLETION_REFUSED:
            stage, message = "completion", "The generator refused the request."
        case AdmissionFailureCode.COMPLETION_TRUNCATED:
            stage, message = "completion", "The generator returned incomplete output."
        case AdmissionFailureCode.COMPLETION_UNSUCCESSFUL:
            stage, message = "completion", "Generation did not complete successfully."
        case AdmissionFailureCode.MISSING_OUTPUT:
            stage, message = "completion", "Generation returned no output."
        case AdmissionFailureCode.RAW_OUTPUT_TOO_LARGE:
            stage, message = "raw_size", "Generated JSON exceeds the 16384-byte limit."
        case AdmissionFailureCode.INVALID_UTF8:
            stage, message = "json", "Generated JSON must contain valid UTF-8 text."
        case AdmissionFailureCode.INVALID_JSON:
            stage, message = "json", "Generated output is not valid JSON."
        case AdmissionFailureCode.DUPLICATE_JSON_PROPERTY:
            stage, message = "json", "Generated JSON contains a duplicate property."
        case AdmissionFailureCode.NON_STANDARD_JSON_NUMBER:
            stage, message = "json", "Generated JSON contains an unsupported numeric value."
        case AdmissionFailureCode.JSON_ROOT_NOT_OBJECT:
            stage, message = "json", "Generated JSON must have an object root."
        case AdmissionFailureCode.JSON_DEPTH_EXCEEDED:
            stage, message = "json", "Generated JSON exceeds the nesting limit."
        case AdmissionFailureCode.CONTRACT_INVALID:
            stage, message = "contract", "Generated content does not satisfy the copy contract."
        case AdmissionFailureCode.TEMPLATE_REFERENCE_MISMATCH:
            stage, message = "references", "Copy references do not belong to the selected template."
        case AdmissionFailureCode.CONTEXT_VARIANT_NOT_PERMITTED:
            stage, message = "references", "The narrative variant is not permitted by this request."
        case AdmissionFailureCode.OBJECTIVE_SLOTS_MISMATCH:
            stage, message = "references", "Objective slots must match the request exactly."
        case AdmissionFailureCode.PREDICTION_WORDING_NOT_PERMITTED:
            stage, message = (
                "references",
                "Prediction wording is not permitted for its outcome slot.",
            )
        case AdmissionFailureCode.FIXED_SLOTS_MISMATCH:
            stage, message = "references", "Required copy slots do not match the V1 contract."
        case AdmissionFailureCode.MISCONCEPTION_SLOTS_MISMATCH:
            stage, message = "references", "Misconception slots must match the request exactly."
        case AdmissionFailureCode.CONTENT_RESTRICTED:
            stage, message = "content", "Generated copy contains prohibited syntax."
    return AdmissionRejected(code=code, stage=stage, message=message)


def _references(
    request: GenerationRequest, content: GeneratedChallengeContent
) -> AdmissionFailureCode | None:
    slots = TEMPLATE_COPY_SLOTS[request.template_family]
    if not (
        set(request.requested_objective_slots) <= slots.objectives
        and set(request.requested_misconception_slots) <= slots.misconceptions
    ):
        return AdmissionFailureCode.TEMPLATE_REFERENCE_MISMATCH
    other_objectives = set().union(
        *(
            value.objectives
            for key, value in TEMPLATE_COPY_SLOTS.items()
            if key != request.template_family
        )
    )
    objectives = {item.slot_key for item in content.objectives}
    if objectives & other_objectives:
        return AdmissionFailureCode.TEMPLATE_REFERENCE_MISMATCH
    if content.context_variant not in request.permitted_narrative_variants:
        return AdmissionFailureCode.CONTEXT_VARIANT_NOT_PERMITTED
    if objectives != set(request.requested_objective_slots):
        return AdmissionFailureCode.OBJECTIVE_SLOTS_MISMATCH
    if (
        content.prediction.choice_wording.model_dump().keys() != PREDICTION_SLOTS
        or content.hints.model_dump().keys() != HINT_SLOTS
        or content.explanations.model_dump().keys() != EXPLANATION_SLOTS
    ):
        return AdmissionFailureCode.FIXED_SLOTS_MISMATCH
    for outcome in ("rejected", "saved", "server_error"):
        approved = getattr(request.approved_prediction_wording, outcome)
        if getattr(content.prediction.choice_wording, outcome) not in {
            item.key for item in approved
        }:
            return AdmissionFailureCode.PREDICTION_WORDING_NOT_PERMITTED
    if {item.slot_key for item in content.misconceptions} != set(
        request.requested_misconception_slots
    ):
        return AdmissionFailureCode.MISCONCEPTION_SLOTS_MISMATCH
    return None


def _copy_texts(content: GeneratedChallengeContent) -> Iterator[str]:
    yield from (
        content.title,
        content.description,
        content.scenario_narrative,
        content.prediction.prompt,
        content.investigation_prompt,
        content.modification_instructions,
        content.hints.orient,
        content.hints.compare,
        content.hints.investigate_evidence,
        content.explanations.concept,
        content.explanations.evidence,
    )
    yield from (objective.statement for objective in content.objectives)
    for misconception in content.misconceptions:
        yield misconception.statement
        yield misconception.suggested_feedback


class ChallengeContentAdmission:
    def admit(
        self, request: GenerationRequest, completion: GenerationCompletion
    ) -> AdmissionResult:
        # A. Never parse a refusal, a partial response or a failed transport.
        if completion.status == "refusal":
            return _reject(AdmissionFailureCode.COMPLETION_REFUSED)
        if completion.status == "truncated":
            return _reject(AdmissionFailureCode.COMPLETION_TRUNCATED)
        if completion.status != "success":
            return _reject(AdmissionFailureCode.COMPLETION_UNSUCCESSFUL)
        raw = completion.raw_json
        if raw is None or not raw.strip():
            # Defensive: the current completion schema already forbids this.
            return _reject(AdmissionFailureCode.MISSING_OUTPUT)

        # B. Count the original text, including whitespace, before parsing JSON.
        # Phase 2.1 accepts only UTF-8 encodable str; bytes fail at that boundary.
        if len(raw.encode("utf-8")) > MAX_GENERATED_CONTENT_BYTES:
            return _reject(AdmissionFailureCode.RAW_OUTPUT_TOO_LARGE)

        # C. Preserve duplicate-key evidence until the hook inspects every object.
        try:
            document: object = json.loads(
                raw, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float
            )
            _json_tree(document)
        except _JSONRejection as exc:
            return _reject(exc.code)
        except RecursionError:
            return _reject(AdmissionFailureCode.JSON_DEPTH_EXCEEDED)
        except ValueError:
            return _reject(AdmissionFailureCode.INVALID_JSON)
        if not isinstance(document, dict):
            return _reject(AdmissionFailureCode.JSON_ROOT_NOT_OBJECT)

        # D. Never relax or bypass the Phase 2.1 model, including its text guards.
        try:
            content = GeneratedChallengeContent.model_validate(document)
        except ValidationError:
            return _reject(AdmissionFailureCode.CONTRACT_INVALID)

        # E. The exact request authorizes references within its trusted family.
        failure = _references(request, content)
        if failure is not None:
            return _reject(failure)

        # F. Explicit final syntax gate; this is not a semantic correctness test.
        try:
            for text in _copy_texts(content):
                educational_copy(text)
        except ValueError:
            return _reject(AdmissionFailureCode.CONTENT_RESTRICTED)
        return AdmissionAccepted(
            contract_version=content.contract_version,
            template_family=request.template_family,
            content=content,
        )
