# Architecture Overview

Squirrel Backend is a high-performance FastAPI application designed to manage and monitor EPICS (Experimental Physics and Industrial Control System) process variables (PVs). It handles 40-50K PVs with real-time monitoring, caching, and snapshot capabilities.

The system uses a **distributed architecture** with separate processes for API serving, PV monitoring, and background task processing, enabling horizontal scaling and fault isolation.

## System Architecture

![System architecture](../assets/figure-1-system-architecture-light.png#only-light)
![System architecture](../assets/figure-1-system-architecture-dark.png#only-dark)

For the full technology stack, see the [Home](../index.md#technology-stack) page.

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
│   │   └── snapshot_tasks.py     # Snapshot create/restore tasks
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
├── docker/                       # Docker configuration
├── scripts/                      # Utility scripts
└── tests/                        # Test suite
```

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

## Database Models

![Data model](../assets/figure-7-data-model-light.png#only-light)
![Data model](../assets/figure-7-data-model-dark.png#only-dark)

## Services Layer

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

## External Services

| Service | Driver | Role |
|---------|--------|------|
| **PostgreSQL** | asyncpg | PV metadata, snapshots, tags, jobs |
| **Redis** | hiredis | PV value cache, pub/sub, Arq job queue, monitor leader lock, WebSocket subscription registry |
| **EPICS** | aioca (CA), p4p (PVA) | Read/write/monitor 40K+ process variables |
