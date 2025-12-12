from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.tag_service import TagService
from app.schemas.tag import (
    TagGroupCreate, TagGroupUpdate, TagGroupDTO, TagGroupSummaryDTO,
    TagCreate, TagUpdate
)
from app.api.responses import success_response, APIException

router = APIRouter(prefix="/tags", tags=["Tags"])


@router.get("", response_model=dict)
async def get_all_tag_groups(
    db: AsyncSession = Depends(get_db)
):
    """Get all tag groups with tag counts."""
    service = TagService(db)
    groups = await service.get_all_groups_summary()
    return success_response(groups)


@router.get("/{group_id}", response_model=dict)
async def get_tag_group(
    group_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get tag group by ID with all tags."""
    service = TagService(db)
    group = await service.get_group_by_id(group_id)
    if not group:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    # Return as array to match frontend expectations
    return success_response([group])


@router.post("", response_model=dict)
async def create_tag_group(
    data: TagGroupCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new tag group."""
    service = TagService(db)
    try:
        group = await service.create_group(data)
        return success_response(group)
    except ValueError as e:
        raise APIException(409, str(e), 409)


@router.put("/{group_id}", response_model=dict)
async def update_tag_group(
    group_id: str,
    data: TagGroupUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a tag group."""
    service = TagService(db)
    try:
        group = await service.update_group(group_id, data)
        if not group:
            raise APIException(404, f"Tag group {group_id} not found", 404)
        return success_response(group)
    except ValueError as e:
        raise APIException(409, str(e), 409)


@router.delete("/{group_id}", response_model=dict)
async def delete_tag_group(
    group_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db)
):
    """Delete a tag group."""
    service = TagService(db)
    success = await service.delete_group(group_id, force=force)
    if not success:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    return success_response(True)


@router.post("/{group_id}/tags", response_model=dict)
async def add_tag_to_group(
    group_id: str,
    data: TagCreate,
    db: AsyncSession = Depends(get_db)
):
    """Add a tag to a group."""
    service = TagService(db)
    try:
        group = await service.add_tag_to_group(group_id, data)
        if not group:
            raise APIException(404, f"Tag group {group_id} not found", 404)
        return success_response(group)
    except ValueError as e:
        raise APIException(409, str(e), 409)


@router.put("/{group_id}/tags/{tag_id}", response_model=dict)
async def update_tag(
    group_id: str,
    tag_id: str,
    data: TagUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a tag in a group."""
    service = TagService(db)
    group = await service.update_tag(group_id, tag_id, data)
    if not group:
        raise APIException(404, f"Tag {tag_id} not found in group {group_id}", 404)
    return success_response(group)


@router.delete("/{group_id}/tags/{tag_id}", response_model=dict)
async def remove_tag(
    group_id: str,
    tag_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Remove a tag from a group."""
    service = TagService(db)
    group = await service.remove_tag(group_id, tag_id)
    if not group:
        raise APIException(404, f"Tag {tag_id} not found in group {group_id}", 404)
    return success_response(group)
