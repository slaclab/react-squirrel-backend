# REST Endpoints

Detailed documentation for all REST API endpoints.

!!! info "Authentication required"
    All endpoints require an `X-API-Key` header. GET endpoints need `readAccess`; POST/PUT/DELETE endpoints need `writeAccess`. See [API Key Management](../getting-started/api-keys.md).

## API Key Endpoints

### List API Keys

```
GET /v1/api-keys
```

Requires `readAccess`.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `active_only` | boolean | Filter to active keys only (default: false) |

**Response:**

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "appName": "my-app",
    "isActive": true,
    "readAccess": true,
    "writeAccess": true,
    "createdAt": "2026-03-27T10:00:00Z",
    "updatedAt": "2026-03-27T10:00:00Z"
  }
]
```

### Create API Key

```
POST /v1/api-keys
```

Requires `writeAccess`.

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
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "appName": "new-client",
  "token": "sq_abc123...",
  "isActive": true,
  "readAccess": true,
  "writeAccess": false,
  "createdAt": "2026-03-27T12:00:00Z",
  "updatedAt": "2026-03-27T12:00:00Z"
}
```

!!! warning
    The `token` field only appears in the creation response. It cannot be retrieved again.

### Deactivate API Key

```
DELETE /v1/api-keys/{id}
```

Requires `writeAccess`. Soft-deletes the key (sets `isActive=false`) and returns the updated `ApiKeyDTO`.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | UUID | API key ID |

### Count API Keys

```
GET /v1/api-keys/count
```

Requires `readAccess`. Returns a bare integer.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `active_only` | boolean | Count only active keys (default: false) |

---

## PV Endpoints

All request/response fields use **camelCase**. `id` in paths is a UUID.

### Search PVs

```
GET /v1/pvs
```

Non-paginated search by name (backward-compatibility helper; returns up to 1000 rows).

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pvName` | string | Search term |

### Search PVs (Paginated)

```
GET /v1/pvs/paged
```

Search PVs with cursor-based pagination and tag filtering.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `pvName` | string | Search term (matches address or description) |
| `pageSize` | integer | Page size (1-1000, default 100) |
| `continuationToken` | string | Opaque cursor returned by the previous response |
| `tagFilters` | string | JSON object: `{groupId: [tagId1, tagId2], ...}` — returns PVs matching (any tag in group A) AND (any tag in group B) |

**Response payload:**

```json
{
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "setpointAddress": "QUAD:LI21:201:BDES",
      "readbackAddress": "QUAD:LI21:201:BACT",
      "description": "Quadrupole magnet",
      "absTolerance": 0.01,
      "relTolerance": 0.001,
      "readOnly": false,
      "tags": [{"id": "...", "name": "Magnet"}]
    }
  ],
  "continuationToken": "eyJpZCI6IjU1MGU4...",
  "hasMore": true
}
```

### Filtered Search (with optional live values)

```
GET /v1/pvs/search
```

Server-side filtered search that optionally returns live values from the Redis cache alongside metadata.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Text search |
| `devices` | array | Filter by device name(s) |
| `tags` | array | Filter by tag IDs |
| `limit` | integer | Max results (≤1000, default 100) |
| `offset` | integer | Pagination offset |
| `include_live_values` | boolean | Include Redis cache values in `liveValues` |

### List Devices

```
GET /v1/pvs/devices
```

Returns the distinct set of device names currently in use.

### Live Values (GET / POST)

```
GET /v1/pvs/live?pv_names=PV:1&pv_names=PV:2
POST /v1/pvs/live
```

Fetch cached live values from Redis. Use `POST` with body `{"pv_names": ["..."]}` when the list is too long for a query string.

### All Live Values

```
GET /v1/pvs/live/all
```

Every PV value currently in the cache (for initial table load).

### Cache Status

```
GET /v1/pvs/cache/status
```

Returns cached PV count and Redis connectivity status.

### Create PV

```
POST /v1/pvs
```

Create a new PV. At least one of `setpointAddress`, `readbackAddress`, or `configAddress` must be provided.

**Request Body:**

```json
{
  "setpointAddress": "TEST:PV:SETPOINT",
  "readbackAddress": "TEST:PV:READBACK",
  "configAddress": null,
  "device": "Test Device",
  "description": "Test PV for documentation",
  "absTolerance": 0.01,
  "relTolerance": 0.001,
  "readOnly": false,
  "tags": ["550e8400-e29b-41d4-a716-446655440000"]
}
```

### Bulk Create PVs

```
POST /v1/pvs/multi
```

Create multiple PVs in one request. Body is a JSON **array** of `NewPVElementDTO` objects (same shape as `POST /v1/pvs`).

### Update PV

```
PUT /v1/pvs/{id}
```

Partially update a PV. Unspecified fields are left unchanged.

**Request Body:**

```json
{
  "description": "Updated description",
  "absTolerance": 0.02,
  "relTolerance": null,
  "readOnly": true,
  "tags": ["tag-id-1", "tag-id-2"]
}
```

### Delete PV

```
DELETE /v1/pvs/{id}
```

---

## Snapshot Endpoints

### List Snapshots

```
GET /v1/snapshots
```

List all snapshots, optionally filtered.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `title` | string | Filter by title substring |
| `tags` | array | Filter by tag IDs (returns snapshots containing PVs with any of these tags) |

Response is an array of `SnapshotSummaryDTO` (`id`, `title`, `description`, `createdDate`, `createdBy`, `pvCount`).

### Create Snapshot

```
POST /v1/snapshots
```

Create a new snapshot. Captures the current state of **all** configured PVs.

**Request Body:**

```json
{
  "title": "Morning snapshot",
  "description": "Before beam tuning"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Snapshot name (required, 1-255 chars) |
| `description` | string | Optional description |

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `async` | boolean | `true` | Return a job ID immediately and run in the background |
| `use_cache` | boolean | `true` | `true` reads from Redis cache (<5s for 40K PVs); `false` reads directly from EPICS (30-60s) |
| `use_arq` | boolean | `true` | `true` uses the Arq persistent queue; `false` uses FastAPI `BackgroundTasks` (lost on restart) |

**Response (async=true):**

```json
{
  "jobId": "770e8400-e29b-41d4-a716-446655440002",
  "message": "Snapshot creation queued for 'Morning snapshot' (from cache)"
}
```

Poll `/v1/jobs/{jobId}` for progress and completion. With `async=false`, the endpoint blocks and returns the completed `SnapshotDTO` inline (may time out on large PV sets).

### Get Snapshot

```
GET /v1/snapshots/{id}
```

Get a snapshot with its PV values.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | integer | Limit number of PV values returned |
| `offset` | integer | Offset for pagination (default 0) |

Returns `SnapshotDTO` with `pvValues: PVValueDTO[]`. Each `PVValueDTO` has `pvId`, `pvName`, `setpointName`, `readbackName`, `setpointValue` (EpicsValueDTO), `readbackValue` (EpicsValueDTO), `tags`.

### Update Snapshot

```
PUT /v1/snapshots/{id}
```

Update snapshot title and/or description.

**Request Body:**

```json
{
  "title": "Morning snapshot v2",
  "description": "After tuning"
}
```

Both fields are optional (nullable).

### Delete Snapshot

```
DELETE /v1/snapshots/{id}
```

Delete a snapshot and all its values.

### Restore Snapshot

```
POST /v1/snapshots/{id}/restore
```

Restore snapshot values to EPICS.

**Request Body (optional):**

```json
{ "pvIds": ["pv-id-1", "pv-id-2"] }
```

If omitted (or `pvIds` is null), all PVs in the snapshot are restored.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `async` | boolean | `true` | Return a job ID and run in the background |
| `use_arq` | boolean | `true` | `true` uses Arq; `false` uses FastAPI `BackgroundTasks` |

**Response (async=true):**

```json
{
  "jobId": "880e8400-e29b-41d4-a716-446655440003",
  "message": "Job started"
}
```

With `async=false`, returns a `RestoreResultDTO` (`{ "totalPVs": ..., "successCount": ..., "failureCount": ..., "failures": [...] }`).

### Compare Snapshots

```
GET /v1/snapshots/{snapshot1_id}/compare/{snapshot2_id}
```

Compare two snapshots. PV-level tolerance (`absTolerance` / `relTolerance` on the PV record) decides whether each pair is within tolerance.

**Response:**

```json
{
  "snapshot1Id": "...",
  "snapshot2Id": "...",
  "differences": [
    {
      "pvId": "...",
      "pvName": "QUAD:LI21:201:BDES",
      "value1": 42.5,
      "value2": 43.2,
      "withinTolerance": false
    }
  ],
  "matchCount": 1477,
  "differenceCount": 23
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
[
  {
    "id": "...",
    "name": "Area",
    "description": "Machine areas",
    "tags": [
      {"id": "...", "name": "LI21"},
      {"id": "...", "name": "LI22"}
    ],
    "createdDate": "2026-01-15T10:00:00Z",
    "lastModifiedDate": "2026-01-15T10:00:00Z"
  }
]
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

Delete a tag group and all its tags. Pass `?force=true` to delete even if the group still has tags referenced by PVs.

### Add Tag to Group

```
POST /v1/tags/{group_id}/tags
```

Add a single tag to an existing group.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip_duplicates` | boolean | `false` | If `true`, adding an existing tag returns `wasCreated: false` instead of 409 |

**Request Body:** `TagCreate` (`{ "name": "...", "description": null }`).

### Update Tag

```
PUT /v1/tags/{group_id}/tags/{tag_id}
```

Rename or update a tag's description. Body: `TagUpdate` (`name` and/or `description`).

### Remove Tag from Group

```
DELETE /v1/tags/{group_id}/tags/{tag_id}
```

### Bulk Import Tags

```
POST /v1/tags/bulk
```

Requires `writeAccess`. Import multiple tag groups and tags in one call, with duplicate handling.

**Request Body:**

```json
{
  "groups": {
    "Area": ["LI21", "LI22", "LI23"],
    "Subsystem": ["Magnet", "BPM", "Feedback"]
  }
}
```

**Response:**

```json
{
  "groupsCreated": 2,
  "tagsCreated": 6,
  "tagsSkipped": 0,
  "warnings": []
}
```

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
  "id": "...",
  "type": "snapshot_create",
  "status": "running",
  "progress": 45,
  "message": "Capturing PV values",
  "resultId": null,
  "error": null,
  "jobData": {
    "processed": 675,
    "total": 1500
  },
  "createdAt": "2026-01-15T10:30:00Z",
  "startedAt": "2026-01-15T10:30:02Z",
  "completedAt": null
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

### Health Summary

```
GET /v1/health/summary
```

Complete health summary for monitoring dashboards. Includes database, Redis, monitor, and watchdog status in a single response.

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
  "status": "healthy",
  "message": "Monitor process is alive",
  "age_seconds": 2.4,
  "leader": "monitor-1"
}
```

`status` is one of `healthy`, `stale`, `unknown`, `error`.

### Watchdog Statistics

```
GET /v1/health/watchdog
```

Get watchdog health monitoring statistics.

### Force Watchdog Check

```
POST /v1/health/watchdog/check
```

Force an immediate watchdog health check. Requires `writeAccess`.

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
  "open_circuit_count": 1,
  "total_circuits": 2,
  "open_circuits": ["BPM:LI22"],
  "circuits": [
    {
      "name": "QUAD:LI21",
      "state": "closed",
      "failure_count": 0,
      "success_count": 1024,
      "call_count": 1024,
      "last_failure": null,
      "opened_at": null
    },
    {
      "name": "BPM:LI22",
      "state": "open",
      "failure_count": 5,
      "success_count": 12,
      "call_count": 17,
      "last_failure": "2026-01-15T10:25:00",
      "opened_at": "2026-01-15T10:25:00"
    }
  ],
  "error": null
}
```

`state` is `closed`, `open`, or `half_open`.

### Force Close Circuit Breaker

```
POST /v1/health/circuits/{circuit_name}/close
```

Force close (reset) a circuit breaker. Requires `writeAccess`.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `circuit_name` | string | Circuit name (IOC identifier derived from PV name, e.g., `QUAD:LI21`) |

### Force Open Circuit Breaker

```
POST /v1/health/circuits/{circuit_name}/open
```

Force open a circuit breaker (block all requests to this IOC). Requires `writeAccess`.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `circuit_name` | string | Circuit name (e.g., `BPM:LI22`) |
