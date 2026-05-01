"""Route tests for /v1/elog/*.

Uses a local ``client`` fixture that skips the Postgres setup in the root
conftest — the e-log routes do not touch the DB directly; auth is stubbed.
"""
from datetime import datetime

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.session import get_db
from app.api.v1.elog import _get_elog_adapter
from app.dependencies import get_api_key
from app.schemas.api_key import ApiKeyDTO
from tests.mocks.elog_mock import (
    ELOG_DEFAULT_TAG,
    ELOG_DEFAULT_LOGBOOK,
    MockElogAdapter,
)


@pytest_asyncio.fixture
async def client() -> AsyncClient:  # overrides the root conftest fixture for this module
    async def override_get_db():
        yield None  # Not used by /v1/elog/* routes

    async def override_get_api_key() -> ApiKeyDTO:
        return ApiKeyDTO(
            id="test-key-id",
            appName="TestClient",
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
    """Override the e-log dependency with a MockElogAdapter."""
    adapter = MockElogAdapter()
    app.dependency_overrides[_get_elog_adapter] = lambda: adapter
    yield adapter
    app.dependency_overrides.pop(_get_elog_adapter, None)


@pytest_asyncio.fixture
async def disable_elog():
    """Override the e-log dependency to return ``None`` (disabled)."""
    app.dependency_overrides[_get_elog_adapter] = lambda: None
    yield
    app.dependency_overrides.pop(_get_elog_adapter, None)


class TestElogConfig:
    async def test_config_disabled_by_default(self, client: AsyncClient, disable_elog):
        resp = await client.get("/v1/elog/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["provider"] == ""

    async def test_config_enabled_when_adapter_configured(self, client: AsyncClient, mock_elog):
        # Monkey-patch get_elog_service to match adapter install
        resp = await client.get("/v1/elog/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True


class TestElogLogbooksAndTags:
    async def test_returns_503_when_disabled(self, client: AsyncClient, disable_elog):
        resp = await client.get("/v1/elog/logbooks")
        assert resp.status_code == 503

    async def test_list_logbooks(self, client: AsyncClient, mock_elog):
        resp = await client.get("/v1/elog/logbooks")
        assert resp.status_code == 200
        body = resp.json()
        assert body == [{"id": ELOG_DEFAULT_LOGBOOK.id, "name": ELOG_DEFAULT_LOGBOOK.name}]

    async def test_list_tags_for_logbook(self, client: AsyncClient, mock_elog):
        resp = await client.get(f"/v1/elog/logbooks/{ELOG_DEFAULT_LOGBOOK.id}/tags")
        assert resp.status_code == 200
        body = resp.json()
        assert body == [{"id": ELOG_DEFAULT_TAG.id, "name": ELOG_DEFAULT_TAG.name}]

    async def test_list_tags_unknown_logbook_returns_empty(self, client: AsyncClient, mock_elog):
        resp = await client.get("/v1/elog/logbooks/does-not-exist/tags")
        assert resp.status_code == 200
        assert resp.json() == []


class TestCreateEntry:
    async def test_returns_503_when_disabled(self, client: AsyncClient, disable_elog):
        resp = await client.post(
            "/v1/elog/entries",
            json={
                "logbooks": ["logbook-1"],
                "title": "Test",
                "bodyMarkdown": "body",
            },
        )
        assert resp.status_code == 503

    async def test_create_entry(self, client: AsyncClient, mock_elog):
        resp = await client.post(
            "/v1/elog/entries",
            json={
                "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                "title": "Snapshot: test",
                "bodyMarkdown": "# hello",
                "tags": [ELOG_DEFAULT_TAG.id],
                "snapshotId": "abc-123",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "entry-1"
        assert len(mock_elog.created_entries) == 1

        stored = mock_elog.created_entries[0]
        assert stored.title == "Snapshot: test"
        assert stored.body_markdown == "# hello"
        assert stored.logbooks == [ELOG_DEFAULT_LOGBOOK.id]
        assert stored.tags == [ELOG_DEFAULT_TAG.id]
        assert stored.snapshot_id == "abc-123"
        # Author is stamped from the API key, not trusted from the client payload.
        assert stored.author == "TestClient"

    async def test_client_cannot_override_author(self, client: AsyncClient, mock_elog):
        # Extra "author" field is ignored by the DTO.
        resp = await client.post(
            "/v1/elog/entries",
            json={
                "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                "title": "Title",
                "bodyMarkdown": "body",
                "author": "hacker",
            },
        )
        assert resp.status_code == 200
        assert mock_elog.created_entries[-1].author == "TestClient"

    async def test_validation_requires_at_least_one_logbook(self, client: AsyncClient, mock_elog):
        resp = await client.post(
            "/v1/elog/entries",
            json={"logbooks": [], "title": "T", "bodyMarkdown": "body"},
        )
        assert resp.status_code == 422

    async def test_validation_rejects_empty_title(self, client: AsyncClient, mock_elog):
        resp = await client.post(
            "/v1/elog/entries",
            json={"logbooks": ["logbook-1"], "title": "", "bodyMarkdown": "body"},
        )
        assert resp.status_code == 422

    async def test_extra_fields_passed_through(self, client: AsyncClient, mock_elog):
        resp = await client.post(
            "/v1/elog/entries",
            json={
                "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                "title": "T",
                "bodyMarkdown": "b",
                "additionalAuthors": ["alice@lab", "bob@lab"],
                "important": True,
                "eventAt": "2026-04-29T09:30:15",
            },
        )
        assert resp.status_code == 200
        stored = mock_elog.created_entries[-1]
        assert stored.additional_authors == ["alice@lab", "bob@lab"]
        assert stored.important is True
        assert stored.event_at == datetime(2026, 4, 29, 9, 30, 15)


class TestFollowUp:
    async def test_routes_to_create_follow_up_when_id_provided(self, client: AsyncClient, mock_elog):
        resp = await client.post(
            "/v1/elog/entries",
            json={
                "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                "title": "Hourly",
                "bodyMarkdown": "body",
                "followsUpEntryId": "parent-1",
            },
        )
        assert resp.status_code == 200
        assert mock_elog.created_entries == []
        assert len(mock_elog.follow_ups) == 1
        parent_id, request = mock_elog.follow_ups[0]
        assert parent_id == "parent-1"
        assert request.title == "Hourly"
        assert request.author == "TestClient"

    async def test_returns_501_when_provider_unsupported(self, client: AsyncClient):
        adapter = MockElogAdapter(supports_follow_up=False)
        app.dependency_overrides[_get_elog_adapter] = lambda: adapter
        try:
            resp = await client.post(
                "/v1/elog/entries",
                json={
                    "logbooks": [ELOG_DEFAULT_LOGBOOK.id],
                    "title": "T",
                    "bodyMarkdown": "b",
                    "followsUpEntryId": "parent-1",
                },
            )
            assert resp.status_code == 501
        finally:
            app.dependency_overrides.pop(_get_elog_adapter, None)


class TestSearchUsers:
    async def test_returns_503_when_disabled(self, client: AsyncClient, disable_elog):
        resp = await client.get("/v1/elog/users", params={"search": "jane"})
        assert resp.status_code == 503

    async def test_search_by_name(self, client: AsyncClient, mock_elog):
        resp = await client.get("/v1/elog/users", params={"search": "jane"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["uid"] == "jdoe"
        assert body[0]["gecos"] == "Jane Doe"
        assert body[0]["mail"] == "jdoe@slac.stanford.edu"

    async def test_search_by_email(self, client: AsyncClient, mock_elog):
        resp = await client.get("/v1/elog/users", params={"search": "jsmith@"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["uid"] == "jsmith"

    async def test_search_no_match(self, client: AsyncClient, mock_elog):
        resp = await client.get("/v1/elog/users", params={"search": "nobody"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_requires_query(self, client: AsyncClient, mock_elog):
        resp = await client.get("/v1/elog/users")
        assert resp.status_code == 422
