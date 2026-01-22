"""
PV Access (PVA) protocol adapter using p4p.

This adapter wraps the p4p library to provide PVA protocol support
within the unified protocol adapter framework.

If p4p is not installed, this adapter gracefully degrades and returns
error responses for all operations.
"""

import asyncio
import logging
from typing import Any
from datetime import datetime

from app.config import get_settings
from app.services.adapters.base_adapter import EpicsValue, BaseAdapter

logger = logging.getLogger(__name__)
settings = get_settings()

# Gracefully handle missing p4p dependency
_P4P_AVAILABLE = False
Context = None
Disconnected = None
P4PTimeoutError = None

try:
    from p4p.client.thread import Context, Disconnected
    from p4p.client.thread import TimeoutError as P4PTimeoutError

    _P4P_AVAILABLE = True
except ImportError:
    logger.warning("[PVA] p4p library not installed. PVA protocol support disabled. " "Install with: pip install p4p")


def is_pva_available() -> bool:
    """Check if PVA protocol support is available."""
    return _P4P_AVAILABLE


class PVAAdapter(BaseAdapter):
    """
    PV Access protocol adapter using p4p.

    This adapter handles all PVA-specific operations including structured
    data types (NTScalar, NTTable, etc.) and metadata extraction.

    If p4p is not installed, all operations return error responses.
    """

    def __init__(self, enable_circuit_breaker: bool = True):
        self._timeout = settings.epics_pva_timeout
        self._enable_circuit_breaker = enable_circuit_breaker
        self._circuit_manager = None
        self._context = None
        self._available = _P4P_AVAILABLE

        if not self._available:
            logger.warning("[PVA] Adapter initialized in degraded mode (p4p not installed)")
            return

        # Initialize p4p Context for PVA operations
        # Using 'pva' provider for PV Access protocol
        self._context = Context("pva")

        # Lazily initialize circuit breaker
        if self._enable_circuit_breaker:
            try:
                from app.services.circuit_breaker import get_circuit_breaker_manager

                self._circuit_manager = get_circuit_breaker_manager()
            except ImportError:
                logger.warning("Circuit breaker not available for PVA adapter")

        logger.info("[PVA] Adapter initialized")

    def _extract_ioc_name(self, pv_name: str) -> str:
        """
        Extract IOC/subsystem name from PV name for circuit grouping.

        Same logic as CA adapter for consistency.
        """
        parts = pv_name.split(":")
        if len(parts) >= 2:
            return f"{parts[0]}:{parts[1]}" if len(parts) > 2 else parts[0]
        return "default"

    def _serialize_pva_value(self, value: Any) -> Any:
        """
        Serialize PVA structured data to JSON-compatible format.

        Handles PVA normative types (NTScalar, NTTable, etc.) by converting
        them to dictionaries that can be JSON-serialized.
        """
        if value is None:
            return None

        # Handle p4p Value (structured type)
        if hasattr(value, "todict"):
            # Convert to dict for JSON serialization
            return value.todict()

        # Handle numpy arrays
        if hasattr(value, "tolist"):
            return value.tolist()

        # Handle dictionaries recursively
        if isinstance(value, dict):
            return {k: self._serialize_pva_value(v) for k, v in value.items()}

        # Handle lists recursively
        if isinstance(value, (list, tuple)):
            return [self._serialize_pva_value(item) for item in value]

        # Primitive types pass through
        return value

    def _extract_epics_value_from_pva(self, pv_name: str, pva_value: Any) -> EpicsValue:
        """
        Convert PVA value to EpicsValue dataclass.

        Extracts metadata from PVA normative types and handles
        both scalar and structured data.
        """
        try:
            # Check if it's a normative type with metadata
            if hasattr(pva_value, "value"):
                # NTScalar, NTScalarArray, etc.
                value = pva_value.value

                # Extract timestamp
                timestamp = None
                if hasattr(pva_value, "timeStamp"):
                    ts = pva_value.timeStamp
                    if hasattr(ts, "secondsPastEpoch"):
                        timestamp = datetime.fromtimestamp(ts.secondsPastEpoch)

                # Extract alarm information
                severity = None
                status = None
                if hasattr(pva_value, "alarm"):
                    alarm = pva_value.alarm
                    severity = getattr(alarm, "severity", None)
                    status = getattr(alarm, "message", None)

                # Extract display information
                units = None
                precision = None
                upper_ctrl_limit = None
                lower_ctrl_limit = None
                if hasattr(pva_value, "display"):
                    display = pva_value.display
                    units = getattr(display, "units", None)
                    precision = getattr(display, "precision", None)
                if hasattr(pva_value, "control"):
                    control = pva_value.control
                    upper_ctrl_limit = getattr(control, "limitHigh", None)
                    lower_ctrl_limit = getattr(control, "limitLow", None)

                return EpicsValue(
                    value=self._sanitize_value(self._serialize_pva_value(value)),
                    status=status,
                    severity=severity,
                    timestamp=timestamp,
                    units=units,
                    precision=precision,
                    upper_ctrl_limit=upper_ctrl_limit,
                    lower_ctrl_limit=lower_ctrl_limit,
                    connected=True,
                    error=None,
                )

            # Non-normative type or plain value - serialize as-is
            return EpicsValue(
                value=self._sanitize_value(self._serialize_pva_value(pva_value)),
                connected=True,
                error=None,
            )

        except Exception as e:
            logger.error(f"[PVA] Error extracting value from {pv_name}: {e}")
            return EpicsValue(value=None, connected=False, error=f"Value extraction error: {e}")

    async def connect_pv(self, pv_name: str) -> bool:
        """
        Pre-connect to a PVA PV.

        Note: p4p doesn't have explicit pre-connect, so this is a no-op.
        """
        if not self._available:
            return False
        # p4p handles connections automatically on first operation
        return True

    async def connect_many(self, pv_names: list[str]) -> None:
        """Pre-connect to multiple PVA PVs (no-op for p4p)."""
        if not self._available:
            logger.warning(f"[PVA] Cannot pre-connect {len(pv_names)} PVs - p4p not installed")
            return
        logger.info(f"[PVA] Pre-connect request for {len(pv_names)} PVs (no-op)")

    async def get_single(self, pv_name: str, timeout: float | None = None) -> EpicsValue:
        """Read a single PVA PV with metadata."""
        if not self._available:
            return EpicsValue(
                value=None,
                connected=False,
                error="PVA protocol not available (p4p not installed)",
            )

        ioc_name = self._extract_ioc_name(pv_name)
        effective_timeout = timeout if timeout is not None else self._timeout

        # Check circuit breaker first
        if self._circuit_manager and self._circuit_manager.is_open(ioc_name):
            logger.debug(f"[PVA] Circuit open for {ioc_name}, skipping {pv_name}")
            return EpicsValue(
                value=None,
                connected=False,
                error=f"Circuit breaker open for {ioc_name}",
            )

        try:
            # Run blocking p4p operation in thread pool
            # p4p Context.get() is synchronous, so we use asyncio.to_thread
            pva_value = await asyncio.to_thread(self._context.get, pv_name, timeout=effective_timeout)

            epics_value = self._extract_epics_value_from_pva(pv_name, pva_value)

            # Record success/failure with circuit breaker
            if self._circuit_manager:
                if epics_value.connected:
                    self._circuit_manager._record_success(ioc_name)
                else:
                    self._circuit_manager._record_failure(ioc_name, Exception(epics_value.error or "Connection failed"))

            return epics_value

        except P4PTimeoutError as e:
            logger.error(f"[PVA] Timeout getting {pv_name}: {e}")
            if self._circuit_manager:
                self._circuit_manager._record_failure(ioc_name, e)
            return EpicsValue(value=None, connected=False, error=f"Timeout: {e}")

        except Disconnected as e:
            logger.error(f"[PVA] Disconnected from {pv_name}: {e}")
            if self._circuit_manager:
                self._circuit_manager._record_failure(ioc_name, e)
            return EpicsValue(value=None, connected=False, error=f"Disconnected: {e}")

        except Exception as e:
            logger.error(f"[PVA] Error getting {pv_name}: {e}")
            if self._circuit_manager:
                self._circuit_manager._record_failure(ioc_name, e)
            return EpicsValue(value=None, connected=False, error=str(e))

    async def get_many(self, pv_names: list[str]) -> dict[str, EpicsValue]:
        """
        Get values for multiple PVA PVs.

        p4p doesn't have built-in batch operations, so we fetch in parallel
        using asyncio tasks.
        """
        logger.info(f"[PVA] Starting get_many for {len(pv_names)} PVs")

        # Create tasks for parallel fetching
        tasks = [self.get_single(pv_name) for pv_name in pv_names]

        # Wait for all tasks to complete, capturing exceptions per-task
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # Build results dictionary, handling any exceptions
        results = {}
        for pv_name, result in zip(pv_names, results_list):
            if isinstance(result, Exception):
                logger.error(f"[PVA] Exception getting {pv_name}: {result}")
                results[pv_name] = EpicsValue(value=None, connected=False, error=str(result))
            else:
                results[pv_name] = result

        logger.info(f"[PVA] Completed get_many: {len(results)}/{len(pv_names)} PVs")
        return results

    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """Write a value to a single PVA PV."""
        if not self._available:
            return False, "PVA protocol not available (p4p not installed)"

        try:
            # Run blocking p4p operation in thread pool
            await asyncio.to_thread(self._context.put, pv_name, value, timeout=self._timeout)
            return True, None

        except P4PTimeoutError as e:
            logger.error(f"[PVA] Timeout putting {pv_name}: {e}")
            return False, f"Timeout: {e}"

        except Disconnected as e:
            logger.error(f"[PVA] Disconnected from {pv_name}: {e}")
            return False, f"Disconnected: {e}"

        except Exception as e:
            logger.error(f"[PVA] Error putting {pv_name}: {e}")
            return False, str(e)

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """
        Put values to multiple PVA PVs.

        Since p4p doesn't have batch put, we write in parallel using tasks.
        """
        # Create tasks for parallel writes
        tasks = [self.put_single(pv_name, value) for pv_name, value in values.items()]
        pv_names = list(values.keys())

        # Wait for all tasks to complete, capturing exceptions per-task
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # Build results dictionary, handling any exceptions
        results = {}
        for pv_name, result in zip(pv_names, results_list):
            if isinstance(result, Exception):
                logger.error(f"[PVA] Exception putting {pv_name}: {result}")
                results[pv_name] = (False, str(result))
            else:
                results[pv_name] = result

        return results

    async def shutdown(self):
        """Cleanup PVA adapter resources."""
        if not self._available or self._context is None:
            return

        try:
            # Close p4p context
            self._context.close()
            logger.info("[PVA] Adapter shutdown complete")
        except Exception as e:
            logger.warning(f"[PVA] Error during shutdown: {e}")
