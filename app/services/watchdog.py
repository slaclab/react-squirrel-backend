"""
PV Watchdog Service

Monitors the health of PV connections and handles recovery:
1. Detects disconnected PVs and attempts reconnection
2. Detects stale PVs (connected but not updating) and verifies them
3. Logs health statistics for monitoring

This is the "Pull" check that complements the "Push" checks from connection callbacks.
"""

import asyncio
import logging
from typing import TYPE_CHECKING
from datetime import datetime
from dataclasses import field, dataclass

from app.config import get_settings
from app.services.pv_protocol import is_unprefixed, parse_pv_name
from app.services.epics_service import EpicsService
from app.services.redis_service import RedisService

if TYPE_CHECKING:
    from app.services.pv_monitor import PVMonitor
    from app.services.pvaccess_monitor import PVAccessMonitor

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class WatchdogStats:
    """Statistics from the watchdog health checks."""

    last_check: datetime | None = None
    check_count: int = 0
    disconnected_count: int = 0
    stale_count: int = 0
    reconnect_attempts: int = 0
    successful_reconnects: int = 0
    failed_reconnects: int = 0
    last_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "check_count": self.check_count,
            "disconnected_count": self.disconnected_count,
            "stale_count": self.stale_count,
            "reconnect_attempts": self.reconnect_attempts,
            "successful_reconnects": self.successful_reconnects,
            "failed_reconnects": self.failed_reconnects,
            "last_errors": self.last_errors[-10:],  # Keep last 10 errors
        }


class PVWatchdog:
    """
    Background watchdog that monitors the health of PV connections.

    Runs periodically to:
    1. Check for disconnected PVs and attempt reconnection
    2. Check for stale PVs (connected but not updating) and verify them
    3. Log health statistics

    This catches edge cases that connection callbacks might miss:
    - PVs that never connected initially
    - Connections that silently dropped
    - IOCs that restarted but the library didn't auto-reconnect
    """

    def __init__(
        self,
        redis_service: RedisService,
        epics_service: EpicsService,
        pv_monitor: "PVMonitor",
        pva_monitor: "PVAccessMonitor | None" = None,
    ):
        self._redis = redis_service
        self._epics = epics_service
        self._pv_monitor = pv_monitor
        self._pva_monitor = pva_monitor

        # Configuration from settings
        self._check_interval = settings.watchdog_check_interval
        self._stale_threshold = settings.watchdog_stale_threshold
        self._reconnect_timeout = settings.watchdog_reconnect_timeout

        self._running = False
        self._task: asyncio.Task | None = None
        self._stats = WatchdogStats()

    async def start(self) -> None:
        """Start the watchdog background task."""
        if self._running:
            logger.warning("Watchdog already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        logger.info(
            f"PV Watchdog started (check interval: {self._check_interval}s, "
            f"stale threshold: {self._stale_threshold}s)"
        )

    async def stop(self) -> None:
        """Stop the watchdog."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("PV Watchdog stopped")

    async def _watchdog_loop(self) -> None:
        """Main watchdog loop."""
        # Wait a bit before first check to let monitors initialize
        await asyncio.sleep(10)

        while self._running:
            try:
                await self._run_health_check()
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
                self._stats.last_errors.append(f"{datetime.now().isoformat()}: {str(e)}")

            await asyncio.sleep(self._check_interval)

    async def _run_health_check(self) -> None:
        """Run a complete health check cycle."""
        start_time = datetime.now()
        logger.info("Watchdog: Starting health check...")

        self._stats.check_count += 1

        # 1. Check disconnected PVs and attempt reconnection
        disconnected_results = await self._check_disconnected_pvs()

        # 2. Check stale PVs (connected but not updating)
        stale_results = await self._check_stale_pvs()

        # 3. Update statistics
        duration = (datetime.now() - start_time).total_seconds()
        self._stats.last_check = datetime.now()
        self._stats.disconnected_count = disconnected_results["still_disconnected"]
        self._stats.stale_count = stale_results["verified_stale"]

        logger.info(
            f"Watchdog: Health check complete in {duration:.2f}s - "
            f"Disconnected: {disconnected_results['still_disconnected']} "
            f"(reconnected: {disconnected_results['reconnected']}), "
            f"Stale: {stale_results['verified_stale']} "
            f"(refreshed: {stale_results['refreshed']})"
        )

    async def _check_disconnected_pvs(self) -> dict:
        """
        Check all disconnected PVs and attempt reconnection.

        Returns dict with reconnection statistics.
        """
        disconnected = await self._redis.get_disconnected_pvs()

        if not disconnected:
            return {"total": 0, "reconnected": 0, "still_disconnected": 0}

        logger.info(f"Watchdog: Checking {len(disconnected)} disconnected PVs")

        reconnected = 0
        still_disconnected = 0

        for pv_name in disconnected:
            # Attempt to read the PV directly
            try:
                value = await self._epics.get_single(pv_name, timeout=self._reconnect_timeout)

                if value is not None and value.connected:
                    # PV is actually alive! Update Redis and restart monitor
                    logger.info(f"Watchdog: Reconnected {pv_name}")

                    await self._redis.set_pv_value(
                        pv_name=pv_name,
                        value=value.value,
                        connected=True,
                        status=value.status,
                        severity=value.severity,
                        timestamp=value.timestamp,
                        units=value.units,
                    )

                    # Restart the monitor for this PV
                    protocol, _ = parse_pv_name(pv_name)
                    if protocol == "pva":
                        if self._pva_monitor:
                            await self._pva_monitor.restart_monitor(pv_name)
                        else:
                            logger.warning(f"No PVA monitor available to restart {pv_name}")
                    else:
                        await self._pv_monitor.restart_monitor(pv_name)
                        if settings.epics_unprefixed_pva_fallback and is_unprefixed(pv_name) and self._pva_monitor:
                            await self._pva_monitor.restart_monitor(pv_name)

                    reconnected += 1
                    self._stats.successful_reconnects += 1
                else:
                    still_disconnected += 1

            except Exception as e:
                logger.debug(f"Watchdog: {pv_name} still disconnected: {e}")
                still_disconnected += 1
                self._stats.failed_reconnects += 1

            self._stats.reconnect_attempts += 1

        if reconnected:
            logger.info(f"Watchdog: Reconnected {reconnected} PVs")
        if still_disconnected:
            logger.warning(f"Watchdog: {still_disconnected} PVs still disconnected")

        return {
            "total": len(disconnected),
            "reconnected": reconnected,
            "still_disconnected": still_disconnected,
        }

    async def _check_stale_pvs(self) -> dict:
        """
        Check for PVs that are marked connected but haven't updated recently.

        This catches the case where:
        - The connection is "alive" but data isn't flowing
        - The IOC restarted and the PV is actually at a different value
        - There's a network issue causing missed updates

        Returns dict with staleness statistics.
        """
        stale_pvs = await self._redis.get_stale_pvs(max_age_seconds=self._stale_threshold)

        if not stale_pvs:
            return {"total": 0, "refreshed": 0, "verified_stale": 0}

        logger.info(f"Watchdog: Checking {len(stale_pvs)} stale PVs")

        refreshed = 0
        verified_stale = 0

        for pv_name in stale_pvs:
            # Issue a manual caget to verify and refresh the value
            try:
                value = await self._epics.get_single(pv_name, timeout=self._reconnect_timeout)

                if value is not None and value.connected:
                    # PV is alive, update the cache with fresh value
                    await self._redis.set_pv_value(
                        pv_name=pv_name,
                        value=value.value,
                        connected=True,
                        status=value.status,
                        severity=value.severity,
                        timestamp=value.timestamp,
                        units=value.units,
                    )
                    logger.debug(f"Watchdog: Refreshed stale PV {pv_name}")
                    refreshed += 1
                else:
                    # PV is not responding - mark as disconnected
                    await self._redis.set_pv_connected(pv_name, connected=False, error="Failed watchdog verification")
                    verified_stale += 1

            except Exception as e:
                logger.warning(f"Watchdog: Stale PV {pv_name} failed verification: {e}")
                await self._redis.set_pv_connected(pv_name, connected=False, error=f"Watchdog verification failed: {e}")
                verified_stale += 1

        return {
            "total": len(stale_pvs),
            "refreshed": refreshed,
            "verified_stale": verified_stale,
        }

    async def force_check(self) -> dict:
        """
        Force an immediate health check.

        Returns the results of the check.
        """
        logger.info("Watchdog: Forced health check requested")
        await self._run_health_check()
        return self._stats.to_dict()

    def get_stats(self) -> WatchdogStats:
        """Get current watchdog statistics."""
        return self._stats

    def is_running(self) -> bool:
        """Check if the watchdog is running."""
        return self._running


# Singleton instance
_watchdog: PVWatchdog | None = None


def get_watchdog(
    redis_service: RedisService | None = None,
    epics_service: EpicsService | None = None,
    pv_monitor: "PVMonitor | None" = None,
    pva_monitor: "PVAccessMonitor | None" = None,
) -> PVWatchdog:
    """Get or create the Watchdog singleton."""
    global _watchdog
    if _watchdog is None:
        if redis_service is None:
            from app.services.redis_service import get_redis_service

            redis_service = get_redis_service()
        if epics_service is None:
            from app.services.epics_service import get_epics_service

            epics_service = get_epics_service()
        if pv_monitor is None:
            from app.services.pv_monitor import get_pv_monitor

            pv_monitor = get_pv_monitor()
        _watchdog = PVWatchdog(redis_service, epics_service, pv_monitor, pva_monitor)
    return _watchdog
