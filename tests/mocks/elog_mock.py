"""In-memory :class:`ElogAdapter` used by API tests."""
from app.services.elog.base import (
    ElogTag,
    ElogAdapter,
    ElogLogbook,
    ElogEntryRequest,
    ElogEntryResult,
)


class MockElogAdapter(ElogAdapter):
    def __init__(
        self,
        logbooks: list[ElogLogbook] | None = None,
        tags_by_logbook: dict[str, list[ElogTag]] | None = None,
    ):
        self._logbooks = logbooks or [ELOG_DEFAULT_LOGBOOK]
        self._tags_by_logbook = tags_by_logbook or {
            ELOG_DEFAULT_LOGBOOK.id: [ELOG_DEFAULT_TAG],
        }
        self.created_entries: list[ElogEntryRequest] = []
        self._next_id = 1

    async def list_logbooks(self) -> list[ElogLogbook]:
        return list(self._logbooks)

    async def list_tags(self, logbook_id: str) -> list[ElogTag]:
        return list(self._tags_by_logbook.get(logbook_id, []))

    async def create_entry(self, request: ElogEntryRequest) -> ElogEntryResult:
        self.created_entries.append(request)
        entry_id = f"entry-{self._next_id}"
        self._next_id += 1
        return ElogEntryResult(id=entry_id)


ELOG_DEFAULT_LOGBOOK = ElogLogbook(id="logbook-1", name="Operations")
ELOG_DEFAULT_TAG = ElogTag(id="tag-1", name="routine")
