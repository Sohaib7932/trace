from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.domain.learning import LearningError
from app.schemas.errors import ErrorDetail, ErrorResponse, ValidationIssue


class ApplicationError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


def error_response(
    request_id: str,
    code: str,
    message: str,
    status_code: int,
    details: list[ValidationIssue] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=request_id, details=details or [])
    )
    return JSONResponse(body.model_dump(), status_code=status_code)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LearningError)
    async def learning_error(request: Request, exc: LearningError) -> JSONResponse:
        statuses = {
            "unauthenticated": 401,
            "forbidden": 403,
            "rate_limited": 429,
            "not_found": 404,
            "conflict": 409,
            "invalid_state": 409,
            "hint_limit": 409,
            "unsupported_change": 422,
            "dependency_unavailable": 503,
        }
        return error_response(
            request.state.request_id, exc.code, exc.message, statuses.get(exc.code, 500)
        )

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return error_response(request.state.request_id, exc.code, exc.message, exc.status_code)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed"}
        messages = {404: "Resource not found.", 405: "Method not allowed."}
        response = error_response(
            request.state.request_id,
            codes.get(exc.status_code, "http_error"),
            messages.get(exc.status_code, "Request could not be completed."),
            exc.status_code,
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never include errors()[input/ctx], which can contain submitted secrets.
        issues = [ValidationIssue(location=list(e["loc"]), code=e["type"]) for e in exc.errors()]
        return error_response(
            request.state.request_id, "validation_error", "Request validation failed.", 422, issues
        )
