"""DTOs for Job-related API operations."""
from datetime import datetime

from pydantic import BaseModel


class JobDTO(BaseModel):
    """Job status response."""

    id: str
    type: str
    status: str
    progress: int
    message: str | None = None
    resultId: str | None = None
    error: str | None = None
    jobData: dict | None = None
    createdAt: datetime
    startedAt: datetime | None = None
    completedAt: datetime | None = None

    class Config:
        from_attributes = True


class JobCreatedDTO(BaseModel):
    """Response when a job is created."""

    jobId: str
    message: str = "Job started"
