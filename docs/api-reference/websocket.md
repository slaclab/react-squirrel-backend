# WebSocket API

The WebSocket API provides real-time PV value streaming with diff-based updates.

## Connection

Connect to the WebSocket endpoint and include your API key in the `X-API-Key` header:

```
ws://localhost:8080/v1/ws/pvs
```

Or for local development:

```
ws://localhost:8000/v1/ws/pvs
```

An alias endpoint is also available at `/v1/ws/live`.

!!! info "Authentication"
    WebSocket connections require an `X-API-Key` header with a key that has `read_access`. Connections without a valid key are rejected with close code `1008 (Policy Violation)`. See [API Key Management](../getting-started/api-keys.md).

## Message Format

All messages are JSON objects. Both client and server messages use a `type` field as the discriminator.

### Client → Server

#### Subscribe to PVs

```json
{
  "type": "subscribe",
  "pvNames": ["PV:NAME:1", "PV:NAME:2", "PV:NAME:3"]
}
```

After subscribing, the server immediately sends an `initial` message with current cached values for any subscribed PVs that exist in Redis.

#### Unsubscribe from PVs

```json
{
  "type": "unsubscribe",
  "pvNames": ["PV:NAME:1"]
}
```

#### Get all cached values

Returns every PV value currently in the Redis cache (one-shot, not tied to your subscriptions).

```json
{ "type": "get_all" }
```

#### Ping

```json
{ "type": "ping" }
```

The server replies with a `pong`.

### Server → Client

#### Initial values

Sent once after a successful `subscribe`, containing the current cached values for subscribed PVs that have data in Redis.

```json
{
  "type": "initial",
  "data": {
    "PV:NAME:1": {
      "value": 42.5,
      "connected": true,
      "updated_at": 1705312200.123,
      "status": "NO_ALARM",
      "severity": 0,
      "timestamp": 1705312200.000,
      "units": "mA"
    }
  },
  "count": 1
}
```

The per-PV shape matches the Redis cache entry (`app/services/redis_service.py::PVCacheEntry`). Null fields are omitted from the payload.

#### Diff updates

Emitted periodically (see batching window below) with only the PVs that changed since the last diff and are in your subscription set.

```json
{
  "type": "diff",
  "data": {
    "PV:NAME:1": {
      "value": 43.0,
      "connected": true,
      "updated_at": 1705312201.456,
      "status": "NO_ALARM",
      "severity": 0
    }
  },
  "count": 1,
  "timestamp": 1705312201.500
}
```

Timestamps in diff and heartbeat messages are Unix seconds (float), not ISO strings.

#### Heartbeat

Sent every ~5 seconds on every connection, regardless of subscriptions. Useful for keep-alive and for surfacing monitor health in the UI.

```json
{
  "type": "heartbeat",
  "timestamp": 1705312205.000,
  "monitor_heartbeat": 1705312204.950,
  "monitor_alive": true
}
```

#### All values

Response to `get_all`.

```json
{
  "type": "all_values",
  "values": { "PV:NAME:1": { "value": 42.5, "connected": true, "updated_at": 1705312200.123 } },
  "count": 1
}
```

#### Pong

Response to `ping`.

```json
{ "type": "pong", "timestamp": 1705312205.000 }
```

#### Error

```json
{
  "type": "error",
  "message": "Error description"
}
```

## JavaScript Example

```javascript
const ws = new WebSocket('ws://localhost:8080/v1/ws/pvs', [], {
  headers: { 'X-API-Key': 'sq_your_token_here' }
});

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: 'subscribe',
    pvNames: ['QUAD:LI21:201:BDES', 'QUAD:LI21:201:BACT']
  }));
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case 'initial':
      console.log('Initial values:', msg.data);
      break;
    case 'diff':
      for (const [pvName, entry] of Object.entries(msg.data)) {
        console.log(`${pvName} = ${entry.value}`);
      }
      break;
    case 'heartbeat':
      if (!msg.monitor_alive) console.warn('PV monitor is down');
      break;
    case 'error':
      console.error(msg.message);
      break;
  }
};
```

## Python Example

```python
import asyncio
import json
import websockets

async def subscribe_to_pvs():
    uri = "ws://localhost:8080/v1/ws/pvs"
    headers = {"X-API-Key": "sq_your_token_here"}

    async with websockets.connect(uri, additional_headers=headers) as ws:
        await ws.send(json.dumps({
            "type": "subscribe",
            "pvNames": ["QUAD:LI21:201:BDES", "QUAD:LI21:201:BACT"]
        }))

        async for message in ws:
            msg = json.loads(message)
            if msg["type"] == "initial":
                print("Initial:", msg["data"])
            elif msg["type"] == "diff":
                for pv_name, entry in msg["data"].items():
                    print(f"{pv_name} = {entry['value']}")
            elif msg["type"] == "heartbeat" and not msg["monitor_alive"]:
                print("Monitor is down")

asyncio.run(subscribe_to_pvs())
```

## React Hook Example

```typescript
import { useEffect, useState } from 'react';

interface PVEntry {
  value: unknown;
  connected: boolean;
  updated_at: number;
  status?: string;
  severity?: number;
  timestamp?: number;
  units?: string;
}

function usePVSubscription(pvNames: string[], apiKey: string) {
  const [values, setValues] = useState<Record<string, PVEntry>>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8080/v1/ws/pvs', [], {
      headers: { 'X-API-Key': apiKey }
    });

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ type: 'subscribe', pvNames }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'initial' || msg.type === 'diff') {
        setValues(prev => ({ ...prev, ...msg.data }));
      }
    };

    ws.onclose = () => setConnected(false);
    return () => ws.close();
  }, [pvNames.join(',')]);

  return { values, connected };
}
```

## Connection Status Endpoint

For diagnostics, `GET /v1/ws/status` returns subscription and connection statistics for the current API instance:

```json
{
  "instanceId": "...",
  "multiInstanceEnabled": true,
  "activeConnections": 3,
  "totalSubscriptions": 42,
  "uniquePVsSubscribed": 37,
  "bufferSize": 0,
  "batchIntervalMs": 100
}
```

Requires `read_access`.

## Performance Considerations

### Batching

`diff` messages are flushed on a rolling window (default 100ms, `SQUIRREL_WEBSOCKET_BATCH_INTERVAL_MS`). Multiple PV changes arriving within the window are coalesced into one message.

### Diff-Based Updates

Only changed PVs are sent after the initial snapshot:

- `initial` carries the current cache state for your subscription set
- `diff` messages only include PVs that changed since the last flush
- Reduces bandwidth 10-100x compared to polling

### Multi-Instance Support

WebSocket connections work across multiple API instances:

- Subscription registry stored in Redis
- PV updates broadcast via Redis pub/sub
- Clients can connect to any API instance

## Reconnection

Clients should implement exponential backoff and re-subscribe on reconnect:

```javascript
function createReconnectingWebSocket(url, apiKey, onMessage) {
  let ws;
  let reconnectInterval = 1000;
  const maxInterval = 30000;

  function connect() {
    ws = new WebSocket(url, [], { headers: { 'X-API-Key': apiKey } });

    ws.onopen = () => {
      reconnectInterval = 1000;
    };

    ws.onmessage = onMessage;

    ws.onclose = () => {
      setTimeout(connect, reconnectInterval);
      reconnectInterval = Math.min(reconnectInterval * 2, maxInterval);
    };
  }

  connect();
  return { send: (data) => ws.send(data), close: () => ws.close() };
}
```
