import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api.v1.router import router as v1_router
from app.api.responses import APIException
from app.services.epics_service import get_epics_service
from app.services.epics_worker import warmup_process_pool

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Squirrel backend...")

    # Initialize EPICS service (for single PV reads via ThreadPool)
    epics = get_epics_service()
    logger.info("EPICS service initialized")

    # Pre-warm the process pool so workers are ready for snapshot operations
    # This avoids slow first-request due to spawn overhead
    logger.info("Warming up EPICS process pool...")
    warmup_process_pool()
    logger.info("EPICS process pool ready")

    yield

    # Cleanup
    logger.info("Shutting down...")
    await epics.shutdown()


app = FastAPI(
    title="Squirrel Backend",
    description="High-performance EPICS snapshot/restore backend",
    version="0.1.0",
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


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Root redirect
@app.get("/")
async def root():
    return {"message": "Squirrel Backend API", "docs": "/docs"}
