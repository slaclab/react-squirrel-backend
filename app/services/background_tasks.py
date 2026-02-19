"""Background task runner for async operations."""
import asyncio
import logging
from datetime import datetime

from app.db.session import async_session_maker
from app.schemas.snapshot import NewSnapshotDTO
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service
from app.services.snapshot_service import SnapshotService
from app.repositories.job_repository import JobRepository

logger = logging.getLogger(__name__)


async def run_snapshot_creation(
    job_id: str, title: str, description: str | None = None, use_cache: bool = True
) -> None:
    """
    Background task to create a snapshot.

    This runs in a separate asyncio task and uses its own database session.
    """
    logger.info(f"Background task started for job {job_id}: Creating snapshot '{title}' (use_cache={use_cache})")

    async with async_session_maker() as session:
        try:
            job_repo = JobRepository(session)

            # Mark job as running
            await job_repo.mark_running(job_id)
            await session.commit()
            await asyncio.sleep(0)  # Yield to event loop

            # Update progress: Starting EPICS read
            await job_repo.update_progress(job_id, 5, "Reading PV addresses from database...")
            await session.commit()
            await asyncio.sleep(0)  # Yield to event loop

            # Create the snapshot
            epics = get_epics_service()
            redis = get_redis_service()
            snapshot_service = SnapshotService(session, epics, redis)

            # Get all PV addresses with timeout to prevent indefinite blocking
            try:
                pv_addresses = await asyncio.wait_for(
                    snapshot_service.pv_repo.get_all_addresses(), timeout=30.0  # 30 second timeout for DB query
                )
            except TimeoutError:
                raise Exception("Timeout reading PV addresses from database (30s)")

            await job_repo.update_progress(job_id, 15, f"Found {len(pv_addresses)} PVs, reading from EPICS...")
            await session.commit()
            await asyncio.sleep(0)  # Yield to event loop

            # Create progress callback (with throttling to avoid too many DB commits)
            last_update = {"progress": 15, "last_time": datetime.now()}

            async def progress_update(current: int, total: int, message: str):
                try:
                    # Map EPICS progress to job progress
                    # Progress ranges: 15-20% (setup), 20-80% (EPICS read), 80-90% (processing), 90-100% (saving)
                    if "Saving" in message:
                        job_progress = 90
                    elif "Processing" in message or (current >= total and total > 0):
                        job_progress = 85
                    else:
                        # EPICS reading: 20-80% (60% range)
                        epics_progress = int((current / total) * 60) if total > 0 else 0
                        job_progress = 20 + epics_progress

                    # Update if progress changed by at least 2% OR 2 seconds elapsed (for responsiveness)
                    # This ensures the frontend sees regular updates even during slow chunks
                    now = datetime.now()
                    time_elapsed = (now - last_update["last_time"]).total_seconds()
                    progress_changed = job_progress - last_update["progress"] >= 2

                    if progress_changed or time_elapsed >= 2.0 or current >= total:
                        last_update["progress"] = job_progress
                        last_update["last_time"] = now
                        await job_repo.update_progress(job_id, job_progress, message)
                        await session.commit()
                        await asyncio.sleep(0)  # Yield to event loop
                except Exception as e:
                    logger.error(f"Error in progress_update: {e}")

            # Call create_snapshot with progress callback
            data = NewSnapshotDTO(title=title, description=description)
            if use_cache:
                result = await snapshot_service.create_snapshot_from_cache(data, progress_callback=progress_update)
            else:
                result = await snapshot_service.create_snapshot(data, progress_callback=progress_update)

            # Mark as completed with the snapshot ID as result
            await job_repo.mark_completed(
                job_id, result_id=result.id, message=f"Snapshot created with {result.pvCount} PV values"
            )
            await session.commit()

            logger.info(f"Background task completed for job {job_id}: Snapshot {result.id} created")

        except Exception as e:
            logger.exception(f"Background task failed for job {job_id}: {e}")
            error_msg = f"{type(e).__name__}: {str(e)}"
            try:
                await session.rollback()
                await job_repo.mark_failed(job_id, error_msg)
                await session.commit()
            except Exception as inner_e:
                logger.exception(f"Failed to update job status: {inner_e}")


def schedule_snapshot_creation(job_id: str, title: str, description: str | None = None, use_cache: bool = True) -> None:
    """
    Schedule a snapshot creation task to run in the background.

    This creates a new asyncio task that will run independently.
    """
    asyncio.create_task(run_snapshot_creation(job_id, title, description, use_cache))
