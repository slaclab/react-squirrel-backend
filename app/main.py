"""
Squirrel Backend - High-performance EPICS snapshot/restore backend

Architecture:
- squirrel-api (this process): REST/WebSocket server, reads from Redis cache
- squirrel-monitor (separate process): PV monitoring, writes to Redis cache

Benefits of decoupled architecture:
- Fast API startup (<1s vs ~8s with embedded monitor)
- API crash doesn't affect PV monitoring
- PV Monitor crash doesn't take down the API
- Independent scaling and deployment
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.responses import APIException
from app.api.v1.router import router as v1_router
from app.api.v1.websocket import get_diff_manager
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

# Environment variable to optionally enable embedded monitor (for backward compatibility)
EMBEDDED_MONITOR = os.environ.get("SQUIRREL_EMBEDDED_MONITOR", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler for the API process.

    NOTE: PV Monitor and Watchdog are now in a separate process (squirrel-monitor).
    This API process only needs Redis connection for reading cached values
    and WebSocket for streaming updates to clients.

    Startup sequence:
    1. Initialize EPICS service (for snapshot restore/direct reads)
    2. Connect to Redis (for reading cached values)
    3. Start WebSocket diff stream manager

    Shutdown sequence:
    1. Stop WebSocket manager
    2. Disconnect Redis
    3. Shutdown EPICS service
    """
    logger.info("Starting Squirrel API...")

    # Initialize EPICS service (still needed for snapshot restore and direct reads)
    epics = get_epics_service()
    logger.info("EPICS service initialized (using aioca)")

    # Initialize Redis service
    redis_service = get_redis_service()
    redis_connected = False

    try:
        await redis_service.connect()
        redis_connected = True
        logger.info("Redis service connected")

        # Check if monitor process is running
        monitor_alive = await redis_service.is_monitor_alive()
        if monitor_alive:
            logger.info("PV Monitor process detected (via heartbeat)")
        else:
            logger.warning(
                "PV Monitor process not detected - start squirrel-monitor separately, "
                "or set SQUIRREL_EMBEDDED_MONITOR=true to run embedded"
            )

        # Optionally start embedded monitor (for backward compatibility/development)
        if EMBEDDED_MONITOR:
            logger.info("Starting EMBEDDED PV Monitor (SQUIRREL_EMBEDDED_MONITOR=true)")
            await _start_embedded_monitor(redis_service, epics)

        # Start WebSocket diff stream manager (subscribes to Redis pub/sub)
        diff_manager = get_diff_manager()
        await diff_manager.start()
        logger.info("WebSocket diff stream manager started")

    except Exception as e:
        logger.warning(f"Redis initialization failed: {e}")
        logger.warning("Running without Redis cache - snapshots will use direct EPICS reads")

    logger.info("Squirrel API startup complete")

    yield

    # Cleanup
    logger.info("Shutting down Squirrel API...")

    # Stop embedded monitor if running
    if EMBEDDED_MONITOR:
        await _stop_embedded_monitor()

    # Stop WebSocket manager
    try:
        diff_manager = get_diff_manager()
        await diff_manager.stop()
        logger.info("WebSocket diff stream manager stopped")
    except Exception as e:
        logger.error(f"Error stopping WebSocket manager: {e}")

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

    logger.info("Squirrel API shutdown complete")


async def _start_embedded_monitor(redis_service, epics):
    """
    Start PV Monitor and Watchdog in embedded mode (backward compatibility).

    This is enabled by setting SQUIRREL_EMBEDDED_MONITOR=true.
    """
    from app.db.session import async_session_maker
    from app.services.watchdog import get_watchdog
    from app.services.pv_monitor import get_pv_monitor
    from app.repositories.pv_repository import PVRepository

    pv_monitor = get_pv_monitor(redis_service)

    # Get all PV addresses from database
    async with async_session_maker() as session:
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
        logger.info(f"[EMBEDDED] Starting PV Monitor for {len(pv_addresses)} unique addresses")
        await pv_monitor.start(list(pv_addresses))
        logger.info(f"[EMBEDDED] PV Monitor started for {len(pv_addresses)} unique addresses")
    else:
        logger.warning("[EMBEDDED] No PV addresses found in database")

    # Start Watchdog if enabled
    if settings.watchdog_enabled:
        watchdog = get_watchdog(redis_service, epics, pv_monitor)
        await watchdog.start()
        logger.info("[EMBEDDED] Watchdog started")


async def _stop_embedded_monitor():
    """Stop embedded PV Monitor and Watchdog."""
    from app.services.watchdog import get_watchdog
    from app.services.pv_monitor import get_pv_monitor

    # Stop Watchdog
    if settings.watchdog_enabled:
        try:
            watchdog = get_watchdog()
            if watchdog.is_running():
                await watchdog.stop()
                logger.info("[EMBEDDED] Watchdog stopped")
        except Exception as e:
            logger.error(f"Error stopping Watchdog: {e}")

    # Stop PV Monitor
    try:
        pv_monitor = get_pv_monitor()
        if pv_monitor.is_running():
            await pv_monitor.stop()
            logger.info("[EMBEDDED] PV Monitor stopped")
    except Exception as e:
        logger.error(f"Error stopping PV Monitor: {e}")


app = FastAPI(
    title="Squirrel Backend",
    description="High-performance EPICS snapshot/restore backend with 40k PV support",
    version="0.2.0",
    lifespan=lifespan,
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
        content={"errorCode": exc.error_code, "errorMessage": exc.error_message, "payload": None},
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
            "payload": None,
        },
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
    return {"message": "Squirrel Backend API", "docs": "/docs", "health": "/v1/health/summary", "version": "0.2.0"}
