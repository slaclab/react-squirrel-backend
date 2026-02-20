"""Repository for Job model operations."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    """Repository for API Key operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(ApiKey, session)

    async def get_by_app_name(self, app_name: str) -> ApiKey | None:
        """Get active API Key by unique app name."""
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.is_active == True).where(ApiKey.app_name == app_name)
        )
        return result.scalars().first()

    async def get_by_token_hash(self, token_hash: str, active_only: bool = False) -> ApiKey | None:
        """Get API Key by token hash, optionally filtered active keys."""
        query = select(ApiKey).where(ApiKey.token_hash == token_hash)
        if active_only:
            query = query.where(ApiKey.is_active == True)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def deactivate_api_key(self, api_key: ApiKey) -> ApiKey:
        """Deactivate an API Key."""
        api_key.is_active = False
        return await self.update(api_key)

    async def get_active(self) -> list[ApiKey]:
        """Get all active API Keys."""
        result = await self.session.execute(select(ApiKey).where(ApiKey.is_active == True))
        return result.scalars().all()
