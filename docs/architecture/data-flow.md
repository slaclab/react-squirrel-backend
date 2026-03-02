# Data Flow

This document describes how data flows through the Squirrel Backend system for key operations.

## Snapshot Creation (Async via Arq)

Snapshot creation is an asynchronous operation that can read PV values from Redis cache (fast) or directly from EPICS (slower but always current).

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

### Performance Comparison

| Source | Time for 40K PVs | Notes |
|--------|------------------|-------|
| Redis Cache | <5 seconds | Uses cached values from PV Monitor |
| EPICS Direct | 30-60 seconds | Parallel reads with chunking |

## Real-Time PV Monitoring

The PV Monitor process maintains a live cache of all PV values in Redis and broadcasts updates to connected WebSocket clients.

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

### Batching Strategy

PV subscriptions are created in batches to prevent overwhelming the EPICS network:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Batch Size | 500 PVs | Prevents UDP packet flood |
| Batch Delay | 100ms | Allows network to stabilize |
| Total Time | ~8s for 40K PVs | Startup time |

## WebSocket Updates

WebSocket clients receive diff-based updates to minimize bandwidth:

```
┌──────────────────┐     ┌──────────────────┐
│  Client A        │     │  Client B        │
│  Subscribed to:  │     │  Subscribed to:  │
│  PV1, PV2, PV3   │     │  PV2, PV4        │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         └───────────┬────────────┘
                     │
                     ▼
         ┌────────────────────────┐
         │  Subscription Registry │
         │  (Redis Set per PV)    │
         └───────────┬────────────┘
                     │
                     ▼
         ┌────────────────────────┐
         │   DiffStreamManager    │
         │   (per API instance)   │
         └───────────┬────────────┘
                     │
                     │ PV2 changes
                     ▼
         ┌────────────────────────┐
         │   Batch updates        │
         │   (100ms window)       │
         └───────────┬────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
┌──────────────────┐     ┌──────────────────┐
│  Client A        │     │  Client B        │
│  Receives: PV2   │     │  Receives: PV2   │
└──────────────────┘     └──────────────────┘
```

### Bandwidth Savings

| Update Type | Payload Size | Bandwidth |
|-------------|--------------|-----------|
| Full snapshot | ~1MB for 40K PVs | High |
| Diff update | ~100B per changed PV | 10-100x less |

## Snapshot Restore

Restoring a snapshot writes values back to EPICS:

```
API Request (/v1/snapshots/{id}/restore POST)
         │
         ▼
┌─────────────────────────────────┐
│   Load snapshot from DB          │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│   Create Job record              │
└─────────────────┬───────────────┘
                  │
         ▼ (enqueue to Arq)
┌─────────────────────────────────┐
│     Return Job ID immediately    │
└─────────────────┬───────────────┘
                  │
         ▼ (Arq worker picks up)
┌─────────────────────────────────┐
│   Parallel EPICS writes          │
│   (chunked, 1000/batch)          │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│   Circuit breaker per IOC        │
│   (fail-fast on unresponsive)    │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│   Mark Job as COMPLETED          │
│   (with success/failure counts)  │
└─────────────────────────────────┘
```

## Job Tracking

All long-running operations use the job tracking system:

```
┌─────────────────┐
│   API Request   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Create Job     │──────────────┐
│  status=PENDING │              │
└────────┬────────┘              │
         │                       │
         ▼                       │
┌─────────────────┐              │
│  Enqueue Task   │              │
│  (Arq/Redis)    │              │
└────────┬────────┘              │
         │                       │
         ▼                       │
┌─────────────────┐              │
│  Return Job ID  │◄─────────────┘
└────────┬────────┘
         │
         │ (client polls)
         ▼
┌─────────────────┐
│  GET /jobs/{id} │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Job Status Response            │
│  {                              │
│    "status": "IN_PROGRESS",     │
│    "progress": 45,              │
│    "data": {...}                │
│  }                              │
└─────────────────────────────────┘
```

### Job States

| State | Description |
|-------|-------------|
| `PENDING` | Job created, waiting for worker |
| `IN_PROGRESS` | Worker processing |
| `COMPLETED` | Successfully finished |
| `FAILED` | Error occurred |
| `RETRYING` | Automatic retry in progress |
