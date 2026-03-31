"""
Pytest configuration and fixtures for squirrel-backend tests.
"""

import asyncio
import logging
from datetime import datetime
from collections.abc import Generator, AsyncGenerator

import pytest
import asyncpg
import pytest_asyncio
import fakeredis.aioredis as aioredis_fake
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.redis_service as redis_module
from app.main import app
from app.models import Base
from app.db.session import get_db
from app.dependencies import get_api_key
from app.schemas.api_key import ApiKeyDTO
from tests.mocks.epics_mock import MockEpicsService
from app.services.epics_service import get_epics_service

# Silence noisy p4p atexit logging during pytest shutdown
_p4p_logger = logging.getLogger("p4p")
_p4p_logger.setLevel(logging.CRITICAL)
_p4p_logger.propagate = False
_p4p_logger.handlers = [logging.NullHandler()]

# Test database URL - uses a separate test database
TEST_DATABASE_URL = "postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel_test"
# Admin DSN used to create squirrel_test if it doesn't exist; uses the built-in `postgres` database
_ADMIN_DSN = "postgresql://squirrel:squirrel@localhost:5432/postgres"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def ensure_test_db():
    """Create the squirrel_test database if it doesn't already exist."""
    conn = await asyncpg.connect(_ADMIN_DSN)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'squirrel_test'")
        if not exists:
            await conn.execute("CREATE DATABASE squirrel_test")
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def fake_redis():
    """Inject a fake Redis instance into the RedisService singleton for all tests."""
    fake = aioredis_fake.FakeRedis(decode_responses=True)
    redis_module._redis_service = None
    service = redis_module.get_redis_service()
    service._redis = fake
    yield service
    await fake.aclose()
    redis_module._redis_service = None


@pytest_asyncio.fixture(scope="function")
async def test_engine(ensure_test_db):
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

    async def override_get_api_key() -> ApiKeyDTO:
        return ApiKeyDTO(
            id="test-key-id",
            appName="TestClient",
            isActive=True,
            readAccess=True,
            writeAccess=True,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )

    # Override dependencies
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_epics_service] = override_get_epics
    app.dependency_overrides[get_api_key] = override_get_api_key

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
    group = response.json()["payload"]["group"]
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
        "/v1/snapshots",
        params={"async": "false", "use_cache": "false"},
        json={"title": "Test Snapshot", "description": "Snapshot for unit tests"},
    )
    assert response.status_code == 200
    return response.json()["payload"]
