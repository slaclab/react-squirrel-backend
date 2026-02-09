from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_name: str = "squirrel"
    debug: bool = False
    api_v1_prefix: str = "/v1"

    # Database - increased pool for concurrent polling during snapshot operations
    database_url: str = "postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel"
    database_pool_size: int = 30
    database_max_overflow: int = 20

    # EPICS configuration (simplified for aioca)
    epics_ca_addr_list: str = ""
    epics_ca_auto_addr_list: str = "YES"
    epics_ca_server_port: str = "5068"
    epics_ca_repeater_port: str = "5069"
    epics_ca_conn_timeout: float = 5.0  # Connection timeout
    epics_ca_timeout: float = 10.0  # Read timeout (includes connection time for batch reads)
    epics_chunk_size: int = 1000  # Batch size for progress updates (smaller for better connection handling)

    # EPICS PVAccess configuration (p4p)
    epics_pva_addr_list: str = ""
    epics_pva_auto_addr_list: str = "YES"
    epics_pva_server_port: str = ""
    epics_pva_broadcast_port: str = ""
    epics_pva_timeout: float = 10.0  # Read timeout for PVAccess

    # Redis configuration
    redis_username: str = ""
    redis_password: str = "squirrel"
    redis_url: str = f"redis://{redis_username}:{redis_password}@localhost:6379/0"
    redis_pv_cache_ttl: int = 60  # seconds
    redis_pv_hash_key: str = "squirrel:pv:values"
    redis_pv_metadata_key: str = "squirrel:pv:metadata"
    redis_pv_updates_channel: str = "squirrel:pv:updates"
    redis_heartbeat_key: str = "squirrel:monitor:heartbeat"
    redis_disconnected_set_key: str = "squirrel:pv:disconnected"

    # PV Monitor - Batched startup to prevent UDP flood
    pv_monitor_batch_size: int = 500  # PVs per batch during startup
    pv_monitor_batch_delay_ms: int = 100  # Delay between batches (ms)
    pv_monitor_heartbeat_interval: float = 1.0  # Heartbeat update interval (seconds)

    # Watchdog - Health monitoring
    watchdog_enabled: bool = True
    watchdog_check_interval: float = 60.0  # How often to run health checks (seconds)
    watchdog_stale_threshold: float = 300.0  # PV considered stale if no update in X seconds
    watchdog_reconnect_timeout: float = 2.0  # Timeout for reconnection attempts

    # WebSocket - Diff streaming
    websocket_batch_interval_ms: int = 100  # Buffer updates for X ms before sending

    # Performance
    bulk_insert_batch_size: int = 5000

    class Config:
        env_file = ".env"
        env_prefix = "SQUIRREL_"
        extra = "ignore"  # Ignore deprecated env vars from old config


@lru_cache
def get_settings() -> Settings:
    return Settings()
