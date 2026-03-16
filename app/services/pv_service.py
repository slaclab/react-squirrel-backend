from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pv import PV
from app.schemas.pv import PVElementDTO, NewPVElementDTO, UpdatePVElementDTO
from app.schemas.tag import TagDTO
from app.schemas.common import PagedResult
from app.repositories.pv_repository import PVRepository
from app.repositories.tag_repository import TagRepository


class PVService:
    """Service for PV management operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.pv_repo = PVRepository(session)
        self.tag_repo = TagRepository(session)

    def _to_dto(self, pv: PV) -> PVElementDTO:
        """Convert PV model to DTO."""
        return PVElementDTO(
            id=pv.id,
            setpointAddress=pv.setpoint_address,
            readbackAddress=pv.readback_address,
            configAddress=pv.config_address,
            device=pv.device,
            description=pv.description,
            absTolerance=pv.abs_tolerance,
            relTolerance=pv.rel_tolerance,
            readOnly=pv.read_only,
            tags=[TagDTO(id=t.id, name=t.name, description=t.description) for t in pv.tags],
            createdDate=pv.created_at,
            lastModifiedDate=pv.updated_at,
        )

    @staticmethod
    def _normalize_address(address: str | None) -> str | None:
        """Normalize optional PV addresses from API payloads."""
        if address is None:
            return None
        normalized = address.strip()
        return normalized or None

    async def search_paged(
        self,
        search: str | None = None,
        page_size: int = 100,
        continuation_token: str | None = None,
        tag_filters: dict[str, list[str]] | None = None,
    ) -> PagedResult[PVElementDTO]:
        """Search PVs with pagination."""
        pvs, next_token, total_count = await self.pv_repo.search_by_name(
            search=search,
            limit=page_size,
            continuation_token=continuation_token,
            tag_filters=tag_filters,
        )

        return PagedResult(
            results=[self._to_dto(pv) for pv in pvs], continuationToken=next_token, totalCount=total_count
        )

    async def get_by_id(self, pv_id: str) -> PVElementDTO | None:
        """Get PV by ID."""
        pv = await self.pv_repo.get_by_id(pv_id)
        if not pv:
            return None
        return self._to_dto(pv)

    async def create(self, data: NewPVElementDTO) -> PVElementDTO:
        """Create a new PV."""
        setpoint_address = self._normalize_address(data.setpointAddress)
        readback_address = self._normalize_address(data.readbackAddress)
        config_address = self._normalize_address(data.configAddress)
        if not any([setpoint_address, readback_address, config_address]):
            raise ValueError("At least one address (setpoint, readback, or config) is required")

        # Check for duplicate addresses
        if setpoint_address:
            existing = await self.pv_repo.find_by_setpoint(setpoint_address)
            if existing:
                raise ValueError(f"PV with setpoint address '{setpoint_address}' already exists")

        # Get tags
        tags = []
        if data.tags:
            tags = await self.tag_repo.get_by_ids(data.tags)
            if len(tags) != len(data.tags):
                raise ValueError("One or more tag IDs are invalid")

        pv = PV(
            setpoint_address=setpoint_address,
            readback_address=readback_address,
            config_address=config_address,
            device=data.device,
            description=data.description,
            abs_tolerance=data.absTolerance,
            rel_tolerance=data.relTolerance,
            read_only=data.readOnly,
            tags=tags,
        )

        try:
            pv = await self.pv_repo.create(pv)
        except IntegrityError as e:
            raise ValueError(f"PV addresses violate uniqueness constraints: {e}") from e
        return self._to_dto(pv)

    async def create_many(self, data_list: list[NewPVElementDTO]) -> list[PVElementDTO]:
        """Bulk create PVs."""
        normalized_records: list[tuple[str | None, str | None, str | None, NewPVElementDTO]] = []
        for data in data_list:
            setpoint_address = self._normalize_address(data.setpointAddress)
            readback_address = self._normalize_address(data.readbackAddress)
            config_address = self._normalize_address(data.configAddress)
            if not any([setpoint_address, readback_address, config_address]):
                raise ValueError("At least one address (setpoint, readback, or config) is required")
            normalized_records.append((setpoint_address, readback_address, config_address, data))

        setpoints = [r[0] for r in normalized_records if r[0]]
        seen = set()
        duplicate_setpoints = set()
        for s in setpoints:
            if s in seen:
                duplicate_setpoints.add(s)
            else:
                seen.add(s)
        if duplicate_setpoints:
            raise ValueError(f"Duplicate setpoint addresses in import: {sorted(duplicate_setpoints)[:10]}")

        existing_setpoints = await self.pv_repo.get_existing_setpoints(setpoints)
        if existing_setpoints:
            raise ValueError(f"Setpoint addresses already exist: {sorted(existing_setpoints)[:10]}")

        # Collect all tag IDs
        all_tag_ids = set()
        for _, _, _, data in normalized_records:
            all_tag_ids.update(data.tags)

        # Fetch all tags at once
        tags_by_id = {}
        if all_tag_ids:
            tags = await self.tag_repo.get_by_ids(list(all_tag_ids))
            tags_by_id = {t.id: t for t in tags}

        # Create PV objects
        pvs = []
        for setpoint_address, readback_address, config_address, data in normalized_records:
            pv_tags = [tags_by_id[tid] for tid in data.tags if tid in tags_by_id]
            pv = PV(
                setpoint_address=setpoint_address,
                readback_address=readback_address,
                config_address=config_address,
                device=data.device,
                description=data.description,
                abs_tolerance=data.absTolerance,
                rel_tolerance=data.relTolerance,
                read_only=data.readOnly,
                tags=pv_tags,
            )
            pvs.append(pv)

        # Bulk insert
        try:
            pvs = await self.pv_repo.bulk_create(pvs)
        except IntegrityError as e:
            raise ValueError(f"PV addresses violate uniqueness constraints: {e}") from e
        return [self._to_dto(pv) for pv in pvs]

    async def update(self, pv_id: str, data: UpdatePVElementDTO) -> PVElementDTO | None:
        """Update a PV."""
        pv = await self.pv_repo.get_by_id(pv_id)
        if not pv:
            return None

        if data.description is not None:
            pv.description = data.description
        if data.absTolerance is not None:
            pv.abs_tolerance = data.absTolerance
        if data.relTolerance is not None:
            pv.rel_tolerance = data.relTolerance
        if data.readOnly is not None:
            pv.read_only = data.readOnly
        if data.tags is not None:
            tags = await self.tag_repo.get_by_ids(data.tags)
            pv.tags = tags

        pv = await self.pv_repo.update(pv)
        return self._to_dto(pv)

    async def delete(self, pv_id: str) -> bool:
        """Delete a PV."""
        pv = await self.pv_repo.get_by_id(pv_id)
        if not pv:
            return False
        await self.pv_repo.delete(pv)
        return True

    async def get_all_for_snapshot(self) -> list[tuple[str, str | None, str | None]]:
        """Get all PV IDs and addresses for snapshot."""
        addresses = await self.pv_repo.get_all_addresses()
        return [(pv_id, setpoint, readback) for pv_id, setpoint, readback, _ in addresses]
