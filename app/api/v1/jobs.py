"""API endpoints for job status monitoring."""
from fastapi import Depends, Security, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import require_read_access
from app.api.responses import APIException, success_response
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", dependencies=[Security(require_read_access)])
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Get the status of a background job.

    Returns the current status, progress percentage, and result when complete.
    Poll this endpoint to track the progress of async operations.
    """
    job_service = JobService(db)
    job = await job_service.get_job(job_id)
    if not job:
        raise APIException(404, f"Job {job_id} not found", 404)
    return success_response(job)
