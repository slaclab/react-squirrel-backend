"""
Health Check API Endpoints

Provides health monitoring endpoints for:
1. System heartbeat - Frontend polls to detect dead monitor
2. Monitor health - Detailed health statistics
3. Watchdog status - Health check results
"""

import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.redis_service import get_redis_service, RedisService
from app.services.pv_monitor import get_pv_monitor, PVMonitor
from app.services.watchdog import get_watchdog, PVWatchdog
from app.api.responses import success_response

router = APIRouter(prefix="/health", tags=["Health"])


# ============================================================
# Response Models
# ============================================================

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


# ============================================================
# Endpoints
# ============================================================

@router.get("/heartbeat", response_model=dict)
async def get_heartbeat():
    """
    Simple heartbeat check for frontend polling.

    Returns just the timestamp and alive status for minimal bandwidth.
    Frontend should poll this every 2-5 seconds and show a warning
    banner if alive=false.
    """
    try:
        redis = get_redis_service()

        # Check if Redis is connected
        if not redis.is_connected():
            return success_response({
                "timestamp": None,
                "alive": False,
                "age_seconds": None,
                "error": "Redis not connected",
            })

        heartbeat = await redis.get_heartbeat()
        alive = await redis.is_monitor_alive(max_age_seconds=5.0)
        age_seconds = await redis.get_heartbeat_age()

        return success_response({
            "timestamp": heartbeat,
            "alive": alive,
            "age_seconds": age_seconds,
        })
    except Exception as e:
        # Redis not available - monitor is definitely not healthy
        return success_response({
            "timestamp": None,
            "alive": False,
            "age_seconds": None,
            "error": str(e),
        })


@router.get("/monitor", response_model=MonitorHealthResponse)
async def get_monitor_health():
    """
    Get detailed monitor health information.

    Includes connection counts, monitor status, and watchdog status.
    """
    try:
        redis = get_redis_service()
        pv_monitor = get_pv_monitor()
        watchdog = get_watchdog()

        # Get heartbeat info
        heartbeat = await redis.get_heartbeat()
        heartbeat_age = await redis.get_heartbeat_age()
        alive = heartbeat_age is not None and heartbeat_age < 5.0

        # Get connection counts
        health_stats = await redis.get_health_stats()

        # Get watchdog info
        watchdog_stats = watchdog.get_stats()

        return MonitorHealthResponse(
            alive=alive,
            last_heartbeat=datetime.fromtimestamp(heartbeat) if heartbeat else None,
            heartbeat_age_seconds=heartbeat_age,
            total_cached_pvs=health_stats["total_cached_pvs"],
            connected_pvs=health_stats["connected_pvs"],
            disconnected_pvs=health_stats["disconnected_pvs"],
            monitored_pvs=pv_monitor.get_monitored_count(),
            active_subscriptions=pv_monitor.get_active_subscription_count(),
            monitor_running=pv_monitor.is_running(),
            watchdog_running=watchdog.is_running(),
            watchdog_last_check=watchdog_stats.last_check,
        )

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Health check failed: {e}")


@router.get("/watchdog", response_model=WatchdogStatsResponse)
async def get_watchdog_stats():
    """
    Get watchdog statistics.

    Shows reconnection attempts, success rates, and recent errors.
    """
    try:
        watchdog = get_watchdog()
        stats = watchdog.get_stats()

        return WatchdogStatsResponse(
            last_check=stats.last_check,
            check_count=stats.check_count,
            disconnected_count=stats.disconnected_count,
            stale_count=stats.stale_count,
            reconnect_attempts=stats.reconnect_attempts,
            successful_reconnects=stats.successful_reconnects,
            failed_reconnects=stats.failed_reconnects,
            last_errors=stats.last_errors[-10:],
        )

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Watchdog stats failed: {e}")


@router.post("/watchdog/check", response_model=WatchdogStatsResponse)
async def force_watchdog_check():
    """
    Force an immediate watchdog health check.

    Useful for manual diagnostics or after making changes.
    """
    try:
        watchdog = get_watchdog()
        await watchdog.force_check()
        stats = watchdog.get_stats()

        return WatchdogStatsResponse(
            last_check=stats.last_check,
            check_count=stats.check_count,
            disconnected_count=stats.disconnected_count,
            stale_count=stats.stale_count,
            reconnect_attempts=stats.reconnect_attempts,
            successful_reconnects=stats.successful_reconnects,
            failed_reconnects=stats.failed_reconnects,
            last_errors=stats.last_errors[-10:],
        )

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Watchdog check failed: {e}")


@router.get("/summary", response_model=HealthSummaryResponse)
async def get_health_summary():
    """
    Get a complete health summary for monitoring dashboards.

    Includes overall status (healthy/degraded/unhealthy) and list of issues.
    """
    issues = []

    try:
        redis = get_redis_service()
        pv_monitor = get_pv_monitor()
        watchdog = get_watchdog()

        # Check heartbeat
        heartbeat_age = await redis.get_heartbeat_age()
        monitor_alive = heartbeat_age is not None and heartbeat_age < 5.0

        if not monitor_alive:
            issues.append("Monitor heartbeat is stale or missing")

        # Check monitor running
        if not pv_monitor.is_running():
            issues.append("PV Monitor is not running")

        # Check watchdog running
        watchdog_running = watchdog.is_running()
        if not watchdog_running:
            issues.append("Watchdog is not running")

        # Get connection stats
        health_stats = await redis.get_health_stats()
        total_pvs = health_stats["total_cached_pvs"]
        connected_pvs = health_stats["connected_pvs"]
        disconnected_pvs = health_stats["disconnected_pvs"]

        # Calculate disconnected percentage
        disconnected_pct = (disconnected_pvs / total_pvs * 100) if total_pvs > 0 else 0

        if disconnected_pct > 10:
            issues.append(f"High disconnection rate: {disconnected_pct:.1f}%")
        elif disconnected_pct > 1:
            issues.append(f"Some PVs disconnected: {disconnected_pvs}")

        # Get watchdog info
        watchdog_stats = watchdog.get_stats()

        # Determine overall status
        if not monitor_alive or not pv_monitor.is_running():
            status = "unhealthy"
        elif disconnected_pct > 10 or len(issues) > 2:
            status = "degraded"
        elif len(issues) > 0:
            status = "degraded"
        else:
            status = "healthy"

        return HealthSummaryResponse(
            status=status,
            monitor_alive=monitor_alive,
            heartbeat_age_seconds=heartbeat_age,
            total_pvs=total_pvs,
            connected_pvs=connected_pvs,
            disconnected_pvs=disconnected_pvs,
            disconnected_percentage=disconnected_pct,
            watchdog_running=watchdog_running,
            last_watchdog_check=watchdog_stats.last_check,
            issues=issues,
        )

    except Exception as e:
        return HealthSummaryResponse(
            status="unhealthy",
            monitor_alive=False,
            heartbeat_age_seconds=None,
            total_pvs=0,
            connected_pvs=0,
            disconnected_pvs=0,
            disconnected_percentage=0,
            watchdog_running=False,
            last_watchdog_check=None,
            issues=[f"Health check failed: {str(e)}"],
        )


@router.get("/disconnected", response_model=dict)
async def get_disconnected_pvs():
    """
    Get list of all disconnected PVs.

    Useful for diagnostics and debugging connection issues.
    """
    try:
        redis = get_redis_service()
        disconnected = await redis.get_disconnected_pvs()

        return {
            "count": len(disconnected),
            "pvs": sorted(list(disconnected)),
        }

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get disconnected PVs: {e}")


@router.get("/stale", response_model=dict)
async def get_stale_pvs(max_age_seconds: float = 300):
    """
    Get list of stale PVs (connected but not updated recently).

    Args:
        max_age_seconds: Consider stale if not updated in this many seconds
    """
    try:
        redis = get_redis_service()
        stale = await redis.get_stale_pvs(max_age_seconds=max_age_seconds)

        return {
            "count": len(stale),
            "threshold_seconds": max_age_seconds,
            "pvs": sorted(stale),
        }

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get stale PVs: {e}")
