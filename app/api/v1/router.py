from fastapi import APIRouter

from app.api.v1.pvs import router as pvs_router
from app.api.v1.elog import router as elog_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.tags import router as tags_router
from app.api.v1.health import router as health_router
from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.snapshots import router as snapshots_router
from app.api.v1.websocket import router as websocket_router

router = APIRouter(prefix="/v1")

router.include_router(api_keys_router)
router.include_router(tags_router)
router.include_router(pvs_router)
router.include_router(snapshots_router)
router.include_router(jobs_router)
router.include_router(websocket_router)
router.include_router(elog_router)
router.include_router(health_router)
