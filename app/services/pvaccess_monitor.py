import os
import time
import asyncio
import logging
from typing import Any
from datetime import datetime

from p4p.client.asyncio import Context

from app.config import get_settings
from app.services.pv_protocol import is_ca, parse_pv_name
from app.services.redis_service import PVCacheEntry, RedisService

logger = logging.getLogger(__name__)
settings = get_settings()

# Configure PVA environment before Context initialization
if settings.epics_pva_addr_list:
    os.environ["EPICS_PVA_ADDR_LIST"] = settings.epics_pva_addr_list
os.environ["EPICS_PVA_AUTO_ADDR_LIST"] = settings.epics_pva_auto_addr_list
if settings.epics_pva_server_port:
    os.environ["EPICS_PVA_SERVER_PORT"] = settings.epics_pva_server_port
if settings.epics_pva_broadcast_port:
    os.environ["EPICS_PVA_BROADCAST_PORT"] = settings.epics_pva_broadcast_port


class PVAccessMonitor:
    """
    Background service that monitors PVAccess PVs and updates Redis cache.

    Mirrors the CA PVMonitor behavior but uses p4p for PVA subscriptions.
    """

    def __init__(self, redis_service: RedisService):
        self._redis = redis_service
        self._running = False
        self._monitored_pvs: set[str] = set()
        self._subscriptions: dict[str, Any] = {}
        self._update_queue: asyncio.Queue = asyncio.Queue()
        self._batch_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

        self._context = Context("pva", nt=False)

        # Configuration from settings (reuse CA settings)
        self._batch_size = settings.pv_monitor_batch_size
        self._batch_delay_ms = settings.pv_monitor_batch_delay_ms
        self._heartbeat_interval = settings.pv_monitor_heartbeat_interval

    async def start(self, pv_addresses: list[str]) -> None:
        """Start monitoring PVAccess PVs with batched initialization."""
        if self._running:
            logger.warning("PVAccess Monitor already running")
            return

        self._running = True
        total = len(pv_addresses)
        logger.info(f"Starting PVAccess Monitor for {total} PVs (batch size: {self._batch_size})")

        self._batch_task = asyncio.create_task(self._process_update_queue())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        total_batches = (total + self._batch_size - 1) // self._batch_size
        started_count = 0
        failed_count = 0

        for i in range(0, total, self._batch_size):
            if not self._running:
                logger.warning("PVAccess Monitor startup interrupted")
                break

            batch = pv_addresses[i : i + self._batch_size]
            batch_num = (i // self._batch_size) + 1
            logger.info(f"Starting PVAccess monitors batch {batch_num}/{total_batches} ({len(batch)} PVs)")

            for pv_name in batch:
                success = await self._start_monitor(pv_name)
                if success:
                    started_count += 1
                else:
                    failed_count += 1

            if i + self._batch_size < total:
                await asyncio.sleep(self._batch_delay_ms / 1000.0)

        self._monitored_pvs = set(pv_addresses)
        logger.info(
            f"PVAccess Monitor started: {started_count} monitors active, "
            f"{failed_count} failed to start, "
            f"{len(self._monitored_pvs)} total PVs tracked"
        )

    async def _start_monitor(self, pv_name: str) -> bool:
        """Start monitoring a single PVAccess PV."""
        try:
            protocol, stripped_name = parse_pv_name(pv_name)
            # Explicit ca:// addresses should not be monitored via PVA.
            if protocol == "ca" and is_ca(pv_name):
                return False

            def on_value_change(value):
                asyncio.create_task(self._queue_update(pv_name, value))

            subscription = self._context.monitor(
                stripped_name,
                on_value_change,
                notify_disconnect=True,
            )
            self._subscriptions[pv_name] = subscription
            return True
        except Exception as e:
            logger.error(f"Failed to start PVA monitor for {pv_name}: {e}")
            try:
                await self._redis.set_pv_connected(pv_name, connected=False, error=str(e))
            except Exception as redis_err:
                logger.error(f"Failed to update Redis for {pv_name}: {redis_err}")
            return False

    def _extract_metadata(self, value: Any) -> tuple[datetime | None, str | None, int | None, str | None]:
        """Best-effort metadata extraction from p4p Value."""
        timestamp = None
        status = None
        severity = None
        units = None

        try:
            if hasattr(value, "get"):
                seconds = value.get("timeStamp.secondsPastEpoch", None)
                nanos = value.get("timeStamp.nanoseconds", 0) or 0
                if seconds is not None:
                    timestamp = datetime.fromtimestamp(seconds + (nanos / 1e9))
                status = value.get("alarm.status", None)
                severity = value.get("alarm.severity", None)
                units = value.get("display.units", None)
        except Exception:
            pass

        return timestamp, status, severity, units

    async def _queue_update(self, pv_name: str, value: Any) -> None:
        """Queue a PVAccess update for batch processing."""
        try:
            now = time.time()

            if value is None or isinstance(value, Exception):
                logger.warning(f"PVA PV disconnected: {pv_name}")
                entry = PVCacheEntry(value=None, connected=False, updated_at=now, error="Disconnected from IOC")
            else:
                # Extract value payload
                raw_value = None
                try:
                    if hasattr(value, "get"):
                        raw_value = value.get("value")
                    elif hasattr(value, "toDict"):
                        raw_value = value.toDict().get("value")
                except Exception:
                    raw_value = None

                if raw_value is None:
                    raw_value = value

                if hasattr(raw_value, "tolist"):
                    raw_value = raw_value.tolist()

                timestamp, status, severity, units = self._extract_metadata(value)

                entry = PVCacheEntry(
                    value=raw_value,
                    connected=True,
                    updated_at=now,
                    status=str(status) if status is not None else None,
                    severity=int(severity) if severity is not None else None,
                    timestamp=timestamp.timestamp() if timestamp else None,
                    units=units,
                )

            await self._update_queue.put((pv_name, entry))
        except Exception as e:
            logger.error(f"Error queuing PVA update for {pv_name}: {e}")

    async def _process_update_queue(self) -> None:
        """Process queued PV updates in batches for efficiency."""
        batch_size = 100
        batch_interval = 0.1

        while self._running:
            try:
                updates: dict[str, PVCacheEntry] = {}
                pv_names_to_publish: list[str] = []

                try:
                    pv_name, entry = await asyncio.wait_for(self._update_queue.get(), timeout=batch_interval)
                    updates[pv_name] = entry
                    pv_names_to_publish.append(pv_name)

                    while len(updates) < batch_size:
                        try:
                            pv_name, entry = self._update_queue.get_nowait()
                            updates[pv_name] = entry
                            pv_names_to_publish.append(pv_name)
                        except asyncio.QueueEmpty:
                            break
                except TimeoutError:
                    continue

                if updates:
                    await self._redis.set_pv_values_bulk(updates)
                    await self._redis.publish_pv_updates_bulk(pv_names_to_publish)
                    logger.debug(f"Processed {len(updates)} PVA PV updates")
            except Exception as e:
                logger.error(f"Error processing PVA update queue: {e}")
                await asyncio.sleep(0.1)

    async def _heartbeat_loop(self) -> None:
        """Continuously update the system heartbeat."""
        logger.info(f"PVA Heartbeat loop started (interval: {self._heartbeat_interval}s)")
        while self._running:
            try:
                await self._redis.update_heartbeat()
            except Exception as e:
                logger.error(f"Failed to update heartbeat (PVA): {e}")
            await asyncio.sleep(self._heartbeat_interval)
        logger.info("PVA Heartbeat loop stopped")

    async def stop(self) -> None:
        """Stop all monitors and cleanup."""
        if not self._running:
            return

        logger.info("Stopping PVAccess Monitor...")
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        close_errors = 0
        for pv_name, subscription in self._subscriptions.items():
            try:
                subscription.close()
            except Exception as e:
                close_errors += 1
                logger.debug(f"Error closing PVA subscription for {pv_name}: {e}")

        if close_errors:
            logger.warning(f"Errors closing {close_errors} PVA subscriptions")

        self._subscriptions.clear()
        self._monitored_pvs.clear()

        logger.info("PVAccess Monitor stopped")

    async def restart_monitor(self, pv_name: str) -> bool:
        """Restart monitoring for a specific PV."""
        if pv_name in self._subscriptions:
            try:
                self._subscriptions[pv_name].close()
            except Exception:
                pass
            del self._subscriptions[pv_name]

        success = await self._start_monitor(pv_name)
        if success:
            logger.info(f"Restarted PVA monitor for {pv_name}")
        return success

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "monitored_pvs": len(self._monitored_pvs),
            "active_subscriptions": len(self._subscriptions),
            "queue_size": self._update_queue.qsize(),
            "batch_size": self._batch_size,
            "heartbeat_interval": self._heartbeat_interval,
        }


_pva_monitor: PVAccessMonitor | None = None


def get_pvaccess_monitor(redis_service: RedisService | None = None) -> PVAccessMonitor:
    """Get or create the PVAccess Monitor singleton."""
    global _pva_monitor
    if _pva_monitor is None:
        if redis_service is None:
            from app.services.redis_service import get_redis_service

            redis_service = get_redis_service()
        _pva_monitor = PVAccessMonitor(redis_service)
    return _pva_monitor
