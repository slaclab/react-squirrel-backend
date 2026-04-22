# Installation

This guide covers all installation options for Squirrel Backend.

## Option 1: Docker Compose (Recommended)

The easiest way to get started with the full distributed architecture:

```bash
# Clone the repository
git clone https://github.com/slaclab/react-squirrel-backend.git
cd react-squirrel-backend/docker

# Configure environment (EPICS network, Redis password, etc.)
cp .env.example .env
# Edit .env if you need to reach EPICS servers outside localhost

# Start the full stack (migrations run automatically via entrypoint.sh)
docker compose up -d --build

# Create an API key (required to use the API)
docker exec squirrel-api python -m scripts.create_key <app-name> [--read] [--write]
```

!!! warning "Save your token"
    The plaintext token is only shown once at creation. Store it securely before continuing.

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

## Option 2: Local Development

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

### 5. Start services

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

## Loading PVs from CSV

The expected CSV format:

```csv
Setpoint,Readback,Region,Area,Subsystem
FBCK:LNG6:1:BC2ELTOL,,"Feedback-All","LIMITS","FBCK"
QUAD:LI21:201:BDES,QUAD:LI21:201:BACT,"Cu Linac","LI21","Magnet"
```

Upload through the UI:

1. Navigate to the "Browse PVs" page
2. Click the "Import PVs" button
3. Select the consolidated CSV

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

```
