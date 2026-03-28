import logging
from uuid import UUID

from arq import create_pool
from fastapi import Query, Depends, Security, APIRouter, BackgroundTasks
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.models.job import JobType
from app.schemas.job import JobCreatedDTO
from app.dependencies import require_read_access, require_write_access
from app.api.responses import APIException, error_response, success_response
from app.schemas.snapshot import NewSnapshotDTO, RestoreRequestDTO, UpdateSnapshotDTO
from app.services.job_service import JobService
from app.services.epics_service import EpicsService, get_epics_service
from app.services.redis_service import get_redis_service
from app.services.background_tasks import run_snapshot_creation
from app.services.snapshot_service import SnapshotService

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


@router.get("", dependencies=[Security(require_read_access)])
async def list_snapshots(
    title: str | None = Query(None),
    tags: list[str]
    | None = Query(None, description="Filter by tag IDs (returns snapshots containing PVs with any of these tags)"),
    db: AsyncSession = Depends(get_db),
    epics: EpicsService = Depends(get_epics_service),
) -> dict:
    """List all snapshots, optionally filtered by title and/or tags."""
    service = SnapshotService(db, epics)
    snapshots = await service.list_snapshots(title=title, tag_ids=tags)
    return success_response(snapshots)


@router.get("/{snapshot_id}", dependencies=[Security(require_read_access)])
async def get_snapshot(
    snapshot_id: str,
    limit: int | None = Query(None, description="Limit number of PV values returned"),
    offset: int = Query(0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db),
    epics: EpicsService = Depends(get_epics_service),
) -> dict:
    """
    Get snapshot by ID with values.

    Use limit/offset for pagination when dealing with large snapshots.
    If limit is not specified, all values are returned.
    """
    try:
        UUID(snapshot_id)
    except ValueError:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)
    service = SnapshotService(db, epics)
    snapshot = await service.get_by_id(snapshot_id, limit=limit, offset=offset)
    if not snapshot:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)
    return success_response(snapshot)


@router.post("", dependencies=[Security(require_write_access)])
async def create_snapshot(
    data: NewSnapshotDTO,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    async_mode: bool = Query(True, alias="async", description="Run snapshot creation in background"),
    use_cache: bool = Query(True, description="Read from Redis cache (instant) vs direct EPICS read"),
    use_arq: bool = Query(True, description="Use Arq persistent queue (recommended) vs FastAPI BackgroundTasks"),
    epics: EpicsService = Depends(get_epics_service),
) -> dict:
    """
    Create a new snapshot by reading all PVs.

    This captures the current state of all configured PVs.

    - use_cache=true (default): Read from Redis cache (instant, <5s for 40k PVs)
    - use_cache=false: Read directly from EPICS (slower, 30-60s for 40k PVs)
    - use_arq=true (default): Use Arq persistent queue (survives restarts)
    - use_arq=false: Use FastAPI BackgroundTasks (lost on restart)

    By default (async=true), this returns immediately with a job ID that can be
    polled for status. Set async=false for synchronous operation (may timeout
    for large numbers of PVs).
    """
    if async_mode:
        # Create a job record
        job_service = JobService(db)
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
                    return success_response(
                        JobCreatedDTO(
                            jobId=job.id,
                            message=f"Snapshot creation queued for '{data.title}'"
                            + (" (from cache)" if use_cache else " (direct EPICS)"),
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to enqueue to Arq, falling back to BackgroundTasks: {e}")

        # Fallback to FastAPI BackgroundTasks
        background_tasks.add_task(run_snapshot_creation, job.id, data.title, data.description, use_cache)
        logger.info(f"Scheduled snapshot job via BackgroundTasks: {job.id}")

        return success_response(
            JobCreatedDTO(
                jobId=job.id,
                message=f"Snapshot creation started for '{data.title}'"
                + (" (from cache)" if use_cache else " (direct EPICS)"),
            )
        )
    else:
        # Synchronous mode (legacy behavior)
        redis = get_redis_service()
        service = SnapshotService(db, epics, redis)

        if use_cache:
            snapshot = await service.create_snapshot_from_cache(data)
        else:
            snapshot = await service.create_snapshot(data)

        return success_response(snapshot)


@router.put("/{snapshot_id}", dependencies=[Security(require_write_access)])
async def update_snapshot(
    snapshot_id: str,
    data: UpdateSnapshotDTO,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update snapshot title and/or description."""
    epics = get_epics_service()
    service = SnapshotService(db, epics)

    snapshot = await service.update_snapshot_metadata(
        snapshot_id,
        title=data.title,
        description=data.description,
    )

    if not snapshot:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)

    return success_response(snapshot)


@router.post("/{snapshot_id}/restore", dependencies=[Security(require_write_access)])
async def restore_snapshot(
    snapshot_id: str,
    request: RestoreRequestDTO | None = None,
    db: AsyncSession = Depends(get_db),
    async_mode: bool = Query(True, alias="async"),
    epics: EpicsService = Depends(get_epics_service),
) -> dict:
    """
    Restore PV values from a snapshot to EPICS.

    Optionally specify pvIds to restore only specific PVs.
    """
    try:
        UUID(snapshot_id)
    except ValueError:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)
    service = SnapshotService(db, epics)

    # Verify snapshot exists
    snapshot = await service.get_by_id(snapshot_id)
    if not snapshot:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)

    if async_mode:
        job_service = JobService(db)
        job = await job_service.create_job(
            JobType.SNAPSHOT_RESTORE,
            job_data={"snapshotId": snapshot_id},
        )

        await db.commit()
        pool = await get_arq_pool()
        if pool:
            try:
                await pool.enqueue_job(
                    "restore_snapshot_task",
                    job_id=str(job.id),
                    snapshot_id=snapshot_id,
                    pv_ids=request.pvIds if request else None,
                )
                logger.info(f"Enqueued restore job to Arq: {job.id}")

                return success_response(
                    JobCreatedDTO(
                        jobId=job.id,
                        message=f"Snapshot restore queued ({snapshot_id})",
                    )
                )
            except Exception as e:
                return error_response(500, f"Failed to enqueue to Arq: {e}")

    result = await service.restore_snapshot(snapshot_id, request)
    return success_response(result)


@router.delete("/{snapshot_id}", dependencies=[Security(require_write_access)])
async def delete_snapshot(
    snapshot_id: str,
    deleteData: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    epics: EpicsService = Depends(get_epics_service),
) -> dict:
    """Delete a snapshot."""
    try:
        UUID(snapshot_id)
    except ValueError:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)
    service = SnapshotService(db, epics)
    success = await service.delete_snapshot(snapshot_id)
    if not success:
        raise APIException(404, f"Snapshot {snapshot_id} not found", 404)
    return success_response(True)


@router.get("/{snapshot1_id}/compare/{snapshot2_id}", dependencies=[Security(require_read_access)])
async def compare_snapshots(
    snapshot1_id: str,
    snapshot2_id: str,
    db: AsyncSession = Depends(get_db),
    epics: EpicsService = Depends(get_epics_service),
) -> dict:
    """Compare two snapshots and return differences."""
    try:
        UUID(snapshot1_id)
        UUID(snapshot2_id)
    except ValueError:
        raise APIException(404, "Snapshot not found", 404)
    service = SnapshotService(db, epics)
    try:
        result = await service.compare_snapshots(snapshot1_id, snapshot2_id)
        return success_response(result)
    except ValueError as e:
        raise APIException(404, str(e), 404)
