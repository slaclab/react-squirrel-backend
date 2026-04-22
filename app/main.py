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

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.services.elog import shutdown_elog_service
from app.api.v1.router import router as v1_router
from app.api.v1.websocket import get_diff_manager
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


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
            logger.warning("PV Monitor process not detected - start squirrel-monitor separately")

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

    # Close e-log adapter HTTP client, if initialized
    try:
        await shutdown_elog_service()
    except Exception as e:
        logger.error(f"Error shutting down e-log adapter: {e}")

    logger.info("Squirrel API shutdown complete")


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


# Generic exception handler — returns FastAPI-style {"detail": ...} body
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) if settings.debug else "Internal server error"},
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
