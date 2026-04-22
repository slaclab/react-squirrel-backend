"""DB-backed tests for the elog last-entry tracking.

Uses the root conftest's Postgres fixtures because the GET /last-entry route
and the upsert in POST /entries both touch the database. An ``ApiKey`` row is
inserted to satisfy the FK from ``elog_last_entry``.
"""
from uuid import uuid4
from datetime import datetime

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.db.session import get_db
from app.api.v1.elog import _get_elog_adapter
from app.dependencies import get_api_key
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyDTO
from tests.mocks.elog_mock import ELOG_DEFAULT_LOGBOOK, MockElogAdapter

PRIMARY_KEY_ID = str(uuid4())
SECONDARY_KEY_ID = str(uuid4())


async def _insert_api_key(db: AsyncSession, *, key_id: str, app_name: str) -> None:
    db.add(
        ApiKey(
            id=key_id,
            app_name=app_name,
            token_hash=f"hash-{key_id}",
            is_active=True,
            read_access=True,
            write_access=True,
        )
    )
    await db.commit()


@pytest_asyncio.fixture
async def primary_client(db_session: AsyncSession) -> AsyncClient:
    """Client that authenticates as PRIMARY_KEY_ID."""
    await _insert_api_key(db_session, key_id=PRIMARY_KEY_ID, app_name="PrimaryClient")

    async def override_get_db():
        yield db_session

    async def override_get_api_key() -> ApiKeyDTO:
        return ApiKeyDTO(
            id=PRIMARY_KEY_ID,
            appName="PrimaryClient",
            isActive=True,
            readAccess=True,
            writeAccess=True,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_api_key] = override_get_api_key

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_api_key, None)


@pytest_asyncio.fixture
async def mock_elog():
    adapter = MockElogAdapter()
    app.dependency_overrides[_get_elog_adapter] = lambda: adapter
    yield adapter
    app.dependency_overrides.pop(_get_elog_adapter, None)


class TestGetLastEntry:
    async def test_returns_null_when_unknown(self, primary_client: AsyncClient, mock_elog):
        resp = await primary_client.get("/v1/elog/last-entry", params={"logbook": ["logbook-1"]})
        assert resp.status_code == 200
        assert resp.json() == {"entryId": None}

    async def test_records_after_create_and_returns_same_id(self, primary_client: AsyncClient, mock_elog):
        post_resp = await primary_client.post(
            "/v1/elog/entries",
            json={
                "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                "title": "Morning",
                "bodyMarkdown": "body",
            },
        )
        assert post_resp.status_code == 200
        entry_id = post_resp.json()["id"]

        get_resp = await primary_client.get("/v1/elog/last-entry", params={"logbook": [ELOG_DEFAULT_LOGBOOK.id]})
        assert get_resp.status_code == 200
        assert get_resp.json() == {"entryId": entry_id}

    async def test_logbook_query_param_is_order_independent(self, primary_client: AsyncClient, mock_elog):
        post_resp = await primary_client.post(
            "/v1/elog/entries",
            json={
                "logbooks": ["lb-A", "lb-B"],
                "title": "T",
                "bodyMarkdown": "b",
            },
        )
        assert post_resp.status_code == 200
        entry_id = post_resp.json()["id"]

        # Reverse order on lookup must hit the same scope key.
        get_resp = await primary_client.get("/v1/elog/last-entry", params={"logbook": ["lb-B", "lb-A"]})
        assert get_resp.json() == {"entryId": entry_id}

    async def test_chain_advances_on_follow_up(self, primary_client: AsyncClient, mock_elog):
        first = await primary_client.post(
            "/v1/elog/entries",
            json={
                "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                "title": "Morning",
                "bodyMarkdown": "b",
            },
        )
        first_id = first.json()["id"]

        second = await primary_client.post(
            "/v1/elog/entries",
            json={
                "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                "title": "Hourly 1",
                "bodyMarkdown": "b",
                "followsUpEntryId": first_id,
            },
        )
        second_id = second.json()["id"]
        assert second_id != first_id

        get_resp = await primary_client.get("/v1/elog/last-entry", params={"logbook": [ELOG_DEFAULT_LOGBOOK.id]})
        assert get_resp.json() == {"entryId": second_id}

    async def test_scoped_per_logbook_set(self, primary_client: AsyncClient, mock_elog):
        ops_post = await primary_client.post(
            "/v1/elog/entries",
            json={"logbooks": ["ops"], "title": "T", "bodyMarkdown": "b"},
        )
        comm_post = await primary_client.post(
            "/v1/elog/entries",
            json={"logbooks": ["commissioning"], "title": "T", "bodyMarkdown": "b"},
        )

        ops_get = await primary_client.get("/v1/elog/last-entry", params={"logbook": ["ops"]})
        comm_get = await primary_client.get("/v1/elog/last-entry", params={"logbook": ["commissioning"]})
        assert ops_get.json() == {"entryId": ops_post.json()["id"]}
        assert comm_get.json() == {"entryId": comm_post.json()["id"]}

    async def test_scoped_per_api_key(self, primary_client: AsyncClient, mock_elog, db_session: AsyncSession):
        # Primary client posts.
        post_resp = await primary_client.post(
            "/v1/elog/entries",
            json={
                "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                "title": "T",
                "bodyMarkdown": "b",
            },
        )
        assert post_resp.status_code == 200

        # Switch auth override to a second key — should see no last entry.
        await _insert_api_key(db_session, key_id=SECONDARY_KEY_ID, app_name="SecondaryClient")

        async def override_get_api_key() -> ApiKeyDTO:
            return ApiKeyDTO(
                id=SECONDARY_KEY_ID,
                appName="SecondaryClient",
                isActive=True,
                readAccess=True,
                writeAccess=True,
                createdAt=datetime.now(),
                updatedAt=datetime.now(),
            )

        app.dependency_overrides[get_api_key] = override_get_api_key
        try:
            get_resp = await primary_client.get(
                "/v1/elog/last-entry",
                params={"logbook": [ELOG_DEFAULT_LOGBOOK.id]},
            )
            assert get_resp.json() == {"entryId": None}
        finally:
            # Other tests may rely on the primary override; restore via fixture teardown.
            pass
