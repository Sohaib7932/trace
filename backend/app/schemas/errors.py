from pydantic import BaseModel, ConfigDict, Field


class ValidationIssue(BaseModel):
    location: list[str | int]
    code: str
    message: str = "Invalid value."


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    request_id: str
    details: list[ValidationIssue] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorDetail
