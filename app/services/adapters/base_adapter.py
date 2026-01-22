"""
Base adapter interface for EPICS protocols.

This module defines the abstract base class that all protocol adapters
(CA, PVA, etc.) must implement to provide a unified interface.
"""

import math
from abc import ABC, abstractmethod
from typing import Any
from datetime import datetime
from dataclasses import dataclass


@dataclass
class EpicsValue:
    """
    Container for EPICS PV value with metadata.

    This is protocol-agnostic and can represent values from both
    CA and PVA protocols.
    """

    value: Any
    status: int | str | None = None  # CA uses int, PVA uses string
    severity: int | None = None
    timestamp: datetime | None = None
    units: str | None = None
    precision: int | None = None
    upper_ctrl_limit: float | None = None
    lower_ctrl_limit: float | None = None
    connected: bool = True
    error: str | None = None


class BaseAdapter(ABC):
    """
    Abstract base class for EPICS protocol adapters.

    All protocol-specific adapters (CA, PVA) must implement this interface
    to ensure consistent behavior across protocols.
    """

    @abstractmethod
    async def get_single(self, pv_name: str) -> EpicsValue:
        """
        Read a single PV with metadata.

        Args:
            pv_name: PV name (without protocol prefix)

        Returns:
            EpicsValue with value and metadata
        """
        pass

    @abstractmethod
    async def get_many(self, pv_names: list[str]) -> dict[str, EpicsValue]:
        """
        Read multiple PVs in parallel.

        Args:
            pv_names: List of PV names (without protocol prefix)

        Returns:
            Dictionary mapping PV name to EpicsValue
        """
        pass

    @abstractmethod
    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """
        Write a value to a single PV.

        Args:
            pv_name: PV name (without protocol prefix)
            value: Value to write

        Returns:
            Tuple of (success: bool, error_message: str | None)
        """
        pass

    @abstractmethod
    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """
        Write values to multiple PVs.

        Args:
            values: Dictionary mapping PV name to value

        Returns:
            Dictionary mapping PV name to (success, error_message) tuple
        """
        pass

    @abstractmethod
    async def connect_pv(self, pv_name: str) -> bool:
        """
        Pre-connect to a PV.

        Args:
            pv_name: PV name (without protocol prefix)

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def connect_many(self, pv_names: list[str]) -> None:
        """
        Pre-connect to multiple PVs.

        Args:
            pv_names: List of PV names (without protocol prefix)
        """
        pass

    @abstractmethod
    async def shutdown(self):
        """Cleanup adapter resources."""
        pass

    def _sanitize_value(self, value: Any) -> Any:
        """
        Sanitize value for JSON storage (handle NaN/Inf).

        This is a common utility method available to all adapters.
        """
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
