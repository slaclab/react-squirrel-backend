"""API endpoints for job status monitoring."""
from fastapi import Depends, Security, APIRouter

from app.dependencies import get_job_service, require_read_access
from app.api.responses import APIException, success_response
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", dependencies=[Security(require_read_access)])
async def get_job_status(
    job_id: str,
    job_service: JobService = Depends(get_job_service),
) -> dict:
    """
    Get the status of a background job.

    Returns the current status, progress percentage, and result when complete.
    Poll this endpoint to track the progress of async operations.
    """
    job = await job_service.get_job(job_id)
    if not job:
        raise APIException(404, f"Job {job_id} not found", 404)
    return success_response(job)
