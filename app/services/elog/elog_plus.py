"""Adapter for the elog-plus backend (https://github.com/slaclab/elog-plus)."""
import logging
from typing import Any

import httpx
import markdown as markdown_lib

from app.services.elog.base import (
    ElogTag,
    ElogUser,
    ElogAdapter,
    ElogLogbook,
    ElogEntryResult,
    ElogRecentEntry,
    ElogEntryRequest,
)

logger = logging.getLogger(__name__)


# elog-plus stores the entry text as-is and parses it as HTML (jsoup) to
# extract image attachments; it does not run a markdown processor. Render on
# our side so the entry displays formatted instead of raw markdown.
_MARKDOWN_EXTENSIONS = ["extra", "sane_lists", "nl2br"]


def _render_markdown(md: str) -> str:
    return markdown_lib.markdown(md, extensions=_MARKDOWN_EXTENSIONS, output_format="html")


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
        self._email: str | None = None

    async def list_logbooks(self) -> list[ElogLogbook]:
        resp = await self._client.get("/v1/logbooks")
        resp.raise_for_status()
        items = _unwrap(resp.json()) or []
        return [ElogLogbook(id=item["id"], name=item["name"]) for item in items]

    async def _resolve_logbook_ids(self, logbooks: list[str]) -> list[str]:
        """Resolve any logbook names in ``logbooks`` to their IDs.

        v1's ``POST /v1/entries`` and ``POST /v1/entries/{id}/follow-ups`` both
        validate logbooks as IDs (auth checks, ``canCreateNewEntry`` /
        ``canCreateNewFollowUp``). Items already matching a known ID pass
        through unchanged.
        """
        all_logbooks = await self.list_logbooks()
        by_id = {lb.id: lb.id for lb in all_logbooks}
        by_name = {lb.name.lower(): lb.id for lb in all_logbooks}
        resolved: list[str] = []
        for entry in logbooks:
            if entry in by_id:
                resolved.append(entry)
            else:
                resolved.append(by_name.get(entry.lower(), entry))
        return resolved

    async def list_tags(self, logbook_id: str) -> list[ElogTag]:
        resp = await self._client.get(f"/v1/logbooks/{logbook_id}/tags")
        resp.raise_for_status()
        items = _unwrap(resp.json()) or []
        return [ElogTag(id=item["id"], name=item["name"]) for item in items]

    async def _resolve_tag_ids(self, tags: list[str], logbook_ids: list[str]) -> list[str]:
        """Resolve tag names to IDs across the given logbooks.

        v1 entries validate ``newEntry.tags`` as IDs
        (``LogbookService::tagIdExistInAnyLogbookIds``). Items already matching
        a known ID pass through unchanged.
        """
        if not tags or not logbook_ids:
            return list(tags)
        by_id: dict[str, str] = {}
        by_name: dict[str, str] = {}
        for lb_id in logbook_ids:
            try:
                logbook_tags = await self.list_tags(lb_id)
            except httpx.HTTPError:
                continue
            for t in logbook_tags:
                by_id[t.id] = t.id
                by_name.setdefault(t.name.lower(), t.id)
        resolved: list[str] = []
        for entry in tags:
            if entry in by_id:
                resolved.append(entry)
            else:
                resolved.append(by_name.get(entry.lower(), entry))
        return resolved

    def _build_entry_dto(self, request: ElogEntryRequest) -> dict[str, Any]:
        body_md = f"_Posted by **{request.author}** via Squirrel_\n\n{request.body_markdown}"
        dto: dict[str, Any] = {
            "logbooks": request.logbooks,
            "title": request.title,
            "text": _render_markdown(body_md),
            "tags": request.tags,
        }
        # elog-plus rejects the whole post if any entry in additionalAuthors is
        # not a valid LDAP email (EntryService.java:374). We forward only the
        # user-selected emails — the API key's app name is already credited in
        # the body attribution above.
        if request.additional_authors:
            dto["additionalAuthors"] = list(request.additional_authors)
        if request.important:
            dto["important"] = True
        if request.event_at is not None:
            # elog-plus expects LocalDateTime (no offset)
            dto["eventAt"] = request.event_at.replace(tzinfo=None).isoformat(timespec="seconds")
        return dto

    @staticmethod
    def _extract_id(body: Any) -> str:
        entry_id = _unwrap(body)
        if isinstance(entry_id, dict):
            entry_id = entry_id.get("id") or entry_id.get("entryId") or ""
        return str(entry_id)

    async def search_users(self, search: str, limit: int = 20) -> list[ElogUser]:
        resp = await self._client.get(
            "/v1/users",
            params={"search": search, "limit": limit},
        )
        resp.raise_for_status()
        items = _unwrap(resp.json()) or []
        return [
            ElogUser(
                uid=item.get("uid", item.get("id", "")),
                commonName=item.get("commonName", item.get("name", "")),
                surname=item.get("surname", ""),
                gecos=item.get("gecos", ""),
                mail=item.get("mail", item.get("email", "")),
            )
            for item in items
        ]

    async def _build_resolved_dto(self, request: ElogEntryRequest) -> dict[str, Any]:
        """Resolve logbook/tag names to IDs and build the v1 JSON payload.

        We use v1 endpoints for both fresh creates and follow-ups because v2's
        ``NewEntryDTO`` is missing ``additionalAuthors`` (silently dropped via
        ``@JsonIgnoreProperties(ignoreUnknown = true)``). v1 takes IDs.
        """
        resolved_logbooks = await self._resolve_logbook_ids(request.logbooks)
        resolved_tags = await self._resolve_tag_ids(request.tags, resolved_logbooks)
        return self._build_entry_dto(request.model_copy(update={"logbooks": resolved_logbooks, "tags": resolved_tags}))

    async def create_entry(self, request: ElogEntryRequest) -> ElogEntryResult:
        dto = await self._build_resolved_dto(request)
        resp = await self._client.post("/v1/entries", json=dto)
        resp.raise_for_status()
        return ElogEntryResult(id=self._extract_id(resp.json()))

    async def create_follow_up(self, parent_entry_id: str, request: ElogEntryRequest) -> ElogEntryResult:
        dto = await self._build_resolved_dto(request)
        resp = await self._client.post(
            f"/v1/entries/{parent_entry_id}/follow-ups",
            json=dto,
        )
        resp.raise_for_status()
        return ElogEntryResult(id=self._extract_id(resp.json()))

    async def _get_own_email(self) -> str:
        """Discover this token's email via ``/v1/users/me``, cached for lifetime."""
        if self._email is None:
            resp = await self._client.get("/v1/users/me")
            resp.raise_for_status()
            me = _unwrap(resp.json())
            self._email = me.get("mail") or me.get("email", "")
            logger.debug("Discovered own elog-plus email: %s", self._email)
        return self._email

    async def list_recent_entries(self, logbook_ids: list[str], limit: int = 5) -> list[ElogRecentEntry]:
        email = await self._get_own_email()
        params: list[tuple[str, str]] = []
        for lb in logbook_ids:
            params.append(("logbooks", lb))
        if email:
            params.append(("authors", email))
        params.append(("limit", str(limit)))
        resp = await self._client.get("/v1/entries", params=params)
        resp.raise_for_status()
        items = _unwrap(resp.json()) or []
        return [
            ElogRecentEntry(
                id=item["id"],
                title=item.get("title", ""),
                logged_at=item.get("loggedAt") or item.get("eventAt", ""),
                logged_by=item.get("loggedBy", ""),
            )
            for item in items
        ]

    async def close(self) -> None:
        await self._client.aclose()
