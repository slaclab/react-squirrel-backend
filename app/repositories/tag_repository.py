from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import Tag, TagGroup
from app.repositories.base import BaseRepository


class TagGroupRepository(BaseRepository[TagGroup]):
    """Repository for TagGroup operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(TagGroup, session)

    async def get_with_tags(self, group_id: str) -> TagGroup | None:
        """Get tag group with all tags loaded."""
        result = await self.session.execute(
            select(TagGroup).options(selectinload(TagGroup.tags)).where(TagGroup.id == group_id)
        )
        return result.scalar_one_or_none()

    async def find_by_name(self, name: str) -> TagGroup | None:
        """Find tag group by name (case-insensitive)."""
        result = await self.session.execute(select(TagGroup).where(func.lower(TagGroup.name) == name.lower()))
        return result.scalar_one_or_none()

    async def get_all_with_counts(self) -> list[tuple[TagGroup, int]]:
        """Get all tag groups with tag counts."""
        result = await self.session.execute(
            select(TagGroup, func.count(Tag.id).label("tag_count"))
            .outerjoin(Tag)
            .group_by(TagGroup.id)
            .order_by(TagGroup.name)
        )
        return list(result.all())


class TagRepository(BaseRepository[Tag]):
    """Repository for Tag operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(Tag, session)

    async def get_by_ids(self, tag_ids: list[str]) -> list[Tag]:
        """Get multiple tags by ID."""
        if not tag_ids:
            return []
        result = await self.session.execute(select(Tag).where(Tag.id.in_(tag_ids)))
        return list(result.scalars().all())

    async def find_by_group_and_name(self, group_id: str, name: str) -> Tag | None:
        """Find tag by group and name."""
        result = await self.session.execute(
            select(Tag).where(Tag.group_id == group_id).where(func.lower(Tag.name) == name.lower())
        )
        return result.scalar_one_or_none()
