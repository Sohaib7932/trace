"""Internal admission results. Copy acceptance is never release authorization."""

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import AfterValidator, Field

from app.domain.lesson_spec.fields import No, Value, plain_text
from app.schemas.generation import ContractVersion, GeneratedChallengeContent, TemplateFamily

type AdmissionPolicyVersion = Literal["1.0.0"]
ADMISSION_POLICY_VERSION: Final[AdmissionPolicyVersion] = "1.0.0"
type AdmissionStage = Literal["completion", "raw_size", "json", "contract", "references", "content"]


class AdmissionFailureCode(StrEnum):
    COMPLETION_REFUSED = "completion_refused"
    COMPLETION_TRUNCATED = "completion_truncated"
    COMPLETION_UNSUCCESSFUL = "completion_unsuccessful"
    MISSING_OUTPUT = "missing_output"
    RAW_OUTPUT_TOO_LARGE = "raw_output_too_large"
    INVALID_UTF8 = "invalid_utf8"
    INVALID_JSON = "invalid_json"
    DUPLICATE_JSON_PROPERTY = "duplicate_json_property"
    NON_STANDARD_JSON_NUMBER = "non_standard_json_number"
    JSON_ROOT_NOT_OBJECT = "json_root_not_object"
    JSON_DEPTH_EXCEEDED = "json_depth_exceeded"
    CONTRACT_INVALID = "contract_invalid"
    TEMPLATE_REFERENCE_MISMATCH = "template_reference_mismatch"
    CONTEXT_VARIANT_NOT_PERMITTED = "context_variant_not_permitted"
    OBJECTIVE_SLOTS_MISMATCH = "objective_slots_mismatch"
    PREDICTION_WORDING_NOT_PERMITTED = "prediction_wording_not_permitted"
    FIXED_SLOTS_MISMATCH = "fixed_slots_mismatch"
    MISCONCEPTION_SLOTS_MISMATCH = "misconception_slots_mismatch"
    CONTENT_RESTRICTED = "content_restricted"


class AdmissionAccepted(Value):
    status: Literal["accepted"] = "accepted"
    contract_version: ContractVersion
    admission_policy_version: AdmissionPolicyVersion = ADMISSION_POLICY_VERSION
    template_family: TemplateFamily
    content: GeneratedChallengeContent = Field(repr=False)
    release_eligible: No = False


class AdmissionRejected(Value):
    status: Literal["rejected"] = "rejected"
    code: AdmissionFailureCode
    stage: AdmissionStage
    message: Annotated[str, Field(min_length=1, max_length=200), AfterValidator(plain_text)]


type AdmissionResult = Annotated[
    AdmissionAccepted | AdmissionRejected, Field(discriminator="status")
]
