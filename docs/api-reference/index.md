# API Reference

Squirrel Backend provides a REST API for managing EPICS PVs, snapshots, and tags.

## Base URL

All API endpoints are prefixed with `/v1/`.

- **Local Development**: `http://localhost:8000/v1/`
- **Docker**: `http://localhost:8080/v1/`

## Interactive Documentation

When the server is running, interactive API documentation is available at:

- **Swagger UI**: [http://localhost:8080/docs](http://localhost:8080/docs)
- **OpenAPI Spec**: [http://localhost:8080/openapi.json](http://localhost:8080/openapi.json)

## Response Format

All responses follow a standard format:

```json
{
  "errorCode": 0,
  "errorMessage": null,
  "payload": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `errorCode` | integer | `0` for success, non-zero for errors |
| `errorMessage` | string | Error description (null on success) |
| `payload` | object | Response data |

### Error Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Validation error |
| `2` | Not found |
| `3` | Database error |
| `4` | EPICS error |
| `5` | Internal error |

## Endpoint Summary

### PV Endpoints (`/v1/pvs`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/pvs` | Search PVs (simple) |
| `GET` | `/v1/pvs/paged` | Search PVs with pagination |
| `POST` | `/v1/pvs` | Create single PV |
| `POST` | `/v1/pvs/multi` | Bulk create PVs |
| `PUT` | `/v1/pvs/{id}` | Update PV |
| `DELETE` | `/v1/pvs/{id}` | Delete PV |

### Snapshot Endpoints (`/v1/snapshots`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/snapshots` | List snapshots |
| `POST` | `/v1/snapshots` | Create snapshot (async) |
| `GET` | `/v1/snapshots/{id}` | Get snapshot with values |
| `DELETE` | `/v1/snapshots/{id}` | Delete snapshot |
| `POST` | `/v1/snapshots/{id}/restore` | Restore to EPICS |
| `GET` | `/v1/snapshots/{id}/compare/{id2}` | Compare two snapshots |

### Tag Endpoints (`/v1/tags`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/tags` | List tag groups |
| `POST` | `/v1/tags` | Create tag group |
| `GET` | `/v1/tags/{id}` | Get tag group with tags |
| `PUT` | `/v1/tags/{id}` | Update tag group |
| `DELETE` | `/v1/tags/{id}` | Delete tag group |

### Job Endpoints (`/v1/jobs`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/jobs/{id}` | Get job status and progress |

### Health Endpoints (`/v1/health`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/health` | Overall health |
| `GET` | `/v1/health/db` | Database connectivity |
| `GET` | `/v1/health/redis` | Redis connectivity |
| `GET` | `/v1/health/monitor/status` | PV monitor health |
| `GET` | `/v1/health/circuits` | Circuit breaker status |

### WebSocket (`/ws`)

Real-time PV value streaming.

## Pagination

Paginated endpoints use continuation tokens (not offset-based):

```json
{
  "items": [...],
  "next_cursor": "abc123",
  "has_more": true
}
```

To get the next page:

```
GET /v1/pvs/paged?cursor=abc123
```

## Authentication

All endpoints require an API key passed via the `X-API-Key` header:

```
X-API-Key: sq_your_token_here
```

Requests without a valid key return `401 Unauthorized`.

### Permission Levels

| Permission | Required for |
|------------|--------------|
| `read_access` | GET requests, WebSocket connections |
| `write_access` | POST, PUT, DELETE requests |

### Getting an API Key

Use the management script to create your first key:

```bash
# Docker
docker exec squirrel-api python scripts/create_key.py <app-name> [--read] [--write]
```

See [API Key Management](../getting-started/api-keys.md) for full details on creating and managing keys.

### API Key Endpoints

The `/v1/api-keys` endpoints allow managing keys via the REST API (requires `write_access`):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/api-keys` | List all API keys |
| `POST` | `/v1/api-keys` | Create a new API key |
| `DELETE` | `/v1/api-keys/{id}` | Deactivate an API key |
| `GET` | `/v1/api-keys/count` | Count API keys |

## Rate Limiting

No rate limiting is currently enforced. For production deployments, consider adding rate limiting at the load balancer level.

## Detailed Documentation

- [REST Endpoints](endpoints.md) - Complete endpoint documentation
- [WebSocket](websocket.md) - Real-time streaming API
