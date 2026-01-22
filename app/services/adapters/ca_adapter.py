"""
Channel Access (CA) protocol adapter using aioca.

This adapter wraps the aioca library to provide CA protocol support
within the unified protocol adapter framework.
"""

import logging
from typing import Any
from datetime import datetime

from aioca import FORMAT_TIME, caget, caput, connect, purge_channel_caches

from app.config import get_settings
from app.services.adapters.base_adapter import EpicsValue, BaseAdapter

logger = logging.getLogger(__name__)
settings = get_settings()


class CAAdapter(BaseAdapter):
    """
    Channel Access protocol adapter using aioca.

    This adapter handles all CA-specific operations and metadata extraction.
    """

    def __init__(self, enable_circuit_breaker: bool = True):
        self._timeout = settings.epics_ca_timeout
        self._conn_timeout = settings.epics_ca_conn_timeout
        self._enable_circuit_breaker = enable_circuit_breaker
        self._circuit_manager = None

        # Lazily initialize circuit breaker
        if self._enable_circuit_breaker:
            try:
                from app.services.circuit_breaker import get_circuit_breaker_manager

                self._circuit_manager = get_circuit_breaker_manager()
            except ImportError:
                logger.warning("Circuit breaker not available for CA adapter")

    def _extract_ioc_name(self, pv_name: str) -> str:
        """
        Extract IOC/subsystem name from PV name for circuit grouping.

        Examples:
            "LINAC:TEMP:1" -> "LINAC:TEMP"
            "BPM:X:1" -> "BPM:X"
            "SYS:IOC:STATUS" -> "SYS:IOC"
        """
        parts = pv_name.split(":")
        if len(parts) >= 2:
            return f"{parts[0]}:{parts[1]}" if len(parts) > 2 else parts[0]
        return "default"

    def _augmented_to_epics_value(self, pv_name: str, result) -> EpicsValue:
        """Convert aioca AugmentedValue to EpicsValue dataclass."""
        if not result.ok:
            return EpicsValue(
                value=None,
                connected=False,
                error=f"Failed to read {pv_name}: {getattr(result, 'errorcode', 'unknown')}",
            )

        # Extract timestamp if available
        timestamp = None
        if hasattr(result, "timestamp") and result.timestamp:
            timestamp = datetime.fromtimestamp(result.timestamp)

        # Extract value, handling arrays
        value = result
        if hasattr(result, "tolist"):
            value = result.tolist()

        return EpicsValue(
            value=self._sanitize_value(value),
            status=getattr(result, "status", None),
            severity=getattr(result, "severity", None),
            timestamp=timestamp,
            units=getattr(result, "units", None),
            precision=getattr(result, "precision", None),
            upper_ctrl_limit=getattr(result, "upper_ctrl_limit", None),
            lower_ctrl_limit=getattr(result, "lower_ctrl_limit", None),
            connected=True,
            error=None,
        )

    async def connect_pv(self, pv_name: str) -> bool:
        """Pre-connect to a CA PV."""
        result = await connect(pv_name, timeout=self._conn_timeout, throw=False)
        return result.ok

    async def connect_many(self, pv_names: list[str]) -> None:
        """Pre-connect to multiple CA PVs."""
        await connect(pv_names, timeout=self._conn_timeout, throw=False)
        logger.info(f"[CA] Pre-connected to {len(pv_names)} PVs")

    async def get_single(self, pv_name: str) -> EpicsValue:
        """Read a single CA PV with metadata."""
        ioc_name = self._extract_ioc_name(pv_name)

        # Check circuit breaker first
        if self._circuit_manager and self._circuit_manager.is_open(ioc_name):
            logger.debug(f"[CA] Circuit open for {ioc_name}, skipping {pv_name}")
            return EpicsValue(
                value=None,
                connected=False,
                error=f"Circuit breaker open for {ioc_name}",
            )

        try:
            result = await caget(pv_name, format=FORMAT_TIME, timeout=self._timeout, throw=False)
            epics_value = self._augmented_to_epics_value(pv_name, result)

            # Record success/failure with circuit breaker
            if self._circuit_manager:
                if epics_value.connected:
                    self._circuit_manager._record_success(ioc_name)
                else:
                    self._circuit_manager._record_failure(ioc_name, Exception(epics_value.error or "Connection failed"))

            return epics_value
        except Exception as e:
            logger.error(f"[CA] Error getting {pv_name}: {e}")

            # Record failure with circuit breaker
            if self._circuit_manager:
                self._circuit_manager._record_failure(ioc_name, e)

            return EpicsValue(value=None, connected=False, error=str(e))

    async def get_many(self, pv_names: list[str]) -> dict[str, EpicsValue]:
        """
        Get values for multiple CA PVs in parallel.

        aioca handles parallel connections internally when given a list.
        """
        results = {}
        logger.info(f"[CA] Starting get_many for {len(pv_names)} PVs")

        try:
            # aioca caget with list returns list of AugmentedValues
            values = await caget(pv_names, format=FORMAT_TIME, timeout=self._timeout, throw=False)

            for pv_name, result in zip(pv_names, values):
                results[pv_name] = self._augmented_to_epics_value(pv_name, result)

        except Exception as e:
            logger.error(f"[CA] Batch read error: {e}")
            for pv_name in pv_names:
                if pv_name not in results:
                    results[pv_name] = EpicsValue(value=None, connected=False, error=str(e))

        logger.info(f"[CA] Completed get_many: {len(results)}/{len(pv_names)} PVs")
        return results

    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """Write a value to a single CA PV."""
        try:
            result = await caput(pv_name, value, timeout=self._timeout, wait=True, throw=False)
            if result.ok:
                return True, None
            return (
                False,
                f"Failed to write to {pv_name}: {getattr(result, 'errorcode', 'unknown')}",
            )
        except Exception as e:
            logger.error(f"[CA] Error putting {pv_name}: {e}")
            return False, str(e)

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """
        Put values to multiple CA PVs.

        aioca caput with lists writes in sequence if PVs are pre-connected.
        """
        results = {}
        pv_names = list(values.keys())
        pv_values = list(values.values())

        try:
            # Pre-connect all PVs for sequential write guarantee
            await connect(pv_names, timeout=self._conn_timeout, throw=False)

            # Write all values
            put_results = await caput(pv_names, pv_values, timeout=self._timeout, wait=True, throw=False)

            for pv_name, result in zip(pv_names, put_results):
                if result.ok:
                    results[pv_name] = (True, None)
                else:
                    results[pv_name] = (
                        False,
                        f"Failed: {getattr(result, 'errorcode', 'unknown')}",
                    )

        except Exception as e:
            logger.error(f"[CA] Batch put error: {e}")
            for pv_name in pv_names:
                if pv_name not in results:
                    results[pv_name] = (False, str(e))

        return results

    async def shutdown(self):
        """Cleanup CA adapter resources."""
        purge_channel_caches()
        logger.info("[CA] Adapter shutdown complete")
