"""
Tests for PV API endpoints.
"""
import pytest
from httpx import AsyncClient


class TestPVCreate:
    """Tests for PV creation endpoints."""

    @pytest.mark.asyncio
    async def test_create_pv_with_setpoint(self, client: AsyncClient):
        """Test creating a PV with setpoint address only."""
        response = await client.post(
            "/v1/pvs", json={"setpointAddress": "CREATE:TEST:SP", "device": "TEST-DEVICE", "description": "Test PV"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert data["payload"]["setpointAddress"] == "CREATE:TEST:SP"
        assert data["payload"]["id"] is not None
        assert data["payload"]["device"] == "TEST-DEVICE"

    @pytest.mark.asyncio
    async def test_create_pv_with_all_addresses(self, client: AsyncClient):
        """Test creating a PV with all address types."""
        response = await client.post(
            "/v1/pvs",
            json={
                "setpointAddress": "FULL:TEST:SP",
                "readbackAddress": "FULL:TEST:RB",
                "configAddress": "FULL:TEST:CFG",
                "device": "FULL-DEVICE",
                "description": "Full test PV",
                "absTolerance": 0.5,
                "relTolerance": 0.05,
                "readOnly": False,
                "tags": [],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        payload = data["payload"]
        assert payload["setpointAddress"] == "FULL:TEST:SP"
        assert payload["readbackAddress"] == "FULL:TEST:RB"
        assert payload["configAddress"] == "FULL:TEST:CFG"
        assert payload["absTolerance"] == 0.5
        assert payload["relTolerance"] == 0.05

    @pytest.mark.asyncio
    async def test_create_pv_requires_at_least_one_address(self, client: AsyncClient):
        """Test that at least one address is required."""
        response = await client.post(
            "/v1/pvs", json={"device": "NO-ADDRESS-DEVICE", "description": "PV without any address"}
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_create_pv_duplicate_address_fails(self, client: AsyncClient, sample_pv: dict):
        """Test that duplicate addresses are rejected."""
        response = await client.post(
            "/v1/pvs", json={"setpointAddress": sample_pv["setpointAddress"], "device": "DUPLICATE-DEVICE"}  # Duplicate
        )

        assert response.status_code == 409
        data = response.json()
        assert data["errorCode"] == 409
        assert "already exists" in data["errorMessage"]

    @pytest.mark.asyncio
    async def test_create_pv_with_tags(self, client: AsyncClient, sample_tag: tuple):
        """Test creating a PV with tags."""
        group, tag = sample_tag
        response = await client.post(
            "/v1/pvs", json={"setpointAddress": "TAGGED:PV:SP", "device": "TAGGED-DEVICE", "tags": [tag["id"]]}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert len(data["payload"]["tags"]) == 1
        assert data["payload"]["tags"][0]["id"] == tag["id"]


class TestPVBulkCreate:
    """Tests for bulk PV creation."""

    @pytest.mark.asyncio
    async def test_bulk_create_pvs(self, client: AsyncClient):
        """Test bulk creation of multiple PVs."""
        pvs_data = [{"setpointAddress": f"BULK:PV:{i}:SP", "device": f"BULK-{i}"} for i in range(10)]

        response = await client.post("/v1/pvs/multi", json=pvs_data)

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert len(data["payload"]) == 10

    @pytest.mark.asyncio
    async def test_bulk_create_empty_list(self, client: AsyncClient):
        """Test bulk creation with empty list."""
        response = await client.post("/v1/pvs/multi", json=[])

        assert response.status_code == 200
        data = response.json()
        assert data["payload"] == []


class TestPVSearch:
    """Tests for PV search endpoints."""

    @pytest.mark.asyncio
    async def test_search_pvs_simple(self, client: AsyncClient, sample_pvs: list):
        """Test simple PV search."""
        response = await client.get("/v1/pvs", params={"pvName": "TEST:PV"})

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert len(data["payload"]) >= 1

    @pytest.mark.asyncio
    async def test_search_pvs_paged(self, client: AsyncClient, sample_pvs: list):
        """Test paginated PV search."""
        response = await client.get("/v1/pvs/paged", params={"pvName": "TEST", "pageSize": 2})

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert len(data["payload"]["results"]) == 2
        assert data["payload"]["totalCount"] >= 5
        assert data["payload"]["continuationToken"] is not None

    @pytest.mark.asyncio
    async def test_search_pvs_pagination_continuation(self, client: AsyncClient, sample_pvs: list):
        """Test pagination with continuation token."""
        # First page
        response1 = await client.get("/v1/pvs/paged", params={"pvName": "TEST", "pageSize": 2})
        data1 = response1.json()
        token = data1["payload"]["continuationToken"]

        # Second page
        response2 = await client.get(
            "/v1/pvs/paged", params={"pvName": "TEST", "pageSize": 2, "continuationToken": token}
        )
        data2 = response2.json()

        # Ensure different results
        ids1 = {p["id"] for p in data1["payload"]["results"]}
        ids2 = {p["id"] for p in data2["payload"]["results"]}
        assert ids1.isdisjoint(ids2)  # No overlap

    @pytest.mark.asyncio
    async def test_search_pvs_no_results(self, client: AsyncClient):
        """Test search with no matching results."""
        response = await client.get("/v1/pvs/paged", params={"pvName": "NONEXISTENT:PV:ADDRESS"})

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert len(data["payload"]["results"]) == 0
        assert data["payload"]["totalCount"] == 0


class TestPVUpdate:
    """Tests for PV update endpoint."""

    @pytest.mark.asyncio
    async def test_update_pv_description(self, client: AsyncClient, sample_pv: dict):
        """Test updating PV description."""
        pv_id = sample_pv["id"]
        response = await client.put(f"/v1/pvs/{pv_id}", json={"description": "Updated description"})

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert data["payload"]["description"] == "Updated description"

    @pytest.mark.asyncio
    async def test_update_pv_tolerances(self, client: AsyncClient, sample_pv: dict):
        """Test updating PV tolerances."""
        pv_id = sample_pv["id"]
        response = await client.put(f"/v1/pvs/{pv_id}", json={"absTolerance": 1.0, "relTolerance": 0.1})

        assert response.status_code == 200
        data = response.json()
        assert data["payload"]["absTolerance"] == 1.0
        assert data["payload"]["relTolerance"] == 0.1

    @pytest.mark.asyncio
    async def test_update_pv_not_found(self, client: AsyncClient):
        """Test updating non-existent PV."""
        response = await client.put("/v1/pvs/nonexistent-id", json={"description": "Should fail"})

        assert response.status_code == 404
        data = response.json()
        assert data["errorCode"] == 404


class TestPVDelete:
    """Tests for PV delete endpoint."""

    @pytest.mark.asyncio
    async def test_delete_pv(self, client: AsyncClient, sample_pv: dict):
        """Test deleting a PV."""
        pv_id = sample_pv["id"]
        response = await client.delete(f"/v1/pvs/{pv_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert data["payload"] is True

        # Verify deletion
        search_response = await client.get("/v1/pvs/paged", params={"pvName": sample_pv["setpointAddress"]})
        assert len(search_response.json()["payload"]["results"]) == 0

    @pytest.mark.asyncio
    async def test_delete_pv_not_found(self, client: AsyncClient):
        """Test deleting non-existent PV."""
        response = await client.delete("/v1/pvs/nonexistent-id")

        assert response.status_code == 404
        data = response.json()
        assert data["errorCode"] == 404
