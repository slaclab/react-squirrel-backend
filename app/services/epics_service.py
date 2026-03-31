import math
import logging
from typing import Any
from datetime import datetime
from collections.abc import Callable

from aioca import FORMAT_TIME, CANothing, caget, caput, connect, purge_channel_caches

from app.config import get_settings
from app.services.epics_types import EpicsValue
from app.services.pv_protocol import is_unprefixed, parse_pv_name
from app.services.pvaccess_service import get_pvaccess_service

logger = logging.getLogger(__name__)
settings = get_settings()


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
        self._unprefixed_pva_fallback = settings.epics_unprefixed_pva_fallback
        self._enable_circuit_breaker = enable_circuit_breaker
        self._circuit_manager = None
        self._pva_service = None

        # Lazily initialize circuit breaker to avoid import issues
        if self._enable_circuit_breaker:
            try:
                from app.services.circuit_breaker import get_circuit_breaker_manager

                self._circuit_manager = get_circuit_breaker_manager()
            except ImportError:
                logger.warning("Circuit breaker not available")

    def _get_pva_service(self):
        if self._pva_service is None:
            self._pva_service = get_pvaccess_service()
        return self._pva_service

    async def _get_single_pva(self, stripped: str, timeout: float | None = None) -> EpicsValue:
        pva = self._get_pva_service()
        return await pva.get_single(stripped, timeout=timeout)

    async def _get_single_ca(self, pv_name: str, stripped: str, timeout: float | None = None) -> EpicsValue:
        ioc_name = self._extract_ioc_name(stripped)
        effective_timeout = timeout if timeout is not None else self._timeout

        if self._circuit_manager and self._circuit_manager.is_open(ioc_name):
            logger.debug(f"Circuit open for {ioc_name}, skipping {pv_name}")
            return EpicsValue(value=None, connected=False, error=f"Circuit breaker open for {ioc_name}")

        try:
            result = await caget(stripped, format=FORMAT_TIME, timeout=effective_timeout, throw=False)
            epics_value = self._augmented_to_epics_value(pv_name, result)

            if self._circuit_manager:
                if epics_value.connected:
                    self._circuit_manager._record_success(ioc_name)
                else:
                    self._circuit_manager._record_failure(ioc_name, Exception(epics_value.error or "Connection failed"))

            return epics_value
        except Exception as e:
            logger.error(f"Error getting {pv_name}: {e}")
            if self._circuit_manager:
                self._circuit_manager._record_failure(ioc_name, e)
            return EpicsValue(value=None, connected=False, error=str(e))

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
        if hasattr(value, "tolist"):
            return self._sanitize_value(value.tolist())
        return value

    def _ca_error_message(self, error_msg: CANothing) -> str:
        """Convert CA error result to a more user-friendly message."""
        msg = str(error_msg).strip()
        if "user specified timeout" in msg.lower():
            return "Connection timeout"
        return msg if msg else "Unknown error"

    def _augmented_to_epics_value(self, pv_name: str, result) -> EpicsValue:
        """Convert aioca AugmentedValue to our EpicsValue dataclass."""
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
        """Pre-connect to a PV."""
        protocol, stripped = parse_pv_name(pv_name)
        if protocol == "pva":
            return True
        result = await connect(stripped, timeout=self._conn_timeout, throw=False)
        if result.ok:
            return True

        if self._unprefixed_pva_fallback and is_unprefixed(pv_name):
            pva_result = await self._get_single_pva(stripped, timeout=self._conn_timeout)
            return pva_result.connected
        return False

    async def connect_many(self, pv_names: list[str]) -> None:
        """Pre-connect to multiple PVs."""
        ca_pvs = []
        for pv_name in pv_names:
            protocol, stripped = parse_pv_name(pv_name)
            if protocol == "ca":
                ca_pvs.append(stripped)
        if ca_pvs:
            await connect(ca_pvs, timeout=self._conn_timeout, throw=False)
            logger.info(f"Pre-connected to {len(ca_pvs)} CA PVs")

    async def get_single(self, pv_name: str, timeout: float | None = None) -> EpicsValue:
        """Read a single PV with metadata."""
        protocol, stripped = parse_pv_name(pv_name)
        if protocol == "pva":
            return await self._get_single_pva(stripped, timeout=timeout)

        ca_result = await self._get_single_ca(pv_name, stripped, timeout=timeout)
        if ca_result.connected:
            return ca_result

        if self._unprefixed_pva_fallback and is_unprefixed(pv_name):
            pva_result = await self._get_single_pva(stripped, timeout=timeout)
            if pva_result.connected:
                return pva_result
        return ca_result

    async def get_many(self, pv_names: list[str]) -> dict[str, EpicsValue]:
        """
        Get values for multiple PVs in parallel.

        aioca handles parallel connections internally when given a list.
        """
        results: dict[str, EpicsValue] = {}
        logger.info(f"Starting get_many for {len(pv_names)} PVs")

        ca_pairs: list[tuple[str, str]] = []
        pva_pairs: list[tuple[str, str]] = []
        unprefixed_pairs: list[tuple[str, str]] = []

        for pv_name in pv_names:
            protocol, stripped = parse_pv_name(pv_name)
            if protocol == "pva":
                pva_pairs.append((pv_name, stripped))
            else:
                ca_pairs.append((pv_name, stripped))
                if is_unprefixed(pv_name):
                    unprefixed_pairs.append((pv_name, stripped))

        try:
            if ca_pairs:
                ca_names = [stripped for _, stripped in ca_pairs]
                values = await caget(ca_names, format=FORMAT_TIME, timeout=self._timeout, throw=False)
                for (original, _), result in zip(ca_pairs, values):
                    results[original] = self._augmented_to_epics_value(original, result)
        except Exception as e:
            logger.error(f"Batch CA read error: {e}")
            for pv_name, _ in ca_pairs:
                if pv_name not in results:
                    results[pv_name] = EpicsValue(value=None, connected=False, error=str(e))

        if pva_pairs:
            try:
                pva = self._get_pva_service()
                pva_names = [stripped for _, stripped in pva_pairs]
                pva_results = await pva.get_many(pva_names)
                for original, stripped in pva_pairs:
                    results[original] = pva_results.get(
                        stripped, EpicsValue(value=None, connected=False, error="PVA read failed")
                    )
            except Exception as e:
                logger.error(f"Batch PVA read error: {e}")
                for original, _ in pva_pairs:
                    if original not in results:
                        results[original] = EpicsValue(value=None, connected=False, error=str(e))

        if self._unprefixed_pva_fallback and unprefixed_pairs:
            fallback_pairs = []
            for original, stripped in unprefixed_pairs:
                existing = results.get(original)
                if existing is None or not existing.connected:
                    fallback_pairs.append((original, stripped))
            if fallback_pairs:
                try:
                    pva = self._get_pva_service()
                    fallback_names = [stripped for _, stripped in fallback_pairs]
                    pva_results = await pva.get_many(fallback_names)
                    for original, stripped in fallback_pairs:
                        pva_result = pva_results.get(stripped)
                        if pva_result and pva_result.connected:
                            results[original] = pva_result
                except Exception as e:
                    logger.error(f"Batch unprefixed PVA fallback read error: {e}")

        logger.info(f"Completed get_many: {len(results)}/{len(pv_names)} PVs")
        return results

    async def get_many_with_progress(
        self, pv_names: list[str], progress_callback: Callable | None = None
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

        results: dict[str, EpicsValue] = {}
        batch_size = self._chunk_size

        ca_pairs: list[tuple[str, str]] = []
        pva_pairs: list[tuple[str, str]] = []
        unprefixed_pairs: list[tuple[str, str]] = []
        for pv_name in pv_names:
            protocol, stripped = parse_pv_name(pv_name)
            if protocol == "pva":
                pva_pairs.append((pv_name, stripped))
            else:
                ca_pairs.append((pv_name, stripped))
                if is_unprefixed(pv_name):
                    unprefixed_pairs.append((pv_name, stripped))

        total_ca = len(ca_pairs)
        for i in range(0, total_ca, batch_size):
            batch_pairs = ca_pairs[i : i + batch_size]
            batch_names = [stripped for _, stripped in batch_pairs]

            try:
                # aioca handles parallel connections internally
                batch_values = await caget(batch_names, format=FORMAT_TIME, timeout=self._timeout, throw=False)

                for (original, _), result in zip(batch_pairs, batch_values):
                    results[original] = self._augmented_to_epics_value(original, result)

            except Exception as e:
                logger.error(f"Batch CA error: {e}")
                for pv_name, _ in batch_pairs:
                    if pv_name not in results:
                        results[pv_name] = EpicsValue(value=None, connected=False, error=str(e))

            # Report progress
            current = min(i + batch_size, total_ca)
            connected_so_far = sum(1 for r in results.values() if r.connected)
            if progress_callback:
                await progress_callback(
                    current, total_pvs, f"Read {current:,}/{total_pvs:,} PVs ({connected_so_far:,} connected)"
                )

            logger.info(f"Read {current:,}/{total_pvs:,} PVs ({connected_so_far} connected)")

        if pva_pairs:
            try:
                pva = self._get_pva_service()
                pva_names = [stripped for _, stripped in pva_pairs]

                async def pva_progress(current: int, total: int, message: str) -> None:
                    if progress_callback:
                        await progress_callback(total_ca + current, total_pvs, message)

                pva_results = await pva.get_many_with_progress(pva_names, pva_progress if progress_callback else None)
                for original, stripped in pva_pairs:
                    results[original] = pva_results.get(
                        stripped, EpicsValue(value=None, connected=False, error="PVA read failed")
                    )
            except Exception as e:
                logger.error(f"PVA progress read error: {e}")
                for original, _ in pva_pairs:
                    if original not in results:
                        results[original] = EpicsValue(value=None, connected=False, error=str(e))

        if self._unprefixed_pva_fallback and unprefixed_pairs:
            fallback_pairs = []
            for original, stripped in unprefixed_pairs:
                existing = results.get(original)
                if existing is None or not existing.connected:
                    fallback_pairs.append((original, stripped))

            if fallback_pairs:
                try:
                    pva = self._get_pva_service()
                    fallback_names = [stripped for _, stripped in fallback_pairs]
                    fallback_results = await pva.get_many_with_progress(fallback_names, None)
                    for original, stripped in fallback_pairs:
                        pva_result = fallback_results.get(stripped)
                        if pva_result and pva_result.connected:
                            results[original] = pva_result
                except Exception as e:
                    logger.error(f"PVA fallback progress read error: {e}")

        if progress_callback:
            connected_count = sum(1 for r in results.values() if r.connected)
            await progress_callback(total_pvs, total_pvs, f"Completed: {connected_count:,}/{total_pvs:,} PVs connected")

        connected_count = sum(1 for r in results.values() if r.connected)
        logger.info(f"Completed get_many_with_progress: {connected_count}/{total_pvs} PVs connected")
        return results

    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """Write a value to a single PV."""
        protocol, stripped = parse_pv_name(pv_name)
        if protocol == "pva":
            pva = self._get_pva_service()
            return await pva.put_single(stripped, value)

        try:
            result = await caput(stripped, value, timeout=self._timeout, wait=True, throw=False)
            if result.ok:
                return True, None
            ca_error = f"Failed to write to {pv_name}: {getattr(result, 'errorcode', 'unknown')}"
            if self._unprefixed_pva_fallback and is_unprefixed(pv_name):
                pva = self._get_pva_service()
                pva_ok, pva_error = await pva.put_single(stripped, value)
                if pva_ok:
                    return True, None
                return False, f"{ca_error}; PVA fallback failed: {pva_error}"
            return False, ca_error
        except Exception as e:
            logger.error(f"Error putting {pv_name}: {e}")
            if self._unprefixed_pva_fallback and is_unprefixed(pv_name):
                pva = self._get_pva_service()
                pva_ok, pva_error = await pva.put_single(stripped, value)
                if pva_ok:
                    return True, None
                return False, f"{e}; PVA fallback failed: {pva_error}"
            return False, str(e)

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """
        Put values to multiple PVs.

        aioca caput with lists writes in sequence if PVs are pre-connected.
        """
        results: dict[str, tuple[bool, str | None]] = {}
        ca_pairs: list[tuple[str, str]] = []
        pva_pairs: list[tuple[str, str]] = []
        unprefixed_pairs: list[tuple[str, str]] = []

        try:
            for pv_name, pv_value in values.items():
                protocol, stripped = parse_pv_name(pv_name)
                if protocol == "pva":
                    pva_pairs.append((pv_name, stripped))
                else:
                    ca_pairs.append((pv_name, stripped))
                    if is_unprefixed(pv_name):
                        unprefixed_pairs.append((pv_name, stripped))

            if ca_pairs:
                pv_names = [stripped for _, stripped in ca_pairs]
                pv_values = [values[original] for original, _ in ca_pairs]

                # Pre-connect all PVs for sequential write guarantee
                await connect(pv_names, timeout=self._conn_timeout, throw=False)

                # Write all values - aioca handles the list
                put_results = await caput(pv_names, pv_values, timeout=self._timeout, wait=True, throw=False)

                for (original, _), result in zip(ca_pairs, put_results):
                    if result.ok:
                        results[original] = (True, None)
                    else:
                        results[original] = (False, self._ca_error_message(result))

        except Exception as e:
            logger.error(f"Batch put error: {e}")
            for pv_name, _ in ca_pairs:
                if pv_name not in results:
                    results[pv_name] = (False, str(e))

        if pva_pairs:
            try:
                pva = self._get_pva_service()
                pva_values = {stripped: values[original] for original, stripped in pva_pairs}
                pva_results = await pva.put_many(pva_values)
                for original, stripped in pva_pairs:
                    results[original] = pva_results.get(stripped, (False, "PVA write failed"))
            except Exception as e:
                logger.error(f"PVA put_many error: {e}")
                for original, _ in pva_pairs:
                    if original not in results:
                        results[original] = (False, str(e))

        if self._unprefixed_pva_fallback and unprefixed_pairs:
            fallback_values: dict[str, Any] = {}
            key_to_original: dict[str, str] = {}
            for original, stripped in unprefixed_pairs:
                ok, _ = results.get(original, (False, None))
                if not ok:
                    fallback_values[stripped] = values[original]
                    key_to_original[stripped] = original

            if fallback_values:
                try:
                    pva = self._get_pva_service()
                    fallback_results = await pva.put_many(fallback_values)
                    for stripped, (ok, err) in fallback_results.items():
                        original = key_to_original[stripped]
                        if ok:
                            results[original] = (True, None)
                        else:
                            prev_ok, prev_err = results.get(original, (False, None))
                            if not prev_ok:
                                if prev_err:
                                    results[original] = (False, f"{prev_err}; PVA fallback failed: {err}")
                                else:
                                    results[original] = (False, err)
                except Exception as e:
                    logger.error(f"PVA put_many fallback error: {e}")

        return results

    async def put_many_with_progress(
        self,
        values: dict[str, Any],
        progress_callback: Callable | None = None,
    ) -> dict[str, tuple[bool, str | None]]:
        """
        Put values to multiple PVs with progress tracking.
        Can be used to update the user on progress when a snapshot restore is initiated.
        """
        total_pvs = len(values)
        results: dict[str, tuple[bool, str | None]] = {}

        logger.info(f"Starting put_many_with_progress for {total_pvs} PVs")

        if progress_callback:
            await progress_callback(0, total_pvs, f"Starting restore of {total_pvs:,} PVs")

        items = list(values.items())
        batch_size = self._chunk_size

        for i in range(0, total_pvs, batch_size):
            batch_items = items[i : i + batch_size]
            batch_values = dict(batch_items)

            try:
                batch_results = await self.put_many(batch_values)
                results.update(batch_results)
            except Exception as e:
                logger.error(f"Chunk put error ({i}-{i + len(batch_items)}): {e}")
                for pv_name, _ in batch_items:
                    if pv_name not in results:
                        results[pv_name] = (False, str(e))

            current = min(i + batch_size, total_pvs)
            success_count = sum(1 for ok, _ in results.values() if ok)

            if progress_callback:
                await progress_callback(
                    current,
                    total_pvs,
                    f"{current:,}/{total_pvs:,} PVs",
                )

            logger.info(f"Restored {current:,}/{total_pvs:,} PVs " f"({success_count:,} successful)")

        logger.info(f"Completed put_many_with_progress: {len(results)}/{total_pvs} PVs processed")
        return results

    async def shutdown(self):
        """Cleanup resources."""
        # aioca manages its own connections via libca
        # Can call purge_channel_caches() if needed
        purge_channel_caches()
        if self._pva_service is not None:
            await self._pva_service.shutdown()


# Singleton instance
_epics_service: EpicsService | None = None


def get_epics_service() -> EpicsService:
    """Get or create the EPICS service singleton."""
    global _epics_service
    if _epics_service is None:
        _epics_service = EpicsService()
    return _epics_service
