from pydantic_settings import BaseSettings
from functools import lru_cache


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

    # Redis configuration
    redis_url: str = "redis://localhost:6379/0"
    redis_pv_cache_ttl: int = 60  # seconds
    redis_pv_hash_key: str = "squirrel:pv:values"
    redis_pv_metadata_key: str = "squirrel:pv:metadata"
    redis_pv_updates_channel: str = "squirrel:pv:updates"

    # Performance
    bulk_insert_batch_size: int = 5000

    class Config:
        env_file = ".env"
        env_prefix = "SQUIRREL_"
        extra = "ignore"  # Ignore deprecated env vars from old config


@lru_cache
def get_settings() -> Settings:
    return Settings()
