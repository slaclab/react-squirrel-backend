"""E-log plugin registry.

``get_elog_service`` returns the configured adapter or ``None`` when e-log
integration is disabled (``SQUIRREL_ELOG_PROVIDER`` unset/empty).
"""
from __future__ import annotations

import logging
from typing import Callable

from app.config import Settings, get_settings
from app.services.elog.base import (
    ElogTag,
    ElogAdapter,
    ElogLogbook,
    ElogEntryRequest,
    ElogEntryResult,
)
from app.services.elog.elog_plus import ElogPlusAdapter

logger = logging.getLogger(__name__)


def _build_elog_plus(settings: Settings) -> ElogAdapter:
    return ElogPlusAdapter(
        base_url=settings.elog_plus_base_url,
        token=settings.elog_plus_token,
        auth_header=settings.elog_plus_auth_header,
        proxy_url=settings.elog_proxy_url or None,
    )


ELOG_PROVIDERS: dict[str, Callable[[Settings], ElogAdapter]] = {
    "elog_plus": _build_elog_plus,
}


_adapter: ElogAdapter | None = None
_adapter_provider: str | None = None


def get_elog_service() -> ElogAdapter | None:
    """Return the configured adapter singleton, or ``None`` when disabled."""
    global _adapter, _adapter_provider

    settings = get_settings()
    provider = (settings.elog_provider or "").strip()

    if not provider:
        return None

    if _adapter is not None and _adapter_provider == provider:
        return _adapter

    factory = ELOG_PROVIDERS.get(provider)
    if factory is None:
        logger.warning("Unknown SQUIRREL_ELOG_PROVIDER=%r; e-log disabled.", provider)
        return None

    _adapter = factory(settings)
    _adapter_provider = provider
    logger.info("E-log adapter initialized: %s", provider)
    return _adapter


async def shutdown_elog_service() -> None:
    """Close the cached adapter, if any. Called from the app lifespan."""
    global _adapter, _adapter_provider
    if _adapter is not None:
        await _adapter.close()
    _adapter = None
    _adapter_provider = None


__all__ = [
    "ELOG_PROVIDERS",
    "ElogAdapter",
    "ElogEntryRequest",
    "ElogEntryResult",
    "ElogLogbook",
    "ElogTag",
    "get_elog_service",
    "shutdown_elog_service",
]
