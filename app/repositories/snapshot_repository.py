import uuid
import asyncio
from collections.abc import Callable

from sqlalchemy import func, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv import pv_tag
from app.models.snapshot import Snapshot, SnapshotValue
from app.repositories.base import BaseRepository

# Chunk size for bulk inserts to prevent blocking event loop
BULK_INSERT_CHUNK_SIZE = 5000


class SnapshotRepository(BaseRepository[Snapshot]):
    """Repository for Snapshot operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(Snapshot, session)

    async def get_with_values(self, snapshot_id: str, limit: int | None = None, offset: int = 0) -> Snapshot | None:
        """
        Get snapshot with values loaded.

        Args:
            snapshot_id: The snapshot ID
            limit: Max number of values to load (None = all)
            offset: Number of values to skip
        """
        # First get the snapshot
        result = await self.session.execute(select(Snapshot).where(Snapshot.id == snapshot_id))
        snapshot = result.scalar_one_or_none()
        if not snapshot:
            return None

        # Then get values with pagination
        values_query = (
            select(SnapshotValue)
            .where(SnapshotValue.snapshot_id == snapshot_id)
            .order_by(SnapshotValue.pv_name)
            .offset(offset)
        )
        if limit is not None:
            values_query = values_query.limit(limit)

        values_result = await self.session.execute(values_query)
        snapshot.values = list(values_result.scalars().all())

        return snapshot

    async def update_metadata(
        self,
        snapshot_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> Snapshot | None:
        """
        Update snapshot metadata (title and/or description).

        Args:
            snapshot_id: The snapshot ID
            title: Optional new title
            description: Optional new description
        """
        result = await self.session.execute(
            select(Snapshot).where(Snapshot.id == snapshot_id)
        )
        snapshot = result.scalar_one_or_none()

        if not snapshot:
            return None

        if title is not None:
            snapshot.title = title

        if description is not None:
            snapshot.description = description

        await self.session.flush()
        return snapshot

    async def search(
        self, title: str | None = None, tag_ids: list[str] | None = None, limit: int = 100
    ) -> list[Snapshot]:
        """Search snapshots by title and/or tags.

        Args:
            title: Optional title filter (case-insensitive contains)
            tag_ids: Optional list of tag IDs - returns snapshots containing PVs with ANY of these tags
            limit: Maximum number of results
        """
        query = select(Snapshot)

        if title:
            query = query.where(Snapshot.title.ilike(f"%{title}%"))

        if tag_ids:
            # Find snapshots that contain PVs with any of the specified tags
            # Subquery: get snapshot IDs that have PVs with matching tags
            snapshot_ids_with_tags = (
                select(SnapshotValue.snapshot_id)
                .distinct()
                .join(pv_tag, SnapshotValue.pv_id == pv_tag.c.pv_id)
                .where(pv_tag.c.tag_id.in_(tag_ids))
            )
            query = query.where(Snapshot.id.in_(snapshot_ids_with_tags))

        query = query.order_by(Snapshot.created_at.desc()).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_value_count(self, snapshot_id: str) -> int:
        """Get count of values in a snapshot."""
        result = await self.session.execute(
            select(func.count()).select_from(SnapshotValue).where(SnapshotValue.snapshot_id == snapshot_id)
        )
        return result.scalar() or 0

    async def get_value_counts_batch(self, snapshot_ids: list[str]) -> dict[str, int]:
        """Get counts of values for multiple snapshots in a single query."""
        if not snapshot_ids:
            return {}
        result = await self.session.execute(
            select(SnapshotValue.snapshot_id, func.count())
            .where(SnapshotValue.snapshot_id.in_(snapshot_ids))
            .group_by(SnapshotValue.snapshot_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def delete_with_values(self, snapshot_id: str) -> bool:
        """Delete snapshot and all its values using direct SQL for performance."""
        # Check if snapshot exists first
        result = await self.session.execute(select(Snapshot.id).where(Snapshot.id == snapshot_id))
        if not result.scalar_one_or_none():
            return False

        # Delete snapshot directly - ON DELETE CASCADE handles values at DB level
        await self.session.execute(delete(Snapshot).where(Snapshot.id == snapshot_id))
        await self.session.flush()
        return True


class SnapshotValueRepository(BaseRepository[SnapshotValue]):
    """Repository for SnapshotValue operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(SnapshotValue, session)

    async def bulk_create(
        self, values: list[SnapshotValue], progress_callback: Callable[[int, int, str], None] | None = None
    ) -> None:
        """
        Bulk insert snapshot values in chunks to prevent blocking the event loop.

        Inserts in chunks of BULK_INSERT_CHUNK_SIZE to:
        1. Prevent long-running DB operations from blocking other requests
        2. Allow progress tracking during large inserts
        3. Reduce memory pressure on the database
        """
        total = len(values)

        if total <= BULK_INSERT_CHUNK_SIZE:
            # Small dataset - single insert
            self.session.add_all(values)
            await self.session.flush()
            await asyncio.sleep(0)  # Yield to event loop
            return

        # Large dataset - chunked insert
        for i in range(0, total, BULK_INSERT_CHUNK_SIZE):
            chunk = values[i : i + BULK_INSERT_CHUNK_SIZE]
            self.session.add_all(chunk)
            await self.session.flush()
            await asyncio.sleep(0)  # Yield to event loop after each chunk

            # Report progress if callback provided
            if progress_callback:
                current = min(i + BULK_INSERT_CHUNK_SIZE, total)
                await progress_callback(current, total, f"Saved {current}/{total} values...")

    async def get_by_snapshot(self, snapshot_id: str) -> list[SnapshotValue]:
        """Get all values for a snapshot."""
        result = await self.session.execute(select(SnapshotValue).where(SnapshotValue.snapshot_id == snapshot_id))
        return list(result.scalars().all())

    async def count_by_snapshot(self, snapshot_id: str) -> int:
        """Get count of values in a snapshot."""
        result = await self.session.execute(
            select(func.count()).select_from(SnapshotValue).where(SnapshotValue.snapshot_id == snapshot_id)
        )
        return result.scalar() or 0

    async def get_by_snapshot_and_pvs(self, snapshot_id: str, pv_ids: list[str]) -> list[SnapshotValue]:
        """Get specific PV values from a snapshot."""
        result = await self.session.execute(
            select(SnapshotValue).where(SnapshotValue.snapshot_id == snapshot_id, SnapshotValue.pv_id.in_(pv_ids))
        )
        return list(result.scalars().all())

    async def bulk_create_fast(self, snapshot_id: str, values: list[dict]) -> int:
        """
        Use PostgreSQL COPY for bulk insert (40k rows in ~2 seconds).

        Args:
            snapshot_id: The snapshot ID
            values: List of dicts with keys:
                - pv_id: str
                - pv_name: str
                - setpoint_value: Any (will be JSON serialized)
                - readback_value: Any (will be JSON serialized)
                - status: int | None
                - severity: int | None
                - timestamp: datetime | None

        Returns:
            Number of rows inserted
        """
        from app.services.bulk_insert_service import get_bulk_insert_service

        bulk_service = await get_bulk_insert_service()

        # Convert to tuples for COPY
        # Pass dicts for JSONB columns - bulk service handles JSON serialization
        records = []
        for v in values:
            records.append(
                (
                    str(uuid.uuid4()),
                    snapshot_id,
                    v["pv_id"],
                    v["pv_name"],
                    v.get("setpoint_value"),  # Dict - will be JSON serialized by bulk service
                    v.get("readback_value"),  # Dict - will be JSON serialized by bulk service
                    v.get("status"),
                    v.get("severity"),
                    v.get("timestamp"),
                )
            )

        return await bulk_service.bulk_insert_snapshot_values(records)
