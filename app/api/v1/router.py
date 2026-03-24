from fastapi import APIRouter

from app.api.v1.pvs import router as pvs_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.tags import router as tags_router
from app.api.v1.health import router as health_router
from app.api.v1.snapshots import router as snapshots_router
from app.api.v1.websocket import router as websocket_router
from app.api.v1.export_csv import router as export_router

router = APIRouter(prefix="/v1")

router.include_router(tags_router)
router.include_router(pvs_router)
router.include_router(snapshots_router)
router.include_router(jobs_router)
router.include_router(websocket_router)
router.include_router(health_router)
router.include_router(export_router)
