from typing import TypeVar

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.schemas.common import ApiResultResponse

T = TypeVar("T")


def success_response(payload: T) -> dict:
    """Wrap successful response."""
    return ApiResultResponse(errorCode=0, errorMessage=None, payload=payload).model_dump()


def error_response(code: int, message: str, status_code: int = 400) -> JSONResponse:
    """Create error response."""
    return JSONResponse(
        status_code=status_code,
        content=ApiResultResponse(errorCode=code, errorMessage=message, payload=None).model_dump(),
    )


class APIException(HTTPException):
    """Custom API exception with error codes."""

    def __init__(self, error_code: int, message: str, status_code: int | None = None):
        if status_code is None:
            status_code = error_code
        super().__init__(status_code=status_code, detail=message)
        self.error_code = error_code
        self.error_message = message
