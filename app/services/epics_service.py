import os
import logging
from typing import Any
from collections.abc import Callable

from app.config import get_settings
from app.services.protocol_parser import parse_pv_address, group_by_protocol
from app.services.adapters.ca_adapter import CAAdapter
from app.services.adapters.pva_adapter import PVAAdapter
from app.services.adapters.base_adapter import EpicsValue, BaseAdapter

logger = logging.getLogger(__name__)
settings = get_settings()

# Set EPICS environment BEFORE any EPICS library imports
# These must be set before libca is loaded
if settings.epics_ca_addr_list:
    os.environ["EPICS_CA_ADDR_LIST"] = settings.epics_ca_addr_list
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = settings.epics_ca_auto_addr_list

# Export EpicsValue for backward compatibility
__all__ = ["EpicsService", "EpicsValue", "get_epics_service"]


class EpicsService:
    """
    Unified EPICS service supporting multiple protocols (CA, PVA).

    This service provides a protocol-agnostic interface that automatically
    routes requests to the appropriate protocol adapter based on PV address
    prefixes (ca:// or pva://).

    Features:
    - Protocol detection via address prefixes
    - Configurable default protocol
    - Circuit breaker integration per protocol
    - Unified EpicsValue responses
    """

    def __init__(self, enable_circuit_breaker: bool = True):
        self._chunk_size = settings.epics_chunk_size
        self._default_protocol = settings.epics_default_protocol

        # Initialize protocol adapters
        self._adapters: dict[str, BaseAdapter] = {
            "ca": CAAdapter(enable_circuit_breaker=enable_circuit_breaker),
            "pva": PVAAdapter(enable_circuit_breaker=enable_circuit_breaker),
        }

        logger.info(
            f"EpicsService initialized with protocols: {list(self._adapters.keys())}, default={self._default_protocol}"
        )

    def _get_adapter(self, protocol: str) -> BaseAdapter:
        """Get adapter for specified protocol."""
        if protocol not in self._adapters:
            raise ValueError(f"Protocol '{protocol}' not supported. Available: {list(self._adapters.keys())}")
        return self._adapters[protocol]

    async def connect_pv(self, pv_address: str) -> bool:
        """Pre-connect to a PV."""
        parsed = parse_pv_address(pv_address, self._default_protocol)
        adapter = self._get_adapter(parsed.protocol)
        return await adapter.connect_pv(parsed.pv_name)

    async def connect_many(self, pv_addresses: list[str]) -> None:
        """Pre-connect to multiple PVs (grouped by protocol)."""
        grouped = group_by_protocol(pv_addresses, self._default_protocol)

        for protocol, addr_pairs in grouped.items():
            pv_names = [pv_name for _, pv_name in addr_pairs]
            adapter = self._get_adapter(protocol)
            await adapter.connect_many(pv_names)

        logger.info(f"Pre-connected to {len(pv_addresses)} PVs across protocols")

    async def get_single(self, pv_address: str) -> EpicsValue:
        """Read a single PV with protocol detection."""
        parsed = parse_pv_address(pv_address, self._default_protocol)
        adapter = self._get_adapter(parsed.protocol)
        return await adapter.get_single(parsed.pv_name)

    async def get_many(self, pv_addresses: list[str]) -> dict[str, EpicsValue]:
        """
        Get values for multiple PVs, grouping by protocol for efficiency.

        Args:
            pv_addresses: List of PV addresses (with or without protocol prefix)

        Returns:
            Dictionary mapping original address to EpicsValue
        """
        logger.info(f"Starting get_many for {len(pv_addresses)} PVs across protocols")

        # Group by protocol
        grouped = group_by_protocol(pv_addresses, self._default_protocol)

        # Fetch each protocol group in parallel
        results = {}
        for protocol, addr_pairs in grouped.items():
            pv_names = [pv_name for _, pv_name in addr_pairs]
            adapter = self._get_adapter(protocol)

            # Get values from adapter
            adapter_results = await adapter.get_many(pv_names)

            # Map back to original addresses
            for orig_addr, pv_name in addr_pairs:
                results[orig_addr] = adapter_results.get(
                    pv_name,
                    EpicsValue(
                        value=None,
                        connected=False,
                        error=f"No result from {protocol} adapter",
                    ),
                )

        logger.info(f"Completed get_many: {len(results)}/{len(pv_addresses)} PVs")
        return results

    async def get_many_with_progress(
        self, pv_addresses: list[str], progress_callback: Callable | None = None
    ) -> dict[str, EpicsValue]:
        """
        Get values for multiple PVs with progress tracking.

        Processes in batches to allow progress updates while maintaining
        efficient parallel connections within each batch.
        """
        total_pvs = len(pv_addresses)
        logger.info(f"Starting get_many_with_progress for {total_pvs} PVs")

        if progress_callback:
            await progress_callback(0, total_pvs, "Starting to read PVs...")

        results = {}
        batch_size = self._chunk_size

        for i in range(0, total_pvs, batch_size):
            batch = pv_addresses[i : i + batch_size]

            # Process batch (grouped by protocol)
            batch_results = await self.get_many(batch)
            results.update(batch_results)

            # Report progress
            current = min(i + batch_size, total_pvs)
            connected_so_far = sum(1 for r in results.values() if r.connected)
            if progress_callback:
                await progress_callback(
                    current,
                    total_pvs,
                    f"Read {current:,}/{total_pvs:,} PVs ({connected_so_far:,} connected)",
                )

            logger.info(f"Read {current:,}/{total_pvs:,} PVs ({connected_so_far} connected)")

        if progress_callback:
            connected_count = sum(1 for r in results.values() if r.connected)
            await progress_callback(
                total_pvs,
                total_pvs,
                f"Completed: {connected_count:,}/{total_pvs:,} PVs connected",
            )

        connected_count = sum(1 for r in results.values() if r.connected)
        logger.info(f"Completed get_many_with_progress: {connected_count}/{total_pvs} PVs connected")
        return results

    async def put_single(self, pv_address: str, value: Any) -> tuple[bool, str | None]:
        """Write a value to a single PV with protocol detection."""
        parsed = parse_pv_address(pv_address, self._default_protocol)
        adapter = self._get_adapter(parsed.protocol)
        return await adapter.put_single(parsed.pv_name, value)

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """
        Put values to multiple PVs (grouped by protocol).

        Args:
            values: Dictionary mapping PV address to value

        Returns:
            Dictionary mapping PV address to (success, error_message) tuple
        """
        results = {}

        # Group by protocol
        pv_addresses = list(values.keys())
        grouped = group_by_protocol(pv_addresses, self._default_protocol)

        for protocol, addr_pairs in grouped.items():
            # Build protocol-specific values dict
            protocol_values = {pv_name: values[orig_addr] for orig_addr, pv_name in addr_pairs}
            adapter = self._get_adapter(protocol)

            # Write values
            adapter_results = await adapter.put_many(protocol_values)

            # Map back to original addresses
            for orig_addr, pv_name in addr_pairs:
                results[orig_addr] = adapter_results.get(pv_name, (False, f"No result from {protocol} adapter"))

        return results

    async def shutdown(self):
        """Cleanup all protocol adapter resources."""
        for protocol, adapter in self._adapters.items():
            logger.info(f"Shutting down {protocol} adapter")
            await adapter.shutdown()


# Singleton instance
_epics_service: EpicsService | None = None


def get_epics_service() -> EpicsService:
    """Get or create the EPICS service singleton."""
    global _epics_service
    if _epics_service is None:
        _epics_service = EpicsService()
    return _epics_service
