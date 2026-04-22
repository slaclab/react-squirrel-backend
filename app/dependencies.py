from typing import Annotated

from fastapi import Depends, Security, WebSocket, HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.exceptions import WebSocketException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.api_key import ApiKeyDTO
from app.services.pv_service import PVService
from app.services.job_service import JobService
from app.services.tag_service import TagService
from app.services.epics_service import EpicsService, get_epics_service
from app.services.redis_service import RedisService, get_redis_service
from app.services.api_key_service import ApiKeyService
from app.services.snapshot_service import SnapshotService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ---------------------------------------------------------------------------
# Service dependencies
# ---------------------------------------------------------------------------

DataBaseDep = Annotated[AsyncSession, Depends(get_db)]

EpicsServiceDep = Annotated[EpicsService, Depends(get_epics_service)]

RedisServiceDep = Annotated[RedisService, Depends(get_redis_service)]


def get_pv_service(db: DataBaseDep) -> PVService:
    return PVService(db)


PVServiceDep = Annotated[PVService, Depends(get_pv_service)]


def get_tag_service(db: DataBaseDep) -> TagService:
    return TagService(db)


TagServiceDep = Annotated[TagService, Depends(get_tag_service)]


def get_api_key_service(db: DataBaseDep) -> ApiKeyService:
    return ApiKeyService(db)


ApiKeyServiceDep = Annotated[ApiKeyService, Depends(get_api_key_service)]


def get_job_service(db: DataBaseDep) -> JobService:
    return JobService(db)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


def get_snapshot_service(db: DataBaseDep, epics: EpicsServiceDep, redis: RedisServiceDep) -> SnapshotService:
    return SnapshotService(db, epics, redis)


SnapshotServiceDep = Annotated[SnapshotService, Depends(get_snapshot_service)]


# ---------------------------------------------------------------------------
# API Key auth dependencies
# ---------------------------------------------------------------------------


async def get_api_key(
    service: ApiKeyServiceDep,
    api_key_header: Annotated[str, Security(api_key_header)],
) -> ApiKeyDTO | None:
    if api_key_header:
        api_key_dto = await service.get_by_token(api_key_header)

        if api_key_dto and api_key_dto.isActive:
            return api_key_dto

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or deactivated API key",
    )


def require_read_access(api_key_dto: Annotated[ApiKeyDTO, Security(get_api_key)]):
    """Dependency that requires a valid, active API Key with read access."""
    if not api_key_dto.readAccess:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key does not have read access",
        )


def require_write_access(api_key_dto: Annotated[ApiKeyDTO, Security(get_api_key)]):
    """Dependency that requires a valid, active API Key with write access."""
    if not api_key_dto.writeAccess:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key does not have write access",
        )


# ---------------------------------------------------------------------------
# WebSocket-specific auth dependencies
# ---------------------------------------------------------------------------


async def ws_get_api_key(websocket: WebSocket, service: ApiKeyServiceDep) -> ApiKeyDTO:
    """WebSocket variant of get_api_key — raises WebSocketException on failure."""
    key_value = websocket.headers.get("X-API-Key")
    if key_value:
        api_key_dto = await service.get_by_token(key_value)

        if api_key_dto and api_key_dto.isActive:
            return api_key_dto

    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing or deactivated API key")


def ws_require_read_access(api_key_dto: Annotated[ApiKeyDTO, Security(ws_get_api_key)]):
    """WebSocket dependency that requires read access."""
    if not api_key_dto.readAccess:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="API key does not have read access")


def ws_require_write_access(api_key_dto: Annotated[ApiKeyDTO, Security(ws_get_api_key)]):
    """WebSocket dependency that requires write access."""
    if not api_key_dto.writeAccess:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="API key does not have write access")
