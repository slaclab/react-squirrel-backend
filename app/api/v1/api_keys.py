"""API endpoints for job status monitoring."""
from fastapi import Depends, APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.responses import APIException
from app.schemas.api_key import ApiKeyDTO, ApiKeyCreateDTO, ApiKeyCreateResultDTO
from app.services.api_key_service import ApiKeyService

router = APIRouter(prefix="/api-keys", tags=["ApiKeys"])


@router.get("")
async def list_all_keys(active: bool, db: AsyncSession = Depends(get_db)) -> list[ApiKeyDTO]:
    """List all API Keys, optionally filtered by active status."""
    service = ApiKeyService(db)
    if active:
        keys = await service.list_active_keys()
    else:
        keys = await service.list_keys()
    return keys


@router.post("")
async def create_api_key(data: ApiKeyCreateDTO, db: AsyncSession = Depends(get_db)) -> ApiKeyCreateResultDTO:
    """Create a new API Key."""
    service = ApiKeyService(db)
    try:
        return await service.create_key(data)
    except ValueError as e:
        raise APIException(status.HTTP_409_CONFLICT, str(e), status_code=status.HTTP_409_CONFLICT)


@router.delete("/{key_id}")
async def deactivate_api_key(key_id: str, db: AsyncSession = Depends(get_db)) -> ApiKeyDTO:
    """Deactivate an API Key by ID."""
    service = ApiKeyService(db)
    try:
        deactivated_key = await service.deactivate_key(key_id)
    except ValueError as e:
        raise APIException(status.HTTP_404_NOT_FOUND, str(e), status_code=status.HTTP_404_NOT_FOUND)
    return deactivated_key


@router.post("/bootstrap")
async def bootstrap_api_key(db: AsyncSession = Depends(get_db)) -> ApiKeyCreateResultDTO:
    """Bootstrap an API Key for initial setup."""
    service = ApiKeyService(db)

    existing_count = await service.get_count_active()
    if existing_count > 0:
        raise APIException(
            status.HTTP_403_FORBIDDEN,
            "API Key already exists. Bootstrapping is only allowed when no keys exist.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    data = ApiKeyCreateDTO(appName="Initial Bootstrap Key", readAccess=True, writeAccess=True)
    return await service.create_key(data)


@router.get("/count")
async def get_api_key_count(db: AsyncSession = Depends(get_db)) -> int:
    """Get the current number of API Keys."""
    service = ApiKeyService(db)
    return await service.get_count()
