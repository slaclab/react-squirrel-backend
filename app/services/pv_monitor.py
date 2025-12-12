import asyncio
import logging
from datetime import datetime
from typing import Any

from aioca import camonitor, CANothing

from app.services.redis_service import RedisService
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class PVMonitor:
    """
    Background service that monitors all PVs and updates Redis cache.

    Uses aioca's camonitor for async EPICS monitoring with callbacks
    on value changes.
    """

    def __init__(self, redis_service: RedisService):
        self._redis = redis_service
        self._running = False
        self._monitored_pvs: set[str] = set()
        self._subscriptions: dict[str, Any] = {}
        self._update_queue: asyncio.Queue = asyncio.Queue()
        self._batch_task: asyncio.Task | None = None

    async def start(self, pv_addresses: list[str]) -> None:
        """
        Start monitoring all PVs using EPICS callbacks.

        Args:
            pv_addresses: List of PV names to monitor
        """
        if self._running:
            logger.warning("PV Monitor already running")
            return

        self._running = True
        logger.info(f"Starting PV Monitor for {len(pv_addresses)} PVs")

        # Start the batch update processor
        self._batch_task = asyncio.create_task(self._process_update_queue())

        # Start monitoring each PV
        for pv_name in pv_addresses:
            await self._start_monitor(pv_name)

        self._monitored_pvs = set(pv_addresses)
        logger.info(f"PV Monitor started, monitoring {len(self._monitored_pvs)} PVs")

    async def _start_monitor(self, pv_name: str) -> None:
        """Start monitoring a single PV."""
        try:
            # Create a callback closure for this PV
            def on_value_change(value, **kwargs):
                # Queue the update for batch processing
                asyncio.create_task(self._queue_update(pv_name, value, kwargs))

            # Start the monitor - camonitor returns a Subscription object
            subscription = camonitor(
                pv_name,
                on_value_change,
                notify_disconnect=True,
                format=2  # FORMAT_TIME for timestamp
            )
            self._subscriptions[pv_name] = subscription

        except Exception as e:
            logger.error(f"Failed to start monitor for {pv_name}: {e}")

    async def _queue_update(self, pv_name: str, value: Any, metadata: dict) -> None:
        """Queue a PV update for batch processing."""
        try:
            # Handle disconnection
            if isinstance(value, CANothing):
                value_dict = {
                    "value": None,
                    "connected": False,
                    "timestamp": datetime.now().isoformat(),
                    "error": "Disconnected"
                }
            else:
                # Extract value, handling arrays
                if hasattr(value, 'tolist'):
                    raw_value = value.tolist()
                else:
                    raw_value = value

                # Build value dict with metadata
                value_dict = {
                    "value": raw_value,
                    "connected": True,
                    "timestamp": datetime.now().isoformat(),
                    "status": metadata.get('status'),
                    "severity": metadata.get('severity'),
                }

            await self._update_queue.put((pv_name, value_dict))

        except Exception as e:
            logger.error(f"Error queuing update for {pv_name}: {e}")

    async def _process_update_queue(self) -> None:
        """Process queued PV updates in batches for efficiency."""
        batch_size = 100
        batch_interval = 0.1  # seconds

        while self._running:
            try:
                updates: dict[str, dict] = {}

                # Collect updates for batch_interval or until batch_size reached
                try:
                    # Wait for first update
                    pv_name, value = await asyncio.wait_for(
                        self._update_queue.get(),
                        timeout=batch_interval
                    )
                    updates[pv_name] = value

                    # Collect more updates without waiting
                    while len(updates) < batch_size:
                        try:
                            pv_name, value = self._update_queue.get_nowait()
                            updates[pv_name] = value
                        except asyncio.QueueEmpty:
                            break

                except asyncio.TimeoutError:
                    continue

                if updates:
                    # Batch update Redis
                    await self._redis.set_pv_values_bulk(updates)

                    # Optionally publish updates for WebSocket clients
                    # await self._redis.publish_pv_updates_bulk(updates)

                    logger.debug(f"Processed {len(updates)} PV updates")

            except Exception as e:
                logger.error(f"Error processing update queue: {e}")
                await asyncio.sleep(0.1)

    async def stop(self) -> None:
        """Stop all monitors and cleanup."""
        if not self._running:
            return

        logger.info("Stopping PV Monitor...")
        self._running = False

        # Stop batch processor
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        # Close all subscriptions
        for pv_name, subscription in self._subscriptions.items():
            try:
                subscription.close()
            except Exception as e:
                logger.error(f"Error closing subscription for {pv_name}: {e}")

        self._subscriptions.clear()
        self._monitored_pvs.clear()

        logger.info("PV Monitor stopped")

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

        # Add new monitors
        for pv_name in to_add:
            await self._start_monitor(pv_name)

        self._monitored_pvs = new_pvs
        logger.info(f"Refreshed PV list: added {len(to_add)}, removed {len(to_remove)}, total {len(new_pvs)}")

    def get_monitored_count(self) -> int:
        """Get the number of monitored PVs."""
        return len(self._monitored_pvs)

    def is_running(self) -> bool:
        """Check if the monitor is running."""
        return self._running


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
