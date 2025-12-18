import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from aioca import camonitor, CANothing

from app.services.redis_service import RedisService, PVCacheEntry
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class PVMonitor:
    """
    Background service that monitors all PVs and updates Redis cache.

    Enhanced for 40k PV reliability with:
    - Batched startup to prevent UDP flood
    - Connection callbacks for tracking connect/disconnect events
    - System heartbeat for health monitoring
    - Proper handling of disconnection events
    """

    def __init__(self, redis_service: RedisService):
        self._redis = redis_service
        self._running = False
        self._monitored_pvs: set[str] = set()
        self._subscriptions: dict[str, Any] = {}
        self._update_queue: asyncio.Queue = asyncio.Queue()
        self._batch_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

        # Configuration from settings
        self._batch_size = settings.pv_monitor_batch_size
        self._batch_delay_ms = settings.pv_monitor_batch_delay_ms
        self._heartbeat_interval = settings.pv_monitor_heartbeat_interval

    async def start(self, pv_addresses: list[str]) -> None:
        """
        Start monitoring all PVs with batched initialization.

        Batching prevents UDP flood that can cause packet loss and
        dropped monitors when starting 40k+ PVs simultaneously.

        Args:
            pv_addresses: List of PV names to monitor
        """
        if self._running:
            logger.warning("PV Monitor already running")
            return

        self._running = True
        total = len(pv_addresses)
        logger.info(f"Starting PV Monitor for {total} PVs (batch size: {self._batch_size})")

        # Start the batch update processor
        self._batch_task = asyncio.create_task(self._process_update_queue())

        # Start the heartbeat loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Batch the startup to avoid UDP flood
        total_batches = (total + self._batch_size - 1) // self._batch_size
        started_count = 0
        failed_count = 0

        for i in range(0, total, self._batch_size):
            if not self._running:
                logger.warning("PV Monitor startup interrupted")
                break

            batch = pv_addresses[i:i + self._batch_size]
            batch_num = (i // self._batch_size) + 1

            logger.info(f"Starting monitors batch {batch_num}/{total_batches} ({len(batch)} PVs)")

            # Start monitors for this batch
            for pv_name in batch:
                success = await self._start_monitor(pv_name)
                if success:
                    started_count += 1
                else:
                    failed_count += 1

            # Wait between batches to let network settle
            if i + self._batch_size < total:
                await asyncio.sleep(self._batch_delay_ms / 1000.0)

        self._monitored_pvs = set(pv_addresses)
        logger.info(
            f"PV Monitor started: {started_count} monitors active, "
            f"{failed_count} failed to start, "
            f"{len(self._monitored_pvs)} total PVs tracked"
        )

    async def _start_monitor(self, pv_name: str) -> bool:
        """
        Start monitoring a single PV with value and connection callbacks.

        Returns True if monitor started successfully, False otherwise.
        """
        try:
            # Create a callback closure for this PV
            def on_value_change(value, **kwargs):
                # Queue the update for batch processing
                asyncio.create_task(self._queue_update(pv_name, value, kwargs))

            # Start the monitor - camonitor returns a Subscription object
            # notify_disconnect=True is CRITICAL for connection tracking
            subscription = camonitor(
                pv_name,
                on_value_change,
                notify_disconnect=True,  # Get notified on disconnect
                format=2  # FORMAT_TIME for timestamp
            )
            self._subscriptions[pv_name] = subscription
            return True

        except Exception as e:
            logger.error(f"Failed to start monitor for {pv_name}: {e}")
            # Mark as disconnected in Redis
            try:
                await self._redis.set_pv_connected(pv_name, connected=False, error=str(e))
            except Exception as redis_err:
                logger.error(f"Failed to update Redis for {pv_name}: {redis_err}")
            return False

    async def _queue_update(self, pv_name: str, value: Any, metadata: dict) -> None:
        """
        Queue a PV update for batch processing.

        Handles both value updates and disconnection events.
        """
        try:
            now = time.time()

            # Handle disconnection (aioca sends CANothing on disconnect)
            if isinstance(value, CANothing):
                logger.warning(f"PV disconnected: {pv_name}")
                entry = PVCacheEntry(
                    value=None,
                    connected=False,
                    updated_at=now,
                    error="Disconnected from IOC"
                )
            else:
                # Extract value, handling numpy arrays
                if hasattr(value, 'tolist'):
                    raw_value = value.tolist()
                elif hasattr(value, '__iter__') and not isinstance(value, (str, bytes)):
                    # Handle other array-like objects
                    try:
                        raw_value = list(value)
                    except Exception:
                        raw_value = value
                else:
                    raw_value = value

                # Extract EPICS metadata
                status = metadata.get('status')
                severity = metadata.get('severity')

                # Convert status to string if it's an enum
                if status is not None and hasattr(status, 'name'):
                    status = status.name
                elif status is not None:
                    status = str(status)

                # Convert severity to int
                if severity is not None:
                    if hasattr(severity, 'value'):
                        severity = severity.value
                    else:
                        severity = int(severity)

                entry = PVCacheEntry(
                    value=raw_value,
                    connected=True,
                    updated_at=now,
                    status=status,
                    severity=severity,
                    timestamp=metadata.get('timestamp'),
                    units=metadata.get('units'),
                )

            await self._update_queue.put((pv_name, entry))

        except Exception as e:
            logger.error(f"Error queuing update for {pv_name}: {e}")

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
                    pv_name, entry = await asyncio.wait_for(
                        self._update_queue.get(),
                        timeout=batch_interval
                    )
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

                except asyncio.TimeoutError:
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

        # Close all subscriptions
        close_errors = 0
        for pv_name, subscription in self._subscriptions.items():
            try:
                subscription.close()
            except Exception as e:
                close_errors += 1
                logger.debug(f"Error closing subscription for {pv_name}: {e}")

        if close_errors:
            logger.warning(f"Errors closing {close_errors} subscriptions")

        self._subscriptions.clear()
        self._monitored_pvs.clear()

        logger.info("PV Monitor stopped")

    async def restart_monitor(self, pv_name: str) -> bool:
        """
        Restart monitoring for a specific PV.

        Called by watchdog when attempting to reconnect a disconnected PV.
        """
        # Close existing subscription if any
        if pv_name in self._subscriptions:
            try:
                self._subscriptions[pv_name].close()
            except Exception:
                pass
            del self._subscriptions[pv_name]

        # Start new monitor
        success = await self._start_monitor(pv_name)
        if success:
            logger.info(f"Restarted monitor for {pv_name}")
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
        for pv_name in to_remove:
            if pv_name in self._subscriptions:
                try:
                    self._subscriptions[pv_name].close()
                    del self._subscriptions[pv_name]
                except Exception as e:
                    logger.error(f"Error removing monitor for {pv_name}: {e}")

            # Remove from Redis cache
            try:
                await self._redis.delete_pv_value(pv_name)
            except Exception as e:
                logger.error(f"Error removing {pv_name} from cache: {e}")

        # Add new monitors (batched to avoid UDP flood)
        if to_add:
            logger.info(f"Adding {len(to_add)} new PV monitors")
            add_list = list(to_add)

            for i in range(0, len(add_list), self._batch_size):
                batch = add_list[i:i + self._batch_size]
                for pv_name in batch:
                    await self._start_monitor(pv_name)

                if i + self._batch_size < len(add_list):
                    await asyncio.sleep(self._batch_delay_ms / 1000.0)

        self._monitored_pvs = new_pvs
        logger.info(
            f"Refreshed PV list: added {len(to_add)}, removed {len(to_remove)}, "
            f"total {len(new_pvs)}"
        )

    def get_monitored_count(self) -> int:
        """Get the number of monitored PVs."""
        return len(self._monitored_pvs)

    def get_active_subscription_count(self) -> int:
        """Get the number of active subscriptions."""
        return len(self._subscriptions)

    def is_running(self) -> bool:
        """Check if the monitor is running."""
        return self._running

    def get_status(self) -> dict:
        """Get current monitor status."""
        return {
            "running": self._running,
            "monitored_pvs": len(self._monitored_pvs),
            "active_subscriptions": len(self._subscriptions),
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
