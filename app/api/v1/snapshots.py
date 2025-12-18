from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.snapshot_service import SnapshotService
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service
from app.services.job_service import JobService
from app.services.background_tasks import run_snapshot_creation
from app.models.job import JobType
from app.schemas.snapshot import (
    NewSnapshotDTO, SnapshotDTO, SnapshotSummaryDTO,
    RestoreRequestDTO, RestoreResultDTO, ComparisonResultDTO
)
from app.schemas.job import JobCreatedDTO
from app.api.responses import success_response, APIException

router = APIRouter(prefix="/snapshots", tags=["Snapshots"])


@router.get("", response_model=dict)
async def list_snapshots(
    title: str | None = Query(None),
    tags: list[str] | None = Query(None, description="Filter by tag IDs (returns snapshots containing PVs with any of these tags)"),
    db: AsyncSession = Depends(get_db)
):
    """List all snapshots, optionally filtered by title and/or tags."""
    epics = get_epics_service()
    service = SnapshotService(db, epics)
    snapshots = await service.list_snapshots(title=title, tag_ids=tags)
    return success_response(snapshots)


@router.get("/{snapshot_id}", response_model=dict)
async def get_snapshot(
    snapshot_id: str,
    limit: int | None = Query(None, description="Limit number of PV values returned"),
    offset: int = Query(0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get snapshot by ID with values.

    Use limit/offset for pagination when dealing with large snapshots.
    If limit is not specified, all values are returned.
    """
    epics = get_epics_service()
    service = SnapshotService(db, epics)
    snapshot = await service.get_by_id(snapshot_id, limit=limit, offset=offset)
    if not snapshot:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)
    return success_response(snapshot)


@router.post("", response_model=dict)
async def create_snapshot(
    data: NewSnapshotDTO,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    async_mode: bool = Query(True, alias="async", description="Run snapshot creation in background"),
    use_cache: bool = Query(True, description="Read from Redis cache (instant) vs direct EPICS read")
):
    """
    Create a new snapshot by reading all PVs.

    This captures the current state of all configured PVs.

    - use_cache=true (default): Read from Redis cache (instant, <5s for 40k PVs)
    - use_cache=false: Read directly from EPICS (slower, 30-60s for 40k PVs)

    By default (async=true), this returns immediately with a job ID that can be
    polled for status. Set async=false for synchronous operation (may timeout
    for large numbers of PVs).
    """
    if async_mode:
        # Create a job and schedule background task
        job_service = JobService(db)
        job = await job_service.create_job(
            JobType.SNAPSHOT_CREATE,
            job_data={"title": data.title, "comment": data.comment, "use_cache": use_cache}
        )

        # CRITICAL: Commit the job to database before returning
        # Otherwise the job won't be visible when frontend immediately polls for it
        await db.commit()

        # Schedule the background task using FastAPI's BackgroundTasks
        background_tasks.add_task(run_snapshot_creation, job.id, data.title, data.comment, use_cache)

        return success_response(JobCreatedDTO(
            jobId=job.id,
            message=f"Snapshot creation started for '{data.title}'" + (" (from cache)" if use_cache else " (direct EPICS)")
        ))
    else:
        # Synchronous mode (legacy behavior)
        epics = get_epics_service()
        redis = get_redis_service()
        service = SnapshotService(db, epics, redis)

        if use_cache:
            snapshot = await service.create_snapshot_from_cache(data)
        else:
            snapshot = await service.create_snapshot(data)

        return success_response(snapshot)


@router.post("/{snapshot_id}/restore", response_model=dict)
async def restore_snapshot(
    snapshot_id: str,
    request: RestoreRequestDTO | None = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Restore PV values from a snapshot to EPICS.

    Optionally specify pvIds to restore only specific PVs.
    """
    epics = get_epics_service()
    service = SnapshotService(db, epics)

    # Verify snapshot exists
    snapshot = await service.get_by_id(snapshot_id)
    if not snapshot:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)

    result = await service.restore_snapshot(snapshot_id, request)
    return success_response(result)


@router.delete("/{snapshot_id}", response_model=dict)
async def delete_snapshot(
    snapshot_id: str,
    deleteData: bool = Query(True),
    db: AsyncSession = Depends(get_db)
):
    """Delete a snapshot."""
    epics = get_epics_service()
    service = SnapshotService(db, epics)
    success = await service.delete_snapshot(snapshot_id)
    if not success:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)
    return success_response(True)


@router.get("/{snapshot1_id}/compare/{snapshot2_id}", response_model=dict)
async def compare_snapshots(
    snapshot1_id: str,
    snapshot2_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Compare two snapshots and return differences."""
    epics = get_epics_service()
    service = SnapshotService(db, epics)
    try:
        result = await service.compare_snapshots(snapshot1_id, snapshot2_id)
        return success_response(result)
    except ValueError as e:
        raise APIException(404, str(e), 404)
