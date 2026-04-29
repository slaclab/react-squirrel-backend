from datetime import datetime

from pydantic import BaseModel


class HeartbeatResponse(BaseModel):
    """Simple heartbeat response for frontend polling."""

    timestamp: float | None
    alive: bool
    age_seconds: float | None = None
    error: str | None = None


class MonitorHealthResponse(BaseModel):
    """Comprehensive monitor health response."""

    alive: bool
    last_heartbeat: datetime | None
    heartbeat_age_seconds: float | None
    total_cached_pvs: int
    connected_pvs: int
    disconnected_pvs: int
    monitored_pvs: int
    active_subscriptions: int
    monitor_running: bool
    watchdog_running: bool
    watchdog_last_check: datetime | None


class WatchdogStatsResponse(BaseModel):
    """Watchdog statistics response."""

    last_check: datetime | None
    check_count: int
    disconnected_count: int
    stale_count: int
    reconnect_attempts: int
    successful_reconnects: int
    failed_reconnects: int
    last_errors: list[str]


class HealthSummaryResponse(BaseModel):
    """Complete health summary for dashboard."""

    status: str  # "healthy", "degraded", "unhealthy"
    monitor_alive: bool
    heartbeat_age_seconds: float | None
    total_pvs: int
    connected_pvs: int
    disconnected_pvs: int
    disconnected_percentage: float
    watchdog_running: bool
    last_watchdog_check: datetime | None
    issues: list[str]


class DisconnectedPVsResponse(BaseModel):
    """List of disconnected PVs."""

    count: int
    pvs: list[str]


class StalePVsResponse(BaseModel):
    """List of stale (un-updated) PVs."""

    count: int
    threshold_seconds: float
    pvs: list[str]


class CircuitStatsResponse(BaseModel):
    """Per-circuit statistics."""

    name: str
    state: str
    failure_count: int
    success_count: int
    call_count: int
    last_failure: str | None = None
    opened_at: str | None = None


class CircuitStatusResponse(BaseModel):
    """Aggregated circuit-breaker status for all EPICS IOCs."""

    open_circuit_count: int
    total_circuits: int
    open_circuits: list[str] = []
    circuits: list[CircuitStatsResponse] = []
    error: str | None = None


class CircuitActionResponse(BaseModel):
    """Result of a force-open / force-close action on a circuit breaker."""

    success: bool
    message: str


class MonitorProcessStatusResponse(BaseModel):
    """Liveness of the separate PV Monitor process."""

    status: str  # "healthy", "stale", "unknown", "error"
    message: str | None = None
    age_seconds: float | None = None
    leader: str | None = None
