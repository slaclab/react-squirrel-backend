from uuid import UUID

from fastapi import Query, Security, APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.tag import (
    TagCreate,
    TagUpdate,
    TagGroupDTO,
    AddTagResponse,
    TagGroupCreate,
    TagGroupUpdate,
    TagGroupSummaryDTO,
)
from app.dependencies import TagServiceDep, require_read_access, require_write_access

router = APIRouter(prefix="/tags", tags=["Tags"])


@router.get(
    "",
    dependencies=[Security(require_read_access)],
    response_model=list[TagGroupSummaryDTO],
)
async def get_all_tag_groups(service: TagServiceDep) -> list[TagGroupSummaryDTO]:
    """Get all tag groups with tag counts."""
    return await service.get_all_groups_summary()


@router.get(
    "/{group_id}",
    dependencies=[Security(require_read_access)],
    response_model=list[TagGroupDTO],
)
async def get_tag_group(group_id: str, service: TagServiceDep) -> list[TagGroupDTO]:
    """Get tag group by ID with all tags."""
    try:
        UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Tag group {group_id} not found")
    group = await service.get_group_by_id(group_id)
    if not group:
        raise HTTPException(status_code=404, detail=f"Tag group {group_id} not found")
    # Return as array to match frontend expectations
    return [group]


@router.post(
    "",
    dependencies=[Security(require_write_access)],
    response_model=TagGroupDTO,
)
async def create_tag_group(data: TagGroupCreate, service: TagServiceDep) -> TagGroupDTO:
    """Create a new tag group."""
    try:
        return await service.create_group(data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put(
    "/{group_id}",
    dependencies=[Security(require_write_access)],
    response_model=TagGroupDTO,
)
async def update_tag_group(
    group_id: str,
    data: TagGroupUpdate,
    service: TagServiceDep,
) -> TagGroupDTO:
    """Update a tag group."""
    try:
        UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Tag group {group_id} not found")
    try:
        group = await service.update_group(group_id, data)
        if not group:
            raise HTTPException(status_code=404, detail=f"Tag group {group_id} not found")
        return group
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete(
    "/{group_id}",
    dependencies=[Security(require_write_access)],
    response_model=bool,
)
async def delete_tag_group(
    group_id: str,
    service: TagServiceDep,
    force: bool = Query(False),
) -> bool:
    """Delete a tag group."""
    try:
        UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Tag group {group_id} not found")
    success = await service.delete_group(group_id, force=force)
    if not success:
        raise HTTPException(status_code=404, detail=f"Tag group {group_id} not found")
    return True


@router.post(
    "/{group_id}/tags",
    dependencies=[Security(require_write_access)],
    response_model=AddTagResponse,
)
async def add_tag_to_group(
    group_id: str,
    data: TagCreate,
    service: TagServiceDep,
    skip_duplicates: bool = Query(False, description="Skip duplicate tags instead of raising error"),
) -> AddTagResponse:
    """Add a tag to a group."""
    try:
        UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Tag group {group_id} not found")
    try:
        group, was_created = await service.add_tag_to_group(group_id, data, skip_duplicates=skip_duplicates)
        if not group:
            raise HTTPException(status_code=404, detail=f"Tag group {group_id} not found")
        return AddTagResponse(group=group, wasCreated=was_created)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put(
    "/{group_id}/tags/{tag_id}",
    dependencies=[Security(require_write_access)],
    response_model=TagGroupDTO,
)
async def update_tag(
    group_id: str,
    tag_id: str,
    data: TagUpdate,
    service: TagServiceDep,
) -> TagGroupDTO:
    """Update a tag in a group."""
    try:
        UUID(group_id)
        UUID(tag_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Tag {tag_id} not found in group {group_id}")
    group = await service.update_tag(group_id, tag_id, data)
    if not group:
        raise HTTPException(status_code=404, detail=f"Tag {tag_id} not found in group {group_id}")
    return group


@router.delete(
    "/{group_id}/tags/{tag_id}",
    dependencies=[Security(require_write_access)],
    response_model=TagGroupDTO,
)
async def remove_tag(
    group_id: str,
    tag_id: str,
    service: TagServiceDep,
) -> TagGroupDTO:
    """Remove a tag from a group."""
    try:
        UUID(group_id)
        UUID(tag_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Tag {tag_id} not found in group {group_id}")
    group = await service.remove_tag(group_id, tag_id)
    if not group:
        raise HTTPException(status_code=404, detail=f"Tag {tag_id} not found in group {group_id}")
    return group


class BulkTagImportRequest(BaseModel):
    """Request schema for bulk tag import."""

    groups: dict[str, list[str]]  # group_name -> list of tag names


class BulkTagImportResponse(BaseModel):
    """Response schema for bulk tag import."""

    groupsCreated: int
    tagsCreated: int
    tagsSkipped: int
    warnings: list[str]


@router.post("/bulk", response_model=BulkTagImportResponse)
async def bulk_import_tags(
    data: BulkTagImportRequest,
    service: TagServiceDep,
) -> BulkTagImportResponse:
    """Bulk import tags with duplicate handling."""
    groups_created = 0
    tags_created = 0
    tags_skipped = 0
    warnings: list[str] = []

    # Get existing tag groups
    existing_summaries = await service.get_all_groups_summary()
    existing_group_map = {g.name: g.id for g in existing_summaries}

    for group_name, tag_names in data.groups.items():
        # Get or create group
        group_id = existing_group_map.get(group_name)
        if not group_id:
            # Create new group
            try:
                group = await service.create_group(TagGroupCreate(name=group_name))
                group_id = group.id
                existing_group_map[group_name] = group_id
                groups_created += 1
            except ValueError as e:
                warnings.append(f"Failed to create group '{group_name}': {e}")
                continue

        # Add tags to group
        for tag_name in tag_names:
            try:
                _, was_created = await service.add_tag_to_group(
                    group_id, TagCreate(name=tag_name), skip_duplicates=True
                )
                if was_created:
                    tags_created += 1
                else:
                    tags_skipped += 1
                    warnings.append(f"Tag '{tag_name}' already exists in group '{group_name}'")
            except Exception as e:
                warnings.append(f"Failed to add tag '{tag_name}' to group '{group_name}': {e}")

    return BulkTagImportResponse(
        groupsCreated=groups_created,
        tagsCreated=tags_created,
        tagsSkipped=tags_skipped,
        warnings=warnings,
    )
