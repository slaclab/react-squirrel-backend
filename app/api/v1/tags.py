from uuid import UUID

from fastapi import Query, Depends, Security, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

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
async def add_tag_to_group(group_id: str, data: TagCreate, db: AsyncSession = Depends(get_db)) -> dict:
    """Add a tag to a group."""
    try:
        UUID(group_id)
    except ValueError:
        raise APIException(404, f"Tag group {group_id} not found", 404)
    service = TagService(db)
    try:
        group = await service.add_tag_to_group(group_id, data)
        if not group:
            raise APIException(404, f"Tag group {group_id} not found", 404)
        return success_response(group)
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
