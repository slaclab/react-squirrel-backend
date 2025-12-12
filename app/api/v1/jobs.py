"""API endpoints for job status monitoring."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.job_service import JobService
from app.api.responses import success_response, APIException

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", response_model=dict)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db)
):
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
