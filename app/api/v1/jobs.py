"""API endpoints for job status monitoring."""
from fastapi import Security, APIRouter, HTTPException

from app.schemas.job import JobDTO
from app.dependencies import JobServiceDep, require_read_access

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", dependencies=[Security(require_read_access)], response_model=JobDTO)
async def get_job_status(job_id: str, job_service: JobServiceDep) -> JobDTO:
    """
    Get the status of a background job.

    Returns the current status, progress percentage, and result when complete.
    Poll this endpoint to track the progress of async operations.
    """
    job = await job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job
