import logging
from uuid import UUID

from arq import create_pool
from fastapi import Query, Security, APIRouter, HTTPException, BackgroundTasks
from arq.connections import RedisSettings

from app.config import get_settings
from app.models.job import JobType
from app.schemas.job import JobCreatedDTO
from app.dependencies import (
    DataBaseDep,
    JobServiceDep,
    SnapshotServiceDep,
    require_read_access,
    require_write_access,
)
from app.schemas.snapshot import (
    SnapshotDTO,
    NewSnapshotDTO,
    RestoreResultDTO,
    RestoreRequestDTO,
    UpdateSnapshotDTO,
    SnapshotSummaryDTO,
    ComparisonResultDTO,
)
from app.services.background_tasks import run_snapshot_restore, run_snapshot_creation
from app.services.analytics_service import log_analytics_event

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/snapshots", tags=["Snapshots"])

# Arq connection pool (reused across requests)
_arq_pool = None


async def get_arq_pool():
    """Get or create the Arq connection pool."""
    global _arq_pool
    if _arq_pool is None:
        try:
            _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            logger.info("Arq connection pool created")
        except Exception as e:
            logger.warning(f"Failed to create Arq pool: {e}")
            return None
    return _arq_pool


@router.get(
    "",
    dependencies=[Security(require_read_access)],
)
async def list_snapshots(
    service: SnapshotServiceDep,
    title: str | None = Query(None),
    tags: list[str]
    | None = Query(None, description="Filter by tag IDs (returns snapshots containing PVs with any of these tags)"),
) -> list[SnapshotSummaryDTO]:
    """List all snapshots, optionally filtered by title and/or tags."""
    return await service.list_snapshots(title=title, tag_ids=tags)


@router.get(
    "/{snapshot_id}",
    dependencies=[Security(require_read_access)],
)
async def get_snapshot(
    snapshot_id: str,
    service: SnapshotServiceDep,
    limit: int | None = Query(None, description="Limit number of PV values returned"),
    offset: int = Query(0, description="Offset for pagination"),
) -> SnapshotDTO:
    """
    Get snapshot by ID with values.

    Use limit/offset for pagination when dealing with large snapshots.
    If limit is not specified, all values are returned.
    """
    try:
        UUID(snapshot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    snapshot = await service.get_by_id(snapshot_id, limit=limit, offset=offset)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    return snapshot


@router.post(
    "",
    dependencies=[Security(require_write_access)],
)
async def create_snapshot(
    data: NewSnapshotDTO,
    background_tasks: BackgroundTasks,
    db: DataBaseDep,
    service: SnapshotServiceDep,
    job_service: JobServiceDep,
    async_mode: bool = Query(True, alias="async", description="Run snapshot creation in background"),
    use_cache: bool = Query(True, description="Read from Redis cache (instant) vs direct EPICS read"),
    use_arq: bool = Query(True, description="Use Arq persistent queue (recommended) vs FastAPI BackgroundTasks"),
) -> JobCreatedDTO | SnapshotSummaryDTO:
    """
    Create a new snapshot by reading all PVs.

    This captures the current state of all configured PVs.

    - use_cache=true (default): Read from Redis cache (instant, <5s for 40k PVs)
    - use_cache=false: Read directly from EPICS (slower, 30-60s for 40k PVs)
    - use_arq=true (default): Use Arq persistent queue (survives restarts)
    - use_arq=false: Use FastAPI BackgroundTasks (lost on restart)

    By default (async=true), this returns immediately with a JobCreatedDTO that can be
    polled for status. Set async=false for synchronous operation — the response is
    the completed SnapshotSummaryDTO (may timeout for large numbers of PVs).
    """
    if async_mode:
        # Create a job record
        job = await job_service.create_job(
            JobType.SNAPSHOT_CREATE,
            job_data={"title": data.title, "description": data.description, "use_cache": use_cache},
        )

        # CRITICAL: Commit the job to database before returning
        # Otherwise the job won't be visible when frontend immediately polls for it
        await db.commit()

        # Try to use Arq for persistent job queue
        if use_arq:
            pool = await get_arq_pool()
            if pool:
                try:
                    await pool.enqueue_job(
                        "create_snapshot_task",
                        job_id=str(job.id),
                        title=data.title,
                        description=data.description,
                        use_cache=use_cache,
                    )
                    logger.info(f"Enqueued snapshot job to Arq: {job.id}")
                    log_analytics_event(
                        "snapshot_create_requested",
                        source="backend",
                        properties={
                            "job_id": str(job.id),
                            "async_mode": True,
                            "use_cache": use_cache,
                            "queue": "arq",
                        },
                    )
                    return JobCreatedDTO(
                        jobId=job.id,
                        message=f"Snapshot creation queued for '{data.title}'"
                        + (" (from cache)" if use_cache else " (direct EPICS)"),
                    )
                except Exception as e:
                    logger.warning(f"Failed to enqueue to Arq, falling back to BackgroundTasks: {e}")

        # Fallback to FastAPI BackgroundTasks
        background_tasks.add_task(run_snapshot_creation, job.id, data.title, data.description, use_cache)
        logger.info(f"Scheduled snapshot job via BackgroundTasks: {job.id}")
        log_analytics_event(
            "snapshot_create_requested",
            source="backend",
            properties={
                "job_id": str(job.id),
                "async_mode": True,
                "use_cache": use_cache,
                "queue": "background_tasks",
            },
        )

        return JobCreatedDTO(
            jobId=job.id,
            message=f"Snapshot creation started for '{data.title}'"
            + (" (from cache)" if use_cache else " (direct EPICS)"),
        )
    else:
        # Synchronous mode (legacy behavior)
        if use_cache:
            snapshot = await service.create_snapshot_from_cache(data)
        else:
            snapshot = await service.create_snapshot(data)

        log_analytics_event(
            "snapshot_create_completed",
            source="backend",
            properties={
                "async_mode": False,
                "use_cache": use_cache,
                "snapshot_id": str(snapshot.id),
                "pv_count": snapshot.pvCount,
            },
        )
        return snapshot


@router.put(
    "/{snapshot_id}",
    dependencies=[Security(require_write_access)],
)
async def update_snapshot(
    snapshot_id: str,
    data: UpdateSnapshotDTO,
    service: SnapshotServiceDep,
) -> SnapshotSummaryDTO:
    """Update snapshot title and/or description."""
    snapshot = await service.update_snapshot_metadata(
        snapshot_id,
        title=data.title,
        description=data.description,
    )

    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    return snapshot


@router.post(
    "/{snapshot_id}/restore",
    dependencies=[Security(require_write_access)],
)
async def restore_snapshot(
    snapshot_id: str,
    background_tasks: BackgroundTasks,
    db: DataBaseDep,
    service: SnapshotServiceDep,
    job_service: JobServiceDep,
    request: RestoreRequestDTO | None = None,
    async_mode: bool = Query(True, alias="async"),
    use_arq: bool = Query(True, description="Use Arq persistent queue (recommended) vs FastAPI BackgroundTasks"),
) -> JobCreatedDTO | RestoreResultDTO:
    """
    Restore PV values from a snapshot to EPICS.

    Optionally specify pvIds to restore only specific PVs.
    """
    try:
        UUID(snapshot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    # Verify snapshot exists
    snapshot = await service.get_by_id(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    if async_mode:
        job = await job_service.create_job(
            JobType.SNAPSHOT_RESTORE,
            job_data={"snapshotId": snapshot_id},
        )

        await db.commit()
        pv_ids = request.pvIds if request else None

        if use_arq:
            pool = await get_arq_pool()
            if pool:
                try:
                    await pool.enqueue_job(
                        "restore_snapshot_task",
                        job_id=str(job.id),
                        snapshot_id=snapshot_id,
                        pv_ids=pv_ids,
                    )
                    logger.info(f"Enqueued restore job to Arq: {job.id}")
                    log_analytics_event(
                        "snapshot_restore_requested",
                        source="backend",
                        properties={
                            "job_id": str(job.id),
                            "snapshot_id": snapshot_id,
                            "async_mode": True,
                            "pv_count": len(pv_ids) if pv_ids else None,
                            "queue": "arq",
                        },
                    )
                    return JobCreatedDTO(
                        jobId=job.id,
                        message=f"Snapshot restore queued ({snapshot_id})",
                    )
                except Exception as e:
                    logger.warning(f"Failed to enqueue to Arq, falling back to BackgroundTasks: {e}")

        # Fallback to FastAPI BackgroundTasks
        background_tasks.add_task(run_snapshot_restore, str(job.id), snapshot_id, pv_ids)
        logger.info(f"Scheduled restore job via BackgroundTasks: {job.id}")
        log_analytics_event(
            "snapshot_restore_requested",
            source="backend",
            properties={
                "job_id": str(job.id),
                "snapshot_id": snapshot_id,
                "async_mode": True,
                "pv_count": len(pv_ids) if pv_ids else None,
                "queue": "background_tasks",
            },
        )
        return JobCreatedDTO(
            jobId=job.id,
            message=f"Snapshot restore started ({snapshot_id})",
        )

    result = await service.restore_snapshot(snapshot_id, request)
    log_analytics_event(
        "snapshot_restore_completed",
        source="backend",
        properties={
            "async_mode": False,
            "snapshot_id": snapshot_id,
            "success_count": result.successCount,
            "failure_count": result.failureCount,
            "total_pvs": result.totalPVs,
        },
    )
    return result


@router.delete(
    "/{snapshot_id}",
    dependencies=[Security(require_write_access)],
)
async def delete_snapshot(
    snapshot_id: str,
    service: SnapshotServiceDep,
    deleteData: bool = Query(True),
) -> bool:
    """Delete a snapshot."""
    try:
        UUID(snapshot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    success = await service.delete_snapshot(snapshot_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    log_analytics_event(
        "snapshot_deleted",
        source="backend",
        properties={
            "snapshot_id": snapshot_id,
            "delete_data": deleteData,
        },
    )
    return True


@router.get(
    "/{snapshot1_id}/compare/{snapshot2_id}",
    dependencies=[Security(require_read_access)],
)
async def compare_snapshots(
    snapshot1_id: str,
    snapshot2_id: str,
    service: SnapshotServiceDep,
) -> ComparisonResultDTO:
    """Compare two snapshots and return differences."""
    try:
        UUID(snapshot1_id)
        UUID(snapshot2_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    try:
        return await service.compare_snapshots(snapshot1_id, snapshot2_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
