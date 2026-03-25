from datetime import datetime

from pydantic import BaseModel


class HeartbeatResponse(BaseModel):
    """Simple heartbeat response for frontend polling."""

    timestamp: float | None
    alive: bool


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
