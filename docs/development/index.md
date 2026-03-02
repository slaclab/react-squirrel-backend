# Development Guide

This guide covers setting up a development environment and contributing to Squirrel Backend.

## Project Structure

```
squirrel-backend/
├── app/
│   ├── main.py              # API entry point
│   ├── monitor_main.py      # PV Monitor entry point
│   ├── worker.py            # Arq worker configuration
│   ├── config.py            # Configuration settings
│   ├── api/v1/              # API endpoints
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic schemas (DTOs)
│   ├── services/            # Business logic layer
│   ├── repositories/        # Data access layer
│   ├── tasks/               # Arq task definitions
│   └── db/                  # Database session management
├── alembic/                 # Database migrations
├── tests/                   # Test suite
├── docker/                  # Docker configuration
└── scripts/                 # Utility scripts
```

## Setting Up Development Environment

### 1. Start Infrastructure

```bash
cd docker
docker compose up -d db redis
```

### 2. Set Up Python Environment

```bash
cd ..
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

Or use the setup script:

```bash
./setup.sh
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env if needed (defaults work with docker compose)
```

### 4. Run Migrations

```bash
alembic upgrade head
```

### 5. Load Test Data

```bash
python -m scripts.seed_pvs --count 100
```

### 6. Start Services

Run each in a separate terminal:

=== "API Server"
    ```bash
    uvicorn app.main:app --reload --port 8000
    ```

=== "PV Monitor"
    ```bash
    python -m app.monitor_main
    ```

=== "Worker"
    ```bash
    arq app.worker.WorkerSettings
    ```

## Development Workflow

### Making Changes

1. Create a feature branch
2. Make your changes
3. Run tests: `pytest`
4. Run linting: `ruff check .`
5. Run type checking: `mypy app/`
6. Submit a pull request

### Hot Reload

The API server supports hot reload with `--reload`:

```bash
uvicorn app.main:app --reload --port 8000
```

Changes to Python files will automatically restart the server.

### Debugging

Enable debug logging:

```bash
export SQUIRREL_DEBUG=true
uvicorn app.main:app --reload --port 8000
```

## Performance Benchmarking

```bash
# Start the backend first, then run:
python -m scripts.benchmark

# With more iterations
python -m scripts.benchmark --iterations 10

# Skip restore benchmark (no EPICS writes)
python -m scripts.benchmark --skip-restore
```

## Utility Scripts

### seed_pvs.py

Generate test PV data:

```bash
# Create 1000 test PVs with tags
python -m scripts.seed_pvs --count 1000

# Create 50K PVs for performance testing
python -m scripts.seed_pvs --count 50000 --batch-size 5000

# Clear existing data first
python -m scripts.seed_pvs --count 1000 --clear
```

### upload_csv.py

Import PVs from CSV:

```bash
# Dry run
python -m scripts.upload_csv your_pvs.csv --dry-run

# Full upload
python -m scripts.upload_csv your_pvs.csv
```

### benchmark.py

Performance testing:

```bash
python -m scripts.benchmark --iterations 5
```

## IDE Setup

### VS Code

Recommended extensions:

- Python
- Pylance
- Ruff

Settings (`.vscode/settings.json`):

```json
{
    "python.defaultInterpreterPath": "./venv/bin/python",
    "python.analysis.typeCheckingMode": "basic",
    "[python]": {
        "editor.formatOnSave": true,
        "editor.codeActionsOnSave": {
            "source.fixAll": "explicit",
            "source.organizeImports": "explicit"
        },
        "editor.defaultFormatter": "charliermarsh.ruff"
    }
}
```

### PyCharm

1. Set project interpreter to `./venv/bin/python`
2. Enable Ruff plugin
3. Configure pytest as default test runner

## Pre-commit Hooks

The project uses pre-commit hooks for code quality:

```bash
# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

## Next Steps

- [Testing](testing.md) - Running and writing tests
- [Database Migrations](migrations.md) - Managing schema changes
- [Code Quality](code-quality.md) - Linting and formatting
