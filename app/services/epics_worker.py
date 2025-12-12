"""
Multiprocessing-based EPICS worker to bypass Python GIL.

This module runs EPICS operations in a separate process pool,
completely avoiding GIL contention with the main FastAPI event loop.

IMPORTANT: Uses 'spawn' context to avoid EPICS CA issues with fork().
Each worker process gets a fresh CA context.
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp

# Force spawn context to avoid EPICS CA fork issues
# Fork doesn't work well with CA because the CA context doesn't survive
mp_context = mp.get_context('spawn')

# Configure logging for worker processes
logger = logging.getLogger(__name__)

# Global CA context for each worker process
_worker_ca_initialized = False


@dataclass
class EpicsResult:
    """Result from an EPICS PV read operation."""
    pv_name: str
    value: Any = None
    status: int | None = None
    severity: int | None = None
    timestamp: datetime | None = None
    units: str | None = None
    precision: int | None = None
    upper_ctrl_limit: float | None = None
    lower_ctrl_limit: float | None = None
    connected: bool = True
    error: str | None = None


def _init_worker(ca_addr_list: str, ca_auto_addr_list: str):
    """Initialize EPICS environment in worker process."""
    global _worker_ca_initialized

    # Set environment before importing epics
    if ca_addr_list:
        os.environ["EPICS_CA_ADDR_LIST"] = ca_addr_list
    os.environ["EPICS_CA_AUTO_ADDR_LIST"] = ca_auto_addr_list

    # Log the configuration being used
    logger.info(f"Worker {os.getpid()} EPICS config: ADDR_LIST='{ca_addr_list}', AUTO_ADDR_LIST='{ca_auto_addr_list}'")

    # Import and initialize CA fresh in this process
    import epics
    import epics.ca as ca

    # Clear any stale CA state and reinitialize
    try:
        ca.finalize_libca()
    except Exception:
        pass  # May not be initialized yet

    # Force CA to reinitialize
    ca.initialize_libca()
    _worker_ca_initialized = True

    # Verify environment was set
    actual_addr = os.environ.get("EPICS_CA_ADDR_LIST", "NOT SET")
    actual_auto = os.environ.get("EPICS_CA_AUTO_ADDR_LIST", "NOT SET")
    logger.info(f"Worker {os.getpid()} initialized - actual env: ADDR_LIST='{actual_addr}', AUTO='{actual_auto}'")


# Counter for diagnostic logging (first N PVs per process)
_pv_read_count = 0

def _read_single_pv(args: tuple) -> dict:
    """
    Read a single PV value. Runs in worker process.

    Args:
        args: Tuple of (pv_name, conn_timeout, read_timeout)

    Returns:
        Dict with PV data (serializable for IPC)
    """
    global _pv_read_count
    pv_name, conn_timeout, read_timeout = args

    try:
        import epics

        # Single caget call with short timeout - skip metadata for speed
        # Use very short timeout to fail fast on disconnected PVs
        value = epics.caget(
            pv_name,
            timeout=conn_timeout,  # Short timeout - fail fast
            as_numpy=True
        )

        # Log first 3 PV reads per process for diagnostics
        _pv_read_count += 1
        if _pv_read_count <= 3:
            logger.info(f"Worker {os.getpid()} PV #{_pv_read_count}: {pv_name} = {value}")

        if value is None:
            return {
                "pv_name": pv_name,
                "value": None,
                "connected": False,
                "error": f"Timeout or disconnected: {pv_name}"
            }

        # Convert numpy to list if needed
        if hasattr(value, 'tolist'):
            value = value.tolist()

        # Return just the value - skip metadata for speed
        # Metadata can be fetched separately if needed
        return {
            "pv_name": pv_name,
            "value": value,
            "status": None,
            "severity": None,
            "timestamp": None,
            "units": None,
            "precision": None,
            "upper_ctrl_limit": None,
            "lower_ctrl_limit": None,
            "connected": True,
            "error": None
        }

    except Exception as e:
        return {
            "pv_name": pv_name,
            "value": None,
            "connected": False,
            "error": str(e)
        }


def _read_pv_batch(args: tuple) -> list[dict]:
    """
    Read a batch of PVs using caget_many for maximum speed.

    caget_many connects to all PVs in parallel, which is MUCH faster
    than sequential caget calls (30ms per PV sequentially vs parallel).
    """
    pv_names, conn_timeout, read_timeout = args
    results = []

    try:
        import epics

        # Use caget_many for parallel connection and reading
        # This is orders of magnitude faster than sequential caget
        values = epics.caget_many(
            pv_names,
            timeout=conn_timeout,
            connection_timeout=conn_timeout,
            as_numpy=True
        )

        # Process results
        for i, (pv_name, value) in enumerate(zip(pv_names, values)):
            if value is None:
                results.append({
                    "pv_name": pv_name,
                    "value": None,
                    "connected": False,
                    "error": f"Timeout or disconnected: {pv_name}"
                })
            else:
                # Convert numpy to list if needed
                if hasattr(value, 'tolist'):
                    value = value.tolist()

                results.append({
                    "pv_name": pv_name,
                    "value": value,
                    "status": None,
                    "severity": None,
                    "timestamp": None,
                    "units": None,
                    "precision": None,
                    "upper_ctrl_limit": None,
                    "lower_ctrl_limit": None,
                    "connected": True,
                    "error": None
                })

        # Log batch stats for diagnostics
        connected = sum(1 for r in results if r["connected"])
        logger.info(f"Worker {os.getpid()} batch: {connected}/{len(pv_names)} connected")

    except Exception as e:
        logger.error(f"Worker {os.getpid()} batch error: {e}")
        # Return all as failed
        for pv_name in pv_names:
            results.append({
                "pv_name": pv_name,
                "value": None,
                "connected": False,
                "error": str(e)
            })

    return results


class EpicsProcessPool:
    """
    Process pool for EPICS operations.

    Uses multiprocessing with 'spawn' context to completely bypass GIL
    and avoid EPICS CA fork issues. Each worker process gets a fresh CA context.
    """

    def __init__(
        self,
        max_workers: int = None,
        ca_addr_list: str = "",
        ca_auto_addr_list: str = "YES",
        conn_timeout: float = 0.5,
        read_timeout: float = 1.0
    ):
        # Default to CPU count * 4 for I/O bound work, cap at 16
        if max_workers is None:
            max_workers = min(mp.cpu_count() * 4, 16)

        self.max_workers = max_workers
        self.ca_addr_list = ca_addr_list
        self.ca_auto_addr_list = ca_auto_addr_list
        self.conn_timeout = conn_timeout
        self.read_timeout = read_timeout
        self._pool: ProcessPoolExecutor | None = None

    def _get_pool(self) -> ProcessPoolExecutor:
        """Get or create the process pool using spawn context."""
        if self._pool is None:
            # Use spawn context to avoid EPICS CA fork issues
            self._pool = ProcessPoolExecutor(
                max_workers=self.max_workers,
                mp_context=mp_context,  # Use spawn instead of fork
                initializer=_init_worker,
                initargs=(self.ca_addr_list, self.ca_auto_addr_list)
            )
            logger.info(f"Created EPICS process pool with {self.max_workers} workers (spawn context)")
        return self._pool

    def read_pvs_sync(
        self,
        pv_names: list[str],
        batch_size: int = 50,
        progress_callback=None
    ) -> dict[str, dict]:
        """
        Read multiple PVs using process pool (synchronous).

        Args:
            pv_names: List of PV names to read
            batch_size: Number of PVs per worker batch
            progress_callback: Optional callback(current, total, message)

        Returns:
            Dict mapping pv_name -> result dict
        """
        pool = self._get_pool()
        results = {}
        total = len(pv_names)

        # Split into batches for workers
        batches = []
        for i in range(0, total, batch_size):
            batch = pv_names[i:i + batch_size]
            batches.append((batch, self.conn_timeout, self.read_timeout))

        logger.info(f"Reading {total} PVs in {len(batches)} batches using {self.max_workers} workers")

        # Submit all batches
        futures = {pool.submit(_read_pv_batch, batch): i for i, batch in enumerate(batches)}

        completed = 0
        for future in as_completed(futures):
            try:
                batch_results = future.result(timeout=30)  # 30s timeout per batch (should be ~5s with 2s+3s timeouts)
                for result in batch_results:
                    results[result["pv_name"]] = result
                    completed += 1

                if progress_callback:
                    progress_callback(completed, total, f"Read {completed}/{total} PVs")

            except Exception as e:
                batch_idx = futures[future]
                logger.error(f"Batch {batch_idx} failed: {e}")
                # Mark all PVs in failed batch as errors
                batch_pv_names = batches[batch_idx][0]
                for pv_name in batch_pv_names:
                    results[pv_name] = {
                        "pv_name": pv_name,
                        "value": None,
                        "connected": False,
                        "error": f"Batch failed: {e}"
                    }
                    completed += 1

        return results

    def shutdown(self):
        """Shutdown the process pool."""
        if self._pool:
            self._pool.shutdown(wait=True)
            self._pool = None


# Global process pool instance
_process_pool: EpicsProcessPool | None = None


def get_epics_process_pool() -> EpicsProcessPool:
    """Get or create the global EPICS process pool."""
    global _process_pool
    if _process_pool is None:
        from app.config import get_settings
        settings = get_settings()
        # Use fewer workers (4-8) to reduce spawn overhead
        # Each worker handles larger batches for better throughput
        num_workers = min(settings.epics_max_workers, 8)
        _process_pool = EpicsProcessPool(
            max_workers=num_workers,
            ca_addr_list=settings.epics_ca_addr_list,
            ca_auto_addr_list=settings.epics_ca_auto_addr_list,
            conn_timeout=settings.epics_ca_conn_timeout,
            read_timeout=settings.epics_ca_timeout
        )
        logger.info(f"Created EPICS process pool with {num_workers} workers")
    return _process_pool


def warmup_process_pool() -> None:
    """Pre-warm the process pool by initializing all workers."""
    pool = get_epics_process_pool()
    # Force pool creation and worker initialization
    pool._get_pool()
    logger.info("EPICS process pool warmed up")
