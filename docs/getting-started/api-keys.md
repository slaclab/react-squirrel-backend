# API Key Management

All Squirrel Backend endpoints require an API key for authentication. Keys are passed via the `X-API-Key` HTTP header and carry either **read**, **write**, or both permissions.

## How It Works

- Tokens are prefixed with `sq_` (e.g., `sq_abc123...`) and are only shown **once** at creation time.
- The server stores a SHA-256 hash of the token — the plaintext is never persisted.
- Each key is associated with an **app name** (a human-readable identifier for the client).
- Permissions are controlled by two flags: `read_access` and `write_access`.

## Permission Model

| Permission | Required for |
|------------|--------------|
| `read_access` | GET requests, WebSocket connections |
| `write_access` | POST, PUT, DELETE requests; creating/deactivating API keys |

A key can have read-only, write-only, or both permissions.

## Bootstrap: Creating Your First Key

Since the API itself requires authentication, use the management scripts to create an initial key directly against the database.

### Docker

```bash
docker exec squirrel-api python scripts/create_key.py <app-name> [-r] [-w]
```

**Example output:**

```
API Key created successfully!
  App Name:   My App
  ID:         892708ba-7b45-4fc4-a980-9ac5c3a360e6
  Access:     read, write
  Created At: 2026-03-30 17:06:04.37
  Token: sq_KnIrtn1btDx-LXyyjI11-ypUrcJpQmCTm09muyQIeG8
```

!!! warning "Save the token"
    The plaintext token is only displayed once. Store it securely (e.g., in a secrets manager or `.env` file). If lost, deactivate the key and create a new one.

## Using API Keys

Include the token in the `X-API-Key` header with every request:

=== "curl"
    ```bash
    curl -H "X-API-Key: sq_your_token_here" http://localhost:8080/v1/pvs
    ```

=== "Python (requests)"
    ```python
    import requests

    headers = {"X-API-Key": "sq_your_token_here"}
    response = requests.get("http://localhost:8080/v1/pvs", headers=headers)
    ```

=== "JavaScript (fetch)"
    ```javascript
    const response = await fetch('http://localhost:8080/v1/pvs', {
      headers: { 'X-API-Key': 'sq_your_token_here' }
    });
    ```

### WebSocket

Pass the token in the `X-API-Key` header, the same as HTTP requests:

=== "Python (websockets)"
    ```python
    import asyncio
    import websockets

    async def connect():
        headers = {"X-API-Key": "sq_your_token_here"}
        async with websockets.connect(
            "ws://localhost:8080/v1/ws/pvs",
            additional_headers=headers
        ) as ws:
            # subscribe, receive updates, etc.
            pass

    asyncio.run(connect())
    ```

=== "JavaScript (WebSocket)"
    ```javascript
    const ws = new WebSocket('ws://localhost:8080/v1/ws/pvs', [], {
      headers: { 'X-API-Key': 'sq_your_token_here' }
    });
    ```

## Managing Keys via Scripts

These scripts connect directly to the database and do not require an existing API key.

### Create a Key

```bash
# Read-only key
python scripts/create_key.py "Frontend App" -r

# Write-only key
python scripts/create_key.py CI-Pipeline -w

# Full access key
python scripts/create_key.py "Admin Tool" -r -w
```

### List Keys

```bash
# All keys
python scripts/list_keys.py

# Active keys only
python scripts/list_keys.py -a
```

**Example output:**

```
+--------------------------------------+--------------+----------+------------+-------------+------------------------+------------------------+
| id                                   | appName      | isActive | readAccess | writeAccess | createdAt              | updatedAt              |
+--------------------------------------+--------------+----------+------------+-------------+------------------------+------------------------+
| 805a358f-4740-46ec-926f-ef4ac8d8ab92 | Frontend App | True     | True       | False       | 2026-03-27 23:23:16.19 | 2026-03-27 23:23:16.19 |
| 3b1c4e5f-8a2d-4b6e-9f0a-1c2d3e4f5a6b | CI-Pipeline  | True     | False      | True        | 2026-03-30 17:06:04.37 | 2026-03-30 17:06:04.37 |
| 892708ba-7b45-4fc4-a980-9ac5c3a360e6 | Admin Tool   | True     | True       | True        | 2026-03-30 18:15:22.54 | 2026-03-30 18:15:22.54 |
+--------------------------------------+--------------+----------+------------+-------------+------------------------+------------------------+
```

### Deactivate a Key

```bash
python scripts/deactivate_key.py 805a358f-4740-46ec-926f-ef4ac8d8ab92
```

**Example output:**

```
API Key deactivated successfully
  App Name:   Frontend App
  ID:         805a358f-4740-46ec-926f-ef4ac8d8ab92
  Access:     read
  Created At: 2026-03-27 23:23:16.19
  Updated At: 2026-03-30 18:30:14.61
```

Deactivated keys are soft-deleted (`is_active=False`) and their app name can be reused for a new key.

## Managing Keys via REST API

Once you have a key with `write_access`, you can manage keys through the API itself.

### List Keys

```
GET /v1/api-keys
```

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
      "created_at": "2026-03-27T10:00:00Z"
    }
  ]
}
```

### Create a Key

```
POST /v1/api-keys
```

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
    "id": "660e8400-...",
    "app_name": "new-client",
    "token": "sq_newTokenHere...",
    "read_access": true,
    "write_access": false,
    "is_active": true,
    "created_at": "2026-03-27T12:00:00Z"
  }
}
```

!!! warning
    The `token` field is only present in the creation response. Subsequent `GET` requests will not include it.

### Deactivate a Key

```
DELETE /v1/api-keys/{key_id}
```

Returns the deactivated key's metadata.

### Count Keys

```
GET /v1/api-keys/count
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `active_only` | boolean | Count only active keys (default: false) |

## Error Responses

| HTTP Status | Cause |
|-------------|-------|
| `401 Unauthorized` | Missing, invalid, or deactivated `X-API-Key` header |
| `401 Unauthorized` | Key exists but lacks the required permission (read or write) |

```json
{
  "detail": "Invalid or missing API key"
}
```

## Security Notes

- Tokens are hashed with SHA-256 before storage; the plaintext is never written to the database.
- Each active app name must be unique; reuse is allowed after deactivation.
- There is no automatic token expiration — rotate keys manually by deactivating the old key and creating a new one.
- For production, restrict key distribution and use read-only keys for clients that only query data.
