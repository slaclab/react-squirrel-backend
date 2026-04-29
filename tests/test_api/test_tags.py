"""
Tests for Tags API endpoints.
"""

import pytest
from httpx import AsyncClient


class TestTagGroupCreate:
    """Tests for tag group creation."""

    @pytest.mark.asyncio
    async def test_create_tag_group(self, client: AsyncClient):
        """Test creating a new tag group."""
        response = await client.post("/v1/tags", json={"name": "Location", "description": "Physical location tags"})

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Location"
        assert data["description"] == "Physical location tags"
        assert data["id"] is not None
        assert data["tags"] == []

    @pytest.mark.asyncio
    async def test_create_tag_group_without_description(self, client: AsyncClient):
        """Test creating a tag group without description."""
        response = await client.post("/v1/tags", json={"name": "System"})

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "System"
        assert data["description"] is None

    @pytest.mark.asyncio
    async def test_create_tag_group_duplicate_name_fails(self, client: AsyncClient, sample_tag_group: dict):
        """Test that duplicate group names are rejected."""
        response = await client.post("/v1/tags", json={"name": sample_tag_group["name"]})  # Duplicate name

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_tag_group_requires_name(self, client: AsyncClient):
        """Test that group name is required."""
        response = await client.post("/v1/tags", json={"description": "No name provided"})

        assert response.status_code == 422  # Validation error


class TestTagGroupGet:
    """Tests for tag group retrieval."""

    @pytest.mark.asyncio
    async def test_get_all_tag_groups(self, client: AsyncClient, sample_tag_group: dict):
        """Test listing all tag groups."""
        response = await client.get("/v1/tags")

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

        # Check that summary includes tag count
        group = next(g for g in data if g["id"] == sample_tag_group["id"])
        assert "tagCount" in group

    @pytest.mark.asyncio
    async def test_get_tag_group_by_id(self, client: AsyncClient, sample_tag_group: dict):
        """Test getting a tag group by ID."""
        group_id = sample_tag_group["id"]
        response = await client.get(f"/v1/tags/{group_id}")

        assert response.status_code == 200
        data = response.json()
        # Response is wrapped in array per frontend expectation
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == group_id

    @pytest.mark.asyncio
    async def test_get_tag_group_not_found(self, client: AsyncClient):
        """Test getting non-existent tag group."""
        response = await client.get("/v1/tags/nonexistent-id")

        assert response.status_code == 404


class TestTagGroupUpdate:
    """Tests for tag group updates."""

    @pytest.mark.asyncio
    async def test_update_tag_group_name(self, client: AsyncClient, sample_tag_group: dict):
        """Test updating tag group name."""
        group_id = sample_tag_group["id"]
        response = await client.put(f"/v1/tags/{group_id}", json={"name": "Updated Location"})

        assert response.status_code == 200
        assert response.json()["name"] == "Updated Location"

    @pytest.mark.asyncio
    async def test_update_tag_group_description(self, client: AsyncClient, sample_tag_group: dict):
        """Test updating tag group description."""
        group_id = sample_tag_group["id"]
        response = await client.put(f"/v1/tags/{group_id}", json={"description": "Updated description"})

        assert response.status_code == 200
        assert response.json()["description"] == "Updated description"

    @pytest.mark.asyncio
    async def test_update_tag_group_not_found(self, client: AsyncClient):
        """Test updating non-existent tag group."""
        response = await client.put("/v1/tags/nonexistent-id", json={"name": "Should Fail"})

        assert response.status_code == 404


class TestTagGroupDelete:
    """Tests for tag group deletion."""

    @pytest.mark.asyncio
    async def test_delete_tag_group(self, client: AsyncClient, sample_tag_group: dict):
        """Test deleting a tag group."""
        group_id = sample_tag_group["id"]
        response = await client.delete(f"/v1/tags/{group_id}")

        assert response.status_code == 200
        assert response.json() is True

        # Verify deletion
        get_response = await client.get(f"/v1/tags/{group_id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_tag_group_not_found(self, client: AsyncClient):
        """Test deleting non-existent tag group."""
        response = await client.delete("/v1/tags/nonexistent-id")

        assert response.status_code == 404


class TestTagOperations:
    """Tests for individual tag operations within groups."""

    @pytest.mark.asyncio
    async def test_add_tag_to_group(self, client: AsyncClient, sample_tag_group: dict):
        """Test adding a tag to a group."""
        group_id = sample_tag_group["id"]
        response = await client.post(
            f"/v1/tags/{group_id}/tags", json={"name": "Building-A", "description": "Building A location"}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["group"]["tags"]) == 1
        assert data["group"]["tags"][0]["name"] == "Building-A"

    @pytest.mark.asyncio
    async def test_add_multiple_tags_to_group(self, client: AsyncClient, sample_tag_group: dict):
        """Test adding multiple tags to a group."""
        group_id = sample_tag_group["id"]

        # Add first tag
        await client.post(f"/v1/tags/{group_id}/tags", json={"name": "Tag-1"})

        # Add second tag
        response = await client.post(f"/v1/tags/{group_id}/tags", json={"name": "Tag-2"})

        assert response.status_code == 200
        assert len(response.json()["group"]["tags"]) == 2

    @pytest.mark.asyncio
    async def test_add_duplicate_tag_fails(self, client: AsyncClient, sample_tag: tuple):
        """Test that duplicate tag names within a group are rejected by default."""
        group, tag = sample_tag
        group_id = group["id"]

        response = await client.post(f"/v1/tags/{group_id}/tags", json={"name": tag["name"]})  # Duplicate name

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_add_duplicate_tag_with_skip_duplicates_succeeds(self, client: AsyncClient, sample_tag: tuple):
        """Test that duplicate tag names succeed when skip_duplicates is true."""
        group, tag = sample_tag
        group_id = group["id"]

        response = await client.post(
            f"/v1/tags/{group_id}/tags?skip_duplicates=true",
            json={"name": tag["name"]},  # Duplicate name
        )

        assert response.status_code == 200
        data = response.json()
        assert data["wasCreated"] is False  # Tag already existed
        assert data["group"]["id"] == group_id

    @pytest.mark.asyncio
    async def test_add_tag_to_nonexistent_group(self, client: AsyncClient):
        """Test adding tag to non-existent group."""
        response = await client.post("/v1/tags/nonexistent-id/tags", json={"name": "Should Fail"})

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_tag(self, client: AsyncClient, sample_tag: tuple):
        """Test updating a tag."""
        group, tag = sample_tag
        group_id = group["id"]
        tag_id = tag["id"]

        response = await client.put(
            f"/v1/tags/{group_id}/tags/{tag_id}",
            json={"name": "Updated-Tag-Name", "description": "Updated description"},
        )

        assert response.status_code == 200
        data = response.json()
        updated_tag = next(t for t in data["tags"] if t["id"] == tag_id)
        assert updated_tag["name"] == "Updated-Tag-Name"

    @pytest.mark.asyncio
    async def test_update_tag_not_found(self, client: AsyncClient, sample_tag_group: dict):
        """Test updating non-existent tag."""
        group_id = sample_tag_group["id"]
        response = await client.put(f"/v1/tags/{group_id}/tags/nonexistent-tag", json={"name": "Should Fail"})

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_remove_tag(self, client: AsyncClient, sample_tag: tuple):
        """Test removing a tag from a group."""
        group, tag = sample_tag
        group_id = group["id"]
        tag_id = tag["id"]

        response = await client.delete(f"/v1/tags/{group_id}/tags/{tag_id}")

        assert response.status_code == 200
        # Tag should be removed from the group
        assert len(response.json()["tags"]) == 0

    @pytest.mark.asyncio
    async def test_remove_tag_not_found(self, client: AsyncClient, sample_tag_group: dict):
        """Test removing non-existent tag."""
        group_id = sample_tag_group["id"]
        response = await client.delete(f"/v1/tags/{group_id}/tags/nonexistent-tag")

        assert response.status_code == 404


class TestBulkTagImport:
    """Tests for bulk tag import endpoint."""

    @pytest.mark.asyncio
    async def test_bulk_import_tags_creates_new_groups_and_tags(self, client: AsyncClient):
        """Test bulk import creates new groups and tags."""
        response = await client.post(
            "/v1/tags/bulk",
            json={
                "groups": {
                    "Location": ["Building-A", "Building-B", "Building-C"],
                    "System": ["System-1", "System-2"],
                }
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["groupsCreated"] == 2
        assert data["tagsCreated"] == 5
        assert data["tagsSkipped"] == 0
        assert len(data["warnings"]) == 0

    @pytest.mark.asyncio
    async def test_bulk_import_tags_skips_duplicates(self, client: AsyncClient, sample_tag: tuple):
        """Test bulk import skips duplicate tags."""
        group, tag = sample_tag
        group_name = group["name"]

        response = await client.post(
            "/v1/tags/bulk",
            json={
                "groups": {
                    group_name: [tag["name"], "New-Tag-1", "New-Tag-2"],
                }
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["groupsCreated"] == 0  # Group already exists
        assert data["tagsCreated"] == 2  # Only new tags created
        assert data["tagsSkipped"] == 1  # Duplicate tag skipped
        assert len(data["warnings"]) == 1
        assert "already exists" in data["warnings"][0]

    @pytest.mark.asyncio
    async def test_bulk_import_tags_with_existing_group(self, client: AsyncClient, sample_tag_group: dict):
        """Test bulk import adds tags to existing group."""
        group_name = sample_tag_group["name"]

        response = await client.post(
            "/v1/tags/bulk",
            json={
                "groups": {
                    group_name: ["New-Tag-A", "New-Tag-B"],
                }
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["groupsCreated"] == 0  # Group already exists
        assert data["tagsCreated"] == 2
        assert data["tagsSkipped"] == 0

    @pytest.mark.asyncio
    async def test_bulk_import_tags_empty_groups(self, client: AsyncClient):
        """Test bulk import with empty groups dict."""
        response = await client.post("/v1/tags/bulk", json={"groups": {}})

        assert response.status_code == 200
        data = response.json()
        assert data["groupsCreated"] == 0
        assert data["tagsCreated"] == 0
        assert data["tagsSkipped"] == 0
