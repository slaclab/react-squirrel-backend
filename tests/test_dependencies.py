"""
Tests for app/dependencies.py — service factories and auth guards.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from app.dependencies import (
    get_api_key,
    get_pv_service,
    get_tag_service,
    require_read_access,
    get_snapshot_service,
    require_write_access,
)
from app.api.responses import APIException
from app.schemas.api_key import ApiKeyDTO
from app.services.pv_service import PVService
from app.services.tag_service import TagService
from app.services.snapshot_service import SnapshotService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api_key_dto(**overrides) -> ApiKeyDTO:
    """Build a minimal ApiKeyDTO with sensible defaults."""
    defaults = {
        "id": "test-id-123",
        "appName": "TestApp",
        "isActive": True,
        "readAccess": True,
        "writeAccess": False,
        "createdAt": datetime.now(),
        "updatedAt": datetime.now(),
    }
    defaults.update(overrides)
    return ApiKeyDTO(**defaults)


# ---------------------------------------------------------------------------
# Service factory functions
# ---------------------------------------------------------------------------


class TestGetPvService:
    """Tests for get_pv_service."""

    def test_returns_pv_service_instance(self):
        db = MagicMock()
        result = get_pv_service(db)
        assert isinstance(result, PVService)

    def test_passes_db_to_service(self):
        db = MagicMock()
        result = get_pv_service(db)
        assert result.session is db


class TestGetTagService:
    """Tests for get_tag_service."""

    def test_returns_tag_service_instance(self):
        db = MagicMock()
        result = get_tag_service(db)
        assert isinstance(result, TagService)

    def test_passes_db_to_service(self):
        db = MagicMock()
        result = get_tag_service(db)
        assert result.session is db


class TestGetSnapshotService:
    """Tests for get_snapshot_service."""

    def test_returns_snapshot_service_instance(self):
        db = MagicMock()
        epics = MagicMock()
        result = get_snapshot_service(db, epics)
        assert isinstance(result, SnapshotService)

    def test_passes_db_and_epics_to_service(self):
        db = MagicMock()
        epics = MagicMock()
        result = get_snapshot_service(db, epics)
        assert result.session is db
        assert result.epics is epics


# ---------------------------------------------------------------------------
# get_api_key
# ---------------------------------------------------------------------------


class TestGetApiKey:
    """Tests for get_api_key dependency."""

    @pytest.mark.asyncio
    async def test_no_header_raises_401(self):
        """Missing header (None) should raise 401 immediately."""
        db = MagicMock()
        with pytest.raises(APIException) as exc_info:
            await get_api_key(db, None)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.error_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_unknown_token_raises_401(self):
        """A token not found in the DB should raise 401."""
        db = MagicMock()
        with patch("app.dependencies.ApiKeyService") as MockService:
            MockService.return_value.get_by_token = AsyncMock(return_value=None)
            with pytest.raises(APIException) as exc_info:
                await get_api_key(db, "sq_unknown")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.error_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_inactive_key_raises_401(self):
        """A deactivated key should raise 401."""
        db = MagicMock()
        inactive_key = _make_api_key_dto(isActive=False)
        with patch("app.dependencies.ApiKeyService") as MockService:
            MockService.return_value.get_by_token = AsyncMock(return_value=inactive_key)
            with pytest.raises(APIException) as exc_info:
                await get_api_key(db, "sq_inactive")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.error_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_active_key_returns_dto(self):
        """A valid, active key should be returned as-is."""
        db = MagicMock()
        active_key = _make_api_key_dto(isActive=True)
        with patch("app.dependencies.ApiKeyService") as MockService:
            MockService.return_value.get_by_token = AsyncMock(return_value=active_key)
            result = await get_api_key(db, "sq_valid_token")
        assert result is active_key

    @pytest.mark.asyncio
    async def test_error_message_mentions_api_key(self):
        """401 error message should reference the API key."""
        db = MagicMock()
        with pytest.raises(APIException) as exc_info:
            await get_api_key(db, None)
        assert "api key" in exc_info.value.error_message.lower()

    @pytest.mark.asyncio
    async def test_service_receives_provided_token(self):
        """The exact header value should be forwarded to ApiKeyService.get_by_token."""
        db = MagicMock()
        token = "sq_specific_token_value"
        with patch("app.dependencies.ApiKeyService") as MockService:
            mock_get = AsyncMock(return_value=None)
            MockService.return_value.get_by_token = mock_get
            with pytest.raises(APIException):
                await get_api_key(db, token)
        mock_get.assert_awaited_once_with(token)


# ---------------------------------------------------------------------------
# require_read_access
# ---------------------------------------------------------------------------


class TestRequireReadAccess:
    """Tests for require_read_access dependency."""

    def test_raises_401_when_read_access_false(self):
        """A key without read access should be rejected."""
        dto = _make_api_key_dto(readAccess=False)
        with pytest.raises(APIException) as exc_info:
            require_read_access(dto)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.error_code == status.HTTP_401_UNAUTHORIZED

    def test_passes_when_read_access_true(self):
        """A key with read access should not raise."""
        dto = _make_api_key_dto(readAccess=True)
        require_read_access(dto)  # must not raise

    def test_error_message_mentions_read(self):
        """Error message should indicate lack of read access."""
        dto = _make_api_key_dto(readAccess=False)
        with pytest.raises(APIException) as exc_info:
            require_read_access(dto)
        assert "read" in exc_info.value.error_message.lower()


# ---------------------------------------------------------------------------
# require_write_access
# ---------------------------------------------------------------------------


class TestRequireWriteAccess:
    """Tests for require_write_access dependency."""

    def test_raises_401_when_write_access_false(self):
        """A key without write access should be rejected."""
        dto = _make_api_key_dto(writeAccess=False)
        with pytest.raises(APIException) as exc_info:
            require_write_access(dto)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.error_code == status.HTTP_401_UNAUTHORIZED

    def test_passes_when_write_access_true(self):
        """A key with write access should not raise."""
        dto = _make_api_key_dto(writeAccess=True)
        require_write_access(dto)  # must not raise

    def test_error_message_mentions_write(self):
        """Error message should indicate lack of write access."""
        dto = _make_api_key_dto(writeAccess=False)
        with pytest.raises(APIException) as exc_info:
            require_write_access(dto)
        assert "write" in exc_info.value.error_message.lower()
