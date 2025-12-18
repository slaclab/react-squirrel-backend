"""
Squirrel Backend - High-performance EPICS snapshot/restore backend

Enhanced for 40k PV reliability with:
- Batched PV monitor startup (prevents UDP flood)
- System heartbeat monitoring
- Watchdog process for health checks
- Diff-based WebSocket streaming
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api.v1.router import router as v1_router
from app.api.responses import APIException
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service
from app.services.pv_monitor import get_pv_monitor
from app.services.watchdog import get_watchdog
from app.api.v1.websocket import get_diff_manager
from app.db.session import async_session_maker

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Startup sequence:
    1. Initialize EPICS service
    2. Connect to Redis
    3. Load PV addresses from database
    4. Start PV Monitor (with batched startup to prevent UDP flood)
    5. Start Watchdog (health monitoring)
    6. Start WebSocket diff stream manager

    Shutdown sequence:
    1. Stop Watchdog
    2. Stop WebSocket manager
    3. Stop PV Monitor
    4. Disconnect Redis
    5. Shutdown EPICS service
    """
    logger.info("Starting Squirrel backend...")

    # Initialize EPICS service
    epics = get_epics_service()
    logger.info("EPICS service initialized (using aioca)")

    # Initialize Redis service
    redis_service = get_redis_service()
    redis_connected = False

    try:
        await redis_service.connect()
        redis_connected = True
        logger.info("Redis service connected")

        # Initialize PV Monitor with Redis
        pv_monitor = get_pv_monitor(redis_service)

        # Get all PV addresses from database
        async with async_session_maker() as session:
            from app.repositories.pv_repository import PVRepository
            pv_repo = PVRepository(session)
            pv_addresses_data = await pv_repo.get_all_addresses()

            # Extract unique addresses (setpoint and readback)
            pv_addresses = set()
            for _, setpoint, readback, config in pv_addresses_data:
                if setpoint:
                    pv_addresses.add(setpoint)
                if readback:
                    pv_addresses.add(readback)

        # Start PV monitoring (with batched startup)
        if pv_addresses:
            logger.info(
                f"Starting PV Monitor for {len(pv_addresses)} unique addresses "
                f"(batch size: {settings.pv_monitor_batch_size}, "
                f"batch delay: {settings.pv_monitor_batch_delay_ms}ms)"
            )
            await pv_monitor.start(list(pv_addresses))
            logger.info(f"PV Monitor started for {len(pv_addresses)} unique addresses")
        else:
            logger.warning("No PV addresses found in database - PV Monitor not started")

        # Start Watchdog if enabled
        if settings.watchdog_enabled:
            watchdog = get_watchdog(redis_service, epics, pv_monitor)
            await watchdog.start()
            logger.info(
                f"Watchdog started (check interval: {settings.watchdog_check_interval}s, "
                f"stale threshold: {settings.watchdog_stale_threshold}s)"
            )
        else:
            logger.info("Watchdog disabled by configuration")

        # Start WebSocket diff stream manager
        diff_manager = get_diff_manager()
        await diff_manager.start()
        logger.info("WebSocket diff stream manager started")

    except Exception as e:
        logger.warning(f"Redis/PV Monitor initialization failed: {e}")
        logger.warning("Running without Redis cache - snapshots will use direct EPICS reads")

    logger.info("Squirrel backend startup complete")

    yield

    # Cleanup
    logger.info("Shutting down Squirrel backend...")

    # Stop Watchdog
    if settings.watchdog_enabled:
        try:
            watchdog = get_watchdog()
            if watchdog.is_running():
                await watchdog.stop()
                logger.info("Watchdog stopped")
        except Exception as e:
            logger.error(f"Error stopping Watchdog: {e}")

    # Stop WebSocket manager
    try:
        diff_manager = get_diff_manager()
        await diff_manager.stop()
        logger.info("WebSocket diff stream manager stopped")
    except Exception as e:
        logger.error(f"Error stopping WebSocket manager: {e}")

    # Stop PV Monitor
    try:
        pv_monitor = get_pv_monitor()
        if pv_monitor.is_running():
            await pv_monitor.stop()
            logger.info("PV Monitor stopped")
    except Exception as e:
        logger.error(f"Error stopping PV Monitor: {e}")

    # Disconnect Redis
    if redis_connected:
        try:
            redis_service = get_redis_service()
            await redis_service.disconnect()
            logger.info("Redis disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting Redis: {e}")

    # Shutdown EPICS
    await epics.shutdown()
    logger.info("EPICS service shut down")

    logger.info("Squirrel backend shutdown complete")


app = FastAPI(
    title="Squirrel Backend",
    description="High-performance EPICS snapshot/restore backend with 40k PV support",
    version="0.2.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handler for APIException
@app.exception_handler(APIException)
async def api_exception_handler(request: Request, exc: APIException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "errorCode": exc.error_code,
            "errorMessage": exc.error_message,
            "payload": None
        }
    )


# Generic exception handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "errorCode": 500,
            "errorMessage": str(exc) if settings.debug else "Internal server error",
            "payload": None
        }
    )


# Include routers
app.include_router(v1_router)


# Health check endpoint (basic - use /v1/health/* for detailed checks)
@app.get("/health")
async def health_check():
    """Basic health check - returns healthy if the server is running."""
    return {"status": "healthy"}


# Root redirect
@app.get("/")
async def root():
    return {
        "message": "Squirrel Backend API",
        "docs": "/docs",
        "health": "/v1/health/summary",
        "version": "0.2.0"
    }
