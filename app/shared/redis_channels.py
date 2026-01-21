"""
Redis keys and channels shared between API and Monitor processes.

Centralizes all Redis key definitions to ensure consistency across processes.
"""


class RedisChannels:
    """
    Redis key and channel definitions for the Squirrel backend.

    Used by both API (squirrel-api) and Monitor (squirrel-monitor) processes.
    """

    # PV Value Storage
    PV_HASH_KEY = "squirrel:pv:values"
    PV_METADATA_KEY = "squirrel:pv:metadata"
    PV_DISCONNECTED_SET = "squirrel:pv:disconnected"

    # Pub/Sub Channels
    PV_UPDATES_CHANNEL = "squirrel:pv:updates"

    # Monitor Health
    MONITOR_HEARTBEAT_KEY = "squirrel:monitor:heartbeat"
    MONITOR_LOCK_KEY = "squirrel:monitor:lock"
    MONITOR_LOCK_TTL = 30  # seconds

    # WebSocket (for multi-instance support)
    WS_CLIENTS_PREFIX = "squirrel:ws:clients:"          # {instance_id} -> Set of client_ids
    WS_SUBSCRIPTIONS_PREFIX = "squirrel:ws:subscriptions:"  # {client_id} -> Set of PV names
    WS_PV_SUBSCRIBERS_PREFIX = "squirrel:ws:pv_subscribers:"  # {pv_name} -> Set of client_ids
    WS_INSTANCE_HEARTBEAT_PREFIX = "squirrel:ws:instance_heartbeat:"  # {instance_id} -> timestamp
    WS_CLIENT_INSTANCE_PREFIX = "squirrel:ws:client_instance:"  # {client_id} -> instance_id

    # Task Queue (for Arq)
    TASK_QUEUE_KEY = "squirrel:tasks"
