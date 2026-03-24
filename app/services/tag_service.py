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

    async def add_tag_to_group(
        self, group_id: str, data: TagCreate, skip_duplicates: bool = False
    ) -> tuple[TagGroupDTO | None, bool]:
        """
        Add a tag to a group.

        Args:
            group_id: The group ID to add the tag to
            data: Tag creation data
            skip_duplicates: If True, return success even if tag already exists

        Returns:
            Tuple of (group_dto, was_created)
            - group_dto: The updated group, or None if group not found
            - was_created: True if tag was created, False if it already existed
        """
        group = await self.group_repo.get_with_tags(group_id)
        if not group:
            return None, False

        # Check for duplicate tag name in group
        existing = await self.tag_repo.find_by_group_and_name(group_id, data.name)
        if existing:
            if skip_duplicates:
                # Return success but indicate tag already existed
                group_dto = await self.get_group_by_id(group_id)
                return group_dto, False
            else:
                # Raise error for strict validation (backward compatibility)
                raise ValueError(f"Tag '{data.name}' already exists in this group")

        tag = Tag(name=data.name, description=data.description, group_id=group_id)
        await self.tag_repo.create(tag)

        # Expire cached group and refresh to get updated tags
        self.group_repo.session.expire(group)
        updated_group = await self.group_repo.get_with_tags(group_id)

        # Type narrowing: updated_group is guaranteed to exist since we just created a tag in it
        assert updated_group is not None

        return (
            TagGroupDTO(
                id=updated_group.id,
                name=updated_group.name,
                description=updated_group.description,
                tags=[TagDTO(id=t.id, name=t.name, description=t.description) for t in updated_group.tags],
                createdDate=updated_group.created_at,
                lastModifiedDate=updated_group.updated_at,
            ),
            True,
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
