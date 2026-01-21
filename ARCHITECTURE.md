# Squirrel Backend Architecture

## Overview

Squirrel Backend is a high-performance FastAPI application designed to manage and monitor EPICS (Experimental Physics and Industrial Control System) process variables (PVs). It handles 40-50K PVs with real-time monitoring, caching, and snapshot capabilities.

The system uses a **distributed architecture** with separate processes for API serving, PV monitoring, and background task processing, enabling horizontal scaling and fault isolation.

## Technology Stack

| Category | Technology | Purpose |
|----------|------------|---------|
| **Framework** | FastAPI 0.109+ | REST API and WebSocket |
| **Language** | Python 3.11+ | Async/await support |
| **Database** | PostgreSQL 16+ | Primary data store |
| **ORM** | SQLAlchemy 2.0+ (async) | Database abstraction |
| **Cache** | Redis 7+ | PV value caching, pub/sub |
| **EPICS** | aioca 1.7+ | Async Channel Access |
| **Task Queue** | Arq | Redis-backed job queue |
| **Server** | Uvicorn | ASGI server |

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Load Balancer                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
    ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
    │   API Instance   │   │   API Instance   │   │   API Instance   │
    │   (squirrel-api) │   │   (squirrel-api) │   │   (squirrel-api) │
    │   REST + WebSocket│   │   REST + WebSocket│   │   REST + WebSocket│
    └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
             │                      │                      │
             └──────────────────────┼──────────────────────┘
                                    │
                                    ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                               Redis                                      │
    │  • PV Value Cache (Hash: pv:values)                                     │
    │  • Pub/Sub (pv updates, WebSocket broadcasts)                           │
    │  • Subscription Registry (multi-instance WebSocket support)             │
    │  • Arq Job Queue                                                        │
    │  • Monitor Leader Election Lock                                         │
    └──────────────────────────────┬──────────────────────────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   PV Monitor     │    │   Arq Worker     │    │   Arq Worker     │
│ (squirrel-monitor)│    │ (squirrel-worker)│    │ (squirrel-worker)│
│ Single instance  │    │ Scalable         │    │ Scalable         │
│ Leader election  │    │                  │    │                  │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                            PostgreSQL                                    │
    │  • PV metadata and configuration                                        │
    │  • Snapshots and snapshot values                                        │
    │  • Tags and tag groups                                                  │
    │  • Job tracking                                                         │
    └─────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │                         EPICS IOCs                                       │
    │  • 40-50K Process Variables                                             │
    │  • Channel Access protocol                                              │
    └─────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
squirrel-backend/
├── app/                          # Main application package
│   ├── main.py                   # FastAPI entry point (API-only)
│   ├── monitor_main.py           # Standalone PV monitor entry point
│   ├── worker.py                 # Arq worker configuration
│   ├── config.py                 # Pydantic settings management
│   ├── dependencies.py           # FastAPI dependency injection
│   │
│   ├── api/                      # API layer
│   │   ├── responses.py          # Response wrappers
│   │   └── v1/                   # API v1 endpoints
│   │       ├── router.py         # Main router aggregator
│   │       ├── pvs.py            # PV CRUD endpoints
│   │       ├── snapshots.py      # Snapshot operations
│   │       ├── tags.py           # Tag management
│   │       ├── jobs.py           # Job status tracking
│   │       ├── health.py         # Health monitoring
│   │       └── websocket.py      # Real-time PV updates
│   │
│   ├── services/                 # Business logic layer
│   │   ├── epics_service.py      # EPICS read/write (aioca)
│   │   ├── redis_service.py      # Redis cache management
│   │   ├── pv_monitor.py         # Background PV monitoring
│   │   ├── pv_service.py         # PV business logic
│   │   ├── snapshot_service.py   # Snapshot creation/restore
│   │   ├── tag_service.py        # Tag operations
│   │   ├── job_service.py        # Job tracking
│   │   ├── watchdog.py           # Health monitoring service
│   │   ├── circuit_breaker.py    # EPICS circuit breaker
│   │   ├── subscription_registry.py # Multi-instance WebSocket support
│   │   ├── bulk_insert_service.py# PostgreSQL COPY inserts
│   │   └── background_tasks.py   # Async background jobs
│   │
│   ├── tasks/                    # Arq task definitions
│   │   ├── __init__.py
│   │   └── snapshot_tasks.py     # Snapshot create/restore tasks
│   │
│   ├── shared/                   # Shared utilities
│   │   ├── __init__.py
│   │   └── redis_channels.py     # Redis channel constants
│   │
│   ├── repositories/             # Data access layer
│   │   ├── base.py               # Base repository class
│   │   ├── pv_repository.py      # PV database operations
│   │   ├── snapshot_repository.py# Snapshot storage
│   │   ├── tag_repository.py     # Tag queries
│   │   └── job_repository.py     # Job tracking
│   │
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── base.py               # Base model with UUID/timestamps
│   │   ├── pv.py                 # PV model
│   │   ├── snapshot.py           # Snapshot models
│   │   ├── tag.py                # Tag models
│   │   └── job.py                # Job model
│   │
│   ├── schemas/                  # Pydantic DTOs
│   │   ├── common.py             # Common response wrappers
│   │   ├── pv.py                 # PV DTOs
│   │   ├── snapshot.py           # Snapshot DTOs
│   │   ├── tag.py                # Tag DTOs
│   │   └── job.py                # Job DTOs
│   │
│   └── db/                       # Database configuration
│       └── session.py            # Async engine and session factory
│
├── alembic/                      # Database migrations
│   ├── alembic.ini
│   └── versions/                 # Migration files
│
├── docker/                       # Docker configuration
│   ├── docker-compose.yml        # Full stack deployment
│   └── Dockerfile.dev            # Development image
│
├── scripts/                      # Utility scripts
│   ├── upload_csv.py             # CSV data loader
│   ├── seed_pvs.py               # Test data generator
│   └── benchmark.py              # Performance testing
│
└── tests/                        # Test suite
    ├── conftest.py               # Pytest fixtures
    ├── test_api/                 # API integration tests
    ├── test_services/            # Service unit tests
    └── mocks/                    # Mock EPICS service
```

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

### 5. Database Models

```
┌──────────────────┐     ┌──────────────────┐
│       PV         │     │     TagGroup     │
├──────────────────┤     ├──────────────────┤
│ setpoint_address │     │ name             │
│ readback_address │     │ description      │
│ config_address   │     └────────┬─────────┘
│ device           │              │
│ description      │              │ 1:n
│ abs_tolerance    │              ▼
│ rel_tolerance    │     ┌──────────────────┐
└────────┬─────────┘     │       Tag        │
         │               ├──────────────────┤
         │ n:m           │ name             │
         └───────────────│ tag_group_id     │
                         └──────────────────┘

┌──────────────────┐     ┌──────────────────┐
│    Snapshot      │     │       Job        │
├──────────────────┤     ├──────────────────┤
│ title            │     │ type (enum)      │
│ comment          │     │ status (enum)    │
│ created_by       │     │ progress (0-100) │
└────────┬─────────┘     │ data (JSONB)     │
         │               │ result_id        │
         │ 1:n           │ retry_count      │
         ▼               └──────────────────┘
┌──────────────────┐
│  SnapshotValue   │
├──────────────────┤
│ pv_name          │
│ setpoint_value   │
│ readback_value   │
│ status           │
│ severity         │
└──────────────────┘
```

### 6. Services Layer

| Service | Responsibility |
|---------|----------------|
| **EPICSService** | aioca wrapper for caget/caput with circuit breaker |
| **RedisService** | PV value cache, connection tracking, pub/sub, leader election |
| **PVMonitor** | Background subscription to all PVs, updates Redis |
| **SnapshotService** | Create/restore snapshots from cache or EPICS |
| **Watchdog** | Periodic health checks, reconnection attempts |
| **CircuitBreaker** | Fail-fast on unresponsive IOCs |
| **SubscriptionRegistry** | Multi-instance WebSocket subscription tracking |
| **BulkInsertService** | High-perf PostgreSQL COPY for bulk data |

## Data Flow

### Snapshot Creation (Async via Arq)

```
API Request (/v1/snapshots POST)
         │
         ▼
┌─────────────────────────────────┐
│   JobService creates Job record │
└─────────────────┬───────────────┘
                  │
         ▼ (enqueue to Arq)
┌─────────────────────────────────┐
│     Return Job ID immediately    │
└─────────────────┬───────────────┘
                  │
         ▼ (Arq worker picks up)
┌─────────────────────────────────┐
│    Read PV addresses from DB     │
└─────────────────┬───────────────┘
                  │
         ▼ (use_cache?)
    ┌─────┴─────┐
    │           │
    ▼           ▼
┌───────┐   ┌───────────────┐
│ Redis │   │ EPICS direct  │
│ <5s   │   │ 30-60s        │
└───┬───┘   └───────┬───────┘
    │               │
    └───────┬───────┘
            │
            ▼
┌─────────────────────────────────┐
│  BulkInsertService (COPY)       │
│  Insert SnapshotValues to DB    │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│   Mark Job as COMPLETED          │
└─────────────────────────────────┘
```

### Real-Time PV Monitoring

```
            PV Monitor Process Startup
                       │
                       ▼
          ┌────────────────────────┐
          │  Acquire Leader Lock   │
          │  (Redis SETNX)         │
          └───────────┬────────────┘
                      │
                      ▼
          ┌────────────────────────┐
          │  Load PV addresses     │
          │  from PostgreSQL       │
          └───────────┬────────────┘
                      │
                      ▼
          ┌────────────────────────┐
          │  Batched PV init       │
          │  (500/batch, 100ms)    │
          └───────────┬────────────┘
                      │
      ┌───────────────┼───────────────┐
      │               │               │
      ▼               ▼               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│ aioca    │   │ aioca    │   │ aioca    │
│ monitor  │   │ monitor  │   │ monitor  │
│ (batch 1)│   │ (batch 2)│   │ (batch N)│
└────┬─────┘   └────┬─────┘   └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    │
                    ▼
          ┌────────────────────────┐
          │     Redis Cache        │
          │  • Hash: pv:values     │
          │  • Pub/Sub: updates    │
          └───────────┬────────────┘
                      │
                      ▼ (Redis pub/sub)
          ┌────────────────────────┐
          │    API Instances       │
          │  DiffStreamManager     │
          └───────────┬────────────┘
                      │
                      ▼
          ┌────────────────────────┐
          │  Subscription Registry │
          │  (Redis-based)         │
          └───────────┬────────────┘
                      │
                      ▼
          ┌────────────────────────┐
          │   WebSocket Clients    │
          │   (100ms batching)     │
          └────────────────────────┘
```

### Circuit Breaker Flow

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

## API Endpoints

**Base URL:** `/v1/`

**Standard Response Format:**
```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {...}
}
```

| Endpoint | Methods | Description |
|----------|---------|-------------|
| `/v1/pvs` | GET, POST | PV management with pagination |
| `/v1/pvs/paged` | GET | Paginated PV search |
| `/v1/snapshots` | GET, POST | Snapshot operations (async via Arq) |
| `/v1/snapshots/{id}/restore` | POST | Restore snapshot to EPICS |
| `/v1/tags` | GET, POST | Tag group management |
| `/v1/jobs/{id}` | GET | Job status polling |
| `/v1/health/*` | GET | Health monitoring endpoints |
| `/v1/health/monitor/status` | GET | Monitor process health |
| `/v1/health/circuits` | GET | Circuit breaker status |
| `/ws` | WebSocket | Real-time PV updates |

## Design Patterns

| Pattern | Usage |
|---------|-------|
| **Repository** | Abstracts database access in `repositories/` |
| **Service Layer** | Business logic separated from API handlers |
| **Dependency Injection** | FastAPI Depends() for resources |
| **Background Tasks** | Arq queue for long operations with Job tracking |
| **Singleton Services** | EPICS, Redis as module-level instances |
| **DTO Pattern** | Pydantic schemas separate from ORM models |
| **Cache-Aside** | Redis cache with Watchdog freshness checks |
| **Diff-Based Streaming** | WebSocket sends only changed PVs |
| **Circuit Breaker** | Fail-fast on unresponsive IOCs |
| **Leader Election** | Single PV monitor via Redis lock |
| **Continuation Token Pagination** | ID-based (not offset) for scalability |

## Performance Optimizations

1. **Process Isolation**
   - API starts in <1s (no PV subscription blocking)
   - Monitor crash doesn't affect API
   - Workers can scale independently

2. **Database**
   - Connection pooling (30 + 20 overflow)
   - PostgreSQL COPY for bulk inserts (10x faster)
   - ID-based pagination (no OFFSET)
   - Indexes on search fields

3. **EPICS**
   - Batched PV startup (500/batch, 100ms delay) prevents UDP flood
   - Async operations via aioca (no blocking)
   - Circuit breaker prevents cascading timeouts
   - Connection pre-caching

4. **Redis Caching**
   - Instant snapshot reads (<5s for 40K PVs)
   - PV Monitor maintains fresh cache
   - Pub/Sub for efficient broadcasts

5. **WebSocket**
   - Diff-based streaming (only deltas)
   - 100ms batching window
   - Redis-based subscription registry for multi-instance
   - Reduces bandwidth 10-100x

6. **Task Queue**
   - Jobs persist across restarts
   - Automatic retries for transient failures
   - Progress tracking in database

## External Services

```
┌─────────────────────────────────────────────────────────────────┐
│                    Squirrel Backend Services                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │   API   │  │ Monitor │  │ Worker  │  │ Worker  │            │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘            │
└───────┼────────────┼────────────┼────────────┼──────────────────┘
        │            │            │            │
        └────────────┼────────────┼────────────┘
                     │            │
        ┌────────────┼────────────┼────────────┐
        ▼            ▼            ▼            ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   PostgreSQL    │ │     Redis       │ │     EPICS       │
│   (asyncpg)     │ │   (hiredis)     │ │    (aioca)      │
├─────────────────┤ ├─────────────────┤ ├─────────────────┤
│ • PV metadata   │ │ • Value cache   │ │ • Channel Access│
│ • Snapshots     │ │ • Pub/Sub       │ │ • 40K+ PVs      │
│ • Tags          │ │ • Job queue     │ │ • Read/Write    │
│ • Jobs          │ │ • Leader lock   │ │ • Monitor       │
│                 │ │ • Subscriptions │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Configuration

Environment variables (prefix: `SQUIRREL_`):

```bash
# Database
SQUIRREL_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/squirrel
SQUIRREL_DATABASE_POOL_SIZE=30
SQUIRREL_DATABASE_MAX_OVERFLOW=20

# EPICS
SQUIRREL_EPICS_CA_ADDR_LIST=""
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

## Deployment

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

## API Documentation

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI Spec: `http://localhost:8000/openapi.json`

## Health Monitoring

| Endpoint | Description |
|----------|-------------|
| `/v1/health` | Overall API health |
| `/v1/health/db` | Database connectivity |
| `/v1/health/redis` | Redis connectivity |
| `/v1/health/monitor/status` | PV monitor process health (via heartbeat) |
| `/v1/health/circuits` | Circuit breaker status by IOC prefix |
