"""Plugin contract for posting entries to an electronic logbook.

Labs running Squirrel with a different e-log system implement :class:`ElogAdapter`,
register the subclass in ``app.services.elog.ELOG_PROVIDERS``, and set
``SQUIRREL_ELOG_PROVIDER`` to the registered key.
"""
from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import Field, BaseModel


class ElogLogbook(BaseModel):
    """A logbook the user can post to."""

    id: str
    name: str


class ElogTag(BaseModel):
    """A tag attachable to an entry within a logbook."""

    id: str
    name: str


class ElogUser(BaseModel):
    """A user/person from the e-log backend (typically backed by LDAP)."""

    uid: str
    commonName: str
    surname: str
    gecos: str
    mail: str


class ElogEntryRequest(BaseModel):
    """Input for :meth:`ElogAdapter.create_entry`."""

    logbooks: list[str] = Field(..., min_length=1, description="Logbook IDs to post into.")
    title: str = Field(..., min_length=1, max_length=255)
    body_markdown: str = Field(..., description="Entry body authored by the user; markdown.")
    tags: list[str] = Field(default_factory=list, description="Tag IDs to attach.")
    author: str = Field(..., description="Human-readable attribution (typically API key's appName).")
    snapshot_id: str | None = Field(default=None, description="Optional source snapshot for auditing.")
    additional_authors: list[str] = Field(
        default_factory=list,
        description="Extra authors to credit on the entry (e.g. emails).",
    )
    important: bool = Field(default=False, description="Mark the entry as important.")
    event_at: datetime | None = Field(
        default=None,
        description="When the event occurred. Adapters should serialize without offset if needed.",
    )


class ElogRecentEntry(BaseModel):
    """A recent entry summary returned by :meth:`ElogAdapter.list_recent_entries`."""

    id: str
    title: str
    logged_at: str = Field(..., description="ISO-8601 datetime string")
    logged_by: str = Field(..., description="Creator username or email")


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

    async def search_users(self, search: str, limit: int = 20) -> list[ElogUser]:
        """Search for users/people by name or email.

        Default raises NotImplementedError — adapters that support user
        lookup override this.
        """
        raise NotImplementedError("This e-log provider does not support user search")

    async def create_follow_up(self, parent_entry_id: str, request: ElogEntryRequest) -> ElogEntryResult:
        """Post ``request`` as a follow-up of ``parent_entry_id``.

        Adapters whose backend has no follow-up concept can leave this default
        in place; the HTTP layer translates the error into 501.
        """
        raise NotImplementedError("This e-log provider does not support follow-ups")

    async def list_recent_entries(self, logbook_ids: list[str], limit: int = 5) -> list[ElogRecentEntry]:
        """Return the most recent entries posted by this adapter's identity.

        Used to offer a selectable list of parent entries for follow-ups.
        Adapters that don't support this leave the default in place.
        """
        raise NotImplementedError("This e-log provider does not support listing recent entries")

    async def close(self) -> None:
        """Release resources (HTTP clients, pools). Called on app shutdown."""
        return None
