import os
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.pv_service import PVService
from app.services.epics_service import get_epics_service
from app.services.epics_worker import get_epics_process_pool
from app.schemas.pv import NewPVElementDTO, UpdatePVElementDTO, PVElementDTO
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


@router.get("/test-epics", response_model=dict)
async def test_epics_connection(
    pv: str = Query("KLYS:LI22:31:KVAC", description="PV name to test")
):
    """
    Test EPICS connectivity from the backend.

    Tests both:
    1. Main process EPICS connection (ThreadPoolExecutor)
    2. Worker process EPICS connection (ProcessPoolExecutor)
    """
    results = {
        "pv_name": pv,
        "environment": {
            "EPICS_CA_ADDR_LIST": os.environ.get("EPICS_CA_ADDR_LIST", "NOT SET"),
            "EPICS_CA_AUTO_ADDR_LIST": os.environ.get("EPICS_CA_AUTO_ADDR_LIST", "NOT SET"),
        },
        "main_process": None,
        "worker_process": None,
    }

    # Test 1: Main process (uses ThreadPoolExecutor)
    try:
        epics_service = get_epics_service()
        main_result = await epics_service.get_single(pv)
        results["main_process"] = {
            "success": main_result.connected,
            "value": main_result.value,
            "error": main_result.error,
        }
    except Exception as e:
        results["main_process"] = {
            "success": False,
            "value": None,
            "error": str(e),
        }

    # Test 2: Worker process (uses ProcessPoolExecutor with spawn)
    try:
        import asyncio
        process_pool = get_epics_process_pool()
        loop = asyncio.get_event_loop()

        # Run in thread pool to not block
        worker_results = await loop.run_in_executor(
            None,
            lambda: process_pool.read_pvs_sync([pv], batch_size=1)
        )

        worker_result = worker_results.get(pv, {})
        results["worker_process"] = {
            "success": worker_result.get("connected", False),
            "value": worker_result.get("value"),
            "error": worker_result.get("error"),
        }
    except Exception as e:
        results["worker_process"] = {
            "success": False,
            "value": None,
            "error": str(e),
        }

    return success_response(results)


@router.get("/test-epics-backends", response_model=dict)
async def test_epics_backends(
    count: int = Query(100, description="Number of PVs to test", ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """
    Compare performance of different EPICS backends (pyepics vs p4p).

    Reads `count` PVs from the database and tests each backend.
    Returns timing and success rate for each.
    """
    import time
    import asyncio
    from app.services.pv_service import PVService
    from app.services.epics_service import P4P_AVAILABLE

    # Get PV names from database
    service = PVService(db)
    pv_result = await service.search_paged(page_size=count)
    # Use setpointAddress as the PV name
    pv_names = [pv.setpointAddress for pv in pv_result.results if pv.setpointAddress]

    if not pv_names:
        raise APIException(400, "No PVs found in database", 400)

    results = {
        "pv_count": len(pv_names),
        "p4p_available": P4P_AVAILABLE,
        "backends": {}
    }

    epics_service = get_epics_service()
    loop = asyncio.get_event_loop()

    # Test pyepics (threading mode)
    start = time.time()
    pyepics_results = await loop.run_in_executor(
        epics_service._executor,
        lambda: epics_service._read_batch_threaded(pv_names)
    )
    pyepics_time = time.time() - start
    pyepics_connected = sum(1 for r in pyepics_results.values() if r.get("connected"))

    results["backends"]["pyepics"] = {
        "time_seconds": round(pyepics_time, 2),
        "connected": pyepics_connected,
        "success_rate": round(pyepics_connected / len(pv_names) * 100, 1),
        "pvs_per_second": round(len(pv_names) / pyepics_time, 1) if pyepics_time > 0 else 0
    }

    # Test p4p if available
    if P4P_AVAILABLE:
        start = time.time()
        p4p_results = await loop.run_in_executor(
            epics_service._executor,
            lambda: epics_service._read_batch_p4p(pv_names)
        )
        p4p_time = time.time() - start
        p4p_connected = sum(1 for r in p4p_results.values() if r.get("connected"))

        results["backends"]["p4p"] = {
            "time_seconds": round(p4p_time, 2),
            "connected": p4p_connected,
            "success_rate": round(p4p_connected / len(pv_names) * 100, 1),
            "pvs_per_second": round(len(pv_names) / p4p_time, 1) if p4p_time > 0 else 0
        }

        # Add comparison
        if pyepics_time > 0 and p4p_time > 0:
            speedup = pyepics_time / p4p_time
            results["comparison"] = {
                "p4p_speedup": round(speedup, 2),
                "faster_backend": "p4p" if speedup > 1 else "pyepics",
                "recommendation": "p4p" if speedup > 1.1 and p4p_connected >= pyepics_connected else "pyepics"
            }
    else:
        results["backends"]["p4p"] = {
            "error": "p4p not installed"
        }

    return success_response(results)
