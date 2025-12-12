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

    # EPICS configuration
    epics_ca_addr_list: str = ""
    epics_ca_auto_addr_list: str = "YES"
    epics_ca_conn_timeout: float = 3.0  # Connection timeout (increased for better capture)
    epics_ca_timeout: float = 5.0  # Read timeout
    epics_max_workers: int = 8  # Workers for parallel operations
    epics_chunk_size: int = 100  # Chunk size for progress updates
    epics_use_threading: bool = True  # Use threading instead of multiprocessing
    epics_backend: str = "pyepics"  # "pyepics" or "p4p" - p4p may be faster for large batches

    # Performance
    bulk_insert_batch_size: int = 5000

    class Config:
        env_file = ".env"
        env_prefix = "SQUIRREL_"


@lru_cache
def get_settings() -> Settings:
    return Settings()
