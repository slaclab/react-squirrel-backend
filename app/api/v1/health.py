"""
Health Check API Endpoints

Provides health monitoring endpoints for:
1. System heartbeat - Frontend polls to detect dead monitor
2. Monitor health - Detailed health statistics
3. Watchdog status - Health check results
"""

from datetime import datetime

from fastapi import Security, APIRouter, HTTPException

from app.dependencies import require_read_access, require_write_access
from app.api.responses import success_response
from app.schemas.health import (
    HealthSummaryResponse,
    MonitorHealthResponse,
    WatchdogStatsResponse,
)
from app.services.watchdog import get_watchdog
from app.services.pv_monitor import get_pv_monitor
from app.services.redis_service import get_redis_service

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/heartbeat")
async def get_heartbeat() -> dict:
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
            return success_response(
                {
                    "timestamp": None,
                    "alive": False,
                    "age_seconds": None,
                    "error": "Redis not connected",
                }
            )

        heartbeat = await redis.get_heartbeat()
        alive = await redis.is_monitor_alive(max_age_seconds=5.0)
        age_seconds = await redis.get_heartbeat_age()

        return success_response(
            {
                "timestamp": heartbeat,
                "alive": alive,
                "age_seconds": age_seconds,
            }
        )
    except Exception as e:
        # Redis not available - monitor is definitely not healthy
        return success_response(
            {
                "timestamp": None,
                "alive": False,
                "age_seconds": None,
                "error": str(e),
            }
        )


@router.get("/monitor", dependencies=[Security(require_read_access)])
async def get_monitor_health() -> MonitorHealthResponse:
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


@router.get("/watchdog", dependencies=[Security(require_read_access)])
async def get_watchdog_stats() -> WatchdogStatsResponse:
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


@router.post("/watchdog/check", dependencies=[Security(require_write_access)])
async def force_watchdog_check() -> WatchdogStatsResponse:
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


@router.get("/summary", dependencies=[Security(require_read_access)])
async def get_health_summary() -> HealthSummaryResponse:
    """
    Get a complete health summary for monitoring dashboards.

    Includes overall status (healthy/degraded/unhealthy) and list of issues.
    """
    issues = []

    try:
        redis = get_redis_service()
        pv_monitor = get_pv_monitor()
        watchdog = get_watchdog()

        # Check heartbeat (monitor process health)
        heartbeat_age = await redis.get_heartbeat_age()
        monitor_alive = heartbeat_age is not None and heartbeat_age < 5.0

        if not monitor_alive:
            issues.append("Monitor heartbeat is stale or missing")

        # Get connection stats from Redis
        health_stats = await redis.get_health_stats()

        # Check if monitor is actually running based on PV count in Redis
        # (In distributed setup, monitor runs in separate container)
        health_stats.get("total_cached_pvs", 0) > 0 or monitor_alive

        # For backwards compatibility, check local instance too (embedded mode)
        pv_monitor = get_pv_monitor()
        watchdog = get_watchdog()
        if pv_monitor.is_running():
            pass
        watchdog_running = watchdog.is_running()
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
        if not monitor_alive:
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


@router.get("/disconnected", dependencies=[Security(require_read_access)])
async def get_disconnected_pvs() -> dict:
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


@router.get("/stale", dependencies=[Security(require_read_access)])
async def get_stale_pvs(max_age_seconds: float = 300) -> dict:
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


@router.get("/circuits", dependencies=[Security(require_read_access)])
async def get_circuit_breaker_status() -> dict:
    """
    Get circuit breaker status for all EPICS IOCs.

    Circuit breakers prevent cascading failures by blocking requests
    to failing IOCs until they recover.

    States:
    - closed: Normal operation, requests allowed
    - open: IOC failing, requests blocked
    - half_open: Testing if IOC recovered

    Returns list of circuits with their current state and statistics.
    """
    try:
        from app.services.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        stats = manager.get_all_stats()
        open_circuits = manager.get_open_circuits()

        return {
            "open_circuit_count": len(open_circuits),
            "total_circuits": len(stats),
            "open_circuits": open_circuits,
            "circuits": [
                {
                    "name": s.name,
                    "state": s.state.value,
                    "failure_count": s.failure_count,
                    "success_count": s.success_count,
                    "call_count": s.call_count,
                    "last_failure": s.last_failure.isoformat() if s.last_failure else None,
                    "opened_at": s.opened_at.isoformat() if s.opened_at else None,
                }
                for s in stats
            ],
        }
    except ImportError:
        return {
            "error": "Circuit breaker not available",
            "open_circuit_count": 0,
            "total_circuits": 0,
            "circuits": [],
        }
    except Exception as e:
        return {
            "error": str(e),
            "open_circuit_count": 0,
            "total_circuits": 0,
            "circuits": [],
        }


@router.post("/circuits/{circuit_name}/close", dependencies=[Security(require_write_access)])
async def force_close_circuit(circuit_name: str) -> dict:
    """
    Force close a circuit breaker (allow requests to IOC).

    Use this to manually recover from a circuit breaker that opened
    due to transient failures.
    """
    try:
        from app.services.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        manager.force_close(circuit_name)
        return {"success": True, "message": f"Circuit '{circuit_name}' forced closed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/circuits/{circuit_name}/open", dependencies=[Security(require_write_access)])
async def force_open_circuit(circuit_name: str) -> dict:
    """
    Force open a circuit breaker (block requests to IOC).

    Use this for maintenance or to protect the system from
    a known-failing IOC.
    """
    try:
        from app.services.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        manager.force_open(circuit_name)
        return {"success": True, "message": f"Circuit '{circuit_name}' forced open"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monitor/status", dependencies=[Security(require_read_access)])
async def monitor_process_status() -> dict:
    """
    Check if the separate PV Monitor process is alive via Redis heartbeat.

    The PV Monitor runs as a separate process (squirrel-monitor) and updates
    a heartbeat timestamp in Redis. This endpoint checks that heartbeat.

    Returns:
        status: "healthy", "stale", or "unknown"
        age_seconds: Age of last heartbeat in seconds (if available)
        leader: Instance ID of current monitor leader (if available)
    """
    try:
        redis = get_redis_service()

        if not redis.is_connected():
            return {
                "status": "unknown",
                "message": "Redis not connected",
                "age_seconds": None,
                "leader": None,
            }

        heartbeat = await redis.get_monitor_heartbeat()
        heartbeat_age = await redis.get_heartbeat_age()
        leader = await redis.get_monitor_lock_holder()

        if heartbeat is None:
            return {
                "status": "unknown",
                "message": "No heartbeat found - monitor may not be running",
                "age_seconds": None,
                "leader": leader,
            }

        if heartbeat_age is not None and heartbeat_age > 30:
            return {
                "status": "stale",
                "message": f"Heartbeat is {heartbeat_age:.1f}s old - monitor may be down",
                "age_seconds": heartbeat_age,
                "leader": leader,
            }

        return {
            "status": "healthy",
            "message": "Monitor process is alive",
            "age_seconds": heartbeat_age,
            "leader": leader,
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "age_seconds": None,
            "leader": None,
        }
