from typing import Any
from datetime import datetime
from dataclasses import dataclass


@dataclass
class EpicsValue:
    """Container for EPICS PV value with metadata."""

    value: Any
    status: int | None = None
    severity: int | None = None
    timestamp: datetime | None = None
    units: str | None = None
    precision: int | None = None
    upper_ctrl_limit: float | None = None
    lower_ctrl_limit: float | None = None
    connected: bool = True
    error: str | None = None
