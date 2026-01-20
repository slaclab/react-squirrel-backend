# Squirrel Backend

High-performance Python FastAPI backend for EPICS control system snapshot/restore operations, designed to handle 40-50K PVs efficiently.

## Features

- **Fast Snapshot Creation**: Parallel EPICS reads for capturing 40-50K PV values in seconds
- **Efficient Restore Operations**: Parallel EPICS writes for quick machine state restoration
- **Tag-based Organization**: Group and categorize PVs using hierarchical tags
- **Snapshot Comparison**: Compare two snapshots with tolerance-based diff
- **PostgreSQL Storage**: Reliable relational database with async support
- **RESTful API**: Clean FastAPI endpoints with automatic OpenAPI documentation

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Database | PostgreSQL 16+ |
| ORM | SQLAlchemy 2.0 (async) |
| EPICS | PyEPICS (Channel Access) |
| Migrations | Alembic |
| Validation | Pydantic v2 |

---

## Quick Start

### Option 1: Docker Compose (Recommended)

The easiest way to get started is using Docker Compose, which sets up both the database and backend:

```bash
# Clone the repository
git clone <repository-url>
cd react-squirrel-backend

# Start the full stack
cd docker
docker-compose up -d --build
```

This starts:
- **PostgreSQL** on port `5432` (user: `squirrel`, password: `squirrel`)
- **FastAPI backend** on port `8000` with hot reload

The API will be available at:
- **API**: http://localhost:8000
- **Swagger Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

To stop the services:
```bash
docker-compose down
```

To reset the database (delete all data):
```bash
docker-compose down -v
```

### Option 2: Local Development (Database in Docker)

Run just the database in Docker, with the backend running locally for faster development:

```bash
# 1. Start only PostgreSQL
cd docker
docker-compose up -d db

# 2. Set up Python environment
cd ..
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env if needed (defaults work with docker-compose db)

# 4. Run database migrations
alembic upgrade head

# 5. Start the backend with hot reload
uvicorn app.main:app --reload --port 8000
```

### Option 3: Full Local Setup

If you have PostgreSQL installed locally:

```bash
# 1. Create database
createdb squirrel

# 2. Set up Python environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your local PostgreSQL connection string

# 4. Run migrations
alembic upgrade head

# 5. Start server
uvicorn app.main:app --reload
```

---

## Loading Data

### Upload PVs from CSV

The expected format:
```csv
Setpoint,Readback,Region,Area,Subsystem
FBCK:LNG6:1:BC2ELTOL,,"Feedback-All","LIMITS","FBCK"
QUAD:LI21:201:BDES,QUAD:LI21:201:BACT,"Cu Linac","LI21","Magnet"
...
```

#### Using the UI
* navigate to the "Browser PVs" page
* click the "Import PVs" button
* select the consolidated CSV

#### Using a bash script
In addition to importing PVs, upload_csv.py also creates tag groups for the tags found in the CSV.  However, it must be run from within the docker service.

```bash
# Copying script and data into docker service
docker cp /path/to/local/upload_csv.py /path/to/local/consolidated.py squirrel-api:/tmp/

# Dry run (see what would be uploaded)
docker exec squirrel-api python /tmp/upload_csv.py /tmp/consolidated.csv --dry-run

# Full upload (~36K PVs)
docker exec squirrel-api python /tmp/upload_csv.py /tmp/consolidated.csv

# With custom batch size
docker exec squirrel-api python /tmp/upload_csv.py /tmp/consolidated.csv --batch-size 1000
```

### Seed Test Data

For development/testing with sample data:

```bash
# Create 1000 test PVs with tags
python -m scripts.seed_pvs --count 1000

# Create 50K PVs for performance testing
python -m scripts.seed_pvs --count 50000 --batch-size 5000

# Clear existing data first
python -m scripts.seed_pvs --count 1000 --clear
```

---

## Development

### Project Structure

```
squirrel-backend/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Configuration settings
│   ├── api/v1/              # API endpoints (pvs, snapshots, tags)
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic schemas (DTOs)
│   ├── services/            # Business logic layer
│   ├── repositories/        # Data access layer
│   └── db/                  # Database session management
├── alembic/                 # Database migrations
│   └── versions/            # Migration files
├── tests/                   # Test suite
│   ├── conftest.py          # Pytest fixtures
│   ├── test_api/            # API integration tests
│   ├── test_services/       # Service unit tests
│   └── mocks/               # Mock services (EPICS)
├── docker/                  # Docker configuration
│   ├── docker-compose.yml   # Full stack setup
│   └── Dockerfile.dev       # Development image
└── scripts/                 # Utility scripts
    ├── upload_csv.py        # CSV data loader
    ├── seed_pvs.py          # Test data generator
    └── benchmark.py         # Performance testing
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_api/test_pvs.py

# Run with coverage report
pytest --cov=app --cov-report=html
# Open htmlcov/index.html in browser
```

**Note**: Tests use a separate test database (`squirrel_test`). Create it first:
```bash
createdb squirrel_test
# Or via Docker:
docker exec -it squirrel-db createdb -U squirrel squirrel_test
```

### Database Migrations

```bash
# Apply all migrations
alembic upgrade head

# Create new migration after model changes
alembic revision --autogenerate -m "description of changes"

# Rollback one migration
alembic downgrade -1

# Show current migration status
alembic current

# Show migration history
alembic history
```

### Code Quality

```bash
# Format code
ruff format .

# Lint code
ruff check .

# Fix auto-fixable lint issues
ruff check . --fix

# Type checking
mypy app/
```

### Performance Benchmarking

```bash
# Start the backend first, then run:
python -m scripts.benchmark

# With more iterations
python -m scripts.benchmark --iterations 10

# Skip restore benchmark (no EPICS writes)
python -m scripts.benchmark --skip-restore
```

---

## API Endpoints

### PV Endpoints (`/v1/pvs`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/pvs` | Search PVs (simple) |
| `GET` | `/v1/pvs/paged` | Search PVs with pagination |
| `POST` | `/v1/pvs` | Create single PV |
| `POST` | `/v1/pvs/multi` | Bulk create PVs |
| `PUT` | `/v1/pvs/{id}` | Update PV |
| `DELETE` | `/v1/pvs/{id}` | Delete PV |

### Snapshot Endpoints (`/v1/snapshots`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/snapshots` | List snapshots |
| `POST` | `/v1/snapshots` | Create snapshot (reads from EPICS) |
| `GET` | `/v1/snapshots/{id}` | Get snapshot with all values |
| `DELETE` | `/v1/snapshots/{id}` | Delete snapshot |
| `POST` | `/v1/snapshots/{id}/restore` | Restore values to EPICS |
| `GET` | `/v1/snapshots/{id}/compare/{id2}` | Compare two snapshots |

### Tag Endpoints (`/v1/tags`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/tags` | List tag groups |
| `POST` | `/v1/tags` | Create tag group |
| `GET` | `/v1/tags/{id}` | Get tag group with tags |
| `PUT` | `/v1/tags/{id}` | Update tag group |
| `DELETE` | `/v1/tags/{id}` | Delete tag group |
| `POST` | `/v1/tags/{id}/tags` | Add tag to group |
| `PUT` | `/v1/tags/{id}/tags/{tagId}` | Update tag |
| `DELETE` | `/v1/tags/{id}/tags/{tagId}` | Remove tag |

---

## Configuration

All configuration is via environment variables (with `SQUIRREL_` prefix):

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_DATABASE_URL` | `postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel` | Database connection |
| `SQUIRREL_DATABASE_POOL_SIZE` | `20` | Connection pool size |
| `SQUIRREL_EPICS_CA_ADDR_LIST` | (empty) | EPICS CA address list |
| `SQUIRREL_EPICS_CA_AUTO_ADDR_LIST` | `YES` | Auto-discover CA servers |
| `SQUIRREL_EPICS_CA_CONN_TIMEOUT` | `2.0` | Connection timeout (seconds) |
| `SQUIRREL_EPICS_CA_TIMEOUT` | `5.0` | Operation timeout (seconds) |
| `SQUIRREL_EPICS_MAX_WORKERS` | `1000` | Thread pool size for parallel EPICS ops |
| `SQUIRREL_EPICS_CHUNK_SIZE` | `1000` | PVs per batch in parallel operations |
| `SQUIRREL_DEBUG` | `false` | Enable debug logging |

See `.env.example` for a template.

---

## Docker Commands Reference

```bash
# Start all services
cd docker
docker-compose up

# Start in background (detached)
docker-compose up -d

# Rebuild images after code changes
docker-compose up --build

# View logs
docker-compose logs -f backend
docker-compose logs -f db

# Stop services
docker-compose down

# Stop and remove volumes (reset database)
docker-compose down -v

# Execute command in running container
docker exec -it squirrel-backend bash
docker exec -it squirrel-db psql -U squirrel

# Run migrations in Docker
docker exec -it squirrel-backend alembic upgrade head
```

---

## Troubleshooting

### Database connection refused
```bash
# Check if PostgreSQL is running
docker-compose ps
# Or for local: pg_isready -h localhost -p 5432
```

### Migrations fail
```bash
# Ensure database exists
docker exec -it squirrel-db createdb -U squirrel squirrel

# Check migration status
alembic current
```

### EPICS connection issues
```bash
# Verify EPICS environment
echo $EPICS_CA_ADDR_LIST

# Test PV connectivity
caget <pv_name>
```

### Port already in use
```bash
# Find process using port 8000
lsof -i :8000

# Use different port
uvicorn app.main:app --reload --port 8001
```

---

## Frontend

The Squirrel React frontend is available at:
- Repository: `/Users/yazar/projects/squirrel`
- Default API URL: `http://localhost:8000`

Configure the frontend to point to this backend by setting the API base URL.

---

## License

MIT License
