import os
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.pv_service import PVService
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service
from app.repositories.pv_repository import PVRepository
from app.schemas.pv import NewPVElementDTO, UpdatePVElementDTO, PVElementDTO, LivePVRequest
from app.schemas.common import PagedResult
from app.api.responses import success_response, APIException

router = APIRouter(prefix="/pvs", tags=["PVs"])


@router.get("", response_model=dict)
async def search_pvs(
    pvName: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Search PVs by name (non-paginated, for backward compatibility)."""
    service = PVService(db)
    result = await service.search_paged(search=pvName, page_size=1000)
    return success_response(result.results)


@router.get("/paged", response_model=dict)
async def search_pvs_paged(
    pvName: str | None = Query(None),
    pageSize: int = Query(100, ge=1, le=1000),
    continuationToken: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Search PVs with pagination."""
    service = PVService(db)
    result = await service.search_paged(
        search=pvName,
        page_size=pageSize,
        continuation_token=continuationToken
    )
    return success_response(result)


@router.post("", response_model=dict)
async def create_pv(
    data: NewPVElementDTO,
    db: AsyncSession = Depends(get_db)
):
    """Create a new PV."""
    service = PVService(db)
    try:
        pv = await service.create(data)
        return success_response(pv)
    except ValueError as e:
        raise APIException(409, str(e), 409)


@router.post("/multi", response_model=dict)
async def create_multiple_pvs(
    data: list[NewPVElementDTO],
    db: AsyncSession = Depends(get_db)
):
    """Bulk create PVs (for CSV import)."""
    service = PVService(db)
    try:
        pvs = await service.create_many(data)
        return success_response(pvs)
    except ValueError as e:
        raise APIException(409, str(e), 409)


@router.put("/{pv_id}", response_model=dict)
async def update_pv(
    pv_id: str,
    data: UpdatePVElementDTO,
    db: AsyncSession = Depends(get_db)
):
    """Update a PV."""
    service = PVService(db)
    pv = await service.update(pv_id, data)
    if not pv:
        raise APIException(404, f"PV {pv_id} not found", 404)
    return success_response(pv)


@router.delete("/{pv_id}", response_model=dict)
async def delete_pv(
    pv_id: str,
    archive: bool = Query(False),
    db: AsyncSession = Depends(get_db)
):
    """Delete a PV."""
    service = PVService(db)
    success = await service.delete(pv_id)
    if not success:
        raise APIException(404, f"PV {pv_id} not found", 404)
    return success_response(True)


@router.get("/search", response_model=dict)
async def search_pvs_filtered(
    q: str | None = Query(None, description="Text search"),
    devices: list[str] = Query(default=[], description="Filter by device"),
    tags: list[str] = Query(default=[], description="Filter by tag IDs"),
    limit: int = Query(100, le=1000, description="Max results"),
    offset: int = Query(0, description="Offset for pagination"),
    include_live_values: bool = Query(False, description="Include Redis cache values"),
    db: AsyncSession = Depends(get_db)
):
    """
    Server-side filtered search with optional live values.

    This is more efficient than client-side filtering for large datasets.
    """
    pv_repo = PVRepository(db)
    service = PVService(db)

    pvs, total = await pv_repo.search_filtered(
        search_term=q,
        devices=devices if devices else None,
        tag_ids=tags if tags else None,
        limit=limit,
        offset=offset
    )

    # Convert to DTOs
    results = [service._to_dto(pv) for pv in pvs]

    response = {
        "results": results,
        "totalCount": total,
        "limit": limit,
        "offset": offset
    }

    # Optionally include live values from Redis
    if include_live_values:
        try:
            redis = get_redis_service()
            pv_addresses = []
            for pv in pvs:
                if pv.setpoint_address:
                    pv_addresses.append(pv.setpoint_address)
                if pv.readback_address:
                    pv_addresses.append(pv.readback_address)

            live_values = await redis.get_pv_values_bulk(pv_addresses)
            response["liveValues"] = live_values
        except Exception as e:
            response["liveValuesError"] = str(e)

    return success_response(response)


@router.get("/devices", response_model=dict)
async def get_all_devices(
    db: AsyncSession = Depends(get_db)
):
    """Get all unique device names for filtering."""
    pv_repo = PVRepository(db)
    devices = await pv_repo.get_all_devices()
    return success_response(devices)


@router.get("/live", response_model=dict)
async def get_live_values(
    pv_names: list[str] = Query(..., description="List of PV names to fetch")
):
    """Get current values from Redis cache (instant)."""
    try:
        redis = get_redis_service()
        entries = await redis.get_pv_values_bulk(pv_names)
        # Convert PVCacheEntry objects to dicts for JSON serialization
        values = {pv_name: entry.to_dict() for pv_name, entry in entries.items()}
        return success_response(values)
    except Exception as e:
        raise APIException(500, f"Failed to get live values: {e}", 500)


@router.post("/live", response_model=dict)
async def get_live_values_post(request: LivePVRequest):
    """Get current values from Redis cache (instant) - POST version for large PV lists."""
    try:
        redis = get_redis_service()
        entries = await redis.get_pv_values_bulk(request.pv_names)
        # Convert PVCacheEntry objects to dicts for JSON serialization
        values = {pv_name: entry.to_dict() for pv_name, entry in entries.items()}
        return success_response(values)
    except Exception as e:
        raise APIException(500, f"Failed to get live values: {e}", 500)


@router.get("/live/all", response_model=dict)
async def get_all_live_values():
    """Get all cached PV values (for initial table load)."""
    try:
        redis = get_redis_service()
        values = await redis.get_all_pv_values_as_dict()
        return success_response({
            "values": values,
            "count": len(values)
        })
    except Exception as e:
        raise APIException(500, f"Failed to get live values: {e}", 500)


@router.get("/cache/status", response_model=dict)
async def get_cache_status():
    """Get Redis cache status."""
    try:
        redis = get_redis_service()
        count = await redis.get_cached_pv_count()
        return success_response({
            "cachedPvCount": count,
            "status": "connected"
        })
    except Exception as e:
        return success_response({
            "cachedPvCount": 0,
            "status": "disconnected",
            "error": str(e)
        })


@router.get("/test-epics", response_model=dict)
async def test_epics_connection(
    pv: str = Query("KLYS:LI22:31:KVAC", description="PV name to test")
):
    """Test EPICS connectivity using aioca."""
    epics = get_epics_service()
    result = await epics.get_single(pv)
    return success_response({
        "pv": pv,
        "connected": result.connected,
        "value": result.value,
        "error": result.error,
        "environment": {
            "EPICS_CA_ADDR_LIST": os.environ.get("EPICS_CA_ADDR_LIST", "NOT SET"),
            "EPICS_CA_AUTO_ADDR_LIST": os.environ.get("EPICS_CA_AUTO_ADDR_LIST", "NOT SET"),
        }
    })
