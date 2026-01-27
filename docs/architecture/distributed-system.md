# Distributed System

Squirrel Backend uses a distributed architecture with separate processes for different concerns, enabling horizontal scaling and fault isolation.

## Core Components

### 1. API Server (`app/main.py`)

FastAPI application serving REST and WebSocket endpoints. **Decoupled from PV monitoring** for fast startup and fault isolation.

**Startup Sequence:**

1. Connect to Redis
2. Start WebSocket DiffManager (subscribes to Redis pub/sub)
3. Initialize EPICS service (for direct reads during snapshot restore)

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
| Database | `database_url`, `pool_size` (30), `max_overflow` (20) |
| EPICS | `ca_addr_list`, `ca_timeout` (10s), `chunk_size` (1000) |
| Redis | `redis_url`, `pv_cache_ttl` (60s) |
| PV Monitor | `batch_size` (500), `batch_delay_ms` (100) |
| Watchdog | `check_interval` (60s), `stale_threshold` (300s) |
| WebSocket | `batch_interval_ms` (100) |

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

```
EPICS Request (caget/caput)
         │
         ▼
┌─────────────────────────────────┐
│   Circuit Breaker Check         │
│   (by IOC prefix)               │
└─────────────────┬───────────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌───────┐   ┌───────────────────┐
│ OPEN  │   │ CLOSED/HALF-OPEN │
│       │   │                   │
│ Fail  │   │ Execute request   │
│ Fast  │   │                   │
└───┬───┘   └─────────┬─────────┘
    │                 │
    │            ┌────┴────┐
    │            │         │
    │            ▼         ▼
    │        ┌───────┐   ┌───────┐
    │        │Success│   │Failure│
    │        └───┬───┘   └───┬───┘
    │            │           │
    │            ▼           ▼
    │     Reset count   Increment count
    │     (HALF→CLOSED) (threshold→OPEN)
    │            │           │
    └────────────┴───────────┘
                 │
                 ▼
             Response
```

**States:**

- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Too many failures, requests fail immediately
- **HALF-OPEN**: Testing if service recovered

## Deployment Options

### Docker Compose (Recommended)

Full distributed deployment with all services:

```bash
cd docker
docker-compose up --build
```

This starts:

- **PostgreSQL** (port 5432)
- **Redis** (port 6379)
- **API** (port 8000) - REST/WebSocket server
- **Monitor** (1 replica) - PV monitoring
- **Worker** (2 replicas) - Background task processing

### Legacy Mode

For simpler deployments or backward compatibility:

```bash
cd docker
docker-compose --profile legacy up backend db redis
```

### Local Development

```bash
# 1. Start infrastructure
cd docker
docker-compose up -d db redis

# 2. Set up Python environment
cd ..
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# 3. Run migrations
alembic upgrade head

# 4. Start services (in separate terminals)
uvicorn app.main:app --reload --port 8000      # API
python -m app.monitor_main                      # Monitor
arq app.worker.WorkerSettings                   # Worker
```

## Health Monitoring

| Endpoint | Description |
|----------|-------------|
| `/v1/health` | Overall API health |
| `/v1/health/db` | Database connectivity |
| `/v1/health/redis` | Redis connectivity |
| `/v1/health/monitor/status` | PV monitor process health (via heartbeat) |
| `/v1/health/circuits` | Circuit breaker status by IOC prefix |
