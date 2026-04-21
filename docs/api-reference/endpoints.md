# REST Endpoints

Detailed documentation for all REST API endpoints.

!!! info "Authentication required"
    All endpoints require an `X-API-Key` header. GET endpoints need `read_access`; POST/PUT/DELETE endpoints need `write_access`. See [API Key Management](../getting-started/api-keys.md).

## API Key Endpoints

### List API Keys

```
GET /v1/api-keys
```

Requires `read_access`.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `active_only` | boolean | Filter to active keys only (default: false) |

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "app_name": "my-app",
      "read_access": true,
      "write_access": true,
      "is_active": true,
      "created_at": "2026-03-27T10:00:00Z",
      "updated_at": "2026-03-27T10:00:00Z"
    }
  ]
}
```

### Create API Key

```
POST /v1/api-keys
```

Requires `write_access`.

**Request Body:**

```json
{
  "appName": "new-client",
  "readAccess": true,
  "writeAccess": false
}
```

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "app_name": "new-client",
    "token": "sq_abc123...",
    "read_access": true,
    "write_access": false,
    "is_active": true,
    "created_at": "2026-03-27T12:00:00Z"
  }
}
```

!!! warning
    The `token` field only appears in the creation response. It cannot be retrieved again.

### Deactivate API Key

```
DELETE /v1/api-keys/{id}
```

Requires `write_access`. Soft-deletes the key (sets `is_active=False`).

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | UUID | API key ID |

### Count API Keys

```
GET /v1/api-keys/count
```

Requires `read_access`.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `active_only` | boolean | Count only active keys (default: false) |

---

## PV Endpoints

### Search PVs

```
GET /v1/pvs
```

Search for PVs with optional filters.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search term (matches address or description) |
| `tag_ids` | array | Filter by tag IDs |
| `limit` | integer | Max results (default: 100) |

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "setpoint_address": "QUAD:LI21:201:BDES",
      "readback_address": "QUAD:LI21:201:BACT",
      "description": "Quadrupole magnet",
      "tags": [
        {"id": "...", "name": "Magnet"}
      ]
    }
  ]
}
```

### Search PVs (Paginated)

```
GET /v1/pvs/paged
```

Search PVs with cursor-based pagination.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search term |
| `tag_ids` | array | Filter by tag IDs |
| `limit` | integer | Page size (default: 100) |
| `cursor` | string | Continuation token |

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "items": [...],
    "next_cursor": "eyJpZCI6IjU1MGU4...",
    "has_more": true
  }
}
```

### Create PV

```
POST /v1/pvs
```

Create a new PV.

**Request Body:**

```json
{
  "setpoint_address": "TEST:PV:SETPOINT",
  "readback_address": "TEST:PV:READBACK",
  "config_address": null,
  "device": "Test Device",
  "description": "Test PV for documentation",
  "abs_tolerance": 0.01,
  "rel_tolerance": 0.001,
  "tag_ids": ["550e8400-e29b-41d4-a716-446655440000"]
}
```

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "setpoint_address": "TEST:PV:SETPOINT",
    "readback_address": "TEST:PV:READBACK",
    ...
  }
}
```

### Bulk Create PVs

```
POST /v1/pvs/multi
```

Create multiple PVs in a single request.

**Request Body:**

```json
{
  "pvs": [
    {
      "setpoint_address": "PV:1",
      "description": "First PV"
    },
    {
      "setpoint_address": "PV:2",
      "description": "Second PV"
    }
  ]
}
```

### Update PV

```
PUT /v1/pvs/{id}
```

Update an existing PV.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | UUID | PV ID |

**Request Body:**

```json
{
  "description": "Updated description",
  "abs_tolerance": 0.02
}
```

### Delete PV

```
DELETE /v1/pvs/{id}
```

Delete a PV.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | UUID | PV ID |

---

## Snapshot Endpoints

### List Snapshots

```
GET /v1/snapshots
```

List all snapshots.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | integer | Max results |
| `offset` | integer | Skip N results |

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": [
    {
      "id": "...",
      "title": "Morning snapshot",
      "comment": "Before tuning",
      "created_by": "operator",
      "created_at": "2024-01-15T10:30:00Z",
      "pv_count": 1500
    }
  ]
}
```

### Create Snapshot

```
POST /v1/snapshots
```

Create a new snapshot (asynchronous operation).

**Request Body:**

```json
{
  "title": "Morning snapshot",
  "comment": "Before beam tuning",
  "created_by": "operator",
  "pv_ids": ["...", "..."],
  "tag_ids": ["..."],
  "use_cache": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Snapshot name |
| `comment` | string | Optional description |
| `created_by` | string | Creator identifier |
| `pv_ids` | array | Specific PVs to include |
| `tag_ids` | array | Include PVs with these tags |
| `use_cache` | boolean | Read from Redis cache (fast) or EPICS (fresh) |

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "job_id": "770e8400-e29b-41d4-a716-446655440002"
  }
}
```

Poll `/v1/jobs/{job_id}` for progress and completion.

### Get Snapshot

```
GET /v1/snapshots/{id}
```

Get a snapshot with all its values.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | UUID | Snapshot ID |

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "id": "...",
    "title": "Morning snapshot",
    "values": [
      {
        "pv_name": "QUAD:LI21:201:BDES",
        "setpoint_value": 42.5,
        "readback_value": 42.48,
        "status": 0,
        "severity": 0
      }
    ]
  }
}
```

### Delete Snapshot

```
DELETE /v1/snapshots/{id}
```

Delete a snapshot and all its values.

### Restore Snapshot

```
POST /v1/snapshots/{id}/restore
```

Restore snapshot values to EPICS (asynchronous operation).

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "job_id": "880e8400-e29b-41d4-a716-446655440003"
  }
}
```

### Compare Snapshots

```
GET /v1/snapshots/{id}/compare/{id2}
```

Compare two snapshots and show differences.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tolerance` | float | Difference threshold (default: uses PV tolerances) |

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "snapshot1_id": "...",
    "snapshot2_id": "...",
    "differences": [
      {
        "pv_name": "QUAD:LI21:201:BDES",
        "value1": 42.5,
        "value2": 43.2,
        "diff": 0.7,
        "diff_percent": 1.6
      }
    ],
    "total_pvs": 1500,
    "different_count": 23
  }
}
```

---

## Tag Endpoints

### List Tag Groups

```
GET /v1/tags
```

List all tag groups with their tags.

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": [
    {
      "id": "...",
      "name": "Area",
      "description": "Machine areas",
      "tags": [
        {"id": "...", "name": "LI21"},
        {"id": "...", "name": "LI22"}
      ]
    }
  ]
}
```

### Create Tag Group

```
POST /v1/tags
```

Create a new tag group.

**Request Body:**

```json
{
  "name": "Subsystem",
  "description": "Device subsystems",
  "tags": [
    {"name": "Magnet"},
    {"name": "BPM"},
    {"name": "Feedback"}
  ]
}
```

### Get Tag Group

```
GET /v1/tags/{id}
```

Get a tag group with all its tags.

### Update Tag Group

```
PUT /v1/tags/{id}
```

Update a tag group.

### Delete Tag Group

```
DELETE /v1/tags/{id}
```

Delete a tag group and all its tags.

---

## Job Endpoints

### Get Job Status

```
GET /v1/jobs/{id}
```

Get the status and progress of a background job.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | UUID | Job ID |

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "id": "...",
    "type": "snapshot_create",
    "status": "running",
    "progress": 45,
    "data": {
      "processed": 675,
      "total": 1500
    },
    "result_id": null,
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:15Z"
  }
}
```

**Job Type Values:**

| Type | Description |
|------|-------------|
| `snapshot_create` | Creating a snapshot |
| `snapshot_restore` | Restoring a snapshot to EPICS |

**Job Status Values:**

| Status | Description |
|--------|-------------|
| `pending` | Job created, waiting for worker |
| `running` | Worker is processing |
| `completed` | Successfully finished |
| `failed` | Error occurred |

---

## Health Endpoints

### Heartbeat

```
GET /v1/health/heartbeat
```

Simple heartbeat check for frontend polling. No authentication required.

### Overall Health

```
GET /v1/health
```

Check overall API health.

### Health Summary

```
GET /v1/health/summary
```

Complete health summary for monitoring dashboards. Includes database, Redis, monitor, and watchdog status.

### Database Health

```
GET /v1/health/db
```

Check database connectivity.

### Redis Health

```
GET /v1/health/redis
```

Check Redis connectivity.

### Monitor Health

```
GET /v1/health/monitor
```

Detailed PV monitor health information.

### Monitor Status

```
GET /v1/health/monitor/status
```

Check PV monitor process health via Redis heartbeat.

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "healthy": true,
    "last_heartbeat": "2024-01-15T10:30:00Z",
    "pv_count": 40000,
    "connected_count": 39850
  }
}
```

### Watchdog Statistics

```
GET /v1/health/watchdog
```

Get watchdog health monitoring statistics.

### Force Watchdog Check

```
POST /v1/health/watchdog/check
```

Force an immediate watchdog health check. Requires `write_access`.

### Disconnected PVs

```
GET /v1/health/disconnected
```

List all PVs currently disconnected from EPICS.

### Stale PVs

```
GET /v1/health/stale
```

List PVs that haven't been updated recently.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `max_age_seconds` | float | Consider PVs stale after this many seconds |

### Circuit Breaker Status

```
GET /v1/health/circuits
```

Check circuit breaker status by IOC prefix.

**Response:**

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": {
    "circuits": {
      "QUAD:LI21": {"state": "CLOSED", "failures": 0},
      "BPM:LI22": {"state": "OPEN", "failures": 5}
    }
  }
}
```

### Force Close Circuit Breaker

```
POST /v1/health/circuits/{circuit_name}/close
```

Force close (reset) a circuit breaker. Requires `write_access`.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `circuit_name` | string | IOC prefix (e.g., `QUAD:LI21`) |

### Force Open Circuit Breaker

```
POST /v1/health/circuits/{circuit_name}/open
```

Force open a circuit breaker (block all requests to this IOC). Requires `write_access`.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `circuit_name` | string | IOC prefix (e.g., `BPM:LI22`) |
