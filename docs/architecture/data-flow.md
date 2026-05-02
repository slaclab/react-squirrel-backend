# Data Flow

This document describes how data flows through the Squirrel Backend system for key operations.

## Snapshot Creation (Async via Arq)

Snapshot creation is an asynchronous operation that can read PV values from Redis cache (fast) or directly from EPICS (slower but always current).

![Snapshot creation flow](../assets/figure-2-snapshot-flow-light.png#only-light)
![Snapshot creation flow](../assets/figure-2-snapshot-flow-dark.png#only-dark)

### Performance Comparison

| Source | Time for 40K PVs | Notes |
|--------|------------------|-------|
| Redis Cache | <5 seconds | Uses cached values from PV Monitor |
| EPICS Direct | 30-60 seconds | Parallel reads with chunking |

## Real-Time PV Monitoring

The PV Monitor process maintains a live cache of all PV values in Redis and broadcasts updates to connected WebSocket clients.

![PV monitor startup and fan-out](../assets/figure-4-monitor-startup-light.png#only-light)
![PV monitor startup and fan-out](../assets/figure-4-monitor-startup-dark.png#only-dark)

### Batching Strategy

PV subscriptions are created in batches to prevent overwhelming the EPICS network:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Batch Size | 500 PVs | Prevents UDP packet flood |
| Batch Delay | 100ms | Allows network to stabilize |
| Total Time | ~8s for 40K PVs | Startup time |

## WebSocket Updates

WebSocket clients receive diff-based updates to minimize bandwidth:

![WebSocket subscription fan-out](../assets/figure-3-pv-fanout-light.png#only-light)
![WebSocket subscription fan-out](../assets/figure-3-pv-fanout-dark.png#only-dark)

### Bandwidth Savings

| Update Type | Payload Size | Bandwidth |
|-------------|--------------|-----------|
| Full snapshot | ~1MB for 40K PVs | High |
| Diff update | ~100B per changed PV | 10-100x less |

## Snapshot Restore

Restoring a snapshot writes values back to EPICS:

![Snapshot restore flow](../assets/figure-8-restore-light.png#only-light)
![Snapshot restore flow](../assets/figure-8-restore-dark.png#only-dark)

## Job Tracking

All long-running operations use the job tracking system:

![Job tracking and client polling](../assets/figure-5-polling-light.png#only-light)
![Job tracking and client polling](../assets/figure-5-polling-dark.png#only-dark)

### Job States

| State | Description |
|-------|-------------|
| `PENDING` | Job created, waiting for worker |
| `IN_PROGRESS` | Worker processing |
| `COMPLETED` | Successfully finished |
| `FAILED` | Error occurred |
| `RETRYING` | Automatic retry in progress |
