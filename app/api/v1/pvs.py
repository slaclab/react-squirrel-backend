import os
import json
from uuid import UUID

from fastapi import Query, Depends, Security, APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.pv import (
    PVElementDTO,
    LivePVRequest,
    NewPVElementDTO,
    EpicsTestResponse,
    UpdatePVElementDTO,
    CacheStatusResponse,
    PVCacheEntryResponse,
    AllLiveValuesResponse,
    FilteredSearchResponse,
)
from app.dependencies import get_pv_service, require_read_access, require_write_access
from app.schemas.common import PagedResult
from app.services.pv_service import PVService
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service
from app.repositories.pv_repository import PVRepository

router = APIRouter(prefix="/pvs", tags=["PVs"])


@router.get(
    "",
    dependencies=[Security(require_read_access)],
    response_model=list[PVElementDTO],
)
async def search_pvs(
    pvName: str | None = Query(None),
    service: PVService = Depends(get_pv_service),
) -> list[PVElementDTO]:
    """Search PVs by name (non-paginated, for backward compatibility)."""
    result = await service.search_paged(search=pvName, page_size=1000)
    return result.results


@router.get(
    "/paged",
    dependencies=[Security(require_read_access)],
    response_model=PagedResult[PVElementDTO],
)
async def search_pvs_paged(
    pvName: str | None = Query(None),
    pageSize: int = Query(100, ge=1, le=1000),
    continuationToken: str | None = Query(None),
    tagFilters: str | None = Query(None, description="JSON object: {groupId: [tagId1, tagId2], ...}"),
    service: PVService = Depends(get_pv_service),
) -> PagedResult[PVElementDTO]:
    """
    Search PVs with pagination and optional tag filtering.

    Example tagFilters: {"group-1": ["tag-a", "tag-b"], "group-2": ["tag-c"]}
    This returns PVs that have (tag-a OR tag-b) AND (tag-c)
    """
    # Parse tag filters from JSON string
    tag_filters = None
    if tagFilters:
        try:
            tag_filters = json.loads(tagFilters)
            if not tag_filters:
                tag_filters = None
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid tagFilters JSON: {e}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return await service.search_paged(
        search=pvName,
        page_size=pageSize,
        continuation_token=continuationToken,
        tag_filters=tag_filters,
    )


@router.post(
    "",
    dependencies=[Security(require_write_access)],
    response_model=PVElementDTO,
)
async def create_pv(data: NewPVElementDTO, service: PVService = Depends(get_pv_service)) -> PVElementDTO:
    """Create a new PV."""
    try:
        return await service.create(data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/multi",
    dependencies=[Security(require_write_access)],
    response_model=list[PVElementDTO],
)
async def create_multiple_pvs(
    data: list[NewPVElementDTO],
    service: PVService = Depends(get_pv_service),
) -> list[PVElementDTO]:
    """Bulk create PVs (for CSV import)."""
    try:
        return await service.create_many(data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put(
    "/{pv_id}",
    dependencies=[Security(require_write_access)],
    response_model=PVElementDTO,
)
async def update_pv(
    pv_id: str,
    data: UpdatePVElementDTO,
    service: PVService = Depends(get_pv_service),
) -> PVElementDTO:
    """Update a PV."""
    try:
        UUID(pv_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"PV {pv_id} not found")
    pv = await service.update(pv_id, data)
    if not pv:
        raise HTTPException(status_code=404, detail=f"PV {pv_id} not found")
    return pv


@router.delete(
    "/{pv_id}",
    dependencies=[Security(require_write_access)],
    response_model=bool,
)
async def delete_pv(pv_id: str, service: PVService = Depends(get_pv_service)) -> bool:
    """Delete a PV."""
    try:
        UUID(pv_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"PV {pv_id} not found")
    success = await service.delete(pv_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"PV {pv_id} not found")
    return True


@router.get(
    "/search",
    dependencies=[Security(require_read_access)],
    response_model=FilteredSearchResponse,
)
async def search_pvs_filtered(
    q: str | None = Query(None, description="Text search"),
    devices: list[str] = Query(default=[], description="Filter by device"),
    tags: list[str] = Query(default=[], description="Filter by tag IDs"),
    limit: int = Query(100, le=1000, description="Max results"),
    offset: int = Query(0, description="Offset for pagination"),
    include_live_values: bool = Query(False, description="Include Redis cache values"),
    db: AsyncSession = Depends(get_db),
    service: PVService = Depends(get_pv_service),
) -> FilteredSearchResponse:
    """
    Server-side filtered search with optional live values.

    This is more efficient than client-side filtering for large datasets.
    """
    pv_repo = PVRepository(db)

    pvs, total = await pv_repo.search_filtered(
        search_term=q, devices=devices if devices else None, tag_ids=tags if tags else None, limit=limit, offset=offset
    )

    # Convert to DTOs
    results = [service._to_dto(pv) for pv in pvs]

    live_values: dict[str, PVCacheEntryResponse] | None = None
    live_values_error: str | None = None

    if include_live_values:
        try:
            redis = get_redis_service()
            pv_addresses = []
            for pv in pvs:
                if pv.setpoint_address:
                    pv_addresses.append(pv.setpoint_address)
                if pv.readback_address:
                    pv_addresses.append(pv.readback_address)

            entries = await redis.get_pv_values_bulk(pv_addresses)
            live_values = {name: PVCacheEntryResponse(**entry.to_dict()) for name, entry in entries.items()}
        except Exception as e:
            live_values_error = str(e)

    return FilteredSearchResponse(
        results=results,
        totalCount=total,
        limit=limit,
        offset=offset,
        liveValues=live_values,
        liveValuesError=live_values_error,
    )


@router.get(
    "/devices",
    dependencies=[Security(require_read_access)],
    response_model=list[str],
)
async def get_all_devices(db: AsyncSession = Depends(get_db)) -> list[str]:
    """Get all unique device names for filtering."""
    pv_repo = PVRepository(db)
    return await pv_repo.get_all_devices()


@router.get(
    "/live",
    dependencies=[Security(require_read_access)],
    response_model=dict[str, PVCacheEntryResponse],
)
async def get_live_values(
    pv_names: list[str] = Query(..., description="List of PV names to fetch"),
) -> dict[str, PVCacheEntryResponse]:
    """Get current values from Redis cache (instant)."""
    try:
        redis = get_redis_service()
        entries = await redis.get_pv_values_bulk(pv_names)
        return {pv_name: PVCacheEntryResponse(**entry.to_dict()) for pv_name, entry in entries.items()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get live values: {e}")


@router.post(
    "/live",
    dependencies=[Security(require_read_access)],
    response_model=dict[str, PVCacheEntryResponse],
)
async def get_live_values_post(request: LivePVRequest) -> dict[str, PVCacheEntryResponse]:
    """Get current values from Redis cache (instant) - POST version for large PV lists."""
    try:
        redis = get_redis_service()
        entries = await redis.get_pv_values_bulk(request.pv_names)
        return {pv_name: PVCacheEntryResponse(**entry.to_dict()) for pv_name, entry in entries.items()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get live values: {e}")


@router.get(
    "/live/all",
    dependencies=[Security(require_read_access)],
    response_model=AllLiveValuesResponse,
)
async def get_all_live_values() -> AllLiveValuesResponse:
    """Get all cached PV values (for initial table load)."""
    try:
        redis = get_redis_service()
        values = await redis.get_all_pv_values_as_dict()
        return AllLiveValuesResponse(
            values={name: PVCacheEntryResponse(**entry) for name, entry in values.items()},
            count=len(values),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get live values: {e}")


@router.get(
    "/cache/status",
    dependencies=[Security(require_read_access)],
    response_model=CacheStatusResponse,
)
async def get_cache_status() -> CacheStatusResponse:
    """Get Redis cache status."""
    try:
        redis = get_redis_service()
        count = await redis.get_cached_pv_count()
        return CacheStatusResponse(cachedPvCount=count, status="connected")
    except Exception as e:
        return CacheStatusResponse(cachedPvCount=0, status="disconnected", error=str(e))


@router.get(
    "/test-epics",
    dependencies=[Security(require_read_access)],
    response_model=EpicsTestResponse,
)
async def test_epics_connection(
    pv: str = Query("KLYS:LI22:31:KVAC", description="PV name to test"),
) -> EpicsTestResponse:
    """Test EPICS connectivity using aioca."""
    epics = get_epics_service()
    result = await epics.get_single(pv)
    return EpicsTestResponse(
        pv=pv,
        connected=result.connected,
        value=result.value,
        error=result.error,
        environment={
            "EPICS_CA_ADDR_LIST": os.environ.get("EPICS_CA_ADDR_LIST", "NOT SET"),
            "EPICS_CA_AUTO_ADDR_LIST": os.environ.get("EPICS_CA_AUTO_ADDR_LIST", "NOT SET"),
        },
    )
