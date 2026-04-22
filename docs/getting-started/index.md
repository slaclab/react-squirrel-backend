# Quick Start

Get the Squirrel Backend running in 2 minutes!

## Prerequisites

- Docker and Docker Compose installed
- (Optional) Python 3.11+ for local development

## Docker Compose (Fastest)

### 1. Configure EPICS DNS (Docker Desktop on macOS/Windows only)

If you need to connect to EPICS servers:

```bash
# Copy the example environment file
cp docker/.env.example docker/.env

# Edit docker/.env with your EPICS server IPs
# Get IPs with: host <hostname>
```

!!! note "Linux users"
    Skip this step and uncomment `network_mode: host` in `docker-compose.yml` instead.

### 2. Start everything

```bash
cd docker
docker compose up --build
```

### 3. Create an API key

All endpoints require authentication. Create your first key using the management script:

```bash
docker exec squirrel-api python -m scripts.create_key <app-name> [--read] [--write]
```

!!! warning "Save your token"
    The token (e.g. `sq_abc123...`) is only shown once. Store it securely before continuing.

**That's it!** The backend is now running:

- **API**: [http://localhost:8080](http://localhost:8080)
- **Swagger docs**: [http://localhost:8080/docs](http://localhost:8080/docs)
- **Health**: [http://localhost:8080/v1/health/summary](http://localhost:8080/v1/health/summary)

### What's Running?

| Service | Description |
|---------|-------------|
| `squirrel-api` | REST/WebSocket API server (port 8080) |
| `squirrel-db` | PostgreSQL database (port 5432) |
| `squirrel-redis` | Redis cache/queue (port 6379) |
| `squirrel-monitor` | EPICS PV monitoring service |
| `squirrel-worker-1` & `squirrel-worker-2` | Background job processors |

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f monitor
docker compose logs -f worker
```

### Stop Everything

```bash
docker compose down

# Or to also delete the database
docker compose down -v
```

## Local Development

Better for active development with hot-reload:

```bash
# 1. Start infrastructure only
cd docker
docker compose up -d db redis

# 2. Run setup script
cd ..
./setup.sh

# 3. Run migrations
alembic upgrade head

# 4. Start services (each in a separate terminal)
uvicorn app.main:app --reload --port 8000      # Terminal 1: API
python -m app.monitor_main                      # Terminal 2: Monitor
arq app.worker.WorkerSettings                   # Terminal 3: Worker
```

Access at: [http://localhost:8000](http://localhost:8000)

## Common Commands

```bash
# Check service status
docker compose ps

# Restart a service
docker compose restart api

# Scale workers
docker compose up -d --scale worker=4

# Access database
docker exec -it squirrel-db psql -U squirrel

# Access Redis CLI
docker exec -it squirrel-redis redis-cli

# Run migrations in Docker
docker exec -it squirrel-api alembic upgrade head
```

## Troubleshooting

### Snapshots are empty

This is normal when no PVs exist on your EPICS network. Make sure your EPICS network is reachable from Docker and that PVs have been loaded via the UI's "Import PVs" flow.

### Worker not running

Snapshots will hang if the worker isn't running:

```bash
docker compose ps worker           # Check status
docker compose up -d worker        # Start if stopped
docker compose logs -f worker      # View logs
```

### Port 8080 already in use

Edit `docker/docker-compose.yml` and change the port:

```yaml
api:
  ports:
    - "8081:8000"  # Change 8080 to 8081
```

### Monitor not connecting

Check Redis connection:

```bash
docker compose logs monitor
docker exec -it squirrel-redis redis-cli PING
```

## Next Steps

- [Installation options](installation.md) for detailed setup instructions
- [Configuration](configuration.md) for environment variables
- [API Keys](api-keys.md) for managing authentication tokens
- [Architecture](../architecture/index.md) for system design
