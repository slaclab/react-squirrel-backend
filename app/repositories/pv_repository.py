from typing import Sequence
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
            .options(selectinload(PV.tags))
            .where(
                or_(
                    PV.setpoint_address == address,
                    PV.readback_address == address,
                    PV.config_address == address
                )
            )
        )
        return result.scalar_one_or_none()

    async def search_by_name(
        self,
        search: str | None = None,
        limit: int = 100,
        continuation_token: str | None = None
    ) -> tuple[list[PV], str | None, int]:
        """
        Search PVs with pagination using continuation tokens.

        Returns: (results, next_token, total_count)
        """
        # Build base query
        query = select(PV).options(selectinload(PV.tags))
        count_query = select(func.count()).select_from(PV)

        # Apply search filter
        if search:
            search_filter = or_(
                PV.setpoint_address.ilike(f"%{search}%"),
                PV.readback_address.ilike(f"%{search}%"),
                PV.config_address.ilike(f"%{search}%"),
                PV.device.ilike(f"%{search}%"),
                PV.description.ilike(f"%{search}%")
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
        result = await self.session.execute(
            select(PV.id, PV.setpoint_address, PV.readback_address, PV.config_address)
        )
        return list(result.all())

    async def bulk_create(self, pvs: list[PV]) -> list[PV]:
        """Bulk insert PVs."""
        self.session.add_all(pvs)
        await self.session.flush()
        for pv in pvs:
            await self.session.refresh(pv)
        return pvs

    async def get_by_ids(self, ids: list[str]) -> list[PV]:
        """Get multiple PVs by ID."""
        result = await self.session.execute(
            select(PV)
            .options(selectinload(PV.tags))
            .where(PV.id.in_(ids))
        )
        return list(result.scalars().all())
