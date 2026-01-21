import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional
import logging
import math

from aioca import caget, caput, connect, FORMAT_TIME, purge_channel_caches
from aiobreaker import CircuitBreakerError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Set EPICS environment BEFORE aioca import (in practice, set in __init__.py or app startup)
# These must be set before libca is loaded
if settings.epics_ca_addr_list:
    os.environ["EPICS_CA_ADDR_LIST"] = settings.epics_ca_addr_list
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = settings.epics_ca_auto_addr_list


@dataclass
class EpicsValue:
    """Container for EPICS PV value with metadata."""
    value: Any
    status: int | None = None
    severity: int | None = None
    timestamp: datetime | None = None
    units: str | None = None
    precision: int | None = None
    upper_ctrl_limit: float | None = None
    lower_ctrl_limit: float | None = None
    connected: bool = True
    error: str | None = None


class EpicsService:
    """
    Native async EPICS service using aioca.

    No ThreadPool needed - aioca is natively async.

    Features:
    - Circuit breaker integration for failure isolation
    - Per-IOC circuit breakers (extracted from PV name prefix)
    - Automatic recovery when IOCs become healthy
    """

    def __init__(self, enable_circuit_breaker: bool = True):
        self._timeout = settings.epics_ca_timeout
        self._conn_timeout = settings.epics_ca_conn_timeout
        self._chunk_size = settings.epics_chunk_size
        self._enable_circuit_breaker = enable_circuit_breaker
        self._circuit_manager = None

        # Lazily initialize circuit breaker to avoid import issues
        if self._enable_circuit_breaker:
            try:
                from app.services.circuit_breaker import get_circuit_breaker_manager
                self._circuit_manager = get_circuit_breaker_manager()
            except ImportError:
                logger.warning("Circuit breaker not available")

    def _extract_ioc_name(self, pv_name: str) -> str:
        """
        Extract IOC/subsystem name from PV name for circuit grouping.

        Examples:
            "LINAC:TEMP:1" -> "LINAC"
            "BPM:X:1" -> "BPM"
            "SYS:IOC:STATUS" -> "SYS:IOC"

        For PVs without a clear prefix, use "default".
        """
        parts = pv_name.split(":")
        if len(parts) >= 2:
            # Use first two parts as IOC identifier
            return f"{parts[0]}:{parts[1]}" if len(parts) > 2 else parts[0]
        return "default"

    def _sanitize_value(self, value: Any) -> Any:
        """Sanitize value for JSON storage (handle NaN/Inf)."""
        if value is None:
            return None
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
        if isinstance(value, list):
            return [self._sanitize_value(v) for v in value]
        if hasattr(value, 'tolist'):
            return self._sanitize_value(value.tolist())
        return value

    def _augmented_to_epics_value(self, pv_name: str, result) -> EpicsValue:
        """Convert aioca AugmentedValue to our EpicsValue dataclass."""
        if not result.ok:
            return EpicsValue(
                value=None,
                connected=False,
                error=f"Failed to read {pv_name}: {getattr(result, 'errorcode', 'unknown')}"
            )

        # Extract timestamp if available
        timestamp = None
        if hasattr(result, 'timestamp') and result.timestamp:
            timestamp = datetime.fromtimestamp(result.timestamp)

        # Extract value, handling arrays
        value = result
        if hasattr(result, 'tolist'):
            value = result.tolist()

        return EpicsValue(
            value=self._sanitize_value(value),
            status=getattr(result, 'status', None),
            severity=getattr(result, 'severity', None),
            timestamp=timestamp,
            units=getattr(result, 'units', None),
            precision=getattr(result, 'precision', None),
            upper_ctrl_limit=getattr(result, 'upper_ctrl_limit', None),
            lower_ctrl_limit=getattr(result, 'lower_ctrl_limit', None),
            connected=True,
            error=None
        )

    async def connect_pv(self, pv_name: str) -> bool:
        """Pre-connect to a PV."""
        result = await connect(pv_name, timeout=self._conn_timeout, throw=False)
        return result.ok

    async def connect_many(self, pv_names: list[str]) -> None:
        """Pre-connect to multiple PVs."""
        await connect(pv_names, timeout=self._conn_timeout, throw=False)
        logger.info(f"Pre-connected to {len(pv_names)} PVs")

    async def get_single(self, pv_name: str) -> EpicsValue:
        """Read a single PV with metadata."""
        ioc_name = self._extract_ioc_name(pv_name)

        # Check circuit breaker first
        if self._circuit_manager and self._circuit_manager.is_open(ioc_name):
            logger.debug(f"Circuit open for {ioc_name}, skipping {pv_name}")
            return EpicsValue(
                value=None,
                connected=False,
                error=f"Circuit breaker open for {ioc_name}"
            )

        try:
            result = await caget(
                pv_name,
                format=FORMAT_TIME,
                timeout=self._timeout,
                throw=False
            )
            epics_value = self._augmented_to_epics_value(pv_name, result)

            # Record success/failure with circuit breaker
            if self._circuit_manager:
                if epics_value.connected:
                    self._circuit_manager._record_success(ioc_name)
                else:
                    self._circuit_manager._record_failure(
                        ioc_name,
                        Exception(epics_value.error or "Connection failed")
                    )

            return epics_value
        except Exception as e:
            logger.error(f"Error getting {pv_name}: {e}")

            # Record failure with circuit breaker
            if self._circuit_manager:
                self._circuit_manager._record_failure(ioc_name, e)

            return EpicsValue(value=None, connected=False, error=str(e))

    async def get_many(self, pv_names: list[str]) -> dict[str, EpicsValue]:
        """
        Get values for multiple PVs in parallel.

        aioca handles parallel connections internally when given a list.
        """
        results = {}
        logger.info(f"Starting get_many for {len(pv_names)} PVs")

        try:
            # aioca caget with list returns list of AugmentedValues
            # throw=False returns values with .ok=False instead of raising
            values = await caget(
                pv_names,
                format=FORMAT_TIME,
                timeout=self._timeout,
                throw=False
            )

            for pv_name, result in zip(pv_names, values):
                results[pv_name] = self._augmented_to_epics_value(pv_name, result)

        except Exception as e:
            logger.error(f"Batch read error: {e}")
            for pv_name in pv_names:
                if pv_name not in results:
                    results[pv_name] = EpicsValue(
                        value=None, connected=False, error=str(e)
                    )

        logger.info(f"Completed get_many: {len(results)}/{len(pv_names)} PVs")
        return results

    async def get_many_with_progress(
        self,
        pv_names: list[str],
        progress_callback: Optional[Callable] = None
    ) -> dict[str, EpicsValue]:
        """
        Get values for multiple PVs with progress tracking.

        Processes in batches to allow progress updates while maintaining
        aioca's efficient parallel connections within each batch.
        """
        total_pvs = len(pv_names)
        logger.info(f"Starting get_many_with_progress for {total_pvs} PVs (using aioca)")

        if progress_callback:
            await progress_callback(0, total_pvs, "Starting to read PVs...")

        results = {}
        batch_size = self._chunk_size

        for i in range(0, total_pvs, batch_size):
            batch = pv_names[i:i + batch_size]

            try:
                # aioca handles parallel connections internally
                batch_values = await caget(
                    batch,
                    format=FORMAT_TIME,
                    timeout=self._timeout,
                    throw=False
                )

                for pv_name, result in zip(batch, batch_values):
                    results[pv_name] = self._augmented_to_epics_value(pv_name, result)

            except Exception as e:
                logger.error(f"Batch error: {e}")
                for pv_name in batch:
                    if pv_name not in results:
                        results[pv_name] = EpicsValue(
                            value=None, connected=False, error=str(e)
                        )

            # Report progress
            current = min(i + batch_size, total_pvs)
            connected_so_far = sum(1 for r in results.values() if r.connected)
            if progress_callback:
                await progress_callback(
                    current, total_pvs,
                    f"Read {current:,}/{total_pvs:,} PVs ({connected_so_far:,} connected)"
                )

            logger.info(f"Read {current:,}/{total_pvs:,} PVs ({connected_so_far} connected)")

        if progress_callback:
            connected_count = sum(1 for r in results.values() if r.connected)
            await progress_callback(
                total_pvs, total_pvs,
                f"Completed: {connected_count:,}/{total_pvs:,} PVs connected"
            )

        connected_count = sum(1 for r in results.values() if r.connected)
        logger.info(f"Completed get_many_with_progress: {connected_count}/{total_pvs} PVs connected")
        return results

    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """Write a value to a single PV."""
        try:
            result = await caput(
                pv_name,
                value,
                timeout=self._timeout,
                wait=True,
                throw=False
            )
            if result.ok:
                return True, None
            return False, f"Failed to write to {pv_name}: {getattr(result, 'errorcode', 'unknown')}"
        except Exception as e:
            logger.error(f"Error putting {pv_name}: {e}")
            return False, str(e)

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """
        Put values to multiple PVs.

        aioca caput with lists writes in sequence if PVs are pre-connected.
        """
        results = {}
        pv_names = list(values.keys())
        pv_values = list(values.values())

        try:
            # Pre-connect all PVs for sequential write guarantee
            await connect(pv_names, timeout=self._conn_timeout, throw=False)

            # Write all values - aioca handles the list
            put_results = await caput(
                pv_names,
                pv_values,
                timeout=self._timeout,
                wait=True,
                throw=False
            )

            for pv_name, result in zip(pv_names, put_results):
                if result.ok:
                    results[pv_name] = (True, None)
                else:
                    results[pv_name] = (
                        False,
                        f"Failed: {getattr(result, 'errorcode', 'unknown')}"
                    )

        except Exception as e:
            logger.error(f"Batch put error: {e}")
            for pv_name in pv_names:
                if pv_name not in results:
                    results[pv_name] = (False, str(e))

        return results

    async def shutdown(self):
        """Cleanup resources."""
        # aioca manages its own connections via libca
        # Can call purge_channel_caches() if needed
        purge_channel_caches()


# Singleton instance
_epics_service: EpicsService | None = None


def get_epics_service() -> EpicsService:
    """Get or create the EPICS service singleton."""
    global _epics_service
    if _epics_service is None:
        _epics_service = EpicsService()
    return _epics_service
