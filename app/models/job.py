"""Job model for tracking async background tasks."""
from datetime import datetime
from enum import Enum

from sqlalchemy import String, Text, Integer, Float, DateTime, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, TimestampMixin


class JobStatus(str, Enum):
    """Status of a background job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    """Type of background job."""
    SNAPSHOT_CREATE = "snapshot_create"
    SNAPSHOT_RESTORE = "snapshot_restore"


class Job(Base, UUIDMixin, TimestampMixin):
    """Model for tracking async background tasks."""
    __tablename__ = "job"

    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=JobStatus.PENDING.value,
        index=True
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )
    message: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )
    result_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True
    )
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )
    job_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
