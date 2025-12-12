import asyncio
import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional
import logging

import epics

from app.config import get_settings

# Try to import p4p for optional faster backend
try:
    from p4p.client.thread import Context as P4PContext
    P4P_AVAILABLE = True
except ImportError:
    P4P_AVAILABLE = False

logger = logging.getLogger(__name__)
settings = get_settings()


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
    High-performance EPICS service for parallel PV operations.

    Uses connection pooling and batch operations for optimal throughput.
    """

    def __init__(self):
        # Set EPICS environment
        if settings.epics_ca_addr_list:
            os.environ["EPICS_CA_ADDR_LIST"] = settings.epics_ca_addr_list
        os.environ["EPICS_CA_AUTO_ADDR_LIST"] = settings.epics_ca_auto_addr_list

        # Thread pool for parallel EPICS operations
        self._executor = ThreadPoolExecutor(max_workers=settings.epics_max_workers)

        # Connection pool (PV name -> epics.PV object)
        self._pv_cache: dict[str, epics.PV] = {}
        self._cache_lock = asyncio.Lock()

        # Settings
        self._conn_timeout = settings.epics_ca_conn_timeout
        self._timeout = settings.epics_ca_timeout
        self._chunk_size = settings.epics_chunk_size

    async def connect_pv(self, pv_name: str) -> epics.PV:
        """Get or create a persistent PV connection."""
        async with self._cache_lock:
            if pv_name not in self._pv_cache:
                # Create PV in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                pv = await loop.run_in_executor(
                    self._executor,
                    lambda: epics.PV(
                        pv_name,
                        connection_timeout=self._conn_timeout,
                        auto_monitor=False
                    )
                )
                self._pv_cache[pv_name] = pv
            return self._pv_cache[pv_name]

    async def connect_many(self, pv_names: list[str]) -> None:
        """Pre-connect to multiple PVs (for warming cache)."""
        tasks = [self.connect_pv(name) for name in pv_names]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Pre-connected to {len(pv_names)} PVs")

    def _get_single(self, pv_name: str) -> EpicsValue:
        """Synchronous single PV get (runs in thread pool)."""
        try:
            # Try to get from cache first
            pv = self._pv_cache.get(pv_name)

            if pv is None:
                # Create new PV with auto_monitor=False for efficiency
                pv = epics.PV(
                    pv_name,
                    connection_timeout=self._conn_timeout,
                    auto_monitor=False
                )
                # Don't cache here - will be cached in get_many if needed

            # Wait for connection
            if not pv.wait_for_connection(timeout=self._conn_timeout):
                return EpicsValue(
                    value=None,
                    connected=False,
                    error=f"Failed to connect to {pv_name}"
                )

            # Get value with timeout
            value = pv.get(timeout=self._timeout, as_numpy=True)

            if value is None:
                return EpicsValue(
                    value=None,
                    connected=False,
                    error=f"Failed to read {pv_name}"
                )

            return EpicsValue(
                value=value.tolist() if hasattr(value, 'tolist') else value,
                status=pv.status,
                severity=pv.severity,
                timestamp=datetime.fromtimestamp(pv.timestamp) if pv.timestamp else None,
                units=pv.units,
                precision=pv.precision,
                upper_ctrl_limit=pv.upper_ctrl_limit,
                lower_ctrl_limit=pv.lower_ctrl_limit,
                connected=pv.connected
            )
        except Exception as e:
            logger.error(f"Error getting {pv_name}: {e}")
            return EpicsValue(
                value=None,
                connected=False,
                error=str(e)
            )

    async def get_single(self, pv_name: str) -> EpicsValue:
        """Async wrapper for single PV get."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._get_single, pv_name)

    def _connect_and_cache_pv(self, pv_name: str) -> epics.PV:
        """Connect to PV and add to cache (runs in thread pool)."""
        # Thread-safe check and insert
        if pv_name in self._pv_cache:
            return self._pv_cache[pv_name]

        # Create PV outside of cache first
        pv = epics.PV(
            pv_name,
            connection_timeout=self._conn_timeout,
            auto_monitor=False
        )

        # Only cache if connection succeeded
        if pv.connected or pv.wait_for_connection(timeout=self._conn_timeout):
            self._pv_cache[pv_name] = pv

        return pv

    async def get_many(self, pv_names: list[str]) -> dict[str, EpicsValue]:
        """
        Get values for multiple PVs in parallel.

        Uses chunked processing with frequent yields for optimal performance
        while keeping the event loop responsive.
        """
        results = {}
        logger.info(f"Starting get_many for {len(pv_names)} PVs")
        loop = asyncio.get_event_loop()

        # Read values in chunks (connection happens lazily in _get_single)
        for i in range(0, len(pv_names), self._chunk_size):
            chunk = pv_names[i:i + self._chunk_size]

            # Parallel get for this chunk
            futures = [
                loop.run_in_executor(self._executor, self._get_single, pv)
                for pv in chunk
            ]

            chunk_results = await asyncio.gather(*futures, return_exceptions=True)

            for pv_name, result in zip(chunk, chunk_results):
                if isinstance(result, Exception):
                    results[pv_name] = EpicsValue(
                        value=None,
                        connected=False,
                        error=str(result)
                    )
                else:
                    results[pv_name] = result

            # Log progress every 1000 PVs
            if (i + self._chunk_size) % 1000 == 0 or (i + self._chunk_size) >= len(pv_names):
                logger.info(f"Read {min(i + self._chunk_size, len(pv_names))}/{len(pv_names)} PVs")

            # Yield to event loop to allow other requests to be processed
            await asyncio.sleep(0)

        logger.info(f"Completed get_many: {len(results)}/{len(pv_names)} PVs")
        return results

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

    def _read_batch_threaded(self, pv_names: list[str]) -> dict[str, dict]:
        """
        Read a batch of PVs using caget_many in the current thread.

        This is faster than multiprocessing when called from a thread pool
        because it avoids process spawn overhead and IPC.
        """
        results = {}
        try:
            # caget_many connects to all PVs in parallel - very efficient
            values = epics.caget_many(
                pv_names,
                timeout=settings.epics_ca_timeout,
                connection_timeout=settings.epics_ca_conn_timeout,
                as_numpy=True
            )

            for pv_name, value in zip(pv_names, values):
                if value is None:
                    results[pv_name] = {
                        "value": None,
                        "connected": False,
                        "error": "Timeout or disconnected"
                    }
                else:
                    results[pv_name] = {
                        "value": self._sanitize_value(value),
                        "connected": True,
                        "error": None
                    }

        except Exception as e:
            logger.error(f"Batch read error: {e}")
            for pv_name in pv_names:
                results[pv_name] = {
                    "value": None,
                    "connected": False,
                    "error": str(e)
                }

        return results

    def _read_batch_p4p(self, pv_names: list[str]) -> dict[str, dict]:
        """
        Read a batch of PVs using p4p Context('ca') for CA compatibility.

        p4p can be faster than pyepics for large batches because:
        1. More efficient connection handling
        2. Better parallelism in the underlying library
        3. Less Python overhead
        """
        results = {}

        if not P4P_AVAILABLE:
            logger.error("p4p not available, falling back to pyepics")
            return self._read_batch_threaded(pv_names)

        try:
            # Create CA context (p4p supports CA protocol via 'ca' provider)
            with P4PContext('ca') as ctx:
                # p4p get() with multiple PVs returns a list
                # timeout is in seconds
                timeout = settings.epics_ca_timeout

                # Use get with throw=False to avoid exceptions on disconnected PVs
                values = ctx.get(pv_names, timeout=timeout, throw=False)

                for pv_name, value in zip(pv_names, values):
                    if value is None:
                        results[pv_name] = {
                            "value": None,
                            "connected": False,
                            "error": "Timeout or disconnected"
                        }
                    elif isinstance(value, Exception):
                        results[pv_name] = {
                            "value": None,
                            "connected": False,
                            "error": str(value)
                        }
                    else:
                        # p4p returns raw values or Value objects depending on type
                        try:
                            # Try to extract value if it's a Value object
                            if hasattr(value, 'value'):
                                raw_value = value.value
                            elif hasattr(value, 'tolist'):
                                raw_value = value.tolist()
                            else:
                                raw_value = value

                            results[pv_name] = {
                                "value": self._sanitize_value(raw_value),
                                "connected": True,
                                "error": None
                            }
                        except Exception as e:
                            results[pv_name] = {
                                "value": None,
                                "connected": False,
                                "error": f"Value extraction error: {e}"
                            }

        except Exception as e:
            logger.error(f"p4p batch read error: {e}")
            for pv_name in pv_names:
                if pv_name not in results:
                    results[pv_name] = {
                        "value": None,
                        "connected": False,
                        "error": str(e)
                    }

        return results

    async def get_many_with_progress(
        self,
        pv_names: list[str],
        progress_callback: Optional[Callable] = None
    ) -> dict[str, EpicsValue]:
        """
        Get values for multiple PVs with progress tracking.

        Args:
            pv_names: List of PV names to read
            progress_callback: Optional async callback(current, total, message) for progress updates

        Uses threading by default (faster, less overhead) or multiprocessing
        if configured. caget_many handles parallel connections internally.
        """
        total_pvs = len(pv_names)
        use_threading = settings.epics_use_threading
        backend = settings.epics_backend  # "pyepics" or "p4p"

        # Determine mode string for logging
        if backend == "p4p" and P4P_AVAILABLE:
            mode = "p4p"
        elif use_threading:
            mode = "threading (pyepics)"
        else:
            mode = "multiprocessing (pyepics)"

        logger.info(f"Starting get_many_with_progress for {total_pvs} PVs (using {mode})")

        if progress_callback:
            await progress_callback(0, total_pvs, "Starting to read PVs...")

        loop = asyncio.get_event_loop()
        results = {}

        # Batch size for progress updates - caget_many handles all PVs in batch in parallel
        batch_size = 5000  # Balance between progress updates and efficiency

        for i in range(0, total_pvs, batch_size):
            batch = pv_names[i:i + batch_size]

            if backend == "p4p" and P4P_AVAILABLE:
                # p4p backend: potentially faster for large batches
                batch_results = await loop.run_in_executor(
                    self._executor,
                    lambda b=batch: self._read_batch_p4p(b)
                )
            elif use_threading:
                # Threading: run caget_many directly in thread pool
                # caget_many releases GIL during I/O, so this is efficient
                batch_results = await loop.run_in_executor(
                    self._executor,
                    lambda b=batch: self._read_batch_threaded(b)
                )
            else:
                # Multiprocessing: use process pool (more overhead but true parallelism)
                from app.services.epics_worker import get_epics_process_pool
                process_pool = get_epics_process_pool()
                # Smaller batch per worker (500) = faster completion per batch
                # With 12 workers, 500 PVs each = 6000 PVs per round
                batch_results = await loop.run_in_executor(
                    None,
                    lambda b=batch: process_pool.read_pvs_sync(b, batch_size=500)
                )

            # Convert results to EpicsValue
            for pv_name, result in batch_results.items():
                if result.get("connected", False):
                    results[pv_name] = EpicsValue(
                        value=result.get("value"),
                        status=result.get("status"),
                        severity=result.get("severity"),
                        timestamp=None,
                        units=result.get("units"),
                        precision=result.get("precision"),
                        upper_ctrl_limit=result.get("upper_ctrl_limit"),
                        lower_ctrl_limit=result.get("lower_ctrl_limit"),
                        connected=True,
                        error=None
                    )
                else:
                    results[pv_name] = EpicsValue(
                        value=None,
                        connected=False,
                        error=result.get("error", "Unknown error")
                    )

            # Report progress after each batch
            current = min(i + batch_size, total_pvs)
            connected_so_far = sum(1 for r in results.values() if r.connected)
            if progress_callback:
                await progress_callback(current, total_pvs, f"Read {current:,}/{total_pvs:,} PVs ({connected_so_far:,} connected)")

            logger.info(f"Read {current:,}/{total_pvs:,} PVs ({connected_so_far} connected)")

            # Yield to event loop between batches
            await asyncio.sleep(0)

        if progress_callback:
            connected_count = sum(1 for r in results.values() if r.connected)
            await progress_callback(total_pvs, total_pvs, f"Completed: {connected_count:,}/{total_pvs:,} PVs connected")

        connected_count = sum(1 for r in results.values() if r.connected)
        logger.info(f"Completed get_many_with_progress: {connected_count}/{total_pvs} PVs connected")
        return results

    def _put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """Synchronous single PV put (runs in thread pool)."""
        try:
            result = epics.caput(
                pv_name,
                value,
                timeout=self._timeout,
                wait=True
            )
            if result is None:
                return False, f"Failed to write to {pv_name}"
            return True, None
        except Exception as e:
            logger.error(f"Error putting {pv_name}: {e}")
            return False, str(e)

    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """Async wrapper for single PV put."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._put_single,
            pv_name,
            value
        )

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """
        Put values to multiple PVs in parallel.

        Returns dict of {pv_name: (success, error_message)}.
        """
        results = {}
        pv_names = list(values.keys())

        # Process in chunks
        for i in range(0, len(pv_names), self._chunk_size):
            chunk = pv_names[i:i + self._chunk_size]

            loop = asyncio.get_event_loop()
            futures = [
                loop.run_in_executor(
                    self._executor,
                    self._put_single,
                    pv,
                    values[pv]
                )
                for pv in chunk
            ]

            chunk_results = await asyncio.gather(*futures, return_exceptions=True)

            for pv_name, result in zip(chunk, chunk_results):
                if isinstance(result, Exception):
                    results[pv_name] = (False, str(result))
                else:
                    results[pv_name] = result

            logger.debug(f"Put chunk {i // self._chunk_size + 1}, "
                        f"total: {len(results)}/{len(pv_names)}")

        return results

    async def shutdown(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=True)
        self._pv_cache.clear()


# Singleton instance
_epics_service: EpicsService | None = None


def get_epics_service() -> EpicsService:
    """Get or create the EPICS service singleton."""
    global _epics_service
    if _epics_service is None:
        _epics_service = EpicsService()
    return _epics_service
