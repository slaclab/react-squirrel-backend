from datetime import datetime
from typing import Any, Callable, Optional
import random

from app.services.epics_service import EpicsValue


class MockEpicsService:
    """Mock EPICS service for testing without real IOCs."""

    def __init__(self):
        self._mock_data: dict[str, Any] = {}

    def set_mock_value(self, pv_name: str, value: Any):
        """Set a mock value for a PV."""
        self._mock_data[pv_name] = value

    def set_mock_values(self, values: dict[str, Any]):
        """Set multiple mock values."""
        self._mock_data.update(values)

    async def connect_pv(self, pv_name: str) -> bool:
        """Mock pre-connect to a PV."""
        return True

    async def connect_many(self, pv_names: list[str]) -> None:
        """Mock pre-connect to multiple PVs."""
        pass

    async def get_single(self, pv_name: str) -> EpicsValue:
        """Read a single PV."""
        if pv_name in self._mock_data:
            return EpicsValue(
                value=self._mock_data[pv_name],
                timestamp=datetime.now(),
                connected=True
            )
        # Generate random value if not mocked
        return EpicsValue(
            value=random.uniform(0, 100),
            timestamp=datetime.now(),
            connected=True
        )

    async def get_many(self, pv_names: list[str]) -> dict[str, EpicsValue]:
        """Read multiple PVs."""
        return {pv: await self.get_single(pv) for pv in pv_names}

    async def get_many_with_progress(
        self,
        pv_names: list[str],
        progress_callback: Optional[Callable] = None
    ) -> dict[str, EpicsValue]:
        """Read multiple PVs with progress callback."""
        total = len(pv_names)
        if progress_callback:
            await progress_callback(0, total, "Starting to read PVs...")

        results = await self.get_many(pv_names)

        if progress_callback:
            await progress_callback(total, total, f"Completed: {total}/{total} PVs connected")

        return results

    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        """Write a value to a single PV."""
        self._mock_data[pv_name] = value
        return True, None

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        """Write values to multiple PVs."""
        results = {}
        for pv_name, value in values.items():
            success, error = await self.put_single(pv_name, value)
            results[pv_name] = (success, error)
        return results

    async def shutdown(self):
        """Cleanup resources."""
        pass
