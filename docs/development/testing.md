# Testing

This guide covers running and writing tests for Squirrel Backend.

## Running Tests

### Basic Usage

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_api/test_pvs.py

# Run specific test function
pytest tests/test_api/test_pvs.py::test_create_pv

# Run tests matching a pattern
pytest -k "snapshot"
```

### Test Coverage

```bash
# Run with coverage report
pytest --cov=app --cov-report=html

# View HTML report
open htmlcov/index.html
```

### Parallel Execution

```bash
# Run tests in parallel (requires pytest-xdist)
pytest -n auto
```

## Test Database Setup

Tests use a separate test database (`squirrel_test`). Create it first:

```bash
# Using local PostgreSQL
createdb squirrel_test

# Using Docker
docker exec -it squirrel-db createdb -U squirrel squirrel_test
```

## Test Structure

```
tests/
├── conftest.py           # Pytest fixtures
├── test_api/             # API integration tests
│   ├── test_pvs.py
│   ├── test_snapshots.py
│   └── test_tags.py
├── test_services/        # Service unit tests
│   ├── test_pv_service.py
│   └── test_snapshot_service.py
└── mocks/                # Mock implementations
    └── mock_epics.py
```

## Writing Tests

### API Tests

API tests use FastAPI's test client:

```python
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_create_pv(async_client: AsyncClient):
    response = await async_client.post(
        "/v1/pvs",
        json={
            "setpoint_address": "TEST:PV:1",
            "description": "Test PV"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["errorCode"] == 0
    assert data["payload"]["setpoint_address"] == "TEST:PV:1"
```

### Service Tests

Service tests focus on business logic:

```python
import pytest
from app.services.pv_service import PVService
from app.repositories.pv_repository import PVRepository

@pytest.mark.asyncio
async def test_get_pv_by_address(db_session):
    repo = PVRepository(db_session)
    service = PVService(repo)

    # Create a test PV
    pv = await service.create_pv(
        setpoint_address="TEST:PV:1",
        description="Test"
    )

    # Retrieve it
    found = await service.get_by_address("TEST:PV:1")
    assert found is not None
    assert found.id == pv.id
```

### Using Fixtures

Common fixtures are defined in `conftest.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.fixture
async def db_session() -> AsyncSession:
    """Provides a database session for tests."""
    # Session setup and teardown
    ...

@pytest.fixture
async def async_client(db_session) -> AsyncClient:
    """Provides an async HTTP client for API tests."""
    ...

@pytest.fixture
def mock_epics():
    """Provides a mock EPICS service."""
    ...
```

### Mocking EPICS

For tests that don't need real EPICS connections:

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_snapshot_creation_with_mock_epics():
    mock_values = {
        "PV:1": 42.0,
        "PV:2": 3.14
    }

    with patch("app.services.epics_service.caget") as mock_caget:
        mock_caget.side_effect = lambda pv: mock_values.get(pv, 0.0)

        # Test snapshot creation
        ...
```

## Test Configuration

### pytest.ini / pyproject.toml

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
filterwarnings = [
    "ignore::DeprecationWarning"
]
```

### Environment Variables

Test-specific environment variables:

```bash
# In .env.test or set directly
SQUIRREL_DATABASE_URL=postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel_test
SQUIRREL_DEBUG=true
SQUIRREL_WATCHDOG_ENABLED=false
```

## Test Categories

### Unit Tests

Test individual functions and methods:

```python
def test_circuit_breaker_opens_after_failures():
    breaker = CircuitBreaker(failure_threshold=3)

    for _ in range(3):
        breaker.record_failure()

    assert breaker.is_open
```

### Integration Tests

Test component interactions:

```python
@pytest.mark.asyncio
async def test_pv_creation_with_tags(async_client, db_session):
    # Create tag group first
    tag_response = await async_client.post(
        "/v1/tags",
        json={"name": "Test Group"}
    )
    tag_group_id = tag_response.json()["payload"]["id"]

    # Create PV with tag
    pv_response = await async_client.post(
        "/v1/pvs",
        json={
            "setpoint_address": "TEST:PV:1",
            "tag_ids": [tag_group_id]
        }
    )

    assert pv_response.status_code == 200
```

### End-to-End Tests

Test complete workflows:

```python
@pytest.mark.asyncio
async def test_snapshot_workflow(async_client):
    # 1. Create PVs
    await async_client.post("/v1/pvs", json={"setpoint_address": "PV:1"})

    # 2. Create snapshot
    snapshot_response = await async_client.post(
        "/v1/snapshots",
        json={"title": "Test Snapshot", "use_cache": True}
    )
    job_id = snapshot_response.json()["payload"]["job_id"]

    # 3. Wait for job completion
    # ... poll job status ...

    # 4. Verify snapshot created
    # ...
```

## Continuous Integration

Tests run automatically on pull requests via GitHub Actions:

```yaml
# .github/workflows/run-test.yml
name: Run Tests

on:
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: squirrel
          POSTGRES_PASSWORD: squirrel
          POSTGRES_DB: squirrel_test
      redis:
        image: redis:7

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e ".[dev]"
      - run: pytest --cov=app
```
