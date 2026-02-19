"""DTOs for API-Key-related API operations."""
from datetime import datetime

from pydantic import BaseModel


class ApiKeyCreateDTO(BaseModel):
    """Request structure for API Key creation."""

    appName: str
    readAccess: bool
    writeAccess: bool


class ApiKeyDTO(BaseModel):
    """Response when an API Key is requested."""

    id: str
    appName: str
    isActive: bool
    readAccess: bool
    writeAccess: bool
    createdAt: datetime
    updatedAt: datetime


class ApiKeyCreateResultDTO(ApiKeyDTO):
    """Response when an API Key is created."""

    token: str
