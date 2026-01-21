"""Repository for Job model operations."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    """Repository for Job CRUD and status operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(Job, session)

    async def get_pending_jobs(self, job_type: str | None = None) -> list[Job]:
        """Get all pending jobs, optionally filtered by type."""
        query = select(Job).where(Job.status == JobStatus.PENDING.value)
        if job_type:
            query = query.where(Job.type == job_type)
        query = query.order_by(Job.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_running_jobs(self, job_type: str | None = None) -> list[Job]:
        """Get all running jobs, optionally filtered by type."""
        query = select(Job).where(Job.status == JobStatus.RUNNING.value)
        if job_type:
            query = query.where(Job.type == job_type)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: int | None = None,
        message: str | None = None,
        result_id: str | None = None,
        error: str | None = None,
    ) -> Job | None:
        """Update job status and related fields."""
        job = await self.get_by_id(job_id)
        if not job:
            return None

        job.status = status.value
        if progress is not None:
            job.progress = progress
        if message is not None:
            job.message = message
        if result_id is not None:
            job.result_id = result_id
        if error is not None:
            job.error = error

        # Set timestamp markers
        if status == JobStatus.RUNNING and not job.started_at:
            job.started_at = datetime.now()
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED):
            job.completed_at = datetime.now()

        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def mark_running(self, job_id: str) -> Job | None:
        """Mark a job as running."""
        return await self.update_status(job_id, JobStatus.RUNNING, progress=0, message="Job started")

    async def mark_completed(self, job_id: str, result_id: str | None = None, message: str | None = None) -> Job | None:
        """Mark a job as completed."""
        return await self.update_status(
            job_id,
            JobStatus.COMPLETED,
            progress=100,
            result_id=result_id,
            message=message or "Job completed successfully",
        )

    async def mark_failed(self, job_id: str, error: str) -> Job | None:
        """Mark a job as failed."""
        return await self.update_status(job_id, JobStatus.FAILED, error=error, message="Job failed")

    async def update_progress(self, job_id: str, progress: int, message: str | None = None) -> Job | None:
        """Update job progress."""
        job = await self.get_by_id(job_id)
        if not job:
            return None

        job.progress = min(max(progress, 0), 100)
        if message:
            job.message = message

        await self.session.flush()
        await self.session.refresh(job)
        return job
