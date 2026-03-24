# Squirrel Backend

High-performance Python FastAPI backend for EPICS control system snapshot/restore operations, designed to handle 40-50K PVs efficiently.

## Features

- **Distributed Architecture**: Separate processes for API, PV monitoring, and background tasks
- **Fast Snapshot Creation**: Parallel EPICS reads or instant Redis cache reads (<5s for 40K PVs)
- **Efficient Restore Operations**: Parallel EPICS writes for quick machine state restoration
- **Real-Time Updates**: WebSocket streaming with diff-based updates and multi-instance support
- **Tag-based Organization**: Group and categorize PVs using hierarchical tags
- **Snapshot Comparison**: Compare two snapshots with tolerance-based diff
- **Persistent Job Queue**: Background tasks survive restarts with automatic retries
- **Circuit Breaker**: Fail-fast protection against unresponsive IOCs
- **PostgreSQL Storage**: Reliable relational database with async support

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Database | PostgreSQL 16+ |
| ORM | SQLAlchemy 2.0 (async) |
| Cache/Queue | Redis 7+ |
| Task Queue | Arq |
| EPICS | aioca (async Channel Access) |
| Migrations | Alembic |
| Validation | Pydantic v2 |

---

## Quick Start

**New here?** See [QUICKSTART.md](QUICKSTART.md) for a 2-minute setup guide!

### Option 1: Docker Compose (Recommended)

The easiest way to get started with the full distributed architecture:

```bash
# Clone the repository
git clone <repository-url>
cd react-squirrel-backend

# Start the full stack
cd docker
cp .env.example .env
# Note: If needing to make EPICS connections outside of your machine's localhost, edit
# the .env file to add the IP addresses or host names to EPICS_CA_ADDR_LIST/EPICS_PVA_ADDR_LIST
# as necessary. For example:
# EPICS_CA_ADDR_LIST=lcls-prod01:5068 lcls-prod01:5063
docker-compose up -d --build

# Configure the database
docker exec squirrel-api alembic upgrade head
```

This starts:
- **PostgreSQL** on port `5432`
- **Redis** on port `6379`
- **API Server** on port `8080` (REST/WebSocket)
- **PV Monitor** (1 replica) - EPICS monitoring process
- **Workers** (2 replicas) - Background task processors

The Docker Compose project is named **`squirrel`**, so containers are:
- `squirrel-api`, `squirrel-db`, `squirrel-redis`, `squirrel-monitor`, `squirrel-worker-1`, `squirrel-worker-2`

The API will be available at:
- **API**: http://localhost:8080
- **Swagger Docs**: http://localhost:8080/docs
- **Health Check**: http://localhost:8080/v1/health/summary

To stop the services:
```bash
docker compose down
```

To reset the database (delete all data):
```bash
docker compose down -v
```

### Option 2: Legacy Mode (Single Process)

For simpler deployments with embedded PV monitoring:

```bash
cd docker
cp .env.example .env
docker compose --profile legacy up backend db redis
```

This runs the API with embedded PV monitor on port `8001`.

**Note**: Workers are still required for snapshot creation. Start them separately:
```bash
docker compose up -d worker
```

### Option 3: Local Development

Run infrastructure in Docker, services locally for faster development:

```bash
# 1. Start PostgreSQL and Redis
cd docker
docker compose up -d db redis

# 2. Set up Python environment (or run ./setup.sh)
cd ..
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Edit .env if needed (defaults work with docker compose)

# 4. Run database migrations
alembic upgrade head

# 5. (Optional) Load test data
python -m scripts.seed_pvs --count 100

# 6. Start services (in separate terminals)
uvicorn app.main:app --reload --port 8000      # API Server
python -m app.monitor_main                      # PV Monitor
arq app.worker.WorkerSettings                   # Worker (REQUIRED for snapshots)
```

**Important**: All three services must be running for full functionality:
- **API**: Handles HTTP/WebSocket requests
- **Monitor**: Maintains Redis cache of live PV values
- **Worker**: Processes background jobs (snapshot creation/restore)

---

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   API Server    │     │   PV Monitor    │     │   Arq Worker    │
│  (squirrel-api) │     │(squirrel-monitor)│     │(squirrel-worker)│
│  REST/WebSocket │     │  EPICS → Redis  │     │  Snapshot jobs  │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
            ┌─────────────┐           ┌─────────────┐
            │    Redis    │           │  PostgreSQL │
            │ Cache/Queue │           │   Storage   │
            └─────────────┘           └─────────────┘
                    │
                    ▼
            ┌─────────────┐
            │  EPICS IOCs │
            │  40-50K PVs │
            └─────────────┘
```

For detailed architecture documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

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
| `POST` | `/v1/snapshots` | Create snapshot (async, returns job ID) |
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

### Job Endpoints (`/v1/jobs`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/jobs/{id}` | Get job status and progress |

### Health Endpoints (`/v1/health`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/health` | Overall health |
| `GET` | `/v1/health/db` | Database connectivity |
| `GET` | `/v1/health/redis` | Redis connectivity |
| `GET` | `/v1/health/monitor/status` | PV monitor process health |
| `GET` | `/v1/health/circuits` | Circuit breaker status |

### WebSocket (`/ws`)

Real-time PV value streaming with diff-based updates:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

// Subscribe to PVs
ws.send(JSON.stringify({
  action: 'subscribe',
  pv_names: ['PV:NAME:1', 'PV:NAME:2']
}));

// Receive updates
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // { pv_name: 'PV:NAME:1', value: 42.0, timestamp: '...' }
};
```

---

## Configuration

All configuration is via environment variables (with `SQUIRREL_` prefix):

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_DATABASE_URL` | `postgresql+asyncpg://...` | Database connection |
| `SQUIRREL_DATABASE_POOL_SIZE` | `30` | Connection pool size |
| `SQUIRREL_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `SQUIRREL_EPICS_CA_TIMEOUT` | `10.0` | Operation timeout (seconds) |
| `SQUIRREL_EPICS_CHUNK_SIZE` | `1000` | PVs per batch in parallel ops |
| `SQUIRREL_PV_MONITOR_BATCH_SIZE` | `500` | PVs per subscription batch |
| `SQUIRREL_WATCHDOG_ENABLED` | `true` | Enable health monitoring |
| `SQUIRREL_EMBEDDED_MONITOR` | `false` | Run monitor in API process |
| `SQUIRREL_DEBUG` | `false` | Enable debug logging |

See `.env.example` for a complete template.

### Docker-Specific Configuration

If needing to create EPICS connections to specific host names, configure EPICS server DNS mappings:

```bash
# Copy the example file
cp docker/.env.example docker/.env

# Edit with your EPICS server hostnames and IPs
# Get IPs with: host <hostname>
```

Example `docker/.env`:
```bash
COMPOSE_PROJECT_NAME=squirrel

EPICS_HOST_PROD=your-epics-server:xxx.xxx.xxx.xxx
EPICS_HOST_DMZ=your-dmz-server:xxx.xxx.xxx.xxx
```

**Note**: `docker/.env` is gitignored and should contain your site-specific configuration.

---

## Docker Commands Reference

```bash
# Start all services
cd docker
docker compose up

# Start in background (detached)
docker compose up -d

# Rebuild images after code changes
docker compose up --build

# View logs
docker compose logs -f api
docker compose logs -f monitor
docker compose logs -f worker

# Stop services
docker compose down

# Stop and remove volumes (reset database)
docker compose down -v

# Scale workers (for high load)
docker compose up -d --scale worker=4

# Execute command in running container
docker exec -it squirrel-api bash
docker exec -it squirrel-db psql -U squirrel

# Run migrations in Docker
docker exec -it squirrel-api alembic upgrade head

# Load test data in Docker
docker compose exec api python -m scripts.seed_pvs --count 100
```

---

## Troubleshooting

### Database connection refused
```bash
# Check if PostgreSQL is running
docker compose ps db

# Check database health
docker compose logs db

# Test connection
docker exec -it squirrel-db pg_isready -U squirrel
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

### PV Monitor not updating
```bash
# Check monitor health via API
curl http://localhost:8000/v1/health/monitor/status

# Check Redis for heartbeat
docker exec -it squirrel-redis redis-cli GET squirrel:monitor:heartbeat
```

### Snapshots hanging or have no data
```bash
# Check if worker is running
docker compose ps worker

# If not running, start it
docker compose up -d worker

# Check worker logs
docker compose logs -f worker

# Verify worker is processing jobs
docker exec -it squirrel-redis redis-cli LLEN arq:queue
```

**Note**: Snapshots will be empty if:
- Test PVs don't exist on EPICS network (expected for development)
- Monitor can't connect to PVs (check EPICS_CA_ADDR_LIST)
- Redis cache is empty and direct EPICS reads fail

### Port already in use
```bash
# Find process using port 8080 (Docker) or 8000 (local)
lsof -i :8080

# Change Docker port in docker-compose.yml:
# ports:
#   - "8081:8000"  # Change 8080 to 8081

# Or use different port locally
uvicorn app.main:app --reload --port 8001
```

---

## Performance Benchmarking

```bash
# Start the backend first, then run:
python -m scripts.benchmark

# With more iterations
python -m scripts.benchmark --iterations 10

# Skip restore benchmark (no EPICS writes)
python -m scripts.benchmark --skip-restore
```

---

## Frontend

The Squirrel React frontend is available at:
- Repository: `squirrel` (separate repo)
- Default API URL: `http://localhost:8000`

Configure the frontend to point to this backend by setting the API base URL.

---

## License

MIT License
