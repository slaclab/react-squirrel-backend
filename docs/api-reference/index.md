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

Endpoints return JSON responses directly — there is no envelope wrapper. A successful response is the resource (or list of resources) itself; failures use HTTP status codes with a `{"detail": "..."}` body, per FastAPI's default `HTTPException` shape.

```http
HTTP/1.1 200 OK
Content-Type: application/json

{ "id": "...", "appName": "..." }
```

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{ "detail": "Snapshot not found" }
```

## Authentication

All endpoints require an API key passed via the `X-API-Key` header:

```
X-API-Key: sq_your_token_here
```

Requests without a valid key return `401 Unauthorized`.

| Permission | Required for |
|------------|--------------|
| `readAccess` | GET requests, WebSocket connections |
| `writeAccess` | POST, PUT, DELETE requests |

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
