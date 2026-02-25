from typing import Annotated

from fastapi import Depends, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.responses import APIException
from app.schemas.api_key import ApiKeyDTO
from app.services.pv_service import PVService
from app.services.tag_service import TagService
from app.services.epics_service import EpicsService, get_epics_service
from app.services.api_key_service import ApiKeyService
from app.services.snapshot_service import SnapshotService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_pv_service(db: AsyncSession = Depends(get_db)) -> PVService:
    """Get PV service instance."""
    return PVService(db)


def get_snapshot_service(
    db: AsyncSession = Depends(get_db), epics: EpicsService = Depends(get_epics_service)
) -> SnapshotService:
    """Get Snapshot service instance."""
    return SnapshotService(db, epics)


def get_tag_service(db: AsyncSession = Depends(get_db)) -> TagService:
    """Get Tag service instance."""
    return TagService(db)


async def get_api_key(
    db: Annotated[AsyncSession, Depends(get_db)], api_key_header: Annotated[str, Security(api_key_header)]
) -> ApiKeyDTO | None:
    if api_key_header:
        service = ApiKeyService(db)
        api_key_dto = await service.get_by_token(api_key_header)

        if api_key_dto and api_key_dto.isActive:
            return api_key_dto

    raise APIException(
        code=status.HTTP_401_UNAUTHORIZED,
        message="Missing or deactivated API key",
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


def require_read_access(api_key_dto: Annotated[ApiKeyDTO, Depends(get_api_key)]):
    """Dependency that requires a valid, active API Key with read access."""
    if not api_key_dto.readAccess:
        raise APIException(
            code=status.HTTP_401_UNAUTHORIZED,
            message="API key does not have read access",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


def require_write_access(api_key_dto: Annotated[ApiKeyDTO, Depends(get_api_key)]):
    """Dependency that requires a valid, active API Key with write access."""
    if not api_key_dto.writeAccess:
        raise APIException(
            code=status.HTTP_401_UNAUTHORIZED,
            message="API key does not have write access",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
