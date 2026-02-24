"""Repository for ApiKey model operations."""
from sqlalchemy import func, select
from typing_extensions import override
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    """Repository for API Key operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(ApiKey, session)

    @override
    async def count(self, active_only: bool = False) -> int:
        """Get count of all API Keys. Optionally filter by active status."""
        query = select(func.count()).select_from(self.model)
        if active_only:
            query = query.where(ApiKey.is_active)
        result = await self.session.execute(query)
        return result.scalar() or 0

    @override
    async def get_all(self, active_only: bool = False) -> list[ApiKey]:
        """Get all API Keys. Optionally filter by active status."""
        query = select(ApiKey)
        if active_only:
            query = query.where(ApiKey.is_active)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_by_app_name(self, app_name: str) -> ApiKey | None:
        """Get active API Key by unique app name."""
        result = await self.session.execute(select(ApiKey).where(ApiKey.is_active).where(ApiKey.app_name == app_name))
        return result.scalars().first()

    async def get_by_token_hash(self, token_hash: str, active_only: bool = False) -> ApiKey | None:
        """Get API Key by token hash, optionally filtered active keys."""
        query = select(ApiKey).where(ApiKey.token_hash == token_hash)
        if active_only:
            query = query.where(ApiKey.is_active)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def deactivate_api_key(self, api_key: ApiKey) -> ApiKey:
        """Deactivate an API Key."""
        api_key.is_active = False
        return await self.update(api_key)
