"""
WebSocket API for Real-time PV Updates

Enhanced for 40k PV efficiency with:
- Diff-based streaming (only send changed values)
- Batched updates (100ms buffer window)
- Per-client subscription tracking
- Heartbeat messages for connection health
- Multi-instance support via Redis subscription registry

Architecture for multi-instance:
- Each API instance has unique instance_id
- Client subscriptions stored in Redis (for multi-instance awareness)
- All instances listen to same pub/sub channel
- Only send to clients connected to THIS instance
"""

import os
import json
import time
import uuid
import asyncio
import logging
from collections import defaultdict

from fastapi import Security, APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.dependencies import require_read_access
from app.services.redis_service import get_redis_service
from app.services.subscription_registry import (
    SubscriptionRegistry,
    get_subscription_registry,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Unique instance ID for this API process
INSTANCE_ID = os.environ.get("SQUIRREL_INSTANCE_ID", str(uuid.uuid4())[:8])

router = APIRouter(prefix="/ws", tags=["WebSocket"])


class DiffStreamManager:
    """
    Manages WebSocket connections and streams only changed PV values.

    Instead of sending all 40k values every time, we:
    1. Track subscriptions per client (in-memory + optional Redis registry)
    2. Listen to Redis pub/sub for PV updates
    3. Batch updates over a short window (configurable, default 100ms)
    4. Send only the changed PVs to subscribed clients

    Multi-instance support:
    - When multi_instance=True, subscriptions are also stored in Redis
    - This allows multiple API instances to share subscription awareness
    - Each instance still manages its own local connections

    This reduces bandwidth from ~5-10MB/sec to only the actual changes.
    """

    def __init__(self, instance_id: str | None = None, multi_instance: bool = False):
        self._instance_id = instance_id or INSTANCE_ID
        self._multi_instance = multi_instance

        self._connections: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[str]] = defaultdict(set)  # client_id -> pv_names
        self._pv_to_clients: dict[str, set[str]] = defaultdict(set)  # pv_name -> client_ids

        # Subscription registry for multi-instance support
        self._registry: SubscriptionRegistry | None = None

        # Update buffer for batching
        self._update_buffer: dict[str, dict] = {}  # pv_name -> latest value dict
        self._buffer_lock = asyncio.Lock()

        # Background tasks
        self._flush_task: asyncio.Task | None = None
        self._pubsub_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False

        # Configuration
        self._batch_interval_ms = settings.websocket_batch_interval_ms

    async def start(self) -> None:
        """Start the diff stream manager background tasks."""
        if self._running:
            return

        self._running = True

        # Initialize subscription registry for multi-instance mode
        if self._multi_instance:
            try:
                redis = get_redis_service()
                if redis.is_connected():
                    self._registry = get_subscription_registry(self._instance_id)
                    await self._registry.connect(redis._redis)
                    await self._registry.start()
                    logger.info(f"Subscription registry enabled (instance: {self._instance_id})")
            except Exception as e:
                logger.warning(f"Failed to initialize subscription registry: {e}")

        # Start the buffer flush task (sends batched updates)
        self._flush_task = asyncio.create_task(self._flush_loop())

        # Start listening to Redis pub/sub
        self._pubsub_task = asyncio.create_task(self._pubsub_listener())

        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info(
            f"DiffStreamManager started (instance: {self._instance_id}, batch interval: {self._batch_interval_ms}ms)"
        )

    async def stop(self) -> None:
        """Stop the manager and cleanup."""
        self._running = False

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Close all connections
        for client_id in list(self._connections.keys()):
            await self.disconnect(client_id)

        # Stop subscription registry
        if self._registry:
            await self._registry.stop()

        logger.info(f"DiffStreamManager stopped (instance: {self._instance_id})")

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """Register a new WebSocket connection."""
        await websocket.accept()
        self._connections[client_id] = websocket
        self._subscriptions[client_id] = set()

        # Register in Redis for multi-instance awareness
        if self._registry:
            await self._registry.register_client(client_id)

        logger.info(
            f"WebSocket client {client_id} connected (instance: {self._instance_id}, total: {len(self._connections)})"
        )

    async def disconnect(self, client_id: str) -> None:
        """Remove a WebSocket connection and clean up subscriptions."""
        if client_id in self._connections:
            try:
                await self._connections[client_id].close()
            except Exception:
                pass
            del self._connections[client_id]

        # Clean up local subscriptions
        pv_names = self._subscriptions.pop(client_id, set())
        for pv_name in pv_names:
            self._pv_to_clients[pv_name].discard(client_id)
            # Clean up empty sets
            if pv_name in self._pv_to_clients and not self._pv_to_clients[pv_name]:
                del self._pv_to_clients[pv_name]

        # Unregister from Redis
        if self._registry:
            await self._registry.unregister_client(client_id)

        logger.info(f"WebSocket client {client_id} disconnected (remaining: {len(self._connections)})")

    async def subscribe(self, client_id: str, pv_names: list[str]) -> None:
        """
        Subscribe a client to specific PVs.

        Sends initial values immediately after subscribing.
        """
        if client_id not in self._connections:
            return

        # Update local subscription tracking
        self._subscriptions[client_id].update(pv_names)
        for pv_name in pv_names:
            self._pv_to_clients[pv_name].add(client_id)

        # Update Redis registry for multi-instance awareness
        if self._registry:
            await self._registry.subscribe(client_id, pv_names)

        logger.debug(f"Client {client_id} subscribed to {len(pv_names)} PVs")

        # Send initial values for subscribed PVs
        try:
            redis = get_redis_service()
            cached_values = await redis.get_pv_values_bulk(pv_names)

            initial_data = {}
            for pv_name in pv_names:
                cached = cached_values.get(pv_name)
                if cached:
                    initial_data[pv_name] = cached.to_dict()

            if initial_data:
                await self._send_to_client(
                    client_id,
                    {
                        "type": "initial",
                        "data": initial_data,
                        "count": len(initial_data),
                    },
                )

        except Exception as e:
            logger.error(f"Error sending initial values to {client_id}: {e}")

    async def unsubscribe(self, client_id: str, pv_names: list[str]) -> None:
        """Unsubscribe a client from specific PVs."""
        if client_id not in self._subscriptions:
            return

        # Update local tracking
        for pv_name in pv_names:
            self._subscriptions[client_id].discard(pv_name)
            self._pv_to_clients[pv_name].discard(client_id)
            if pv_name in self._pv_to_clients and not self._pv_to_clients[pv_name]:
                del self._pv_to_clients[pv_name]

        # Update Redis registry
        if self._registry:
            await self._registry.unsubscribe(client_id, pv_names)

        logger.debug(f"Client {client_id} unsubscribed from {len(pv_names)} PVs")

    async def _pubsub_listener(self) -> None:
        """Listen for PV updates from Redis pub/sub and buffer them."""
        while self._running:
            try:
                redis = get_redis_service()

                # Create a new pubsub instance
                pubsub = redis._redis.pubsub()
                await pubsub.subscribe(settings.redis_pv_updates_channel)

                logger.info(f"WebSocket pubsub listener started on channel: {settings.redis_pv_updates_channel}")

                async for message in pubsub.listen():
                    if not self._running:
                        break

                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            pv_name = data.get("pv_name")
                            value = data.get("value", {})

                            if pv_name:
                                await self._buffer_update(pv_name, value)

                        except Exception as e:
                            logger.error(f"Error processing pubsub message: {e}")

                await pubsub.close()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Pubsub listener error: {e}")
                # Try to reconnect after a delay
                if self._running:
                    await asyncio.sleep(5)

    async def _buffer_update(self, pv_name: str, value: dict) -> None:
        """Buffer a PV update for batched sending."""
        # Only buffer if someone is subscribed to this PV
        if pv_name not in self._pv_to_clients:
            return

        async with self._buffer_lock:
            self._update_buffer[pv_name] = value

    async def _flush_loop(self) -> None:
        """Periodically flush buffered updates to clients."""
        interval_seconds = self._batch_interval_ms / 1000.0

        while self._running:
            try:
                await asyncio.sleep(interval_seconds)

                async with self._buffer_lock:
                    if not self._update_buffer:
                        continue

                    updates = self._update_buffer.copy()
                    self._update_buffer.clear()

                # Group updates by client
                client_updates: dict[str, dict[str, dict]] = defaultdict(dict)

                for pv_name, value in updates.items():
                    for client_id in self._pv_to_clients.get(pv_name, set()):
                        client_updates[client_id][pv_name] = value

                # Send to each client
                for client_id, pv_updates in client_updates.items():
                    if client_id in self._connections:
                        await self._send_to_client(
                            client_id,
                            {
                                "type": "diff",
                                "data": pv_updates,
                                "count": len(pv_updates),
                                "timestamp": time.time(),
                            },
                        )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Flush loop error: {e}")

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat messages to all clients."""
        while self._running:
            try:
                await asyncio.sleep(5)  # Send heartbeat every 5 seconds

                # Get current heartbeat from Redis
                try:
                    redis = get_redis_service()
                    heartbeat = await redis.get_heartbeat()
                    monitor_alive = await redis.is_monitor_alive()
                except Exception:
                    heartbeat = None
                    monitor_alive = False

                message = {
                    "type": "heartbeat",
                    "timestamp": time.time(),
                    "monitor_heartbeat": heartbeat,
                    "monitor_alive": monitor_alive,
                }

                # Send to all connected clients
                for client_id in list(self._connections.keys()):
                    await self._send_to_client(client_id, message)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")

    async def _send_to_client(self, client_id: str, message: dict) -> None:
        """Send a message to a specific client."""
        websocket = self._connections.get(client_id)
        if not websocket:
            return

        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.debug(f"Failed to send to client {client_id}: {e}")
            await self.disconnect(client_id)

    def get_connection_count(self) -> int:
        """Get the number of active connections."""
        return len(self._connections)

    def get_subscription_stats(self) -> dict:
        """Get subscription statistics."""
        total_subscriptions = sum(len(pvs) for pvs in self._subscriptions.values())
        unique_pvs = len(self._pv_to_clients)

        return {
            "instance_id": self._instance_id,
            "multi_instance_enabled": self._registry is not None,
            "active_connections": len(self._connections),
            "total_subscriptions": total_subscriptions,
            "unique_pvs_subscribed": unique_pvs,
            "buffer_size": len(self._update_buffer),
        }


# Global manager instance
_manager: DiffStreamManager | None = None


def get_diff_manager(multi_instance: bool = False) -> DiffStreamManager:
    """
    Get or create the diff stream manager singleton.

    Args:
        multi_instance: Enable Redis-based subscription registry for
                       running multiple API instances behind a load balancer
    """
    global _manager
    if _manager is None:
        _manager = DiffStreamManager(instance_id=INSTANCE_ID, multi_instance=multi_instance)
    return _manager


def get_connection_manager() -> DiffStreamManager:
    """Get the connection manager (returns diff manager for compatibility)."""
    return get_diff_manager()


# ============================================================
# WebSocket Endpoints
# ============================================================


@router.websocket("/ws/pvs")
async def websocket_pvs(websocket: WebSocket):
    """
    WebSocket endpoint for real-time PV updates with diff streaming.

    Protocol:
    - Client sends: {"type": "subscribe", "pvNames": ["PV1", "PV2"]}
    - Client sends: {"type": "unsubscribe", "pvNames": ["PV1"]}
    - Client sends: {"type": "get_all"}
    - Client sends: {"type": "ping"}

    Server sends:
    - Initial values: {"type": "initial", "data": {"PV1": {...}}, "count": N}
    - Diff updates: {"type": "diff", "data": {"PV1": {...}}, "count": N, "timestamp": T}
    - Heartbeat: {"type": "heartbeat", "timestamp": T, "monitor_alive": bool}
    - All values: {"type": "all_values", "values": {...}, "count": N}
    - Pong: {"type": "pong"}
    - Error: {"type": "error", "message": "..."}
    """
    diff_manager = get_diff_manager()
    client_id = str(uuid.uuid4())

    await diff_manager.connect(websocket, client_id)

    try:
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "subscribe":
                pv_names = data.get("pvNames", [])
                await diff_manager.subscribe(client_id, pv_names)

            elif message_type == "unsubscribe":
                pv_names = data.get("pvNames", [])
                await diff_manager.unsubscribe(client_id, pv_names)

            elif message_type == "get_all":
                # Send all cached values (legacy support)
                try:
                    redis = get_redis_service()
                    all_values = await redis.get_all_pv_values_as_dict()
                    await websocket.send_json(
                        {
                            "type": "all_values",
                            "values": all_values,
                            "count": len(all_values),
                        }
                    )
                except Exception as e:
                    logger.error(f"Error getting all values: {e}")
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": str(e),
                        }
                    )

            elif message_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})

    except WebSocketDisconnect:
        await diff_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
        await diff_manager.disconnect(client_id)


@router.websocket("/ws/live")
async def websocket_live_stream(websocket: WebSocket):
    """
    Alternative WebSocket endpoint (alias for /ws/pvs).

    Provided for frontend compatibility with the hardening plan naming.
    """
    await websocket_pvs(websocket)


@router.get("/status", dependencies=[Security(require_read_access)])
async def websocket_status() -> dict:
    """Get WebSocket connection and subscription status."""
    diff_manager = get_diff_manager()
    stats = diff_manager.get_subscription_stats()

    return {
        "instanceId": stats.get("instance_id"),
        "multiInstanceEnabled": stats.get("multi_instance_enabled", False),
        "activeConnections": stats["active_connections"],
        "totalSubscriptions": stats["total_subscriptions"],
        "uniquePVsSubscribed": stats["unique_pvs_subscribed"],
        "bufferSize": stats["buffer_size"],
        "batchIntervalMs": settings.websocket_batch_interval_ms,
    }
