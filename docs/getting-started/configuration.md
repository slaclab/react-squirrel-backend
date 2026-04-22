# Configuration

Application settings use the `SQUIRREL_` prefix and are defined in [`app/config.py`](https://github.com/slaclab/react-squirrel-backend/blob/main/app/config.py). EPICS networking is controlled by the standard EPICS environment variables (no `SQUIRREL_` prefix) and is consumed by `aioca` / `p4p` directly.

## Application Environment Variables

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_DATABASE_URL` | `postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel` | Database connection string |
| `SQUIRREL_DATABASE_POOL_SIZE` | `30` | Connection pool size |
| `SQUIRREL_DATABASE_MAX_OVERFLOW` | `20` | Max overflow connections |

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_REDIS_URL` | `redis://:squirrel@localhost:6379/0` | Redis connection string (includes `REDIS_PASSWORD` by default) |
| `SQUIRREL_REDIS_USERNAME` | (empty) | Redis authentication username |
| `SQUIRREL_REDIS_PASSWORD` | `squirrel` | Redis authentication password |
| `SQUIRREL_REDIS_PV_CACHE_TTL` | `60` | PV cache TTL in seconds |

### EPICS (application-level)

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_EPICS_CA_TIMEOUT` | `10.0` | Channel Access read timeout in seconds |
| `SQUIRREL_EPICS_CA_CONN_TIMEOUT` | `5.0` | Channel Access connection timeout in seconds |
| `SQUIRREL_EPICS_PVA_TIMEOUT` | `10.0` | PVAccess protocol timeout in seconds |
| `SQUIRREL_EPICS_UNPREFIXED_PVA_FALLBACK` | `false` | If true, unprefixed PVs try CA then PVA on failure |
| `SQUIRREL_EPICS_CHUNK_SIZE` | `1000` | PVs per batch in parallel operations |

### EPICS networking (library-level, no `SQUIRREL_` prefix)

These are standard EPICS environment variables, read by `aioca` and `p4p`. Docker Compose passes them through from `docker/.env` — see [Docker-Specific Configuration](#docker-specific-configuration) below.

| Variable | Purpose |
|----------|---------|
| `EPICS_CA_ADDR_LIST` | Space-separated list of Channel Access server addresses |
| `EPICS_CA_AUTO_ADDR_LIST` | `YES` to broadcast-discover servers on the local subnet |
| `EPICS_CA_SERVER_PORT`, `EPICS_CA_REPEATER_PORT` | CA ports |
| `EPICS_PVA_ADDR_LIST`, `EPICS_PVA_AUTO_ADDR_LIST` | PVAccess equivalents |
| `EPICS_PVA_SERVER_PORT`, `EPICS_PVA_BROADCAST_PORT` | PVAccess ports |

### PV Monitor

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_PV_MONITOR_BATCH_SIZE` | `500` | PVs per subscription batch |
| `SQUIRREL_PV_MONITOR_BATCH_DELAY_MS` | `100` | Delay between batches in ms |
| `SQUIRREL_PV_MONITOR_HEARTBEAT_INTERVAL` | `1.0` | Heartbeat update interval in seconds |

### Watchdog

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_WATCHDOG_ENABLED` | `true` | Enable health monitoring |
| `SQUIRREL_WATCHDOG_CHECK_INTERVAL` | `60.0` | Check interval in seconds |
| `SQUIRREL_WATCHDOG_STALE_THRESHOLD` | `300.0` | Stale data threshold in seconds |
| `SQUIRREL_WATCHDOG_RECONNECT_TIMEOUT` | `2.0` | Timeout for reconnection attempts in seconds |

### WebSocket

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_WEBSOCKET_BATCH_INTERVAL_MS` | `100` | Batch interval for updates in ms |

### Debug

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_DEBUG` | `false` | Enable debug logging |

### Bulk Operations

| Variable | Default | Description |
|----------|---------|-------------|
| `SQUIRREL_BULK_INSERT_BATCH_SIZE` | `5000` | Batch size for PostgreSQL COPY bulk inserts |

## Example .env File

```bash
# Database
SQUIRREL_DATABASE_URL=postgresql+asyncpg://squirrel:squirrel@localhost:5432/squirrel
SQUIRREL_DATABASE_POOL_SIZE=30
SQUIRREL_DATABASE_MAX_OVERFLOW=20

# EPICS (application-level)
SQUIRREL_EPICS_CA_TIMEOUT=10.0
SQUIRREL_EPICS_CA_CONN_TIMEOUT=5.0
SQUIRREL_EPICS_PVA_TIMEOUT=10.0
SQUIRREL_EPICS_CHUNK_SIZE=1000

# EPICS networking (library-level — no SQUIRREL_ prefix)
EPICS_CA_AUTO_ADDR_LIST=YES
# EPICS_CA_ADDR_LIST="lcls-prod01:5068 lcls-prod01:5063"

# Redis
SQUIRREL_REDIS_URL=redis://localhost:6379/0
SQUIRREL_REDIS_USERNAME=
SQUIRREL_REDIS_PASSWORD=squirrel
SQUIRREL_REDIS_PV_CACHE_TTL=60

# PV Monitor
SQUIRREL_PV_MONITOR_BATCH_SIZE=500
SQUIRREL_PV_MONITOR_BATCH_DELAY_MS=100
SQUIRREL_PV_MONITOR_HEARTBEAT_INTERVAL=1.0

# Watchdog
SQUIRREL_WATCHDOG_ENABLED=true
SQUIRREL_WATCHDOG_CHECK_INTERVAL=60.0
SQUIRREL_WATCHDOG_STALE_THRESHOLD=300.0
SQUIRREL_WATCHDOG_RECONNECT_TIMEOUT=2.0

# WebSocket
SQUIRREL_WEBSOCKET_BATCH_INTERVAL_MS=100

# Bulk Operations
SQUIRREL_BULK_INSERT_BATCH_SIZE=5000
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
