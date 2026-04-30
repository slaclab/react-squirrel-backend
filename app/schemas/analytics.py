from typing import Any
from datetime import datetime

from pydantic import Field, BaseModel


class AnalyticsEventCreateDTO(BaseModel):
    """Incoming analytics event from the frontend."""

    event: str
    sessionId: str | None = None
    route: str | None = None
    path: str | None = None
    clientTs: datetime | None = None
    properties: dict[str, Any] | None = Field(default_factory=dict)
