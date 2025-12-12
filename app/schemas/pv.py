from datetime import datetime
from pydantic import BaseModel, Field, model_validator
from typing import Any

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
