"""HTTP routes for posting snapshots (and arbitrary entries) to an e-log.

Returns 503 when no e-log provider is configured so the frontend can hide the
"Post to elog" affordance.
"""
import logging
from typing import Annotated

import httpx
from fastapi import Depends, Security, APIRouter, HTTPException
from pydantic import Field, BaseModel

from app.dependencies import get_api_key, require_read_access
from app.schemas.api_key import ApiKeyDTO
from app.services.elog import (
    ElogTag,
    ElogAdapter,
    ElogLogbook,
    ElogEntryRequest,
    ElogEntryResult,
    get_elog_service,
)
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/elog", tags=["Elog"])


# ---------------------------------------------------------------------------
# Request/Response models specific to the HTTP surface
# ---------------------------------------------------------------------------


class ElogConfigDTO(BaseModel):
    """Exposes whether e-log posting is available to the frontend."""

    enabled: bool
    provider: str = ""
    defaultLogbooks: list[str] = []


class CreateEntryRequestDTO(BaseModel):
    """Posted by the frontend to create an e-log entry.

    ``author`` is *not* trusted from the client — we stamp it from the API key.
    """

    logbooks: list[str] = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=255)
    bodyMarkdown: str
    tags: list[str] = Field(default_factory=list)
    snapshotId: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_adapter(adapter: ElogAdapter | None) -> ElogAdapter:
    if adapter is None:
        raise HTTPException(status_code=503, detail="E-log integration is not configured")
    return adapter


def _get_elog_adapter() -> ElogAdapter | None:
    """FastAPI dependency wrapper; lets tests override via ``app.dependency_overrides``."""
    return get_elog_service()


async def _proxy_upstream(coro):
    """Translate upstream HTTP errors into 502/504 responses."""
    try:
        return await coro
    except httpx.HTTPStatusError as exc:
        logger.warning("E-log upstream error: %s %s", exc.response.status_code, exc.response.text[:500])
        raise HTTPException(status_code=502, detail=f"E-log upstream returned {exc.response.status_code}") from exc
    except httpx.TimeoutException as exc:
        logger.warning("E-log upstream timeout: %s", exc)
        raise HTTPException(status_code=504, detail="E-log upstream timed out") from exc
    except httpx.HTTPError as exc:
        logger.warning("E-log upstream HTTP error: %s", exc)
        raise HTTPException(status_code=502, detail="E-log upstream unreachable") from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/config", response_model=ElogConfigDTO)
async def get_elog_config(
    settings: Annotated[Settings, Depends(get_settings)],
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
) -> ElogConfigDTO:
    """Feature-flag endpoint. Always returns 200 — no auth required."""
    provider = (settings.elog_provider or "").strip()
    return ElogConfigDTO(
        enabled=adapter is not None,
        provider=provider if adapter is not None else "",
        defaultLogbooks=list(settings.elog_default_logbooks) if adapter is not None else [],
    )


@router.get(
    "/logbooks",
    dependencies=[Security(require_read_access)],
    response_model=list[ElogLogbook],
)
async def list_logbooks(
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
) -> list[ElogLogbook]:
    return await _proxy_upstream(_require_adapter(adapter).list_logbooks())


@router.get(
    "/logbooks/{logbook_id}/tags",
    dependencies=[Security(require_read_access)],
    response_model=list[ElogTag],
)
async def list_tags(
    logbook_id: str,
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
) -> list[ElogTag]:
    return await _proxy_upstream(_require_adapter(adapter).list_tags(logbook_id))


@router.post(
    "/entries",
    response_model=ElogEntryResult,
)
async def create_entry(
    payload: CreateEntryRequestDTO,
    api_key: Annotated[ApiKeyDTO, Security(get_api_key)],
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
) -> ElogEntryResult:
    """Create an e-log entry. Requires write access."""
    if not api_key.writeAccess:
        raise HTTPException(status_code=401, detail="API key does not have write access")

    request = ElogEntryRequest(
        logbooks=payload.logbooks,
        title=payload.title,
        body_markdown=payload.bodyMarkdown,
        tags=payload.tags,
        author=api_key.appName,
        snapshot_id=payload.snapshotId,
    )
    return await _proxy_upstream(_require_adapter(adapter).create_entry(request))
