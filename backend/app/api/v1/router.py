from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_health_service
from app.core.errors import ApplicationError
from app.schemas.errors import ErrorResponse
from app.services.health import HealthService

router = APIRouter(
    prefix="/api/v1",
    tags=["health"],
    responses={
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"


@router.get("/health/live", response_model=LivenessResponse, operation_id="health_live")
def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    operation_id="health_ready",
    responses={503: {"model": ErrorResponse}},
)
def readiness(service: Annotated[HealthService, Depends(get_health_service)]) -> ReadinessResponse:
    if not service.is_ready():
        raise ApplicationError(
            "dependency_unavailable", "Required dependencies are not ready.", 503
        )
    return ReadinessResponse()
