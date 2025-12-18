from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class EpicsValueDTO(BaseModel):
    """EPICS value with metadata."""
    model_config = {"extra": "ignore"}  # Ignore extra fields from JSONB

    value: Any
    status: int | None = None
    severity: int | None = None
    timestamp: datetime | None = None
    units: str | None = None
    precision: int | None = None
    upper_ctrl_limit: float | None = None
    lower_ctrl_limit: float | None = None


class TagInfoDTO(BaseModel):
    """Lightweight tag info for PV values."""
    id: str
    name: str
    groupName: str


class PVValueDTO(BaseModel):
    """PV value in a snapshot."""
    pvId: str
    pvName: str  # Primary name (setpoint or readback)
    setpointName: str | None = None  # Actual setpoint PV address
    readbackName: str | None = None  # Actual readback PV address
    setpointValue: EpicsValueDTO | None = None
    readbackValue: EpicsValueDTO | None = None
    status: int | None = None
    severity: int | None = None
    timestamp: datetime | None = None
    tags: list[TagInfoDTO] = []


class SnapshotBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    comment: str | None = None


class NewSnapshotDTO(SnapshotBase):
    """DTO for creating a snapshot. PVs are automatically included."""
    pass


class SnapshotSummaryDTO(SnapshotBase):
    """Summary DTO for listing snapshots."""
    id: str
    createdDate: datetime
    createdBy: str | None = None
    pvCount: int = 0

    class Config:
        from_attributes = True


class SnapshotDTO(SnapshotSummaryDTO):
    """Full snapshot with all values."""
    pvValues: list[PVValueDTO] = []


class RestoreRequestDTO(BaseModel):
    """Request to restore PV values from a snapshot."""
    pvIds: list[str] | None = None  # If None, restore all


class RestoreResultDTO(BaseModel):
    """Result of a restore operation."""
    totalPVs: int
    successCount: int
    failureCount: int
    failures: list[dict] = []  # [{pvId, pvName, error}]


class ComparisonResultDTO(BaseModel):
    """Comparison between two snapshots."""
    snapshot1Id: str
    snapshot2Id: str
    differences: list[dict] = []  # [{pvId, pvName, value1, value2, withinTolerance}]
    matchCount: int
    differenceCount: int
