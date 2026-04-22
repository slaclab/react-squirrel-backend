"""API endpoints for API key management."""
from fastapi import Depends, APIRouter, HTTPException, status

from app.dependencies import (
    get_api_key_service,
    require_read_access,
    require_write_access,
)
from app.schemas.api_key import ApiKeyDTO, ApiKeyCreateDTO, ApiKeyCreateResultDTO
from app.services.api_key_service import ApiKeyService

router = APIRouter(prefix="/api-keys", tags=["ApiKeys"])


@router.get("", dependencies=[Depends(require_read_access)], response_model=list[ApiKeyDTO])
async def list_all_keys(
    active_only: bool = False,
    service: ApiKeyService = Depends(get_api_key_service),
) -> list[ApiKeyDTO]:
    """List all API Keys, optionally filtered by active status."""
    return await service.list_keys(active_only)


@router.post("", dependencies=[Depends(require_write_access)], response_model=ApiKeyCreateResultDTO)
async def create_api_key(
    data: ApiKeyCreateDTO,
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyCreateResultDTO:
    """Create a new API Key."""
    try:
        return await service.create_key(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.delete("/{key_id}", dependencies=[Depends(require_write_access)], response_model=ApiKeyDTO)
async def deactivate_api_key(
    key_id: str,
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyDTO:
    """Deactivate an API Key by ID."""
    try:
        return await service.deactivate_key(key_id)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/count", dependencies=[Depends(require_read_access)], response_model=int)
async def get_api_key_count(
    active_only: bool = False,
    service: ApiKeyService = Depends(get_api_key_service),
) -> int:
    """Get the current number of API Keys."""
    return await service.get_count(active_only)
