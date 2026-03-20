import math
import logging
from typing import Any
from datetime import datetime
from collections.abc import Callable

from p4p.client.asyncio import Context

from app.config import get_settings
from app.services.epics_types import EpicsValue

logger = logging.getLogger(__name__)
settings = get_settings()


class PVAccessService:
    """
    Native async PVAccess service using p4p.

    This service provides methods to read and write PVs using the PVAccess protocol.
    It handles timeouts, batch operations, and converts p4p values into a consistent EpicsValue
    """

    def __init__(self):
        self._timeout = settings.epics_pva_timeout
        self._chunk_size = settings.epics_chunk_size
        self._context = Context("pva", nt=False)

    def _sanitize_value(self, value: Any) -> Any:
        """Sanitize value for JSON storage (handle NaN/Inf)."""
        if value is None:
            return None
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
        if isinstance(value, list):
            return [self._sanitize_value(v) for v in value]
        if hasattr(value, "tolist"):
            return self._sanitize_value(value.tolist())
        return value

    def _pva_value_to_epics(self, pv_name: str, value: Any) -> EpicsValue:
        """Convert a p4p Value (or Exception) into EpicsValue."""
        if isinstance(value, Exception):
            return EpicsValue(value=None, connected=False, error=f"Failed to read {pv_name}: {value}")

        # If automatic unwrapping happened, we only have the value.
        if not hasattr(value, "get") and not hasattr(value, "toDict"):
            return EpicsValue(value=self._sanitize_value(value), connected=True)

        # Best-effort metadata extraction
        timestamp = None
        status = None
        severity = None
        units = None

        try:
            if hasattr(value, "get"):
                seconds = value.get("timeStamp.secondsPastEpoch", None)
                nanos = value.get("timeStamp.nanoseconds", 0) or 0
                if seconds is not None:
                    timestamp = datetime.fromtimestamp(seconds + (nanos / 1e9))
                status = value.get("alarm.status", None)
                severity = value.get("alarm.severity", None)
                units = value.get("display.units", None)
        except Exception:
            pass

        # Extract the main value field if available
        raw_value = None
        try:
            if hasattr(value, "get"):
                raw_value = value.get("value")
            elif hasattr(value, "toDict"):
                raw_value = value.toDict().get("value")
        except Exception:
            raw_value = None

        if raw_value is None:
            raw_value = value

        return EpicsValue(
            value=self._sanitize_value(raw_value),
            status=status,
            severity=severity,
            timestamp=timestamp,
            units=units,
            connected=True,
            error=None,
        )

    async def get_single(self, pv_name: str, timeout: float | None = None) -> EpicsValue:
        """Read a single PVAccess PV."""
        try:
            effective_timeout = self._timeout if timeout is None else timeout
            value = (
                await self._context.get(pv_name)
                if effective_timeout is None
                else await self._with_timeout(self._context.get(pv_name), effective_timeout)
            )
            return self._pva_value_to_epics(pv_name, value)
        except Exception as e:
            logger.error(f"PVA get_single error for {pv_name}: {e}")
            return EpicsValue(value=None, connected=False, error=str(e))

    async def get_many(self, pv_names: list[str]) -> dict[str, EpicsValue]:
        """Read multiple PVAccess PVs."""
        results: dict[str, EpicsValue] = {}
        try:
            values = await self._context.get(pv_names) if pv_names else []
            for pv_name, value in zip(pv_names, values):
                results[pv_name] = self._pva_value_to_epics(pv_name, value)
        except Exception as e:
            logger.error(f"PVA get_many error: {e}")
            for pv_name in pv_names:
                if pv_name not in results:
                    results[pv_name] = EpicsValue(value=None, connected=False, error=str(e))
        return results

    async def get_many_with_progress(
        self, pv_names: list[str], progress_callback: Callable | None = None
    ) -> dict[str, EpicsValue]:
        """Read multiple PVAccess PVs in batches with progress tracking."""
        total = len(pv_names)
        results: dict[str, EpicsValue] = {}

        if progress_callback:
            await progress_callback(0, total, "Starting to read PVA PVs...")

        batch_size = self._chunk_size
        for i in range(0, total, batch_size):
            batch = pv_names[i : i + batch_size]
            try:
                values = await self._context.get(batch)
                for pv_name, value in zip(batch, values):
                    results[pv_name] = self._pva_value_to_epics(pv_name, value)
            except Exception as e:
                logger.error(f"PVA batch read error: {e}")
                for pv_name in batch:
                    if pv_name not in results:
                        results[pv_name] = EpicsValue(value=None, connected=False, error=str(e))

            if progress_callback:
                current = min(i + batch_size, total)
                connected_so_far = sum(1 for r in results.values() if r.connected)
                await progress_callback(
                    current, total, f"Read {current:,}/{total:,} PVA PVs ({connected_so_far:,} connected)"
                )

        if progress_callback:
            connected_count = sum(1 for r in results.values() if r.connected)
            await progress_callback(total, total, f"Completed: {connected_count:,}/{total:,} PVA PVs connected")

        return results

    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """Write a value to a single PVAccess PV."""
        try:
            await self._context.put(pv_name, value, wait=True)
            return True, None
        except Exception as e:
            logger.error(f"PVA put_single error for {pv_name}: {e}")
            return False, str(e)

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """Write values to multiple PVAccess PVs."""
        results: dict[str, tuple[bool, str | None]] = {}
        pv_names = list(values.keys())
        pv_values = list(values.values())
        try:
            put_result = await self._context.put(
                pv_names,
                pv_values,
                request=[None] * len(pv_names),
                wait=True,
            )
            if isinstance(put_result, list):
                for pv_name, res in zip(pv_names, put_result):
                    if res is None:
                        results[pv_name] = (True, None)
                    elif isinstance(res, Exception):
                        results[pv_name] = (False, str(res))
                    else:
                        results[pv_name] = (True, None)
            else:
                for pv_name in pv_names:
                    results[pv_name] = (True, None)
        except Exception as e:
            logger.error(f"PVA put_many error: {e}")
            for pv_name in pv_names:
                if pv_name not in results:
                    results[pv_name] = (False, str(e))
        return results

    async def shutdown(self) -> None:
        """Cleanup resources."""
        try:
            self._context.close()
        except Exception as e:
            logger.debug(f"Error closing PVA context: {e}")

    async def _with_timeout(self, coro, timeout: float):
        """Run a coroutine with a timeout."""
        import asyncio

        return await asyncio.wait_for(coro, timeout=timeout)


_pva_service: PVAccessService | None = None


def get_pvaccess_service() -> PVAccessService:
    """Get or create the PVAccess service singleton."""
    global _pva_service
    if _pva_service is None:
        _pva_service = PVAccessService()
    return _pva_service
