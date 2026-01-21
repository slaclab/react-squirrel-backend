"""
Redis-based WebSocket subscription registry for multi-instance support.

This enables running multiple API instances behind a load balancer while
maintaining consistent WebSocket subscriptions across all instances.

Architecture:
- Each API instance has a unique instance_id
- Client subscriptions are stored in Redis
- When a PV update comes in, any instance can look up which clients need it
- Instance heartbeats track which instances are alive
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Set

import redis.asyncio as redis

from app.config import get_settings
from app.shared.redis_channels import RedisChannels

logger = logging.getLogger(__name__)
settings = get_settings()


class SubscriptionRegistry:
    """
    Redis-based subscription registry for multi-instance WebSocket support.

    Data structures in Redis:
    - squirrel:ws:clients:{instance_id} -> Set of client_ids on this instance
    - squirrel:ws:subscriptions:{client_id} -> Set of PV names subscribed
    - squirrel:ws:pv_subscribers:{pv_name} -> Set of client_ids subscribed to this PV
    - squirrel:ws:client_instance:{client_id} -> instance_id owning this client
    - squirrel:ws:instance_heartbeat:{instance_id} -> last heartbeat timestamp
    """

    def __init__(self, instance_id: str | None = None):
        self.instance_id = instance_id or str(uuid.uuid4())[:8]
        self._redis: redis.Redis | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False

    async def connect(self, redis_client: redis.Redis) -> None:
        """Initialize with a Redis client."""
        self._redis = redis_client
        logger.info(f"SubscriptionRegistry initialized (instance: {self.instance_id})")

    async def start(self) -> None:
        """Start background tasks for heartbeat and cleanup."""
        if self._running:
            return

        self._running = True

        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start cleanup task (removes stale subscriptions from dead instances)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info(f"SubscriptionRegistry started (instance: {self.instance_id})")

    async def stop(self) -> None:
        """Stop background tasks and cleanup."""
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cleanup our subscriptions on shutdown
        await self._cleanup_instance_subscriptions()

        logger.info(f"SubscriptionRegistry stopped (instance: {self.instance_id})")

    async def register_client(self, client_id: str) -> None:
        """Register a new client connection on this instance."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        instance_clients_key = f"{RedisChannels.WS_CLIENTS_PREFIX}{self.instance_id}"
        client_instance_key = f"{RedisChannels.WS_CLIENT_INSTANCE_PREFIX}{client_id}"

        async with self._redis.pipeline() as pipe:
            await pipe.sadd(instance_clients_key, client_id)
            await pipe.set(client_instance_key, self.instance_id, ex=3600)  # 1 hour TTL
            await pipe.execute()

        logger.debug(f"Registered client {client_id} on instance {self.instance_id}")

    async def unregister_client(self, client_id: str) -> None:
        """Unregister a client connection."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        # Get all subscribed PVs for this client
        subscriptions_key = f"{RedisChannels.WS_SUBSCRIPTIONS_PREFIX}{client_id}"
        pv_names = await self._redis.smembers(subscriptions_key)

        async with self._redis.pipeline() as pipe:
            # Remove client from instance's client list
            instance_clients_key = f"{RedisChannels.WS_CLIENTS_PREFIX}{self.instance_id}"
            await pipe.srem(instance_clients_key, client_id)

            # Remove client->instance mapping
            client_instance_key = f"{RedisChannels.WS_CLIENT_INSTANCE_PREFIX}{client_id}"
            await pipe.delete(client_instance_key)

            # Remove client's subscription list
            await pipe.delete(subscriptions_key)

            # Remove client from all PV subscriber lists
            for pv_name in pv_names:
                pv_subscribers_key = f"{RedisChannels.WS_PV_SUBSCRIBERS_PREFIX}{pv_name}"
                await pipe.srem(pv_subscribers_key, client_id)

            await pipe.execute()

        logger.debug(f"Unregistered client {client_id}, removed {len(pv_names)} subscriptions")

    async def subscribe(self, client_id: str, pv_names: list[str]) -> None:
        """Subscribe a client to PVs."""
        if not self._redis or not pv_names:
            return

        subscriptions_key = f"{RedisChannels.WS_SUBSCRIPTIONS_PREFIX}{client_id}"

        async with self._redis.pipeline() as pipe:
            # Add PVs to client's subscription list
            await pipe.sadd(subscriptions_key, *pv_names)
            await pipe.expire(subscriptions_key, 3600)  # 1 hour TTL

            # Add client to each PV's subscriber list
            for pv_name in pv_names:
                pv_subscribers_key = f"{RedisChannels.WS_PV_SUBSCRIBERS_PREFIX}{pv_name}"
                await pipe.sadd(pv_subscribers_key, client_id)
                await pipe.expire(pv_subscribers_key, 3600)

            await pipe.execute()

        logger.debug(f"Client {client_id} subscribed to {len(pv_names)} PVs")

    async def unsubscribe(self, client_id: str, pv_names: list[str]) -> None:
        """Unsubscribe a client from PVs."""
        if not self._redis or not pv_names:
            return

        subscriptions_key = f"{RedisChannels.WS_SUBSCRIPTIONS_PREFIX}{client_id}"

        async with self._redis.pipeline() as pipe:
            # Remove PVs from client's subscription list
            await pipe.srem(subscriptions_key, *pv_names)

            # Remove client from each PV's subscriber list
            for pv_name in pv_names:
                pv_subscribers_key = f"{RedisChannels.WS_PV_SUBSCRIBERS_PREFIX}{pv_name}"
                await pipe.srem(pv_subscribers_key, client_id)

            await pipe.execute()

        logger.debug(f"Client {client_id} unsubscribed from {len(pv_names)} PVs")

    async def get_subscribers(self, pv_name: str) -> Set[str]:
        """Get all client IDs subscribed to a PV (across all instances)."""
        if not self._redis:
            return set()

        pv_subscribers_key = f"{RedisChannels.WS_PV_SUBSCRIBERS_PREFIX}{pv_name}"
        return await self._redis.smembers(pv_subscribers_key)

    async def get_local_subscribers(self, pv_name: str) -> Set[str]:
        """Get client IDs subscribed to a PV on THIS instance only."""
        if not self._redis:
            return set()

        # Get all subscribers for this PV
        all_subscribers = await self.get_subscribers(pv_name)

        # Filter to only clients on this instance
        instance_clients_key = f"{RedisChannels.WS_CLIENTS_PREFIX}{self.instance_id}"
        local_clients = await self._redis.smembers(instance_clients_key)

        return all_subscribers & local_clients

    async def get_client_subscriptions(self, client_id: str) -> Set[str]:
        """Get all PVs a client is subscribed to."""
        if not self._redis:
            return set()

        subscriptions_key = f"{RedisChannels.WS_SUBSCRIPTIONS_PREFIX}{client_id}"
        return await self._redis.smembers(subscriptions_key)

    async def get_stats(self) -> dict:
        """Get subscription statistics."""
        if not self._redis:
            return {}

        instance_clients_key = f"{RedisChannels.WS_CLIENTS_PREFIX}{self.instance_id}"
        local_clients = await self._redis.smembers(instance_clients_key)

        total_subscriptions = 0
        for client_id in local_clients:
            subscriptions_key = f"{RedisChannels.WS_SUBSCRIPTIONS_PREFIX}{client_id}"
            count = await self._redis.scard(subscriptions_key)
            total_subscriptions += count

        return {
            "instance_id": self.instance_id,
            "local_clients": len(local_clients),
            "total_subscriptions": total_subscriptions,
        }

    async def _heartbeat_loop(self) -> None:
        """Update heartbeat timestamp periodically."""
        heartbeat_key = f"{RedisChannels.WS_INSTANCE_HEARTBEAT_PREFIX}{self.instance_id}"

        while self._running:
            try:
                if self._redis:
                    await self._redis.set(heartbeat_key, str(time.time()), ex=60)
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)

    async def _cleanup_loop(self) -> None:
        """Periodically cleanup subscriptions from dead instances."""
        while self._running:
            try:
                await asyncio.sleep(60)  # Run every minute
                await self._cleanup_dead_instances()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def _cleanup_dead_instances(self) -> None:
        """Remove subscriptions from instances that haven't sent heartbeat."""
        if not self._redis:
            return

        # Find all instance heartbeat keys
        pattern = f"{RedisChannels.WS_INSTANCE_HEARTBEAT_PREFIX}*"
        cursor = 0
        dead_instances = []

        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                heartbeat = await self._redis.get(key)
                if heartbeat:
                    age = time.time() - float(heartbeat)
                    if age > 120:  # Dead if no heartbeat for 2 minutes
                        instance_id = key.replace(RedisChannels.WS_INSTANCE_HEARTBEAT_PREFIX, "")
                        dead_instances.append(instance_id)

            if cursor == 0:
                break

        # Cleanup dead instances
        for instance_id in dead_instances:
            logger.warning(f"Cleaning up subscriptions from dead instance: {instance_id}")
            await self._cleanup_instance_subscriptions(instance_id)

    async def _cleanup_instance_subscriptions(self, instance_id: str | None = None) -> None:
        """Remove all subscriptions for an instance."""
        if not self._redis:
            return

        target_instance = instance_id or self.instance_id
        instance_clients_key = f"{RedisChannels.WS_CLIENTS_PREFIX}{target_instance}"

        # Get all clients for this instance
        client_ids = await self._redis.smembers(instance_clients_key)

        for client_id in client_ids:
            # Get client's subscriptions
            subscriptions_key = f"{RedisChannels.WS_SUBSCRIPTIONS_PREFIX}{client_id}"
            pv_names = await self._redis.smembers(subscriptions_key)

            async with self._redis.pipeline() as pipe:
                # Remove client from PV subscriber lists
                for pv_name in pv_names:
                    pv_subscribers_key = f"{RedisChannels.WS_PV_SUBSCRIBERS_PREFIX}{pv_name}"
                    await pipe.srem(pv_subscribers_key, client_id)

                # Remove client's subscription list
                await pipe.delete(subscriptions_key)

                # Remove client->instance mapping
                client_instance_key = f"{RedisChannels.WS_CLIENT_INSTANCE_PREFIX}{client_id}"
                await pipe.delete(client_instance_key)

                await pipe.execute()

        # Remove instance's client list and heartbeat
        async with self._redis.pipeline() as pipe:
            await pipe.delete(instance_clients_key)
            await pipe.delete(f"{RedisChannels.WS_INSTANCE_HEARTBEAT_PREFIX}{target_instance}")
            await pipe.execute()

        logger.info(f"Cleaned up {len(client_ids)} clients from instance {target_instance}")


# Singleton instance
_registry: SubscriptionRegistry | None = None


def get_subscription_registry(instance_id: str | None = None) -> SubscriptionRegistry:
    """Get or create the subscription registry singleton."""
    global _registry
    if _registry is None:
        _registry = SubscriptionRegistry(instance_id)
    return _registry
