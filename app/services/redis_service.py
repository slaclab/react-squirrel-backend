import json
import logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Callable

import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class PVCacheEntry:
    """
    Complete PV state stored in Redis.

    Includes connection tracking and timestamps for health monitoring.
    """
    value: Any
    connected: bool
    updated_at: float  # Unix timestamp when we last updated this entry
    status: str | None = None
    severity: int | None = None
    timestamp: float | None = None  # EPICS timestamp
    units: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "PVCacheEntry":
        """Create from dictionary."""
        return cls(
            value=data.get("value"),
            connected=data.get("connected", False),
            updated_at=data.get("updated_at", 0),
            status=data.get("status"),
            severity=data.get("severity"),
            timestamp=data.get("timestamp"),
            units=data.get("units"),
            error=data.get("error"),
        )


class RedisService:
    """
    Manages Redis connection and PV value cache with connection tracking.

    Enhanced for 40k PV monitoring with:
    - Per-PV connection state tracking (connected/disconnected)
    - Heartbeat mechanism for system health monitoring
    - Disconnected PV set for quick lookup
    - Timestamps for stale data detection
    """

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._hash_key = settings.redis_pv_hash_key
        self._metadata_key = settings.redis_pv_metadata_key
        self._updates_channel = settings.redis_pv_updates_channel
        self._heartbeat_key = settings.redis_heartbeat_key
        self._disconnected_set_key = settings.redis_disconnected_set_key
        self._ttl = settings.redis_pv_cache_ttl

    async def connect(self) -> None:
        """Establish Redis connection."""
        self._redis = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        # Test connection
        await self._redis.ping()
        logger.info(f"Connected to Redis at {settings.redis_url}")

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("Disconnected from Redis")

    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        return self._redis is not None

    # ============================================================
    # PV Value Operations (Enhanced with connection tracking)
    # ============================================================

    async def set_pv_value(
        self,
        pv_name: str,
        value: Any,
        connected: bool = True,
        status: str | None = None,
        severity: int | None = None,
        timestamp: float | None = None,
        units: str | None = None,
        error: str | None = None,
    ) -> None:
        """
        Set a single PV value in the cache with full metadata.

        Args:
            pv_name: The PV name/address
            value: The PV value (can be scalar or array)
            connected: Whether the PV is currently connected
            status: EPICS alarm status string
            severity: EPICS alarm severity (0-3)
            timestamp: EPICS timestamp
            units: Engineering units
            error: Error message if disconnected
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        entry = PVCacheEntry(
            value=value,
            connected=connected,
            updated_at=time.time(),
            status=status,
            severity=severity,
            timestamp=timestamp,
            units=units,
            error=error,
        )

        # Store in hash for O(1) lookup
        await self._redis.hset(self._hash_key, pv_name, json.dumps(entry.to_dict()))

        # Track disconnected PVs in a separate set for quick lookup
        if connected:
            await self._redis.srem(self._disconnected_set_key, pv_name)
        else:
            await self._redis.sadd(self._disconnected_set_key, pv_name)

    async def set_pv_connected(self, pv_name: str, connected: bool, error: str | None = None) -> None:
        """
        Update only the connection state of a PV.

        Called from connection callbacks when PV connects/disconnects.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        # Get existing entry or create minimal one
        existing = await self.get_pv_value(pv_name)

        if existing:
            existing.connected = connected
            existing.updated_at = time.time()
            if error:
                existing.error = error
            elif connected:
                existing.error = None
            await self._redis.hset(self._hash_key, pv_name, json.dumps(existing.to_dict()))
        else:
            # PV not in cache yet - create minimal entry
            entry = PVCacheEntry(
                value=None,
                connected=connected,
                updated_at=time.time(),
                error=error,
            )
            await self._redis.hset(self._hash_key, pv_name, json.dumps(entry.to_dict()))

        # Update disconnected set
        if connected:
            await self._redis.srem(self._disconnected_set_key, pv_name)
        else:
            await self._redis.sadd(self._disconnected_set_key, pv_name)

    async def set_pv_values_bulk(self, values: dict[str, PVCacheEntry | dict]) -> None:
        """
        Set multiple PV values in the cache (atomic).

        Args:
            values: Dict of pv_name -> PVCacheEntry or dict
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        if not values:
            return

        # Convert to JSON strings and track connection states
        mapping = {}
        connected_pvs = []
        disconnected_pvs = []

        for pv_name, v in values.items():
            if isinstance(v, PVCacheEntry):
                entry_dict = v.to_dict()
                is_connected = v.connected
            else:
                # Legacy dict format - add updated_at if missing
                entry_dict = v.copy()
                if "updated_at" not in entry_dict:
                    entry_dict["updated_at"] = time.time()
                is_connected = entry_dict.get("connected", True)

            mapping[pv_name] = json.dumps(entry_dict)

            if is_connected:
                connected_pvs.append(pv_name)
            else:
                disconnected_pvs.append(pv_name)

        # Use pipeline for atomic bulk operations
        async with self._redis.pipeline() as pipe:
            await pipe.hset(self._hash_key, mapping=mapping)

            # Update disconnected set
            if connected_pvs:
                await pipe.srem(self._disconnected_set_key, *connected_pvs)
            if disconnected_pvs:
                await pipe.sadd(self._disconnected_set_key, *disconnected_pvs)

            await pipe.execute()

        logger.debug(f"Cached {len(values)} PV values in Redis")

    async def get_pv_value(self, pv_name: str) -> PVCacheEntry | None:
        """Get a single PV value from the cache."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        value = await self._redis.hget(self._hash_key, pv_name)
        if value:
            return PVCacheEntry.from_dict(json.loads(value))
        return None

    async def get_pv_values_bulk(self, pv_names: list[str]) -> dict[str, PVCacheEntry]:
        """Get multiple PV values from the cache."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        if not pv_names:
            return {}

        # Use HMGET for efficient bulk retrieval
        values = await self._redis.hmget(self._hash_key, pv_names)

        result = {}
        for pv_name, value in zip(pv_names, values):
            if value:
                result[pv_name] = PVCacheEntry.from_dict(json.loads(value))

        return result

    async def get_all_pv_values(self) -> dict[str, PVCacheEntry]:
        """Get all cached PV values."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        # HGETALL returns all fields and values
        raw_values = await self._redis.hgetall(self._hash_key)

        result = {}
        for pv_name, value in raw_values.items():
            result[pv_name] = PVCacheEntry.from_dict(json.loads(value))

        return result

    async def get_all_pv_values_as_dict(self) -> dict[str, dict]:
        """Get all cached PV values as plain dicts (for JSON serialization)."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        raw_values = await self._redis.hgetall(self._hash_key)

        result = {}
        for pv_name, value in raw_values.items():
            result[pv_name] = json.loads(value)

        return result

    async def delete_pv_value(self, pv_name: str) -> None:
        """Delete a single PV value from the cache."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        await self._redis.hdel(self._hash_key, pv_name)
        await self._redis.srem(self._disconnected_set_key, pv_name)

    async def clear_all_pv_values(self) -> None:
        """Clear all cached PV values."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        await self._redis.delete(self._hash_key)
        await self._redis.delete(self._disconnected_set_key)
        logger.info("Cleared all PV values from Redis cache")

    async def get_cached_pv_count(self) -> int:
        """Get the number of cached PV values."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        return await self._redis.hlen(self._hash_key)

    # ============================================================
    # Connection State Tracking
    # ============================================================

    async def get_disconnected_pvs(self) -> set[str]:
        """Get all PVs currently marked as disconnected."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        return await self._redis.smembers(self._disconnected_set_key)

    async def get_disconnected_count(self) -> int:
        """Get count of disconnected PVs."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        return await self._redis.scard(self._disconnected_set_key)

    async def get_stale_pvs(self, max_age_seconds: float | None = None) -> list[str]:
        """
        Get PVs that haven't been updated recently (potential staleness).

        Args:
            max_age_seconds: Maximum age in seconds. Defaults to config value.

        Returns:
            List of PV names that are stale
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        if max_age_seconds is None:
            max_age_seconds = settings.watchdog_stale_threshold

        stale = []
        cutoff = time.time() - max_age_seconds

        # Get all PV values and check timestamps
        raw_values = await self._redis.hgetall(self._hash_key)

        for pv_name, value_json in raw_values.items():
            try:
                data = json.loads(value_json)
                updated_at = data.get("updated_at", 0)
                connected = data.get("connected", True)

                # Only check stale if connected (disconnected handled separately)
                if connected and updated_at < cutoff:
                    stale.append(pv_name)
            except Exception:
                # Invalid data - consider stale
                stale.append(pv_name)

        return stale

    # ============================================================
    # System Heartbeat
    # ============================================================

    async def update_heartbeat(self) -> None:
        """Update the monitor heartbeat timestamp."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        await self._redis.set(self._heartbeat_key, str(time.time()))

    async def get_heartbeat(self) -> float | None:
        """Get the last heartbeat timestamp."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        value = await self._redis.get(self._heartbeat_key)
        return float(value) if value else None

    async def get_heartbeat_age(self) -> float | None:
        """Get the age of the last heartbeat in seconds."""
        heartbeat = await self.get_heartbeat()
        if heartbeat is None:
            return None
        return time.time() - heartbeat

    async def is_monitor_alive(self, max_age_seconds: float = 5.0) -> bool:
        """Check if the monitor process is still alive."""
        heartbeat = await self.get_heartbeat()
        if heartbeat is None:
            return False
        return (time.time() - heartbeat) < max_age_seconds

    # ============================================================
    # Pub/Sub for Real-time Updates
    # ============================================================

    async def publish_pv_update(self, pv_name: str, value: dict | None = None) -> None:
        """
        Publish a PV value update to the pub/sub channel.

        If value is None, the current cached value will be fetched.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        if value is None:
            cached = await self.get_pv_value(pv_name)
            value = cached.to_dict() if cached else {}

        message = json.dumps({"pv_name": pv_name, "value": value})
        await self._redis.publish(self._updates_channel, message)

    async def publish_pv_updates_bulk(self, pv_names: list[str]) -> None:
        """
        Publish multiple PV value updates.

        Fetches current values from cache and publishes them.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        if not pv_names:
            return

        # Get current values
        values = await self.get_pv_values_bulk(pv_names)

        # Use pipeline for efficient bulk publish
        async with self._redis.pipeline() as pipe:
            for pv_name in pv_names:
                value = values.get(pv_name)
                value_dict = value.to_dict() if value else {}
                message = json.dumps({"pv_name": pv_name, "value": value_dict})
                await pipe.publish(self._updates_channel, message)
            await pipe.execute()

    async def subscribe_pv_updates(self, callback: Callable[[str, dict], Any]) -> None:
        """Subscribe to PV value updates."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self._updates_channel)

        logger.info(f"Subscribed to PV updates channel: {self._updates_channel}")

        async for message in self._pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await callback(data["pv_name"], data["value"])
                except Exception as e:
                    logger.error(f"Error processing PV update: {e}")

    # ============================================================
    # Health Statistics
    # ============================================================

    async def get_health_stats(self) -> dict:
        """Get comprehensive health statistics."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        total_pvs = await self.get_cached_pv_count()
        disconnected_count = await self.get_disconnected_count()
        heartbeat = await self.get_heartbeat()
        heartbeat_age = await self.get_heartbeat_age()

        return {
            "total_cached_pvs": total_pvs,
            "disconnected_pvs": disconnected_count,
            "connected_pvs": total_pvs - disconnected_count,
            "last_heartbeat": heartbeat,
            "heartbeat_age_seconds": heartbeat_age,
            "monitor_alive": heartbeat_age is not None and heartbeat_age < 5.0,
        }

    # ============================================================
    # Monitor Leader Election
    # ============================================================

    MONITOR_LOCK_KEY = "squirrel:monitor:lock"
    MONITOR_LOCK_TTL = 30  # seconds

    async def acquire_monitor_lock(self, instance_id: str) -> bool:
        """
        Acquire exclusive lock for monitor process (leader election).

        Only one monitor instance should run at a time. This uses Redis
        SET with NX (only set if not exists) for atomic leader election.

        Args:
            instance_id: Unique identifier for this monitor instance

        Returns:
            True if lock acquired, False if another instance holds it
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        result = await self._redis.set(
            self.MONITOR_LOCK_KEY,
            instance_id,
            nx=True,  # Only set if not exists
            ex=self.MONITOR_LOCK_TTL  # Expire after TTL
        )
        return result is True

    async def renew_monitor_lock(self, instance_id: str) -> bool:
        """
        Renew lock if we still own it.

        Must be called periodically (< MONITOR_LOCK_TTL) to maintain leadership.

        Args:
            instance_id: Our instance ID to verify ownership

        Returns:
            True if renewed successfully, False if we lost leadership
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        current = await self._redis.get(self.MONITOR_LOCK_KEY)
        if current == instance_id:
            await self._redis.expire(self.MONITOR_LOCK_KEY, self.MONITOR_LOCK_TTL)
            return True
        return False

    async def release_monitor_lock(self, instance_id: str) -> bool:
        """
        Release the monitor lock if we own it.

        Args:
            instance_id: Our instance ID to verify ownership

        Returns:
            True if released, False if we didn't own it
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        current = await self._redis.get(self.MONITOR_LOCK_KEY)
        if current == instance_id:
            await self._redis.delete(self.MONITOR_LOCK_KEY)
            return True
        return False

    async def get_monitor_lock_holder(self) -> str | None:
        """
        Get the current monitor lock holder instance ID.

        Returns:
            Instance ID of current leader, or None if no leader
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")

        return await self._redis.get(self.MONITOR_LOCK_KEY)

    async def get_monitor_heartbeat(self) -> float | None:
        """
        Get the last monitor heartbeat timestamp.

        Alias for get_heartbeat() for clearer API.
        """
        return await self.get_heartbeat()


# Singleton instance
_redis_service: RedisService | None = None


def get_redis_service() -> RedisService:
    """Get or create the Redis service singleton."""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
