"""API endpoints for API key management."""
from fastapi import Security, APIRouter, HTTPException, status

from app.dependencies import ApiKeyServiceDep, require_read_access, require_write_access
from app.schemas.api_key import ApiKeyDTO, ApiKeyCreateDTO, ApiKeyCreateResultDTO

router = APIRouter(prefix="/api-keys", tags=["ApiKeys"])


@router.get("", dependencies=[Security(require_read_access)], response_model=list[ApiKeyDTO])
async def list_all_keys(
    service: ApiKeyServiceDep,
    active_only: bool = False,
) -> list[ApiKeyDTO]:
    """List all API Keys, optionally filtered by active status."""
    return await service.list_keys(active_only)


@router.post("", dependencies=[Security(require_write_access)], response_model=ApiKeyCreateResultDTO)
async def create_api_key(
    data: ApiKeyCreateDTO,
    service: ApiKeyServiceDep,
) -> ApiKeyCreateResultDTO:
    """Create a new API Key."""
    try:
        return await service.create_key(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.delete("/{key_id}", dependencies=[Security(require_write_access)], response_model=ApiKeyDTO)
async def deactivate_api_key(
    key_id: str,
    service: ApiKeyServiceDep,
) -> ApiKeyDTO:
    """Deactivate an API Key by ID."""
    try:
        deactivated = await service.deactivate_key(key_id)
        if deactivated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"API key {key_id} not found")
        return deactivated
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/count", dependencies=[Security(require_read_access)], response_model=int)
async def get_api_key_count(
    service: ApiKeyServiceDep,
    active_only: bool = False,
) -> int:
    """Get the current number of API Keys."""
    return await service.get_count(active_only)
