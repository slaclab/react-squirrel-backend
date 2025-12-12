from dataclasses import dataclass
from datetime import datetime
from typing import Any
import random


@dataclass
class MockEpicsValue:
    value: Any
    status: int = 0
    severity: int = 0
    timestamp: datetime = None
    units: str = ""
    precision: int = 3
    upper_ctrl_limit: float = 100.0
    lower_ctrl_limit: float = 0.0
    connected: bool = True
    error: str | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


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

    async def connect_pv(self, pv_name: str):
        pass

    async def connect_many(self, pv_names: list[str]):
        pass

    async def get_single(self, pv_name: str) -> MockEpicsValue:
        if pv_name in self._mock_data:
            return MockEpicsValue(value=self._mock_data[pv_name])
        # Generate random value if not mocked
        return MockEpicsValue(value=random.uniform(0, 100))

    async def get_many(self, pv_names: list[str]) -> dict[str, MockEpicsValue]:
        return {pv: await self.get_single(pv) for pv in pv_names}

    async def put_single(self, pv_name: str, value: Any) -> tuple[bool, str | None]:
        self._mock_data[pv_name] = value
        return True, None

    async def put_many(self, values: dict[str, Any]) -> dict[str, tuple[bool, str | None]]:
        results = {}
        for pv_name, value in values.items():
            success, error = await self.put_single(pv_name, value)
            results[pv_name] = (success, error)
        return results

    async def shutdown(self):
        pass
