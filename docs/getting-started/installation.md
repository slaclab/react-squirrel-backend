# Installation

This guide covers all installation options for Squirrel Backend.

## Option 1: Docker Compose (Recommended)

The easiest way to get started with the full distributed architecture:

```bash
# Clone the repository
git clone https://github.com/slaclab/react-squirrel-backend.git
cd react-squirrel-backend

# Start the full stack
cd docker
docker-compose up -d --build

# Configure the database
docker exec squirrel-api alembic upgrade head
```

This starts:

| Service | Port | Description |
|---------|------|-------------|
| **PostgreSQL** | 5432 | Database |
| **Redis** | 6379 | Cache/Queue |
| **API Server** | 8080 | REST/WebSocket |
| **PV Monitor** | - | EPICS monitoring (1 replica) |
| **Workers** | - | Background tasks (2 replicas) |

The Docker Compose project is named **`squirrel`**, so containers are:

- `squirrel-api`
- `squirrel-db`
- `squirrel-redis`
- `squirrel-monitor`
- `squirrel-worker-1`
- `squirrel-worker-2`

### Accessing the Services

- **API**: http://localhost:8080
- **Swagger Docs**: http://localhost:8080/docs
- **Health Check**: http://localhost:8080/v1/health/summary

### Stopping Services

```bash
# Stop services
docker compose down

# Reset database (delete all data)
docker compose down -v
```

## Option 2: Legacy Mode (Single Process)

For simpler deployments with embedded PV monitoring:

```bash
cd docker
docker compose --profile legacy up backend db redis
```

This runs the API with embedded PV monitor on port `8001`.

!!! warning "Workers still required"
    Workers are still required for snapshot creation. Start them separately:
    ```bash
    docker compose up -d worker
    ```

## Option 3: Local Development

Run infrastructure in Docker, services locally for faster development:

### 1. Start PostgreSQL and Redis

```bash
cd docker
docker compose up -d db redis
```

### 2. Set up Python environment

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

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env if needed (defaults work with docker compose)
```

### 4. Run database migrations

```bash
alembic upgrade head
```

### 5. (Optional) Load test data

```bash
python -m scripts.seed_pvs --count 100
```

### 6. Start services

In separate terminals:

=== "Terminal 1: API Server"
    ```bash
    uvicorn app.main:app --reload --port 8000
    ```

=== "Terminal 2: PV Monitor"
    ```bash
    python -m app.monitor_main
    ```

=== "Terminal 3: Worker"
    ```bash
    arq app.worker.WorkerSettings
    ```

!!! important "All services required"
    All three services must be running for full functionality:

    - **API**: Handles HTTP/WebSocket requests
    - **Monitor**: Maintains Redis cache of live PV values
    - **Worker**: Processes background jobs (snapshot creation/restore)

## Loading Data

### Upload PVs from CSV

The expected format:

```csv
Setpoint,Readback,Region,Area,Subsystem
FBCK:LNG6:1:BC2ELTOL,,"Feedback-All","LIMITS","FBCK"
QUAD:LI21:201:BDES,QUAD:LI21:201:BACT,"Cu Linac","LI21","Magnet"
```

#### Using the UI

1. Navigate to the "Browse PVs" page
2. Click the "Import PVs" button
3. Select the consolidated CSV

#### Using a bash script

```bash
# Copy script and data into docker service
docker cp /path/to/local/upload_csv.py squirrel-api:/tmp/
docker cp /path/to/local/consolidated.csv squirrel-api:/tmp/

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
