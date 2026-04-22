# API Reference

Squirrel Backend provides a REST API and WebSocket streaming API for managing EPICS PVs, snapshots, and tags.

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

## Authentication

All endpoints require an API key passed via the `X-API-Key` header:

```
X-API-Key: sq_your_token_here
```

Requests without a valid key return `401 Unauthorized`.

| Permission | Required for |
|------------|--------------|
| `read_access` | GET requests, WebSocket connections |
| `write_access` | POST, PUT, DELETE requests |

See [API Key Management](../getting-started/api-keys.md) for details on creating and managing keys.

## Pagination

Paginated endpoints use continuation tokens (not offset-based):

```json
{
  "results": [...],
  "continuationToken": "abc123",
  "hasMore": true
}
```

To get the next page:

```
GET /v1/pvs/paged?continuationToken=abc123
```

## Rate Limiting

No rate limiting is currently enforced. For production deployments, consider adding rate limiting at the load balancer level.

## Detailed Documentation

- [REST Endpoints](endpoints.md) — complete per-endpoint request/response documentation
- [WebSocket](websocket.md) — real-time streaming API
