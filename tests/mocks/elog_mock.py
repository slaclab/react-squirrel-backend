"""In-memory :class:`ElogAdapter` used by API tests."""
from app.services.elog.base import (
    ElogTag,
    ElogUser,
    ElogAdapter,
    ElogLogbook,
    ElogEntryResult,
    ElogEntryRequest,
)

ELOG_DEFAULT_LOGBOOK = ElogLogbook(id="logbook-1", name="Operations")
ELOG_DEFAULT_TAG = ElogTag(id="tag-1", name="routine")
ELOG_DEFAULT_USERS = [
    ElogUser(uid="jdoe", commonName="Jane Doe", surname="Doe", gecos="Jane Doe", mail="jdoe@slac.stanford.edu"),
    ElogUser(
        uid="jsmith", commonName="John Smith", surname="Smith", gecos="John Smith", mail="jsmith@slac.stanford.edu"
    ),
]


class MockElogAdapter(ElogAdapter):
    def __init__(
        self,
        logbooks: list[ElogLogbook] | None = None,
        tags_by_logbook: dict[str, list[ElogTag]] | None = None,
        supports_follow_up: bool = True,
        users: list[ElogUser] | None = None,
    ):
        self._logbooks = logbooks or [ELOG_DEFAULT_LOGBOOK]
        self._tags_by_logbook = tags_by_logbook or {
            ELOG_DEFAULT_LOGBOOK.id: [ELOG_DEFAULT_TAG],
        }
        self.supports_follow_up = supports_follow_up
        self.created_entries: list[ElogEntryRequest] = []
        self.follow_ups: list[tuple[str, ElogEntryRequest]] = []
        self._users = users if users is not None else list(ELOG_DEFAULT_USERS)
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

    async def search_users(self, search: str, limit: int = 20) -> list[ElogUser]:
        search_lower = search.lower()
        return [u for u in self._users if search_lower in u.gecos.lower() or search_lower in u.mail.lower()][:limit]

    async def create_follow_up(self, parent_entry_id: str, request: ElogEntryRequest) -> ElogEntryResult:
        if not self.supports_follow_up:
            raise NotImplementedError("Mock adapter has follow-up disabled")
        self.follow_ups.append((parent_entry_id, request))
        entry_id = f"entry-{self._next_id}"
        self._next_id += 1
        return ElogEntryResult(id=entry_id)
