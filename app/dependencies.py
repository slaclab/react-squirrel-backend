from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.epics_service import get_epics_service, EpicsService
from app.services.pv_service import PVService
from app.services.snapshot_service import SnapshotService
from app.services.tag_service import TagService


def get_pv_service(db: AsyncSession = Depends(get_db)) -> PVService:
    """Get PV service instance."""
    return PVService(db)


def get_snapshot_service(
    db: AsyncSession = Depends(get_db),
    epics: EpicsService = Depends(get_epics_service)
) -> SnapshotService:
    """Get Snapshot service instance."""
    return SnapshotService(db, epics)


def get_tag_service(db: AsyncSession = Depends(get_db)) -> TagService:
    """Get Tag service instance."""
    return TagService(db)
