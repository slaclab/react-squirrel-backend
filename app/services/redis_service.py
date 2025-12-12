import json
import logging
from typing import Any, Callable

import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RedisService:
    """Manages Redis connection and PV value cache."""

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._hash_key = settings.redis_pv_hash_key
        self._metadata_key = settings.redis_pv_metadata_key
        self._updates_channel = settings.redis_pv_updates_channel
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
        logger.info("Disconnected from Redis")

    async def set_pv_value(self, pv_name: str, value: dict) -> None:
        """Set a single PV value in the cache."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        # Store in hash for O(1) lookup
        await self._redis.hset(self._hash_key, pv_name, json.dumps(value))

    async def set_pv_values_bulk(self, values: dict[str, dict]) -> None:
        """Set multiple PV values in the cache (atomic)."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        if not values:
            return

        # Convert values to JSON strings
        mapping = {pv_name: json.dumps(v) for pv_name, v in values.items()}

        # Use pipeline for atomic bulk insert
        async with self._redis.pipeline() as pipe:
            await pipe.hset(self._hash_key, mapping=mapping)
            await pipe.execute()

        logger.debug(f"Cached {len(values)} PV values in Redis")

    async def get_pv_value(self, pv_name: str) -> dict | None:
        """Get a single PV value from the cache."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        value = await self._redis.hget(self._hash_key, pv_name)
        if value:
            return json.loads(value)
        return None

    async def get_pv_values_bulk(self, pv_names: list[str]) -> dict[str, dict]:
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
                result[pv_name] = json.loads(value)

        return result

    async def get_all_pv_values(self) -> dict[str, dict]:
        """Get all cached PV values."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        # HGETALL returns all fields and values
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

    async def clear_all_pv_values(self) -> None:
        """Clear all cached PV values."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        await self._redis.delete(self._hash_key)
        logger.info("Cleared all PV values from Redis cache")

    async def get_cached_pv_count(self) -> int:
        """Get the number of cached PV values."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        return await self._redis.hlen(self._hash_key)

    async def publish_pv_update(self, pv_name: str, value: dict) -> None:
        """Publish a PV value update to the pub/sub channel."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        message = json.dumps({"pv_name": pv_name, "value": value})
        await self._redis.publish(self._updates_channel, message)

    async def publish_pv_updates_bulk(self, values: dict[str, dict]) -> None:
        """Publish multiple PV value updates."""
        if not self._redis:
            raise RuntimeError("Redis not connected")

        # Use pipeline for efficient bulk publish
        async with self._redis.pipeline() as pipe:
            for pv_name, value in values.items():
                message = json.dumps({"pv_name": pv_name, "value": value})
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


# Singleton instance
_redis_service: RedisService | None = None


def get_redis_service() -> RedisService:
    """Get or create the Redis service singleton."""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
