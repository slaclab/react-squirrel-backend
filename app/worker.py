"""
Arq worker configuration for background task processing.

Run with: arq app.worker.WorkerSettings

This worker handles long-running tasks like:
- Snapshot creation (reading 40k+ PVs)
- Snapshot restoration (writing to EPICS)
- Bulk operations

Benefits over asyncio.create_task():
- Job persistence across restarts
- Automatic retries with backoff
- Job timeout handling
- Separate worker scaling
- Dead letter queue for failed jobs
"""
import logging

from arq.connections import RedisSettings

from app.tasks import create_snapshot_task, restore_snapshot_task
from app.config import get_settings
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


async def startup(ctx: dict) -> None:
    """
    Worker startup - initialize services.

    Called once when the worker process starts.
    """
    logger.info("Arq worker starting up...")

    # Initialize EPICS service
    from app.services.epics_service import get_epics_service

    ctx["epics"] = get_epics_service()
    logger.info("EPICS service initialized")

    # Initialize Redis service
    from app.services.redis_service import get_redis_service

    ctx["redis"] = get_redis_service()
    await ctx["redis"].connect()
    logger.info("Redis service connected")

    logger.info("Arq worker startup complete")


async def shutdown(ctx: dict) -> None:
    """
    Worker shutdown - cleanup resources.

    Called when the worker process is stopping.
    """
    logger.info("Arq worker shutting down...")

    # Disconnect Redis
    if "redis" in ctx:
        await ctx["redis"].disconnect()
        logger.info("Redis service disconnected")

    # Shutdown EPICS
    if "epics" in ctx:
        await ctx["epics"].shutdown()
        logger.info("EPICS service shut down")

    logger.info("Arq worker shutdown complete")


async def on_job_start(ctx: dict) -> None:
    """Called at the start of each job."""
    job_id = ctx.get("job_id", "unknown")
    logger.info(f"Starting job: {job_id}")


async def on_job_end(ctx: dict) -> None:
    """Called at the end of each job (success or failure)."""
    job_id = ctx.get("job_id", "unknown")
    logger.info(f"Finished job: {job_id}")


class WorkerSettings:
    """
    Arq worker settings.

    Configuration for the background task worker.
    """

    # Task functions to register
    functions = [
        create_snapshot_task,
        restore_snapshot_task,
    ]

    # Lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown
    on_job_start = on_job_start
    on_job_end = on_job_end

    # Redis connection
    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    # Worker configuration
    max_jobs = 10  # Max concurrent jobs per worker
    job_timeout = 600  # 10 minutes max per job
    retry_jobs = True  # Enable automatic retries
    max_tries = 3  # Max retry attempts

    # Queue settings
    queue_name = "arq:queue"  # Default queue name
    health_check_interval = 10  # Health check frequency

    # Logging
    log_results = True
