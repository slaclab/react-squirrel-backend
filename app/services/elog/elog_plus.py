"""Adapter for the elog-plus backend (https://github.com/slaclab/elog-plus)."""
import logging
from typing import Any

import httpx

from app.services.elog.base import (
    ElogTag,
    ElogAdapter,
    ElogLogbook,
    ElogEntryRequest,
    ElogEntryResult,
)

logger = logging.getLogger(__name__)


def _unwrap(body: Any) -> Any:
    """Strip elog-plus' ``ApiResultResponse`` envelope when present."""
    if isinstance(body, dict) and "payload" in body:
        return body["payload"]
    return body


class ElogPlusAdapter(ElogAdapter):
    """Calls the elog-plus REST API over HTTP."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        auth_header: str = "x-vouch-idp-accesstoken",
        proxy_url: str | None = None,
        timeout: float = 15.0,
    ):
        if not base_url:
            raise ValueError("elog_plus_base_url is required")
        if not token:
            raise ValueError("elog_plus_token is required")

        self._auth_header = auth_header
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={auth_header: token},
            timeout=timeout,
            proxy=proxy_url or None,
            trust_env=False,
        )

    async def list_logbooks(self) -> list[ElogLogbook]:
        resp = await self._client.get("/v1/logbooks")
        resp.raise_for_status()
        items = _unwrap(resp.json()) or []
        return [ElogLogbook(id=item["id"], name=item["name"]) for item in items]

    async def list_tags(self, logbook_id: str) -> list[ElogTag]:
        resp = await self._client.get(f"/v1/logbooks/{logbook_id}/tags")
        resp.raise_for_status()
        items = _unwrap(resp.json()) or []
        return [ElogTag(id=item["id"], name=item["name"]) for item in items]

    async def create_entry(self, request: ElogEntryRequest) -> ElogEntryResult:
        body = f"_Posted by **{request.author}** via Squirrel_\n\n{request.body_markdown}"
        dto: dict[str, Any] = {
            "logbooks": request.logbooks,
            "title": request.title,
            "text": body,
            "tags": request.tags,
        }
        if request.author:
            dto["additionalAuthors"] = [request.author]
        resp = await self._client.post("/v1/entries", json=dto)
        resp.raise_for_status()
        entry_id = _unwrap(resp.json())
        if isinstance(entry_id, dict):
            entry_id = entry_id.get("id") or entry_id.get("entryId") or ""
        return ElogEntryResult(id=str(entry_id))

    async def close(self) -> None:
        await self._client.aclose()
