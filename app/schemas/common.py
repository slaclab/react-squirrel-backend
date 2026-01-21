from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResultResponse(BaseModel, Generic[T]):
    """Standard API response wrapper matching frontend expectations."""

    errorCode: int = 0
    errorMessage: str | None = None
    payload: T


class PagedResult(BaseModel, Generic[T]):
    """Paginated result with continuation token."""

    results: list[T]
    continuationToken: str | None = None
    totalCount: int | None = None
