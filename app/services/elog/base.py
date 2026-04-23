"""Plugin contract for posting entries to an electronic logbook.

Labs running Squirrel with a different e-log system implement :class:`ElogAdapter`,
register the subclass in ``app.services.elog.ELOG_PROVIDERS``, and set
``SQUIRREL_ELOG_PROVIDER`` to the registered key.
"""
from abc import ABC, abstractmethod

from pydantic import Field, BaseModel


class ElogLogbook(BaseModel):
    """A logbook the user can post to."""

    id: str
    name: str


class ElogTag(BaseModel):
    """A tag attachable to an entry within a logbook."""

    id: str
    name: str


class ElogEntryRequest(BaseModel):
    """Input for :meth:`ElogAdapter.create_entry`."""

    logbooks: list[str] = Field(..., min_length=1, description="Logbook IDs to post into.")
    title: str = Field(..., min_length=1, max_length=255)
    body_markdown: str = Field(..., description="Entry body authored by the user; markdown.")
    tags: list[str] = Field(default_factory=list, description="Tag IDs to attach.")
    author: str = Field(..., description="Human-readable attribution (typically API key's appName).")
    snapshot_id: str | None = Field(default=None, description="Optional source snapshot for auditing.")


class ElogEntryResult(BaseModel):
    """Returned from :meth:`ElogAdapter.create_entry`."""

    id: str
    url: str | None = None


class ElogAdapter(ABC):
    """Abstract base class for e-log backend plugins."""

    @abstractmethod
    async def list_logbooks(self) -> list[ElogLogbook]:
        ...

    @abstractmethod
    async def list_tags(self, logbook_id: str) -> list[ElogTag]:
        ...

    @abstractmethod
    async def create_entry(self, request: ElogEntryRequest) -> ElogEntryResult:
        ...

    async def close(self) -> None:
        """Release resources (HTTP clients, pools). Called on app shutdown."""
        return None
