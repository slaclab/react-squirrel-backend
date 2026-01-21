from sqlalchemy import or_, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv import PV
from app.models.tag import Tag
from app.repositories.base import BaseRepository


class PVRepository(BaseRepository[PV]):
    """Repository for PV operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(PV, session)

    async def find_by_address(self, address: str) -> PV | None:
        """Find PV by any address (setpoint, readback, or config)."""
        result = await self.session.execute(
            select(PV)
            .options(selectinload(PV.tags).selectinload(Tag.group))
            .where(or_(PV.setpoint_address == address, PV.readback_address == address, PV.config_address == address))
        )
        return result.scalar_one_or_none()

    async def search_by_name(
        self, search: str | None = None, limit: int = 100, continuation_token: str | None = None
    ) -> tuple[list[PV], str | None, int]:
        """
        Search PVs with pagination using continuation tokens.

        Returns: (results, next_token, total_count)
        """
        # Build base query
        query = select(PV).options(selectinload(PV.tags).selectinload(Tag.group))
        count_query = select(func.count()).select_from(PV)

        # Apply search filter
        if search:
            search_filter = or_(
                PV.setpoint_address.ilike(f"%{search}%"),
                PV.readback_address.ilike(f"%{search}%"),
                PV.config_address.ilike(f"%{search}%"),
                PV.device.ilike(f"%{search}%"),
                PV.description.ilike(f"%{search}%"),
            )
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        # Apply continuation token (ID-based pagination)
        if continuation_token:
            query = query.where(PV.id > continuation_token)

        # Order and limit
        query = query.order_by(PV.id).limit(limit + 1)  # +1 to check for more

        # Execute
        result = await self.session.execute(query)
        pvs = list(result.scalars().all())

        # Get total count
        count_result = await self.session.execute(count_query)
        total_count = count_result.scalar() or 0

        # Determine next token
        next_token = None
        if len(pvs) > limit:
            pvs = pvs[:limit]
            next_token = pvs[-1].id

        return pvs, next_token, total_count

    async def get_all_addresses(self) -> list[tuple[str, str | None, str | None, str | None]]:
        """Get all PV IDs and addresses for snapshot operations."""
        result = await self.session.execute(select(PV.id, PV.setpoint_address, PV.readback_address, PV.config_address))
        return list(result.all())

    async def bulk_create(self, pvs: list[PV]) -> list[PV]:
        """Bulk insert PVs."""
        self.session.add_all(pvs)
        await self.session.flush()
        for pv in pvs:
            await self.session.refresh(pv)
        return pvs

    async def get_by_ids(self, ids: list[str]) -> list[PV]:
        """
        Get multiple PVs by ID.

        Batches queries to avoid PostgreSQL's 32,767 parameter limit.
        """
        if not ids:
            return []

        # PostgreSQL limit is 32767 parameters, use 30000 to be safe
        batch_size = 30000
        all_pvs = []

        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            result = await self.session.execute(
                select(PV).options(selectinload(PV.tags).selectinload(Tag.group)).where(PV.id.in_(batch_ids))
            )
            all_pvs.extend(result.scalars().all())

        return all_pvs

    async def search_filtered(
        self,
        search_term: str | None = None,
        devices: list[str] | None = None,
        tag_ids: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[PV], int]:
        """
        Server-side filtered search with proper indexing.

        Returns (results, total_count).
        """
        query = select(PV).options(selectinload(PV.tags).selectinload(Tag.group))
        count_query = select(func.count()).select_from(PV)

        # Apply search filter
        if search_term:
            search_filter = or_(
                PV.setpoint_address.ilike(f"%{search_term}%"),
                PV.readback_address.ilike(f"%{search_term}%"),
                PV.config_address.ilike(f"%{search_term}%"),
                PV.device.ilike(f"%{search_term}%"),
                PV.description.ilike(f"%{search_term}%"),
            )
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        # Apply device filter
        if devices:
            query = query.where(PV.device.in_(devices))
            count_query = count_query.where(PV.device.in_(devices))

        # Apply tag filter
        if tag_ids:
            query = query.join(PV.tags).where(Tag.id.in_(tag_ids))
            count_query = count_query.join(PV.tags).where(Tag.id.in_(tag_ids))

        # Get total count
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        # Get paginated results
        query = query.order_by(PV.setpoint_address).offset(offset).limit(limit)
        result = await self.session.execute(query)

        return list(result.scalars().all()), total

    async def get_all_devices(self) -> list[str]:
        """Get all unique device names."""
        result = await self.session.execute(
            select(PV.device).where(PV.device.isnot(None)).distinct().order_by(PV.device)
        )
        return [r[0] for r in result.all() if r[0]]

    async def get_all_as_map(self) -> dict[str, "PV"]:
        """Get all PVs as a dictionary keyed by ID."""
        result = await self.session.execute(select(PV).options(selectinload(PV.tags).selectinload(Tag.group)))
        pvs = result.scalars().all()
        return {pv.id: pv for pv in pvs}
