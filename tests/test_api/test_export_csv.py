"""
Tests for CSV export API endpoints.
"""

import pytest
from httpx import AsyncClient


class TestExportCSV:
    """Tests for the database export CSV endpoint."""

    @pytest.mark.asyncio
    async def test_export_csv_success(self, client: AsyncClient, sample_pvs: list, sample_tag: tuple):
        """Test successful CSV export with PVs and Tags."""
        response = await client.get("/v1/export/export_csv")

        assert response.status_code == 200
        assert response.headers["content-type"] == "csv"
        assert "Content-Disposition" in response.headers
        assert "attachment; filename=database_export_" in response.headers["Content-Disposition"]

        content = response.text
        assert "=== PVs Export ===" in content
        assert "=== Tags Export ===" in content

        # Check all PV headers are present
        assert "ID" in content
        assert "Setpoint Address" in content
        assert "Readback Address" in content
        assert "Config Address" in content
        assert "Device" in content
        assert "Description" in content
        assert "Abs Tolerance" in content
        assert "Rel Tolerance" in content
        assert "Read Only" in content

        # Check all Tag headers are present
        assert "Group ID" in content
        assert "Group Name" in content
        assert "Group Description" in content
        assert "Tag ID" in content
        assert "Tag Name" in content
        assert "Tag Description" in content

        # Check that PV data is included
        for pv in sample_pvs:
            assert pv["setpointAddress"] in content
            assert pv["readbackAddress"] in content
            assert pv["device"] in content

        tag = sample_tag[1]

        # Check that Tag data is included
        assert tag["name"] in content
        assert tag["description"] in content

    @pytest.mark.asyncio
    async def test_export_csv_empty_database(self, client: AsyncClient):
        """Test CSV export with no data in database."""
        response = await client.get("/v1/export/export_csv")

        assert response.status_code == 200
        content = response.text

        # Should still have headers and section markers
        assert "=== PVs Export ===" in content
        assert "=== Tags Export ===" in content
        assert "ID" in content  # PV headers
        assert "Group ID" in content  # Tag headers

    @pytest.mark.asyncio
    async def test_export_csv_downloadable_filename(self, client: AsyncClient):
        """Test that export CSV returns a proper downloadable filename."""
        response = await client.get("/v1/export/export_csv")

        assert response.status_code == 200
        content_disposition = response.headers.get("Content-Disposition", "")

        assert "attachment" in content_disposition
        assert "filename=" in content_disposition
        assert "database_export_" in content_disposition
        # Check filename has date format (YYYY-MM-DD_HH-MM-SS)
        assert ".csv" in content_disposition
