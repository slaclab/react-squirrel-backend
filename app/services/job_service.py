"""Service for managing background jobs."""
import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus, JobType
from app.repositories.job_repository import JobRepository
from app.schemas.job import JobDTO, JobCreatedDTO

logger = logging.getLogger(__name__)


class JobService:
    """Service for creating and managing background jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = JobRepository(session)

    async def create_job(
        self,
        job_type: JobType,
        job_data: dict | None = None
    ) -> Job:
        """Create a new job record."""
        job = Job(
            type=job_type.value,
            status=JobStatus.PENDING.value,
            progress=0,
            job_data=job_data
        )
        return await self.repo.create(job)

    async def get_job(self, job_id: str) -> JobDTO | None:
        """Get job status by ID."""
        job = await self.repo.get_by_id(job_id)
        if not job:
            return None
        return self._to_dto(job)

    async def update_progress(
        self,
        job_id: str,
        progress: int,
        message: str | None = None
    ) -> JobDTO | None:
        """Update job progress."""
        job = await self.repo.update_progress(job_id, progress, message)
        return self._to_dto(job) if job else None

    async def mark_running(self, job_id: str) -> JobDTO | None:
        """Mark a job as running."""
        job = await self.repo.mark_running(job_id)
        return self._to_dto(job) if job else None

    async def mark_completed(
        self,
        job_id: str,
        result_id: str | None = None,
        message: str | None = None
    ) -> JobDTO | None:
        """Mark a job as completed."""
        job = await self.repo.mark_completed(job_id, result_id, message)
        return self._to_dto(job) if job else None

    async def mark_failed(self, job_id: str, error: str) -> JobDTO | None:
        """Mark a job as failed."""
        job = await self.repo.mark_failed(job_id, error)
        return self._to_dto(job) if job else None

    def _to_dto(self, job: Job) -> JobDTO:
        """Convert Job model to DTO."""
        return JobDTO(
            id=job.id,
            type=job.type,
            status=job.status,
            progress=job.progress,
            message=job.message,
            resultId=job.result_id,
            error=job.error,
            createdAt=job.created_at,
            startedAt=job.started_at,
            completedAt=job.completed_at
        )
