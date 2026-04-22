"""HTTP routes for posting snapshots (and arbitrary entries) to an e-log.

Returns 503 when no e-log provider is configured so the frontend can hide the
"Post to elog" affordance.
"""
import logging
from typing import Annotated
from datetime import datetime

import httpx
from fastapi import Query, Depends, Security, APIRouter, HTTPException
from pydantic import Field, BaseModel

from app.config import Settings, get_settings
from app.dependencies import (
    DataBaseDep,
    get_api_key,
    require_read_access,
    require_write_access,
)
from app.services.elog import (
    ElogTag,
    ElogUser,
    ElogAdapter,
    ElogLogbook,
    ElogEntryResult,
    ElogRecentEntry,
    ElogEntryRequest,
    get_elog_service,
)
from app.schemas.api_key import ApiKeyDTO
from app.services.elog.last_entry import get_last_entry_id, upsert_last_entry

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
    followsUpEntryId: str | None = Field(
        default=None,
        description="If set, post as a follow-up of this entry id instead of a fresh entry.",
    )
    additionalAuthors: list[str] = Field(default_factory=list)
    important: bool = False
    eventAt: datetime | None = None


class LastEntryResponseDTO(BaseModel):
    """The most recent entry id this api key posted/followed-up for a logbook set."""

    entryId: str | None = None


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
        body_excerpt = (exc.response.text or "").strip()[:500]
        logger.warning("E-log upstream error: %s %s", exc.response.status_code, body_excerpt)
        detail = f"E-log upstream returned {exc.response.status_code}"
        if body_excerpt:
            detail = f"{detail}: {body_excerpt}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.TimeoutException as exc:
        logger.warning("E-log upstream timeout: %s", exc)
        raise HTTPException(status_code=504, detail="E-log upstream timed out") from exc
    except httpx.HTTPError as exc:
        logger.warning("E-log upstream HTTP error: %s", exc)
        raise HTTPException(status_code=502, detail="E-log upstream unreachable") from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/config")
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
)
async def list_logbooks(
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
) -> list[ElogLogbook]:
    return await _proxy_upstream(_require_adapter(adapter).list_logbooks())


@router.get(
    "/users",
    dependencies=[Security(require_read_access)],
)
async def search_users(
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
    search: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ElogUser]:
    """Search for users/people by name or email via the e-log provider."""
    svc = _require_adapter(adapter)
    try:
        return await _proxy_upstream(svc.search_users(search, limit=limit))
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc) or "User search unsupported") from exc


@router.get(
    "/logbooks/{logbook_id}/tags",
    dependencies=[Security(require_read_access)],
)
async def list_tags(
    logbook_id: str,
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
) -> list[ElogTag]:
    return await _proxy_upstream(_require_adapter(adapter).list_tags(logbook_id))


@router.get(
    "/last-entry",
    dependencies=[Security(require_read_access)],
)
async def get_last_entry(
    api_key: Annotated[ApiKeyDTO, Security(get_api_key)],
    db: DataBaseDep,
    logbook: Annotated[list[str], Query(min_length=1)],
) -> LastEntryResponseDTO:
    """Return the last entry id this api key posted/followed-up for the given logbook set."""
    entry_id = await get_last_entry_id(db, api_key_id=api_key.id, logbooks=list(logbook))
    return LastEntryResponseDTO(entryId=entry_id)


@router.get(
    "/recent-entries",
    dependencies=[Security(require_read_access)],
)
async def get_recent_entries(
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
    logbook: Annotated[list[str], Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[ElogRecentEntry]:
    """Return recent entries posted by this token for the given logbooks."""
    svc = _require_adapter(adapter)
    try:
        return await _proxy_upstream(svc.list_recent_entries(list(logbook), limit=limit))
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc) or "Recent entries unsupported") from exc


@router.post(
    "/entries",
    dependencies=[Security(require_write_access)],
)
async def create_entry(
    payload: CreateEntryRequestDTO,
    api_key: Annotated[ApiKeyDTO, Security(get_api_key)],
    adapter: Annotated[ElogAdapter | None, Depends(_get_elog_adapter)],
    db: DataBaseDep,
) -> ElogEntryResult:
    """Create an e-log entry, or a follow-up if ``followsUpEntryId`` is set."""
    adapter = _require_adapter(adapter)

    request = ElogEntryRequest(
        logbooks=payload.logbooks,
        title=payload.title,
        body_markdown=payload.bodyMarkdown,
        tags=payload.tags,
        author=api_key.appName,
        snapshot_id=payload.snapshotId,
        additional_authors=payload.additionalAuthors,
        important=payload.important,
        event_at=payload.eventAt,
    )

    try:
        if payload.followsUpEntryId:
            result = await _proxy_upstream(adapter.create_follow_up(payload.followsUpEntryId, request))
        else:
            result = await _proxy_upstream(adapter.create_entry(request))
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc) or "Follow-up unsupported") from exc

    try:
        await upsert_last_entry(
            db,
            api_key_id=api_key.id,
            logbooks=payload.logbooks,
            entry_id=result.id,
        )
    except Exception:
        logger.exception("Failed to record last elog entry id; continuing")

    return result
