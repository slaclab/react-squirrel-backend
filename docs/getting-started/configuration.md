# Configuration

All configuration is via environment variables with the `SQUIRREL_` prefix.

## Environment Variables

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_DATABASE_URL` | `postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel` | Database connection string |
| `SQUIRREL_DATABASE_POOL_SIZE` | `30` | Connection pool size |
| `SQUIRREL_DATABASE_MAX_OVERFLOW` | `20` | Max overflow connections |

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `SQUIRREL_REDIS_PV_CACHE_TTL` | `60` | PV cache TTL in seconds |

### EPICS

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_EPICS_CA_ADDR_LIST` | (empty) | EPICS CA address list |
| `SQUIRREL_EPICS_CA_TIMEOUT` | `10.0` | Operation timeout in seconds |
| `SQUIRREL_EPICS_CHUNK_SIZE` | `1000` | PVs per batch in parallel operations |

### PV Monitor

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_PV_MONITOR_BATCH_SIZE` | `500` | PVs per subscription batch |
| `SQUIRREL_PV_MONITOR_BATCH_DELAY_MS` | `100` | Delay between batches in ms |

### Watchdog

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_WATCHDOG_ENABLED` | `true` | Enable health monitoring |
| `SQUIRREL_WATCHDOG_CHECK_INTERVAL` | `60.0` | Check interval in seconds |
| `SQUIRREL_WATCHDOG_STALE_THRESHOLD` | `300.0` | Stale data threshold in seconds |

### WebSocket

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_WEBSOCKET_BATCH_INTERVAL_MS` | `100` | Batch interval for updates in ms |

### Legacy Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_EMBEDDED_MONITOR` | `false` | Run monitor in API process |

### Debug

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_DEBUG` | `false` | Enable debug logging |

## Example .env File

```bash
# Database
SQUIRREL_DATABASE_URL=postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel
SQUIRREL_DATABASE_POOL_SIZE=30
SQUIRREL_DATABASE_MAX_OVERFLOW=20

# EPICS
SQUIRREL_EPICS_CA_ADDR_LIST=
SQUIRREL_EPICS_CA_TIMEOUT=10.0
SQUIRREL_EPICS_CHUNK_SIZE=1000

# Redis
SQUIRREL_REDIS_URL=redis://localhost:6379/0
SQUIRREL_REDIS_PV_CACHE_TTL=60

# PV Monitor
SQUIRREL_PV_MONITOR_BATCH_SIZE=500
SQUIRREL_PV_MONITOR_BATCH_DELAY_MS=100

# Watchdog
SQUIRREL_WATCHDOG_ENABLED=true
SQUIRREL_WATCHDOG_CHECK_INTERVAL=60.0
SQUIRREL_WATCHDOG_STALE_THRESHOLD=300.0

# WebSocket
SQUIRREL_WEBSOCKET_BATCH_INTERVAL_MS=100

# Legacy Mode (embedded monitor in API process)
SQUIRREL_EMBEDDED_MONITOR=false
```

## Docker-Specific Configuration

For Docker Desktop on macOS/Windows, configure EPICS server DNS mappings:

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

!!! note
    `docker/.env` is gitignored and should contain your site-specific configuration.

## Configuration Categories

### Performance Tuning

For high-load environments (40K+ PVs):

```bash
# Increase database pool
SQUIRREL_DATABASE_POOL_SIZE=50
SQUIRREL_DATABASE_MAX_OVERFLOW=30

# Larger batches for bulk operations
SQUIRREL_EPICS_CHUNK_SIZE=2000

# More frequent WebSocket updates
SQUIRREL_WEBSOCKET_BATCH_INTERVAL_MS=50
```

### Development Settings

For local development:

```bash
SQUIRREL_DEBUG=true
SQUIRREL_WATCHDOG_ENABLED=false
SQUIRREL_PV_MONITOR_BATCH_SIZE=100
```

### Production Settings

For production deployments:

```bash
SQUIRREL_DEBUG=false
SQUIRREL_WATCHDOG_ENABLED=true
SQUIRREL_WATCHDOG_CHECK_INTERVAL=30.0
SQUIRREL_DATABASE_POOL_SIZE=50
```
