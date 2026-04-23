from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PagedResult(BaseModel, Generic[T]):
    """Paginated result with continuation token."""

    results: list[T]
    continuationToken: str | None = None
    totalCount: int | None = None
