"""Service for managing API Keys for authorization."""

import hashlib
import logging
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyDTO, ApiKeyCreateDTO, ApiKeyCreateResultDTO
from app.repositories.api_key_repository import ApiKeyRepository

logger = logging.getLogger(__name__)


class ApiKeyService:
    """Service for creating and managing API Keys for authorization."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ApiKeyRepository(session)

    def _to_dto(self, api_key: ApiKey) -> ApiKeyDTO:
        """Convert API Key model to DTO."""
        return ApiKeyDTO(
            id=api_key.id,
            appName=api_key.app_name,
            isActive=api_key.is_active,
            readAccess=api_key.read_access,
            writeAccess=api_key.write_access,
            createdAt=api_key.created_at,
            updatedAt=api_key.updated_at,
        )

    def _hash_token(self, token: str) -> str:
        """Hash the API token using SHA-256."""
        return hashlib.sha256(token.encode()).hexdigest()

    async def create_key(self, data: ApiKeyCreateDTO) -> ApiKeyCreateResultDTO:
        """Create a new API Key record."""
        existing_key = await self.repo.get_by_app_name(data.appName)
        if existing_key:
            raise ValueError(f"An API Key with appName '{data.appName}' already exists.")
        if not (data.readAccess or data.writeAccess):
            raise ValueError("Cannot create an API Key with no access.")

        plaintext_token = "sq_" + secrets.token_urlsafe(32)
        api_key = ApiKey(
            app_name=data.appName,
            token_hash=self._hash_token(plaintext_token),
            read_access=data.readAccess,
            write_access=data.writeAccess,
        )

        created_key = await self.repo.create(api_key)
        return ApiKeyCreateResultDTO(token=plaintext_token, **self._to_dto(created_key).model_dump())

    async def get_count(self, active_only: bool = False) -> int:
        """Get total count of API Keys. Optionally filter by active status."""
        return await self.repo.count(active_only)

    async def get_by_id(self, key_id: str) -> ApiKeyDTO | None:
        """Get API Key by ID."""
        api_key = await self.repo.get_by_id(key_id)
        return self._to_dto(api_key) if api_key else None

    async def get_by_token(self, plaintext_token: str, active_only: bool = False) -> ApiKeyDTO | None:
        """Get API Key by the plaintext token."""
        token_hash = self._hash_token(plaintext_token)
        api_key = await self.repo.get_by_token_hash(token_hash, active_only)
        return self._to_dto(api_key) if api_key else None

    async def list_keys(self, active_only: bool = False) -> list[ApiKeyDTO]:
        """List all API Keys (without token hash). Optionally filter by active status."""
        all_keys = await self.repo.get_all(active_only)
        return list(map(self._to_dto, all_keys))

    async def deactivate_key(self, key_id: str) -> ApiKeyDTO | None:
        """Deactivate API Key by ID."""
        api_key = await self.repo.get_by_id(key_id)
        if not api_key:
            raise LookupError(f"API Key with id '{key_id}' not found.")
        if not api_key.is_active:
            raise ValueError(f"API Key with id '{key_id}' is already inactive.")
        inactive_key = await self.repo.deactivate_api_key(api_key)
        return self._to_dto(inactive_key)
