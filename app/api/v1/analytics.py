from fastapi import Depends, Request, APIRouter

from app.dependencies import get_optional_api_key
from app.api.responses import success_response
from app.schemas.analytics import AnalyticsEventCreateDTO
from app.services.analytics_service import log_analytics_event

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.post("/events")
async def create_event(
    data: AnalyticsEventCreateDTO,
    request: Request,
    api_key=Depends(get_optional_api_key),
) -> dict:
    log_analytics_event(
        data.event,
        source="frontend",
        session_id=data.sessionId,
        api_key_id=str(api_key.id) if api_key else None,
        api_key_app=api_key.appName if api_key else None,
        route=data.route,
        path=data.path,
        client_ts=data.clientTs,
        properties={
            **(data.properties or {}),
            "user_agent": request.headers.get("user-agent"),
        },
    )

    return success_response(True)
