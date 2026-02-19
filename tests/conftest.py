"""
Pytest configuration and fixtures for squirrel-backend tests.
"""
import asyncio
from collections.abc import Generator, AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.models import Base
from app.db.session import get_db
from tests.mocks.epics_mock import MockEpicsService
from app.services.epics_service import get_epics_service

# Test database URL - uses a separate test database
TEST_DATABASE_URL = "postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel_test"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create test database engine and tables."""
    engine = create_async_engine(
        TEST_DATABASE_URL, echo=False, poolclass=NullPool  # Disable connection pooling for tests
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create database session for tests with automatic rollback."""
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def mock_epics() -> MockEpicsService:
    """Create mock EPICS service for testing without real IOCs."""
    return MockEpicsService()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession, mock_epics: MockEpicsService) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client with overridden dependencies."""

    async def override_get_db():
        yield db_session

    def override_get_epics():
        return mock_epics

    # Override dependencies
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_epics_service] = override_get_epics

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client

    # Clear overrides after test
    app.dependency_overrides.clear()


# Helper fixtures for creating test data


@pytest_asyncio.fixture
async def sample_tag_group(client: AsyncClient) -> dict:
    """Create a sample tag group for testing."""
    response = await client.post("/v1/tags", json={"name": "Test Location", "description": "Test location tags"})
    assert response.status_code == 200
    return response.json()["payload"]


@pytest_asyncio.fixture
async def sample_tag(client: AsyncClient, sample_tag_group: dict) -> tuple[dict, dict]:
    """Create a sample tag within a tag group."""
    group_id = sample_tag_group["id"]
    response = await client.post(
        f"/v1/tags/{group_id}/tags", json={"name": "Building-A", "description": "Building A location"}
    )
    assert response.status_code == 200
    group = response.json()["payload"]
    tag = group["tags"][0]
    return group, tag


@pytest_asyncio.fixture
async def sample_pv(client: AsyncClient) -> dict:
    """Create a sample PV for testing."""
    response = await client.post(
        "/v1/pvs",
        json={
            "setpointAddress": "TEST:PV:001:SP",
            "readbackAddress": "TEST:PV:001:RB",
            "device": "TEST-DEVICE-001",
            "description": "Test PV for unit tests",
            "absTolerance": 0.1,
            "relTolerance": 0.01,
            "tags": [],
        },
    )
    assert response.status_code == 200
    return response.json()["payload"]


@pytest_asyncio.fixture
async def sample_pvs(client: AsyncClient) -> list[dict]:
    """Create multiple sample PVs for testing."""
    pvs_data = [
        {
            "setpointAddress": f"TEST:PV:{i:03d}:SP",
            "readbackAddress": f"TEST:PV:{i:03d}:RB",
            "device": f"TEST-DEVICE-{i:03d}",
            "description": f"Test PV {i}",
            "absTolerance": 0.1,
            "relTolerance": 0.01,
            "tags": [],
        }
        for i in range(1, 6)
    ]
    response = await client.post("/v1/pvs/multi", json=pvs_data)
    assert response.status_code == 200
    return response.json()["payload"]


@pytest_asyncio.fixture
async def sample_snapshot(client: AsyncClient, sample_pvs: list[dict], mock_epics: MockEpicsService) -> dict:
    """Create a sample snapshot for testing."""
    # Set mock values for all PVs
    for pv in sample_pvs:
        if pv.get("setpointAddress"):
            mock_epics.set_mock_value(pv["setpointAddress"], 42.0)
        if pv.get("readbackAddress"):
            mock_epics.set_mock_value(pv["readbackAddress"], 41.8)

    response = await client.post(
        "/v1/snapshots", json={"title": "Test Snapshot", "description": "Snapshot for unit tests"}
    )
    assert response.status_code == 200
    return response.json()["payload"]
