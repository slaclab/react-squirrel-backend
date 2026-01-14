# Squirrel Backend - Quick Start Guide

Get the backend running in 2 minutes!

## Prerequisites

- Docker and Docker Compose installed
- (Optional) Python 3.11+ for local development

## Option 1: Docker Compose (Fastest)

Start everything with one command:

```bash
cd docker
docker compose up --build
```

**That's it!** The backend is now running:
- API: http://localhost:8080
- Swagger docs: http://localhost:8080/docs
- Health: http://localhost:8080/v1/health/summary

### What's Running?

- `squirrel-api` - REST/WebSocket API server (port 8080)
- `squirrel-db` - PostgreSQL database (port 5432)
- `squirrel-redis` - Redis cache/queue (port 6379)
- `squirrel-monitor` - EPICS PV monitoring service
- `squirrel-worker-1` & `squirrel-worker-2` - Background job processors

### Load Test Data

```bash
# In a new terminal
docker compose exec api python -m scripts.seed_pvs --count 100
```

This creates 100 test PVs with tags. Now you can test snapshots!

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

## Option 2: Local Development

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

# 4. Load test data
python -m scripts.seed_pvs --count 100

# 5. Start services (each in a separate terminal)
uvicorn app.main:app --reload --port 8000      # Terminal 1: API
python -m app.monitor_main                      # Terminal 2: Monitor
arq app.worker.WorkerSettings                   # Terminal 3: Worker
```

Access at: http://localhost:8000

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
This is normal! Test PVs don't exist on a real EPICS network. To test with real data:
1. Upload real PV addresses via CSV: `python -m scripts.upload_csv your_pvs.csv`
2. Make sure your EPICS network is accessible from Docker

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

- Read the full [README.md](README.md) for detailed documentation
- Check out [ARCHITECTURE.md](ARCHITECTURE.md) for system design
- See [API documentation](http://localhost:8080/docs) after starting the backend

## Need Help?

- Check logs: `docker compose logs -f [service]`
- Verify all services are running: `docker compose ps`
- Restart everything: `docker compose restart`
- Reset database: `docker compose down -v && docker compose up -d`

Happy snapshoting! 🐿️
