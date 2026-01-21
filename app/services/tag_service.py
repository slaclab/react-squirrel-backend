from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import Tag, TagGroup
from app.schemas.tag import (
    TagDTO,
    TagCreate,
    TagUpdate,
    TagGroupDTO,
    TagGroupCreate,
    TagGroupUpdate,
    TagGroupSummaryDTO,
)
from app.repositories.tag_repository import TagRepository, TagGroupRepository


class TagService:
    """Service for tag management operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.group_repo = TagGroupRepository(session)
        self.tag_repo = TagRepository(session)

    async def get_all_groups_summary(self) -> list[TagGroupSummaryDTO]:
        """Get all tag groups with counts."""
        groups_with_counts = await self.group_repo.get_all_with_counts()
        return [
            TagGroupSummaryDTO(id=group.id, name=group.name, description=group.description, tagCount=count)
            for group, count in groups_with_counts
        ]

    async def get_group_by_id(self, group_id: str) -> TagGroupDTO | None:
        """Get tag group with all tags."""
        group = await self.group_repo.get_with_tags(group_id)
        if not group:
            return None
        return TagGroupDTO(
            id=group.id,
            name=group.name,
            description=group.description,
            tags=[TagDTO(id=t.id, name=t.name, description=t.description) for t in group.tags],
            createdDate=group.created_at,
            lastModifiedDate=group.updated_at,
        )

    async def create_group(self, data: TagGroupCreate) -> TagGroupDTO:
        """Create a new tag group."""
        # Check for duplicate name
        existing = await self.group_repo.find_by_name(data.name)
        if existing:
            raise ValueError(f"Tag group with name '{data.name}' already exists")

        group = TagGroup(name=data.name, description=data.description)
        group = await self.group_repo.create(group)

        return TagGroupDTO(
            id=group.id,
            name=group.name,
            description=group.description,
            tags=[],
            createdDate=group.created_at,
            lastModifiedDate=group.updated_at,
        )

    async def update_group(self, group_id: str, data: TagGroupUpdate) -> TagGroupDTO | None:
        """Update a tag group."""
        group = await self.group_repo.get_with_tags(group_id)
        if not group:
            return None

        if data.name is not None:
            # Check for duplicate name
            existing = await self.group_repo.find_by_name(data.name)
            if existing and existing.id != group_id:
                raise ValueError(f"Tag group with name '{data.name}' already exists")
            group.name = data.name

        if data.description is not None:
            group.description = data.description

        group = await self.group_repo.update(group)

        return TagGroupDTO(
            id=group.id,
            name=group.name,
            description=group.description,
            tags=[TagDTO(id=t.id, name=t.name, description=t.description) for t in group.tags],
            createdDate=group.created_at,
            lastModifiedDate=group.updated_at,
        )

    async def delete_group(self, group_id: str, force: bool = False) -> bool:
        """Delete a tag group."""
        group = await self.group_repo.get_by_id(group_id)
        if not group:
            return False

        # TODO: Check if tags are in use (if not force)

        await self.group_repo.delete(group)
        return True

    async def add_tag_to_group(self, group_id: str, data: TagCreate) -> TagGroupDTO | None:
        """Add a tag to a group."""
        group = await self.group_repo.get_with_tags(group_id)
        if not group:
            return None

        # Check for duplicate tag name in group
        existing = await self.tag_repo.find_by_group_and_name(group_id, data.name)
        if existing:
            raise ValueError(f"Tag '{data.name}' already exists in this group")

        tag = Tag(name=data.name, description=data.description, group_id=group_id)
        await self.tag_repo.create(tag)

        # Expire cached group and refresh to get updated tags
        self.group_repo.session.expire(group)
        group = await self.group_repo.get_with_tags(group_id)

        return TagGroupDTO(
            id=group.id,
            name=group.name,
            description=group.description,
            tags=[TagDTO(id=t.id, name=t.name, description=t.description) for t in group.tags],
            createdDate=group.created_at,
            lastModifiedDate=group.updated_at,
        )

    async def update_tag(self, group_id: str, tag_id: str, data: TagUpdate) -> TagGroupDTO | None:
        """Update a tag in a group."""
        tag = await self.tag_repo.get_by_id(tag_id)
        if not tag or tag.group_id != group_id:
            return None

        if data.name is not None:
            tag.name = data.name
        if data.description is not None:
            tag.description = data.description

        await self.tag_repo.update(tag)

        return await self.get_group_by_id(group_id)

    async def remove_tag(self, group_id: str, tag_id: str) -> TagGroupDTO | None:
        """Remove a tag from a group."""
        tag = await self.tag_repo.get_by_id(tag_id)
        if not tag or tag.group_id != group_id:
            return None

        await self.tag_repo.delete(tag)

        return await self.get_group_by_id(group_id)
