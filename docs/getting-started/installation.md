# Installation

This is the canonical setup guide for Squirrel Backend. Two paths are supported: a fully containerized stack via Docker Compose (recommended), and a hybrid setup that runs infrastructure in containers but the application processes locally.

## Prerequisites

- Docker and Docker Compose
- (Local development only) Python 3.11+

## Option 1: Docker Compose (Recommended)

### 1. Clone and configure

```bash
git clone https://github.com/slaclab/react-squirrel-backend.git
cd react-squirrel-backend

# Copy the example environment file and edit for your site
cp docker/.env.example docker/.env
```

`docker/.env` is gitignored. Edit it if you need to reach EPICS servers outside `localhost` — see [Configuration](configuration.md#docker-configuration-docker-env).

!!! note "Linux users"
    On Linux you can skip the EPICS DNS mappings and uncomment `network_mode: host` in `docker/docker-compose.yml` instead.

### 2. Start the stack

```bash
cd docker
docker compose up -d --build
```

Migrations run automatically via the API container's entrypoint. The Compose project is named **`squirrel`**, so containers are named:

| Container | Port | Role |
|---|---|---|
| `squirrel-api` | 8080 | REST + WebSocket API |
| `squirrel-db` | 5432 | PostgreSQL |
| `squirrel-redis` | 6379 | Cache, queue, pub/sub |
| `squirrel-monitor` | — | EPICS PV monitor (1 replica) |
| `squirrel-worker-1`, `squirrel-worker-2` | — | Arq background workers |

### 3. Create an API key

All endpoints require authentication. Create your first key from inside the API container:

```bash
docker exec squirrel-api python -m scripts.create_key <app-name> [--read] [--write]
```

!!! warning "Save your token"
    The plaintext token (`sq_…`) is only shown once. Store it securely before continuing.

### 4. Access the services

- **API**: [http://localhost:8080](http://localhost:8080)
- **Swagger UI**: [http://localhost:8080/docs](http://localhost:8080/docs)
- **Health summary**: [http://localhost:8080/v1/health/summary](http://localhost:8080/v1/health/summary)

## Option 2: Local Development

Run PostgreSQL and Redis in Docker; run the API, monitor, and worker on the host with hot-reload.

### 1. Start infrastructure

```bash
cd docker
docker compose up -d db redis
```

### 2. Set up the Python environment

```bash
cd ..
python -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Run migrations

```bash
alembic upgrade head
```

### 4. Start the application processes

Each in its own terminal:

=== "Terminal 1: API"
    ```bash
    uvicorn app.main:app --reload --port 8000
    ```

=== "Terminal 2: PV monitor"
    ```bash
    python -m app.monitor_main
    ```

=== "Terminal 3: Worker"
    ```bash
    arq app.worker.WorkerSettings
    ```

!!! important "All three are required"
    - **API** handles HTTP and WebSocket traffic.
    - **Monitor** maintains the Redis cache of live PV values.
    - **Worker** processes background jobs (snapshot create / restore).

For configuration, see [Configuration](configuration.md). For native runs the `SQUIRREL_*` settings come from your shell environment — there is no top-level `.env` file in this repo.

## Loading PVs from CSV

Expected CSV columns:

```csv
Setpoint,Readback,Region,Area,Subsystem
FBCK:LNG6:1:BC2ELTOL,,"Feedback-All","LIMITS","FBCK"
QUAD:LI21:201:BDES,QUAD:LI21:201:BACT,"Cu Linac","LI21","Magnet"
```

Upload through the UI:

1. Open the "Browse PVs" page in the frontend.
2. Click "Import PVs".
3. Select the CSV.

## Docker command reference

```bash
# Start all services (foreground)
cd docker
docker compose up

# Start detached
docker compose up -d

# Rebuild after code changes
docker compose up --build

# Tail logs
docker compose logs -f api
docker compose logs -f monitor
docker compose logs -f worker

# Stop everything
docker compose down

# Stop and wipe the database
docker compose down -v

# Scale workers
docker compose up -d --scale worker=4

# Shell into a container
docker exec -it squirrel-api bash
docker exec -it squirrel-db psql -U squirrel
docker exec -it squirrel-redis redis-cli

# Run a one-off migration
docker exec -it squirrel-api alembic upgrade head
```

## Troubleshooting

### Snapshots are empty

Expected when no PVs exist on your EPICS network. Make sure the network is reachable from Docker (or your local machine) and that PVs have been imported.

### Workers not running

Snapshots will hang if no worker is consuming from the queue:

```bash
docker compose ps worker
docker compose up -d worker
docker compose logs -f worker
```

### Port 8080 already in use

Edit `docker/docker-compose.yml` and remap the port:

```yaml
api:
  ports:
    - "8081:8000"   # Change 8080 → 8081
```

…or override `API_HOST_PORT` in `docker/.env`.

### Monitor not connecting

Check the monitor logs and Redis connectivity:

```bash
docker compose logs monitor
docker exec -it squirrel-redis redis-cli PING
```

## Next steps

- [Configuration](configuration.md) — environment variables and `docker/.env`
- [API Keys](api-keys.md) — create, list, deactivate
- [API Reference](../api-reference/index.md) — REST and WebSocket endpoints
- [Architecture](../architecture/index.md) — system design
