"""
Tests for API Keys endpoints.
"""

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CREATE_PAYLOAD = {"appName": "TestApp", "readAccess": True, "writeAccess": False}


async def _create_key(
    client: AsyncClient, app_name: str = "TestApp", *, read: bool = True, write: bool = False
) -> dict:
    """Helper to create an API key and return the response body."""
    response = await client.post("/v1/api-keys", json={"appName": app_name, "readAccess": read, "writeAccess": write})
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestApiKeyCreate:
    """Tests for POST /v1/api-keys."""

    @pytest.mark.asyncio
    async def test_create_key_returns_token(self, client: AsyncClient):
        """Newly created key includes a plaintext token (only time it is returned)."""
        data = await _create_key(client)

        assert data["token"].startswith("sq_")
        assert data["appName"] == "TestApp"
        assert data["isActive"] is True
        assert data["id"] is not None
        assert data["createdAt"] is not None
        assert data["updatedAt"] is not None

    @pytest.mark.asyncio
    async def test_create_key_respects_access_flags(self, client: AsyncClient):
        """Read/write access flags are stored as provided."""
        data = await _create_key(client, read=True, write=True)

        assert data["readAccess"] is True
        assert data["writeAccess"] is True

    @pytest.mark.asyncio
    async def test_create_key_token_hash_not_exposed(self, client: AsyncClient):
        """The token_hash field must never appear in the response."""
        data = await _create_key(client)

        assert "tokenHash" not in data
        assert "token_hash" not in data

    @pytest.mark.asyncio
    async def test_create_key_duplicate_app_name_returns_409(self, client: AsyncClient):
        """Creating a second active key for the same appName is rejected with 409."""
        await _create_key(client, app_name="DuplicateApp")

        response = await client.post(
            "/v1/api-keys", json={"appName": "DuplicateApp", "readAccess": False, "writeAccess": False}
        )

        assert response.status_code == 409
        assert "DuplicateApp" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_key_missing_required_field_returns_422(self, client: AsyncClient):
        """Omitting required fields triggers request validation error."""
        response = await client.post("/v1/api-keys", json={"readAccess": True})

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestApiKeyList:
    """Tests for GET /v1/api-keys."""

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty_list(self, client: AsyncClient):
        """With no keys created, the endpoint returns an empty list."""
        response = await client.get("/v1/api-keys")

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_returns_created_keys(self, client: AsyncClient):
        """All created keys appear in the list."""
        await _create_key(client, app_name="App1")
        await _create_key(client, app_name="App2")

        response = await client.get("/v1/api-keys")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        app_names = {k["appName"] for k in data}
        assert app_names == {"App1", "App2"}

    @pytest.mark.asyncio
    async def test_list_does_not_include_token(self, client: AsyncClient):
        """Listing keys never exposes the plaintext token or hash."""
        await _create_key(client)

        response = await client.get("/v1/api-keys")
        data = response.json()

        for key in data:
            assert "token" not in key
            assert "tokenHash" not in key
            assert "token_hash" not in key

    @pytest.mark.asyncio
    async def test_list_active_only_excludes_inactive(self, client: AsyncClient):
        """active_only=true filters out deactivated keys."""
        key1 = await _create_key(client, app_name="ActiveApp")
        key2 = await _create_key(client, app_name="InactiveApp")

        # Deactivate one key
        await client.delete(f"/v1/api-keys/{key2['id']}")

        response = await client.get("/v1/api-keys", params={"active_only": "true"})

        assert response.status_code == 200
        data = response.json()
        ids = [k["id"] for k in data]
        assert key1["id"] in ids
        assert key2["id"] not in ids

    @pytest.mark.asyncio
    async def test_list_without_active_only_includes_inactive(self, client: AsyncClient):
        """Without the active_only flag, deactivated keys are still returned."""
        key = await _create_key(client)
        await client.delete(f"/v1/api-keys/{key['id']}")

        response = await client.get("/v1/api-keys")

        assert response.status_code == 200
        data = response.json()
        assert any(k["id"] == key["id"] for k in data)


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------


class TestApiKeyCount:
    """Tests for GET /v1/api-keys/count."""

    @pytest.mark.asyncio
    async def test_count_empty(self, client: AsyncClient):
        """Count is zero when no keys exist."""
        response = await client.get("/v1/api-keys/count")

        assert response.status_code == 200
        assert response.json() == 0

    @pytest.mark.asyncio
    async def test_count_reflects_created_keys(self, client: AsyncClient):
        """Count increases as keys are created."""
        await _create_key(client, app_name="App1")
        await _create_key(client, app_name="App2")

        response = await client.get("/v1/api-keys/count")

        assert response.status_code == 200
        assert response.json() == 2

    @pytest.mark.asyncio
    async def test_count_active_only_excludes_inactive(self, client: AsyncClient):
        """active_only=true count does not include deactivated keys."""
        await _create_key(client, app_name="App1")
        key2 = await _create_key(client, app_name="App2")
        await client.delete(f"/v1/api-keys/{key2['id']}")

        response = await client.get("/v1/api-keys/count", params={"active_only": "true"})

        assert response.status_code == 200
        assert response.json() == 1

    @pytest.mark.asyncio
    async def test_count_total_includes_inactive(self, client: AsyncClient):
        """Total count (no filter) includes inactive keys."""
        key = await _create_key(client)
        await client.delete(f"/v1/api-keys/{key['id']}")

        response = await client.get("/v1/api-keys/count")

        assert response.status_code == 200
        assert response.json() == 1


# ---------------------------------------------------------------------------
# Deactivate
# ---------------------------------------------------------------------------


class TestApiKeyDeactivate:
    """Tests for DELETE /v1/api-keys/{key_id}."""

    @pytest.mark.asyncio
    async def test_deactivate_sets_is_active_false(self, client: AsyncClient):
        """Deactivating a key flips isActive to False."""
        key = await _create_key(client)
        key_id = key["id"]

        response = await client.delete(f"/v1/api-keys/{key_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == key_id
        assert data["isActive"] is False

    @pytest.mark.asyncio
    async def test_deactivated_key_still_retrievable(self, client: AsyncClient):
        """After deactivation the key still appears in the unfiltered list."""
        key = await _create_key(client)
        await client.delete(f"/v1/api-keys/{key['id']}")

        response = await client.get("/v1/api-keys")
        data = response.json()

        deactivated = next((k for k in data if k["id"] == key["id"]), None)
        assert deactivated is not None
        assert deactivated["isActive"] is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_key_returns_404(self, client: AsyncClient):
        """Attempting to deactivate an unknown ID returns 404."""
        response = await client.delete("/v1/api-keys/00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_deactivate_already_inactive_key_returns_409(self, client: AsyncClient):
        """Deactivating an already-inactive key is a conflict, not 'not found'."""
        key = await _create_key(client)
        await client.delete(f"/v1/api-keys/{key['id']}")

        # Attempt to deactivate again
        response = await client.delete(f"/v1/api-keys/{key['id']}")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_deactivate_allows_reuse_of_app_name(self, client: AsyncClient):
        """After deactivation, a new key with the same appName can be created."""
        key = await _create_key(client, app_name="ReusableApp")
        await client.delete(f"/v1/api-keys/{key['id']}")

        response = await client.post(
            "/v1/api-keys", json={"appName": "ReusableApp", "readAccess": True, "writeAccess": False}
        )

        assert response.status_code == 200
        new_key = response.json()
        assert new_key["id"] != key["id"]
        assert new_key["isActive"] is True

    @pytest.mark.asyncio
    async def test_deactivate_own_key_returns_409(self, client: AsyncClient):
        """Deactivating the authenticated key is blocked without force."""
        response = await client.delete("/v1/api-keys/00000000-0000-0000-0000-000000000001")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_deactivate_own_key_with_force_succeeds(self, client: AsyncClient):
        """Deactivating the authenticated key succeeds with ?force=true."""
        response = await client.delete("/v1/api-keys/00000000-0000-0000-0000-000000000001", params={"force": "true"})

        assert response.status_code == 404  # key doesn't exist in DB, but guard passed
