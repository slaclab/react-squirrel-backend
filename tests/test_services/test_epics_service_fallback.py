import pytest

import app.services.epics_service as epics_module
from app.services.epics_types import EpicsValue
from app.services.epics_service import EpicsService


class _DummyCaResult:
    def __init__(self, ok: bool, errorcode: str = "DISCONNECTED"):
        self.ok = ok
        self.errorcode = errorcode


class _DummyPVAService:
    async def get_single(self, pv_name: str, timeout=None):
        return EpicsValue(value=123.4, connected=True)

    async def put_single(self, pv_name: str, value):
        return True, None


@pytest.mark.asyncio
async def test_get_single_unprefixed_falls_back_to_pva(monkeypatch):
    async def fake_caget(*args, **kwargs):
        return _DummyCaResult(ok=False)

    monkeypatch.setattr(epics_module, "caget", fake_caget)

    service = EpicsService(enable_circuit_breaker=False)
    service._unprefixed_pva_fallback = True
    service._get_pva_service = lambda: _DummyPVAService()

    value = await service.get_single("TEST:PV")
    assert value.connected is True
    assert value.value == 123.4


@pytest.mark.asyncio
async def test_get_single_explicit_ca_does_not_fall_back(monkeypatch):
    async def fake_caget(*args, **kwargs):
        return _DummyCaResult(ok=False)

    monkeypatch.setattr(epics_module, "caget", fake_caget)

    service = EpicsService(enable_circuit_breaker=False)
    service._unprefixed_pva_fallback = True
    service._get_pva_service = lambda: _DummyPVAService()

    value = await service.get_single("ca://TEST:PV")
    assert value.connected is False


@pytest.mark.asyncio
async def test_put_single_unprefixed_falls_back_to_pva(monkeypatch):
    async def fake_caput(*args, **kwargs):
        return _DummyCaResult(ok=False, errorcode="NO_CHANNEL")

    monkeypatch.setattr(epics_module, "caput", fake_caput)

    service = EpicsService(enable_circuit_breaker=False)
    service._unprefixed_pva_fallback = True
    service._get_pva_service = lambda: _DummyPVAService()

    ok, err = await service.put_single("TEST:PV", 1.0)
    assert ok is True
    assert err is None
