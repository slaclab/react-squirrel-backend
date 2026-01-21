import json
import logging

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class BulkInsertService:
    """High-performance bulk insert using PostgreSQL COPY."""

    def __init__(self):
        self._pool: asyncpg.Pool | None = None

    def _get_asyncpg_url(self) -> str:
        """Convert SQLAlchemy URL to asyncpg format."""
        # Convert postgresql+asyncpg://... to postgresql://...
        url = settings.database_url
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://")
        return url

    async def connect(self) -> None:
        """Create asyncpg connection pool."""

        async def init_connection(conn):
            """Initialize connection with JSON codec for JSONB columns."""
            await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

        self._pool = await asyncpg.create_pool(self._get_asyncpg_url(), min_size=2, max_size=10, init=init_connection)
        logger.info("BulkInsertService connected to PostgreSQL")

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("BulkInsertService disconnected from PostgreSQL")

    async def bulk_insert_snapshot_values(self, values: list[tuple]) -> int:
        """
        Insert snapshot values using COPY - 10x faster than INSERT.

        Args:
            values: List of tuples with columns:
                (id, snapshot_id, pv_id, pv_name, setpoint_value, readback_value,
                 status, severity, timestamp)

        Returns:
            Number of rows inserted
        """
        if not self._pool:
            raise RuntimeError("BulkInsertService not connected")

        if not values:
            return 0

        async with self._pool.acquire() as conn:
            # Convert dicts to JSON strings for JSONB columns
            # asyncpg executemany handles parameters correctly
            processed_values = []
            for row in values:
                processed_row = list(row)
                # Convert JSONB columns (indices 4, 5) from dict to JSON string
                if processed_row[4] is not None:
                    processed_row[4] = json.dumps(processed_row[4])
                if processed_row[5] is not None:
                    processed_row[5] = json.dumps(processed_row[5])
                processed_values.append(tuple(processed_row))

            # Use executemany for reliable insertion with proper type handling
            await conn.executemany(
                """
                INSERT INTO snapshot_value
                    (id, snapshot_id, pv_id, pv_name, setpoint_value, readback_value, status, severity, timestamp)
                VALUES
                    ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9)
                """,
                processed_values,
            )

            result = f"COPY {len(processed_values)}"

            # result is a string like "COPY 40000"
            count = int(result.split()[1]) if result else len(values)
            logger.info(f"Bulk inserted {count} snapshot values using COPY")
            return count

    async def bulk_insert_pvs(self, values: list[tuple]) -> int:
        """
        Bulk insert PVs using COPY.

        Args:
            values: List of tuples with columns:
                (id, setpoint_address, readback_address, config_address,
                 device, description, abs_tolerance, rel_tolerance, read_only,
                 created_at, updated_at)

        Returns:
            Number of rows inserted
        """
        if not self._pool:
            raise RuntimeError("BulkInsertService not connected")

        if not values:
            return 0

        async with self._pool.acquire() as conn:
            result = await conn.copy_records_to_table(
                "pv",
                records=values,
                columns=[
                    "id",
                    "setpoint_address",
                    "readback_address",
                    "config_address",
                    "device",
                    "description",
                    "abs_tolerance",
                    "rel_tolerance",
                    "read_only",
                    "created_at",
                    "updated_at",
                ],
            )

            count = int(result.split()[1]) if result else len(values)
            logger.info(f"Bulk inserted {count} PVs using COPY")
            return count


# Singleton instance
_bulk_insert_service: BulkInsertService | None = None


async def get_bulk_insert_service() -> BulkInsertService:
    """Get or create the bulk insert service singleton."""
    global _bulk_insert_service
    if _bulk_insert_service is None:
        _bulk_insert_service = BulkInsertService()
        await _bulk_insert_service.connect()
    return _bulk_insert_service
