"""
Tests for Snapshot API endpoints.
"""
import pytest
from httpx import AsyncClient

from tests.mocks.epics_mock import MockEpicsService


class TestSnapshotCreate:
    """Tests for snapshot creation."""

    @pytest.mark.asyncio
    async def test_create_snapshot(self, client: AsyncClient, sample_pvs: list[dict], mock_epics: MockEpicsService):
        """Test creating a snapshot captures all PV values."""
        # Set mock values for all PVs
        for pv in sample_pvs:
            if pv.get("setpointAddress"):
                mock_epics.set_mock_value(pv["setpointAddress"], 100.0)
            if pv.get("readbackAddress"):
                mock_epics.set_mock_value(pv["readbackAddress"], 99.5)

        response = await client.post(
            "/v1/snapshots",
            params={"async": "false", "use_cache": "false"},
            json={"title": "Test Snapshot Creation", "description": "Testing snapshot functionality"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert data["payload"]["title"] == "Test Snapshot Creation"
        assert data["payload"]["pvCount"] >= len(sample_pvs)
        assert data["payload"]["id"] is not None

    @pytest.mark.asyncio
    async def test_create_snapshot_with_disconnected_pvs(
        self, client: AsyncClient, sample_pvs: list[dict], mock_epics: MockEpicsService
    ):
        """Test snapshot handles disconnected PVs gracefully."""
        # Only set values for some PVs (others will return random/default)
        mock_epics.set_mock_value(sample_pvs[0]["setpointAddress"], 50.0)

        response = await client.post(
            "/v1/snapshots",
            params={"async": "false", "use_cache": "false"},
            json={"title": "Partial Connection Snapshot"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        # Should still create snapshot even with some missing values

    @pytest.mark.asyncio
    async def test_create_snapshot_requires_title(self, client: AsyncClient):
        """Test that snapshot title is required."""
        response = await client.post("/v1/snapshots", json={"description": "No title provided"})

        assert response.status_code == 422  # Validation error


class TestSnapshotGet:
    """Tests for snapshot retrieval."""

    @pytest.mark.asyncio
    async def test_get_snapshot_by_id(self, client: AsyncClient, sample_snapshot: dict):
        """Test getting a snapshot by ID includes all values."""
        snapshot_id = sample_snapshot["id"]
        response = await client.get(f"/v1/snapshots/{snapshot_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert data["payload"]["id"] == snapshot_id
        assert data["payload"]["title"] == sample_snapshot["title"]
        assert "pvValues" in data["payload"]
        assert len(data["payload"]["pvValues"]) > 0

    @pytest.mark.asyncio
    async def test_get_snapshot_not_found(self, client: AsyncClient):
        """Test getting non-existent snapshot."""
        response = await client.get("/v1/snapshots/nonexistent-id")

        assert response.status_code == 404
        data = response.json()
        assert data["errorCode"] == 404

    @pytest.mark.asyncio
    async def test_list_snapshots(self, client: AsyncClient, sample_snapshot: dict):
        """Test listing all snapshots."""
        response = await client.get("/v1/snapshots")

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert len(data["payload"]) >= 1

    @pytest.mark.asyncio
    async def test_list_snapshots_with_filter(self, client: AsyncClient, sample_snapshot: dict):
        """Test listing snapshots with title filter."""
        response = await client.get("/v1/snapshots", params={"title": "Test"})

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert len(data["payload"]) >= 1


class TestSnapshotRestore:
    """Tests for snapshot restore functionality."""

    @pytest.mark.asyncio
    async def test_restore_snapshot(self, client: AsyncClient, sample_snapshot: dict, mock_epics: MockEpicsService):
        """Test restoring a snapshot writes values to EPICS."""
        snapshot_id = sample_snapshot["id"]
        response = await client.post(f"/v1/snapshots/{snapshot_id}/restore")

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert "successCount" in data["payload"]
        assert "failureCount" in data["payload"]
        assert data["payload"]["failureCount"] == 0

    @pytest.mark.asyncio
    async def test_restore_snapshot_partial(
        self, client: AsyncClient, sample_snapshot: dict, sample_pvs: list[dict], mock_epics: MockEpicsService
    ):
        """Test restoring only specific PVs."""
        snapshot_id = sample_snapshot["id"]
        pv_ids = [sample_pvs[0]["id"], sample_pvs[1]["id"]]

        response = await client.post(f"/v1/snapshots/{snapshot_id}/restore", json={"pvIds": pv_ids})

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        # Only 2 PVs should be restored
        assert data["payload"]["totalPVs"] <= 2

    @pytest.mark.asyncio
    async def test_restore_snapshot_not_found(self, client: AsyncClient):
        """Test restoring non-existent snapshot."""
        response = await client.post("/v1/snapshots/nonexistent-id/restore")

        assert response.status_code == 404


class TestSnapshotCompare:
    """Tests for snapshot comparison."""

    @pytest.mark.asyncio
    async def test_compare_snapshots_identical(
        self, client: AsyncClient, sample_pvs: list[dict], mock_epics: MockEpicsService
    ):
        """Test comparing two identical snapshots."""
        # Set consistent values
        for pv in sample_pvs:
            if pv.get("setpointAddress"):
                mock_epics.set_mock_value(pv["setpointAddress"], 50.0)
            if pv.get("readbackAddress"):
                mock_epics.set_mock_value(pv["readbackAddress"], 49.5)

        # Create first snapshot
        resp1 = await client.post(
            "/v1/snapshots",
            params={"async": "false", "use_cache": "false"},
            json={"title": "Snapshot 1"},
        )
        snap1_id = resp1.json()["payload"]["id"]

        # Create second snapshot (same values)
        resp2 = await client.post(
            "/v1/snapshots",
            params={"async": "false", "use_cache": "false"},
            json={"title": "Snapshot 2"},
        )
        snap2_id = resp2.json()["payload"]["id"]

        # Compare
        response = await client.get(f"/v1/snapshots/{snap1_id}/compare/{snap2_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert data["payload"]["differenceCount"] == 0
        assert data["payload"]["matchCount"] > 0

    @pytest.mark.asyncio
    async def test_compare_snapshots_different(
        self, client: AsyncClient, sample_pvs: list[dict], mock_epics: MockEpicsService
    ):
        """Test comparing two different snapshots."""
        # Set initial values
        for pv in sample_pvs:
            if pv.get("setpointAddress"):
                mock_epics.set_mock_value(pv["setpointAddress"], 50.0)
            if pv.get("readbackAddress"):
                mock_epics.set_mock_value(pv["readbackAddress"], 49.5)

        # Create first snapshot
        resp1 = await client.post(
            "/v1/snapshots",
            params={"async": "false", "use_cache": "false"},
            json={"title": "Before Change"},
        )
        snap1_id = resp1.json()["payload"]["id"]

        # Change values significantly (beyond default tolerance)
        for pv in sample_pvs:
            if pv.get("setpointAddress"):
                mock_epics.set_mock_value(pv["setpointAddress"], 100.0)
            if pv.get("readbackAddress"):
                mock_epics.set_mock_value(pv["readbackAddress"], 99.5)

        # Create second snapshot
        resp2 = await client.post(
            "/v1/snapshots",
            params={"async": "false", "use_cache": "false"},
            json={"title": "After Change"},
        )
        snap2_id = resp2.json()["payload"]["id"]

        # Compare
        response = await client.get(f"/v1/snapshots/{snap1_id}/compare/{snap2_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert data["payload"]["differenceCount"] > 0

    @pytest.mark.asyncio
    async def test_compare_snapshots_not_found(self, client: AsyncClient, sample_snapshot: dict):
        """Test comparing with non-existent snapshot."""
        snapshot_id = sample_snapshot["id"]
        response = await client.get(f"/v1/snapshots/{snapshot_id}/compare/nonexistent-id")

        assert response.status_code == 404


class TestSnapshotDelete:
    """Tests for snapshot deletion."""

    @pytest.mark.asyncio
    async def test_delete_snapshot(self, client: AsyncClient, sample_snapshot: dict):
        """Test deleting a snapshot."""
        snapshot_id = sample_snapshot["id"]
        response = await client.delete(f"/v1/snapshots/{snapshot_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["errorCode"] == 0
        assert data["payload"] is True

        # Verify deletion
        get_response = await client.get(f"/v1/snapshots/{snapshot_id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_snapshot_not_found(self, client: AsyncClient):
        """Test deleting non-existent snapshot."""
        response = await client.delete("/v1/snapshots/nonexistent-id")

        assert response.status_code == 404
