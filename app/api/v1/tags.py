from uuid import UUID

from fastapi import Query, Depends, Security, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db.session import get_db
from app.schemas.tag import TagCreate, TagUpdate, TagGroupCreate, TagGroupUpdate
from app.dependencies import require_read_access, require_write_access
from app.api.responses import APIException, success_response
from app.services.tag_service import TagService

router = APIRouter(prefix="/tags", tags=["Tags"])


@router.get("", dependencies=[Security(require_read_access)])
async def get_all_tag_groups(db: AsyncSession = Depends(get_db)) -> dict:
    """Get all tag groups with tag counts."""
    service = TagService(db)
    groups = await service.get_all_groups_summary()
    return success_response(groups)


@router.get("/{group_id}", dependencies=[Security(require_read_access)])
async def get_tag_group(group_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Get tag group by ID with all tags."""
    try:
        UUID(group_id)
    except ValueError:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    service = TagService(db)
    group = await service.get_group_by_id(group_id)
    if not group:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    # Return as array to match frontend expectations
    return success_response([group])


@router.post("", dependencies=[Security(require_write_access)])
async def create_tag_group(data: TagGroupCreate, db: AsyncSession = Depends(get_db)) -> dict:
    """Create a new tag group."""
    service = TagService(db)
    try:
        group = await service.create_group(data)
        return success_response(group)
    except ValueError as e:
        raise APIException(409, str(e), 409)


@router.put("/{group_id}", dependencies=[Security(require_write_access)])
async def update_tag_group(group_id: str, data: TagGroupUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Update a tag group."""
    try:
        UUID(group_id)
    except ValueError:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    service = TagService(db)
    try:
        group = await service.update_group(group_id, data)
        if not group:
            raise APIException(404, f"Tag group {group_id} not found", 404)
        return success_response(group)
    except ValueError as e:
        raise APIException(409, str(e), 409)


@router.delete("/{group_id}", dependencies=[Security(require_write_access)])
async def delete_tag_group(group_id: str, force: bool = Query(False), db: AsyncSession = Depends(get_db)) -> dict:
    """Delete a tag group."""
    try:
        UUID(group_id)
    except ValueError:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    service = TagService(db)
    success = await service.delete_group(group_id, force=force)
    if not success:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    return success_response(True)


@router.post("/{group_id}/tags", dependencies=[Security(require_write_access)])
async def add_tag_to_group(
    group_id: str,
    data: TagCreate,
    skip_duplicates: bool = Query(False, description="Skip duplicate tags instead of raising error"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a tag to a group."""
    try:
        UUID(group_id)
    except ValueError:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    service = TagService(db)
    try:
        group, was_created = await service.add_tag_to_group(group_id, data, skip_duplicates=skip_duplicates)
        if not group:
            raise APIException(404, f"Tag group {group_id} not found", 404)
        return success_response({"group": group, "wasCreated": was_created})
    except ValueError as e:
        raise APIException(409, str(e), 409)


@router.put("/{group_id}/tags/{tag_id}", dependencies=[Security(require_write_access)])
async def update_tag(group_id: str, tag_id: str, data: TagUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Update a tag in a group."""
    try:
        UUID(group_id)
        UUID(tag_id)
    except ValueError:
        raise APIException(404, f"Tag {tag_id} not found in group {group_id}", 404)
    service = TagService(db)
    group = await service.update_tag(group_id, tag_id, data)
    if not group:
        raise APIException(404, f"Tag {tag_id} not found in group {group_id}", 404)
    return success_response(group)


@router.delete("/{group_id}/tags/{tag_id}", dependencies=[Security(require_write_access)])
async def remove_tag(group_id: str, tag_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Remove a tag from a group."""
    try:
        UUID(group_id)
        UUID(tag_id)
    except ValueError:
        raise APIException(404, f"Tag {tag_id} not found in group {group_id}", 404)
    service = TagService(db)
    group = await service.remove_tag(group_id, tag_id)
    if not group:
        raise APIException(404, f"Tag {tag_id} not found in group {group_id}", 404)
    return success_response(group)


class BulkTagImportRequest(BaseModel):
    """Request schema for bulk tag import."""

    groups: dict[str, list[str]]  # group_name -> list of tag names


class BulkTagImportResponse(BaseModel):
    """Response schema for bulk tag import."""

    groupsCreated: int
    tagsCreated: int
    tagsSkipped: int
    warnings: list[str]


@router.post("/bulk", response_model=dict)
async def bulk_import_tags(data: BulkTagImportRequest, db: AsyncSession = Depends(get_db)):
    """Bulk import tags with duplicate handling."""
    service = TagService(db)

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

    return success_response(
        BulkTagImportResponse(
            groupsCreated=groups_created,
            tagsCreated=tags_created,
            tagsSkipped=tags_skipped,
            warnings=warnings,
        )
    )
