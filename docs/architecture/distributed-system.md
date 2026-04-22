# Distributed System

Squirrel Backend uses a distributed architecture with separate processes for different concerns, enabling horizontal scaling and fault isolation.

## Core Components

### 1. API Server (`app/main.py`)

FastAPI application serving REST and WebSocket endpoints. **Decoupled from PV monitoring** for fast startup and fault isolation.

**Startup Sequence:**

1. Initialize EPICS service (for direct reads during snapshot restore)
2. Connect to Redis (used for reading cached values)
3. Start WebSocket DiffManager (subscribes to Redis pub/sub)

**Key Features:**

- Sub-second startup time (no PV subscription blocking)
- Horizontally scalable behind load balancer
- Crash-isolated from EPICS/aioca issues

### 2. PV Monitor (`app/monitor_main.py`)

Dedicated process for EPICS PV monitoring. Runs as a **single instance** with leader election.

**Responsibilities:**

- Subscribe to all PVs via aioca monitors
- Update Redis cache with PV values
- Publish updates to Redis pub/sub
- Run Watchdog for health checks

**Leader Election:**

- Uses Redis lock (`squirrel:monitor:lock`) with TTL
- Prevents duplicate monitoring in multi-instance deployments
- Auto-recovers if leader dies

### 3. Arq Worker (`app/worker.py`)

Background task processor using Redis-backed Arq queue.

**Features:**

- Job persistence across restarts
- Automatic retries with exponential backoff
- Scalable (can run multiple workers)
- 10-minute job timeout

**Tasks:**

- `create_snapshot_task` - Create snapshots from cache or EPICS
- `restore_snapshot_task` - Restore snapshot values to EPICS

### 4. Configuration (`app/config.py`)

Pydantic-Settings with environment variable support (prefix: `SQUIRREL_`):

| Category | Key Settings |
|----------|--------------|
| Database | `database_url`, `database_pool_size` (30), `database_max_overflow` (20) |
| EPICS | `epics_ca_timeout` (10s), `epics_ca_conn_timeout` (5s), `epics_chunk_size` (1000) |
| Redis | `redis_url`, `redis_pv_cache_ttl` (60s) |
| PV Monitor | `pv_monitor_batch_size` (500), `pv_monitor_batch_delay_ms` (100) |
| Watchdog | `watchdog_check_interval` (60s), `watchdog_stale_threshold` (300s) |
| WebSocket | `websocket_batch_interval_ms` (100) |

EPICS network discovery (`EPICS_CA_ADDR_LIST`, `EPICS_PVA_ADDR_LIST`, etc.) is configured via the standard EPICS library env vars — not through Pydantic settings.

## Performance Optimizations

### 1. Process Isolation

- API starts in <1s (no PV subscription blocking)
- Monitor crash doesn't affect API
- Workers can scale independently

### 2. Database

- Connection pooling (30 + 20 overflow)
- PostgreSQL COPY for bulk inserts (10x faster)
- ID-based pagination (no OFFSET)
- Indexes on search fields

### 3. EPICS

- Batched PV startup (500/batch, 100ms delay) prevents UDP flood
- Async operations via aioca (no blocking)
- Circuit breaker prevents cascading timeouts
- Connection pre-caching

### 4. Redis Caching

- Instant snapshot reads (<5s for 40K PVs)
- PV Monitor maintains fresh cache
- Pub/Sub for efficient broadcasts

### 5. WebSocket

- Diff-based streaming (only deltas)
- 100ms batching window
- Redis-based subscription registry for multi-instance
- Reduces bandwidth 10-100x

### 6. Task Queue

- Jobs persist across restarts
- Automatic retries for transient failures
- Progress tracking in database

## Circuit Breaker Pattern

The circuit breaker prevents cascading failures when EPICS IOCs become unresponsive.

![Circuit breaker state flow](../assets/figure-6-circuit-breaker-light.png#only-light)
![Circuit breaker state flow](../assets/figure-6-circuit-breaker-dark.png#only-dark)

**States:**

- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Too many failures, requests fail immediately
- **HALF-OPEN**: Testing if service recovered

## Deployment Options

For Docker Compose and local-development setup, see [Installation](../getting-started/installation.md).

## Health Monitoring

| Endpoint | Description |
|----------|-------------|
| `/v1/health/heartbeat` | Lightweight liveness check (no auth) |
| `/v1/health/summary` | Consolidated health for dashboards (DB, Redis, monitor, watchdog) |
| `/v1/health/monitor/status` | PV monitor process health (via heartbeat) |
| `/v1/health/circuits` | Circuit breaker status by IOC prefix |

See [REST Endpoints › Health](../api-reference/endpoints.md#health-endpoints) for the full list.
