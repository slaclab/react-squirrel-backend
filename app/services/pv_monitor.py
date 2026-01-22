import time
import asyncio
import logging
from typing import Any

from aioca import CANothing, camonitor
from p4p.client.thread import Context, Disconnected

from app.config import get_settings
from app.services.redis_service import PVCacheEntry, RedisService
from app.services.protocol_parser import parse_pv_address, group_by_protocol

logger = logging.getLogger(__name__)
settings = get_settings()


class PVMonitor:
    """
    Background service that monitors all PVs (CA and PVA) and updates Redis cache.

    Enhanced for 40k PV reliability with:
    - Batched startup to prevent UDP flood
    - Multi-protocol support (CA via aioca, PVA via p4p)
    - Connection callbacks for tracking connect/disconnect events
    - System heartbeat for health monitoring
    - Proper handling of disconnection events
    """

    def __init__(self, redis_service: RedisService):
        self._redis = redis_service
        self._running = False
        self._monitored_pvs: set[str] = set()

        # Separate subscriptions per protocol
        self._ca_subscriptions: dict[str, Any] = {}  # aioca subscriptions
        self._pva_subscriptions: dict[str, Any] = {}  # p4p subscriptions

        self._update_queue: asyncio.Queue = asyncio.Queue()
        self._batch_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

        # PVA context for monitoring
        self._pva_context: Context | None = None

        # Configuration from settings
        self._batch_size = settings.pv_monitor_batch_size
        self._batch_delay_ms = settings.pv_monitor_batch_delay_ms
        self._heartbeat_interval = settings.pv_monitor_heartbeat_interval
        self._default_protocol = settings.epics_default_protocol

    async def start(self, pv_addresses: list[str]) -> None:
        """
        Start monitoring all PVs with batched initialization.

        Supports mixed CA and PVA addresses. Batching prevents UDP flood
        that can cause packet loss and dropped monitors.

        Args:
            pv_addresses: List of PV addresses (with or without protocol prefix)
        """
        if self._running:
            logger.warning("PV Monitor already running")
            return

        self._running = True
        total = len(pv_addresses)
        logger.info(f"Starting PV Monitor for {total} PVs (batch size: {self._batch_size})")

        # Initialize PVA context
        self._pva_context = Context("pva")

        # Start the batch update processor
        self._batch_task = asyncio.create_task(self._process_update_queue())

        # Start the heartbeat loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Group PVs by protocol
        grouped = group_by_protocol(pv_addresses, self._default_protocol)

        ca_addresses = []
        pva_addresses = []

        if "ca" in grouped:
            ca_addresses = [orig_addr for orig_addr, _ in grouped["ca"]]
        if "pva" in grouped:
            pva_addresses = [orig_addr for orig_addr, _ in grouped["pva"]]

        logger.info(f"Protocol distribution: {len(ca_addresses)} CA, {len(pva_addresses)} PVA")

        # Start CA monitors
        ca_started = 0
        ca_failed = 0
        if ca_addresses:
            logger.info(f"Starting {len(ca_addresses)} CA monitors...")
            ca_started, ca_failed = await self._start_ca_monitors_batched(ca_addresses)

        # Start PVA monitors
        pva_started = 0
        pva_failed = 0
        if pva_addresses:
            logger.info(f"Starting {len(pva_addresses)} PVA monitors...")
            pva_started, pva_failed = await self._start_pva_monitors_batched(pva_addresses)

        self._monitored_pvs = set(pv_addresses)
        total_started = ca_started + pva_started
        total_failed = ca_failed + pva_failed

        logger.info(
            f"PV Monitor started: {total_started} monitors active "
            f"(CA: {ca_started}, PVA: {pva_started}), "
            f"{total_failed} failed, "
            f"{len(self._monitored_pvs)} total PVs tracked"
        )

    async def _start_ca_monitors_batched(self, pv_addresses: list[str]) -> tuple[int, int]:
        """
        Start CA monitors in batches.

        Returns:
            Tuple of (started_count, failed_count)
        """
        total = len(pv_addresses)
        total_batches = (total + self._batch_size - 1) // self._batch_size
        started_count = 0
        failed_count = 0

        for i in range(0, total, self._batch_size):
            if not self._running:
                logger.warning("CA monitor startup interrupted")
                break

            batch = pv_addresses[i : i + self._batch_size]
            batch_num = (i // self._batch_size) + 1

            logger.info(f"[CA] Starting monitors batch {batch_num}/{total_batches} ({len(batch)} PVs)")

            for pv_address in batch:
                success = await self._start_ca_monitor(pv_address)
                if success:
                    started_count += 1
                else:
                    failed_count += 1

            # Wait between batches to let network settle
            if i + self._batch_size < total:
                await asyncio.sleep(self._batch_delay_ms / 1000.0)

        return started_count, failed_count

    async def _start_pva_monitors_batched(self, pv_addresses: list[str]) -> tuple[int, int]:
        """
        Start PVA monitors in batches.

        Returns:
            Tuple of (started_count, failed_count)
        """
        total = len(pv_addresses)
        total_batches = (total + self._batch_size - 1) // self._batch_size
        started_count = 0
        failed_count = 0

        for i in range(0, total, self._batch_size):
            if not self._running:
                logger.warning("PVA monitor startup interrupted")
                break

            batch = pv_addresses[i : i + self._batch_size]
            batch_num = (i // self._batch_size) + 1

            logger.info(f"[PVA] Starting monitors batch {batch_num}/{total_batches} ({len(batch)} PVs)")

            for pv_address in batch:
                success = await self._start_pva_monitor(pv_address)
                if success:
                    started_count += 1
                else:
                    failed_count += 1

            # Wait between batches
            if i + self._batch_size < total:
                await asyncio.sleep(self._batch_delay_ms / 1000.0)

        return started_count, failed_count

    async def _start_ca_monitor(self, pv_address: str) -> bool:
        """
        Start monitoring a single CA PV.

        Returns True if monitor started successfully, False otherwise.
        """
        try:
            # Parse to get PV name without protocol prefix
            parsed = parse_pv_address(pv_address, self._default_protocol)
            pv_name = parsed.pv_name

            # Create a callback closure for this PV
            def on_value_change(value, **kwargs):
                # Queue the update for batch processing
                asyncio.create_task(self._queue_ca_update(pv_address, pv_name, value, kwargs))

            # Start the CA monitor
            subscription = camonitor(
                pv_name,
                on_value_change,
                notify_disconnect=True,  # Get notified on disconnect
                format=2,  # FORMAT_TIME for timestamp
            )
            self._ca_subscriptions[pv_address] = subscription
            return True

        except Exception as e:
            logger.error(f"[CA] Failed to start monitor for {pv_address}: {e}")
            try:
                await self._redis.set_pv_connected(pv_address, connected=False, error=str(e))
            except Exception as redis_err:
                logger.error(f"Failed to update Redis for {pv_address}: {redis_err}")
            return False

    async def _start_pva_monitor(self, pv_address: str) -> bool:
        """
        Start monitoring a single PVA PV.

        Returns True if monitor started successfully, False otherwise.
        """
        try:
            # Parse to get PV name without protocol prefix
            parsed = parse_pv_address(pv_address, self._default_protocol)
            pv_name = parsed.pv_name

            # Create callback for PVA updates
            def on_pva_update(value):
                asyncio.create_task(self._queue_pva_update(pv_address, pv_name, value))

            # Start PVA monitor using p4p
            # Run in thread pool since p4p monitor is blocking
            subscription = await asyncio.to_thread(
                self._pva_context.monitor,
                pv_name,
                on_pva_update,
                notify_disconnect=True,
            )

            self._pva_subscriptions[pv_address] = subscription
            return True

        except Exception as e:
            logger.error(f"[PVA] Failed to start monitor for {pv_address}: {e}")
            try:
                await self._redis.set_pv_connected(pv_address, connected=False, error=str(e))
            except Exception as redis_err:
                logger.error(f"Failed to update Redis for {pv_address}: {redis_err}")
            return False

    async def _queue_ca_update(self, pv_address: str, pv_name: str, value: Any, metadata: dict) -> None:
        """
        Queue a CA PV update for batch processing.

        Handles both value updates and disconnection events.
        """
        try:
            now = time.time()

            # Handle disconnection (aioca sends CANothing on disconnect)
            if isinstance(value, CANothing):
                logger.warning(f"[CA] PV disconnected: {pv_address}")
                entry = PVCacheEntry(
                    value=None,
                    connected=False,
                    updated_at=now,
                    error="Disconnected from IOC",
                )
            else:
                # Extract value, handling numpy arrays
                if hasattr(value, "tolist"):
                    raw_value = value.tolist()
                elif hasattr(value, "__iter__") and not isinstance(value, str | bytes):
                    try:
                        raw_value = list(value)
                    except Exception:
                        raw_value = value
                else:
                    raw_value = value

                # Extract EPICS metadata
                status = metadata.get("status")
                severity = metadata.get("severity")

                # Convert status to string if it's an enum
                if status is not None and hasattr(status, "name"):
                    status = status.name
                elif status is not None:
                    status = str(status)

                # Convert severity to int
                if severity is not None:
                    if hasattr(severity, "value"):
                        severity = severity.value
                    else:
                        severity = int(severity)

                entry = PVCacheEntry(
                    value=raw_value,
                    connected=True,
                    updated_at=now,
                    status=status,
                    severity=severity,
                    timestamp=metadata.get("timestamp"),
                    units=metadata.get("units"),
                )

            await self._update_queue.put((pv_address, entry))

        except Exception as e:
            logger.error(f"[CA] Error queuing update for {pv_address}: {e}")

    async def _queue_pva_update(self, pv_address: str, pv_name: str, value: Any) -> None:
        """
        Queue a PVA PV update for batch processing.
        """
        try:
            now = time.time()

            # Handle disconnection
            if isinstance(value, Disconnected):
                logger.warning(f"[PVA] PV disconnected: {pv_address}")
                entry = PVCacheEntry(
                    value=None,
                    connected=False,
                    updated_at=now,
                    error="Disconnected",
                )
            else:
                # Extract value and metadata from PVA structure
                raw_value = None
                status = None
                severity = None
                timestamp = None
                units = None

                # Check if it's a normative type with metadata
                if hasattr(value, "value"):
                    raw_value = value.value

                    # Handle arrays
                    if hasattr(raw_value, "tolist"):
                        raw_value = raw_value.tolist()

                    # Extract timestamp
                    if hasattr(value, "timeStamp"):
                        ts = value.timeStamp
                        if hasattr(ts, "secondsPastEpoch"):
                            timestamp = ts.secondsPastEpoch

                    # Extract alarm
                    if hasattr(value, "alarm"):
                        alarm = value.alarm
                        severity = getattr(alarm, "severity", None)
                        status = getattr(alarm, "message", None)

                    # Extract units
                    if hasattr(value, "display"):
                        display = value.display
                        units = getattr(display, "units", None)
                else:
                    # Plain value without metadata
                    raw_value = value
                    if hasattr(raw_value, "tolist"):
                        raw_value = raw_value.tolist()

                entry = PVCacheEntry(
                    value=raw_value,
                    connected=True,
                    updated_at=now,
                    status=status,
                    severity=severity,
                    timestamp=timestamp,
                    units=units,
                )

            await self._update_queue.put((pv_address, entry))

        except Exception as e:
            logger.error(f"[PVA] Error queuing update for {pv_address}: {e}")

    async def _process_update_queue(self) -> None:
        """
        Process queued PV updates in batches for efficiency.

        Batching reduces Redis round-trips and improves throughput.
        """
        batch_size = 100
        batch_interval = 0.1  # seconds

        while self._running:
            try:
                updates: dict[str, PVCacheEntry] = {}
                pv_names_to_publish: list[str] = []

                # Collect updates for batch_interval or until batch_size reached
                try:
                    # Wait for first update
                    pv_name, entry = await asyncio.wait_for(self._update_queue.get(), timeout=batch_interval)
                    updates[pv_name] = entry
                    pv_names_to_publish.append(pv_name)

                    # Collect more updates without waiting
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
                    # Batch update Redis
                    await self._redis.set_pv_values_bulk(updates)

                    # Publish updates for WebSocket clients
                    await self._redis.publish_pv_updates_bulk(pv_names_to_publish)

                    logger.debug(f"Processed {len(updates)} PV updates")

            except Exception as e:
                logger.error(f"Error processing update queue: {e}")
                await asyncio.sleep(0.1)

    async def _heartbeat_loop(self) -> None:
        """
        Continuously update the system heartbeat.

        This allows the frontend to detect if the monitor process is dead.
        """
        logger.info(f"Heartbeat loop started (interval: {self._heartbeat_interval}s)")

        while self._running:
            try:
                await self._redis.update_heartbeat()
            except Exception as e:
                logger.error(f"Failed to update heartbeat: {e}")

            await asyncio.sleep(self._heartbeat_interval)

        logger.info("Heartbeat loop stopped")

    async def stop(self) -> None:
        """Stop all monitors and cleanup."""
        if not self._running:
            return

        logger.info("Stopping PV Monitor...")
        self._running = False

        # Stop heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Stop batch processor
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        # Close all CA subscriptions
        close_errors = 0
        for pv_name, subscription in self._ca_subscriptions.items():
            try:
                subscription.close()
            except Exception as e:
                close_errors += 1
                logger.debug(f"[CA] Error closing subscription for {pv_name}: {e}")

        # Close all PVA subscriptions
        for pv_name, subscription in self._pva_subscriptions.items():
            try:
                subscription.close()
            except Exception as e:
                close_errors += 1
                logger.debug(f"[PVA] Error closing subscription for {pv_name}: {e}")

        if close_errors:
            logger.warning(f"Errors closing {close_errors} subscriptions")

        # Close PVA context
        if self._pva_context:
            try:
                self._pva_context.close()
            except Exception as e:
                logger.error(f"[PVA] Error closing context: {e}")

        self._ca_subscriptions.clear()
        self._pva_subscriptions.clear()
        self._monitored_pvs.clear()

        logger.info("PV Monitor stopped")

    async def restart_monitor(self, pv_address: str) -> bool:
        """
        Restart monitoring for a specific PV.

        Called by watchdog when attempting to reconnect a disconnected PV.
        """
        # Parse to determine protocol
        parsed = parse_pv_address(pv_address, self._default_protocol)
        protocol = parsed.protocol

        # Close existing subscription if any
        if protocol == "ca" and pv_address in self._ca_subscriptions:
            try:
                self._ca_subscriptions[pv_address].close()
                del self._ca_subscriptions[pv_address]
            except Exception:
                pass
        elif protocol == "pva" and pv_address in self._pva_subscriptions:
            try:
                self._pva_subscriptions[pv_address].close()
                del self._pva_subscriptions[pv_address]
            except Exception:
                pass

        # Start new monitor
        if protocol == "ca":
            success = await self._start_ca_monitor(pv_address)
        else:  # pva
            success = await self._start_pva_monitor(pv_address)

        if success:
            logger.info(f"Restarted monitor for {pv_address} (protocol: {protocol})")
        return success

    async def refresh_pv_list(self, pv_addresses: list[str]) -> None:
        """
        Reload PV list from database (called when PVs added/removed).

        Adds new monitors and removes stale ones.
        """
        new_pvs = set(pv_addresses)
        current_pvs = self._monitored_pvs

        # Find PVs to add and remove
        to_add = new_pvs - current_pvs
        to_remove = current_pvs - new_pvs

        # Remove old monitors
        for pv_address in to_remove:
            parsed = parse_pv_address(pv_address, self._default_protocol)

            if parsed.protocol == "ca" and pv_address in self._ca_subscriptions:
                try:
                    self._ca_subscriptions[pv_address].close()
                    del self._ca_subscriptions[pv_address]
                except Exception as e:
                    logger.error(f"Error removing CA monitor for {pv_address}: {e}")
            elif parsed.protocol == "pva" and pv_address in self._pva_subscriptions:
                try:
                    self._pva_subscriptions[pv_address].close()
                    del self._pva_subscriptions[pv_address]
                except Exception as e:
                    logger.error(f"Error removing PVA monitor for {pv_address}: {e}")

            # Remove from Redis cache
            try:
                await self._redis.delete_pv_value(pv_address)
            except Exception as e:
                logger.error(f"Error removing {pv_address} from cache: {e}")

        # Add new monitors (batched and grouped by protocol)
        if to_add:
            logger.info(f"Adding {len(to_add)} new PV monitors")
            add_list = list(to_add)
            grouped = group_by_protocol(add_list, self._default_protocol)

            # Add CA monitors
            if "ca" in grouped:
                ca_addresses = [orig_addr for orig_addr, _ in grouped["ca"]]
                await self._start_ca_monitors_batched(ca_addresses)

            # Add PVA monitors
            if "pva" in grouped:
                pva_addresses = [orig_addr for orig_addr, _ in grouped["pva"]]
                await self._start_pva_monitors_batched(pva_addresses)

        self._monitored_pvs = new_pvs
        logger.info(f"Refreshed PV list: added {len(to_add)}, removed {len(to_remove)}, " f"total {len(new_pvs)}")

    def get_monitored_count(self) -> int:
        """Get the number of monitored PVs."""
        return len(self._monitored_pvs)

    def get_active_subscription_count(self) -> int:
        """Get the number of active subscriptions."""
        return len(self._ca_subscriptions) + len(self._pva_subscriptions)

    def is_running(self) -> bool:
        """Check if the monitor is running."""
        return self._running

    def get_status(self) -> dict:
        """Get current monitor status."""
        return {
            "running": self._running,
            "monitored_pvs": len(self._monitored_pvs),
            "active_subscriptions": self.get_active_subscription_count(),
            "ca_subscriptions": len(self._ca_subscriptions),
            "pva_subscriptions": len(self._pva_subscriptions),
            "queue_size": self._update_queue.qsize(),
            "batch_size": self._batch_size,
            "heartbeat_interval": self._heartbeat_interval,
        }


# Singleton instance
_pv_monitor: PVMonitor | None = None


def get_pv_monitor(redis_service: RedisService | None = None) -> PVMonitor:
    """Get or create the PV Monitor singleton."""
    global _pv_monitor
    if _pv_monitor is None:
        if redis_service is None:
            from app.services.redis_service import get_redis_service

            redis_service = get_redis_service()
        _pv_monitor = PVMonitor(redis_service)
    return _pv_monitor
