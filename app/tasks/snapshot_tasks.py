"""
Arq task definitions for snapshot operations.

These tasks run in the Arq worker process for:
- Job persistence across restarts
- Automatic retries with backoff
- Separate worker scaling
"""
import logging

from arq import Retry

from app.db.session import async_session_maker
from app.schemas.snapshot import NewSnapshotDTO
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service
from app.services.snapshot_service import SnapshotService
from app.services.analytics_service import log_analytics_event
from app.repositories.job_repository import JobRepository

logger = logging.getLogger(__name__)


async def create_snapshot_task(
    ctx: dict, job_id: str, title: str, description: str | None = None, use_cache: bool = True
) -> str:
    """
    Create a snapshot - runs in Arq worker process.

    This is a persistent task that survives worker restarts.

    Args:
        ctx: Arq context (contains epics, redis services from worker startup)
        job_id: Job ID for progress tracking
        title: Snapshot title
        description: Optional snapshot description
        use_cache: Whether to read from Redis cache or direct EPICS

    Returns:
        snapshot_id on success

    Raises:
        Retry: On transient errors (will be retried)
        Exception: On permanent errors (job marked as failed)
    """
    logger.info(f"Starting snapshot creation task: job_id={job_id}, title='{title}'")

    async with async_session_maker() as session:
        job_repo = JobRepository(session)

        try:
            # Mark job as running
            await job_repo.mark_running(job_id)
            await session.commit()

            # Create progress callback for job updates
            async def on_progress(current: int, total: int, message: str) -> None:
                progress = int((current / total) * 100) if total > 0 else 0
                await job_repo.update_progress(job_id, progress, message)
                await session.commit()
                logger.debug(f"Job {job_id} progress: {progress}% - {message}")

            # Initialize services
            epics = ctx.get("epics") or get_epics_service()
            redis = ctx.get("redis") or get_redis_service()

            # Create snapshot service
            snapshot_service = SnapshotService(session, epics, redis)

            # Create the snapshot
            data = NewSnapshotDTO(title=title, description=description)

            if use_cache:
                result = await snapshot_service.create_snapshot_from_cache(data, progress_callback=on_progress)
            else:
                result = await snapshot_service.create_snapshot(data, progress_callback=on_progress)

            # Mark job as completed
            await job_repo.mark_completed(job_id, result_id=result.id)
            await session.commit()

            logger.info(f"Snapshot created successfully: job_id={job_id}, snapshot_id={result.id}")
            log_analytics_event(
                "snapshot_create_completed",
                source="backend",
                properties={
                    "job_id": job_id,
                    "snapshot_id": str(result.id),
                    "use_cache": use_cache,
                },
            )
            return result.id

        except Exception as e:
            logger.error(f"Snapshot creation failed: job_id={job_id}, error={e}")
            log_analytics_event(
                "snapshot_create_failed",
                source="backend",
                properties={
                    "job_id": job_id,
                    "use_cache": use_cache,
                    "error": str(e),
                },
            )

            # Mark job as failed
            try:
                await job_repo.mark_failed(job_id, str(e))
                await session.commit()
            except Exception as commit_error:
                logger.error(f"Failed to mark job as failed: {commit_error}")

            # Retry on transient errors (connection issues)
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["connection", "timeout", "redis", "database"]):
                logger.info(f"Retrying snapshot creation due to transient error: {e}")
                raise Retry(defer=10)  # Retry in 10 seconds

            # Re-raise for permanent errors
            raise


async def restore_snapshot_task(ctx: dict, job_id: str, snapshot_id: str, pv_ids: list[str] | None = None) -> dict:
    """
    Restore a snapshot to EPICS - runs in Arq worker process.

    Args:
        ctx: Arq context (contains epics, redis services from worker startup)
        job_id: Job ID for progress tracking
        snapshot_id: ID of snapshot to restore
        pv_ids: Optional list of specific PV IDs to restore

    Returns:
        dict with restore results (success_count, failure_count, etc.)

    Raises:
        Retry: On transient errors (will be retried)
        Exception: On permanent errors (job marked as failed)
    """
    logger.info(f"Starting snapshot restore task: job_id={job_id}, snapshot_id={snapshot_id}")

    async with async_session_maker() as session:
        job_repo = JobRepository(session)

        try:
            # Mark job as running
            await job_repo.mark_running(job_id)
            await session.commit()

            # Create progress callback for job updates
            async def on_progress(current: int, total: int, message: str) -> None:
                progress = int((current / total) * 100) if total > 0 else 0
                await job_repo.update_progress(job_id, progress, message)
                await session.commit()
                logger.debug(f"Restore job {job_id} progress: {progress}% - {message}")

            # Initialize services
            epics = ctx.get("epics") or get_epics_service()

            # Create snapshot service
            snapshot_service = SnapshotService(session, epics)

            # Build restore request
            from app.schemas.snapshot import RestoreRequestDTO

            request = RestoreRequestDTO(pvIds=pv_ids) if pv_ids else None

            # Restore the snapshot
            result = await snapshot_service.restore_snapshot(
                snapshot_id,
                request,
                progress_callback=on_progress,
            )

            # Mark job as completed
            result_data = {
                "total_pvs": result.totalPVs,
                "success_count": result.successCount,
                "failure_count": result.failureCount,
                "failures": [
                    {"pvId": f["pvId"], "pvName": f["pvName"], "error": f["error"]} for f in result.failures[:50]
                ],
            }
            if result.failureCount > 0:
                completion_message = (
                    f"Restored {result.successCount:,}/{result.totalPVs:,} PVs " f"({result.failureCount} failed)"
                )
            else:
                completion_message = f"All {result.totalPVs:,} PVs have been restored to their snapshot values."
            await job_repo.mark_completed(
                job_id,
                result_id=snapshot_id,
                message=completion_message,
                result_data=result_data,
            )
            await session.commit()

            logger.info(
                f"Snapshot restored successfully: job_id={job_id}, "
                f"success={result.successCount}, failures={result.failureCount}"
            )
            log_analytics_event(
                "snapshot_restore_completed",
                source="backend",
                properties={
                    "job_id": job_id,
                    "snapshot_id": snapshot_id,
                    "success_count": result.successCount,
                    "failure_count": result.failureCount,
                    "total_pvs": result.totalPVs,
                },
            )
            return result_data

        except Exception as e:
            logger.error(f"Snapshot restore failed: job_id={job_id}, error={e}")
            log_analytics_event(
                "snapshot_restore_failed",
                source="backend",
                properties={
                    "job_id": job_id,
                    "snapshot_id": snapshot_id,
                    "error": str(e),
                },
            )

            # Mark job as failed
            try:
                await job_repo.mark_failed(job_id, str(e))
                await session.commit()
            except Exception as commit_error:
                logger.error(f"Failed to mark job as failed: {commit_error}")

            # Retry on transient errors
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["connection", "timeout"]):
                logger.info(f"Retrying snapshot restore due to transient error: {e}")
                raise Retry(defer=10)

            raise
