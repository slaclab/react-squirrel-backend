import json
import logging
from typing import Any
from datetime import UTC, datetime

from app.config import get_settings

analytics_logger = logging.getLogger("analytics")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def log_analytics_event(
    event: str,
    *,
    source: str,
    session_id: str | None = None,
    api_key_id: str | None = None,
    api_key_app: str | None = None,
    route: str | None = None,
    path: str | None = None,
    client_ts: datetime | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()
    if not getattr(settings, "analytics_enabled", True):
        return

    payload = {
        "type": "analytics",
        "event": event,
        "source": source,
        "timestamp": _now_iso(),
        "session_id": session_id,
        "api_key_id": api_key_id,
        "api_key_app": api_key_app,
        "route": route,
        "path": path,
        "client_ts": client_ts.isoformat() if client_ts else None,
        "properties": properties or {},
    }

    analytics_logger.info(json.dumps(payload, default=str))
