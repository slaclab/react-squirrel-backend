"""API endpoints for API key management."""
from fastapi import Depends, APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import require_read_access, require_write_access
from app.api.responses import APIException
from app.schemas.common import ApiResultResponse
from app.schemas.api_key import ApiKeyCreateDTO
from app.services.api_key_service import ApiKeyService

router = APIRouter(prefix="/api-keys", tags=["ApiKeys"])


@router.get("", dependencies=[Depends(require_read_access)])
async def list_all_keys(active_only: bool = False, db: AsyncSession = Depends(get_db)) -> ApiResultResponse:
    """List all API Keys, optionally filtered by active status."""
    service = ApiKeyService(db)
    keys = await service.list_keys(active_only)
    key_response = ApiResultResponse(errorCode=0, errorMessage=None, payload=keys)
    return key_response


@router.post("", dependencies=[Depends(require_write_access)])
async def create_api_key(data: ApiKeyCreateDTO, db: AsyncSession = Depends(get_db)) -> ApiResultResponse:
    """Create a new API Key."""
    service = ApiKeyService(db)
    try:
        new_key = await service.create_key(data)
        return ApiResultResponse(errorCode=0, errorMessage=None, payload=new_key)
    except ValueError as e:
        raise APIException(status.HTTP_409_CONFLICT, str(e), status_code=status.HTTP_409_CONFLICT)


@router.delete("/{key_id}", dependencies=[Depends(require_write_access)])
async def deactivate_api_key(key_id: str, db: AsyncSession = Depends(get_db)) -> ApiResultResponse:
    """Deactivate an API Key by ID."""
    service = ApiKeyService(db)
    try:
        deactivated_key = await service.deactivate_key(key_id)
    except LookupError as e:
        raise APIException(status.HTTP_404_NOT_FOUND, str(e), status_code=status.HTTP_404_NOT_FOUND)
    except ValueError as e:
        raise APIException(status.HTTP_409_CONFLICT, str(e), status_code=status.HTTP_409_CONFLICT)
    return ApiResultResponse(errorCode=0, errorMessage=None, payload=deactivated_key)


@router.get("/count", dependencies=[Depends(require_read_access)])
async def get_api_key_count(active_only: bool = False, db: AsyncSession = Depends(get_db)) -> ApiResultResponse:
    """Get the current number of API Keys."""
    service = ApiKeyService(db)
    count = await service.get_count(active_only)
    return ApiResultResponse(errorCode=0, errorMessage=None, payload=count)
