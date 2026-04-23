from typing import Any
from datetime import datetime

from pydantic import Field, BaseModel, model_validator

from app.schemas.tag import TagDTO


class PVBase(BaseModel):
    setpointAddress: str | None = Field(None, max_length=255)
    readbackAddress: str | None = Field(None, max_length=255)
    configAddress: str | None = Field(None, max_length=255)
    device: str | None = Field(None, max_length=255)
    description: str | None = None
    absTolerance: float = 0.0
    relTolerance: float = 0.0
    readOnly: bool = False


class NewPVElementDTO(PVBase):
    """DTO for creating a new PV."""

    tags: list[str] = []  # Tag IDs

    @model_validator(mode="after")
    def validate_at_least_one_address(self):
        if not any([self.setpointAddress, self.readbackAddress, self.configAddress]):
            raise ValueError("At least one address (setpoint, readback, or config) is required")
        return self


class UpdatePVElementDTO(BaseModel):
    """DTO for updating a PV."""

    description: str | None = None
    absTolerance: float | None = None
    relTolerance: float | None = None
    readOnly: bool | None = None
    tags: list[str] | None = None  # Tag IDs


class PVElementDTO(PVBase):
    """Full PV response DTO."""

    id: str
    tags: list[TagDTO] = []
    createdDate: datetime
    lastModifiedDate: datetime
    createdBy: str | None = None
    lastModifiedBy: str | None = None

    class Config:
        from_attributes = True


class LivePVRequest(BaseModel):
    """DTO for requesting live PV values via POST."""

    pv_names: list[str] = Field(..., description="List of PV names to fetch")


class PVCacheEntryResponse(BaseModel):
    """Single PV cache entry as returned by live-value endpoints."""

    model_config = {"extra": "allow"}  # accept any extra metadata fields

    value: Any | None = None
    connected: bool = False
    updated_at: float | None = None
    status: str | None = None
    severity: int | None = None
    timestamp: float | None = None
    units: str | None = None
    error: str | None = None


class FilteredSearchResponse(BaseModel):
    """Response from GET /v1/pvs/search."""

    results: list[PVElementDTO]
    totalCount: int
    limit: int
    offset: int
    liveValues: dict[str, PVCacheEntryResponse] | None = None
    liveValuesError: str | None = None


class AllLiveValuesResponse(BaseModel):
    """Response from GET /v1/pvs/live/all."""

    values: dict[str, PVCacheEntryResponse]
    count: int


class CacheStatusResponse(BaseModel):
    """Response from GET /v1/pvs/cache/status."""

    cachedPvCount: int
    status: str  # "connected" | "disconnected"
    error: str | None = None


class EpicsTestResponse(BaseModel):
    """Response from GET /v1/pvs/test-epics."""

    pv: str
    connected: bool
    value: Any | None = None
    error: str | None = None
    environment: dict[str, str]
