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

An alias endpoint is also available at `/v1/ws/live` for compatibility.

!!! info "Authentication"
    WebSocket connections require an `X-API-Key` header with a key that has `read_access`. Connections without a valid key are rejected with close code `1008 (Policy Violation)`. See [API Key Management](../getting-started/api-keys.md).

## Message Format

All messages are JSON objects with an `action` field.

### Client Messages

#### Subscribe to PVs

```json
{
  "action": "subscribe",
  "pv_names": ["PV:NAME:1", "PV:NAME:2", "PV:NAME:3"]
}
```

#### Unsubscribe from PVs

```json
{
  "action": "unsubscribe",
  "pv_names": ["PV:NAME:1"]
}
```

#### Get Current Subscriptions

```json
{
  "action": "list_subscriptions"
}
```

### Server Messages

#### PV Update

When a subscribed PV value changes:

```json
{
  "type": "update",
  "pv_name": "PV:NAME:1",
  "value": 42.5,
  "timestamp": "2024-01-15T10:30:00.123456Z",
  "status": 0,
  "severity": 0
}
```

#### Batch Update

Multiple updates are batched together (100ms window):

```json
{
  "type": "batch_update",
  "updates": [
    {
      "pv_name": "PV:NAME:1",
      "value": 42.5,
      "timestamp": "2024-01-15T10:30:00.123456Z"
    },
    {
      "pv_name": "PV:NAME:2",
      "value": 3.14,
      "timestamp": "2024-01-15T10:30:00.123789Z"
    }
  ]
}
```

#### Subscription Confirmation

```json
{
  "type": "subscribed",
  "pv_names": ["PV:NAME:1", "PV:NAME:2"],
  "initial_values": {
    "PV:NAME:1": {"value": 42.5, "timestamp": "..."},
    "PV:NAME:2": {"value": 3.14, "timestamp": "..."}
  }
}
```

#### Error

```json
{
  "type": "error",
  "message": "PV not found: INVALID:PV:NAME"
}
```

## JavaScript Example

```javascript
const ws = new WebSocket('ws://localhost:8080/v1/ws/pvs', [], {
  headers: { 'X-API-Key': 'sq_your_token_here' }
});

ws.onopen = () => {
  console.log('Connected to WebSocket');

  // Subscribe to PVs
  ws.send(JSON.stringify({
    action: 'subscribe',
    pv_names: ['QUAD:LI21:201:BDES', 'QUAD:LI21:201:BACT']
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch (data.type) {
    case 'subscribed':
      console.log('Subscribed to:', data.pv_names);
      console.log('Initial values:', data.initial_values);
      break;

    case 'update':
      console.log(`${data.pv_name} = ${data.value}`);
      break;

    case 'batch_update':
      data.updates.forEach(update => {
        console.log(`${update.pv_name} = ${update.value}`);
      });
      break;

    case 'error':
      console.error('WebSocket error:', data.message);
      break;
  }
};

ws.onclose = () => {
  console.log('Disconnected from WebSocket');
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
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

    async with websockets.connect(uri, additional_headers=headers) as websocket:
        # Subscribe to PVs
        await websocket.send(json.dumps({
            "action": "subscribe",
            "pv_names": ["QUAD:LI21:201:BDES", "QUAD:LI21:201:BACT"]
        }))

        # Receive updates
        async for message in websocket:
            data = json.loads(message)

            if data["type"] == "subscribed":
                print(f"Subscribed to: {data['pv_names']}")

            elif data["type"] == "update":
                print(f"{data['pv_name']} = {data['value']}")

            elif data["type"] == "batch_update":
                for update in data["updates"]:
                    print(f"{update['pv_name']} = {update['value']}")

asyncio.run(subscribe_to_pvs())
```

## React Hook Example

```typescript
import { useEffect, useState, useCallback } from 'react';

interface PVValue {
  value: number;
  timestamp: string;
  status: number;
  severity: number;
}

function usePVSubscription(pvNames: string[], apiKey: string) {
  const [values, setValues] = useState<Record<string, PVValue>>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8080/v1/ws/pvs', [], {
      headers: { 'X-API-Key': apiKey }
    });

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({
        action: 'subscribe',
        pv_names: pvNames
      }));
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'subscribed') {
        setValues(data.initial_values);
      } else if (data.type === 'update') {
        setValues(prev => ({
          ...prev,
          [data.pv_name]: {
            value: data.value,
            timestamp: data.timestamp,
            status: data.status,
            severity: data.severity
          }
        }));
      } else if (data.type === 'batch_update') {
        setValues(prev => {
          const updated = { ...prev };
          data.updates.forEach((update: any) => {
            updated[update.pv_name] = {
              value: update.value,
              timestamp: update.timestamp,
              status: update.status || 0,
              severity: update.severity || 0
            };
          });
          return updated;
        });
      }
    };

    ws.onclose = () => setConnected(false);

    return () => ws.close();
  }, [pvNames.join(',')]);

  return { values, connected };
}

// Usage
function PVDisplay() {
  const { values, connected } = usePVSubscription(
    ['QUAD:LI21:201:BDES', 'QUAD:LI21:201:BACT'],
    'sq_your_token_here'
  );

  return (
    <div>
      <p>Status: {connected ? 'Connected' : 'Disconnected'}</p>
      {Object.entries(values).map(([name, pv]) => (
        <p key={name}>{name}: {pv.value}</p>
      ))}
    </div>
  );
}
```

## Performance Considerations

### Batching

Updates are batched with a 100ms window to reduce message frequency:

- Individual updates within 100ms are combined
- Reduces WebSocket message overhead
- Client receives fewer, larger messages

### Diff-Based Updates

Only changed values are sent:

- Initial subscription sends all current values
- Subsequent messages only include changed PVs
- Reduces bandwidth by 10-100x compared to polling

### Multi-Instance Support

WebSocket connections work across multiple API instances:

- Subscription registry stored in Redis
- PV updates broadcast via Redis pub/sub
- Clients can connect to any API instance

## Status and Severity Codes

EPICS alarm status and severity are included in updates:

**Status Codes:**

| Code | Meaning |
|------|---------|
| 0 | NO_ALARM |
| 1 | READ |
| 2 | WRITE |
| 3 | HIHI |
| 4 | HIGH |
| 5 | LOLO |
| 6 | LOW |
| 7 | STATE |
| 8 | COS |
| 9 | COMM |
| 10 | TIMEOUT |

**Severity Codes:**

| Code | Meaning |
|------|---------|
| 0 | NO_ALARM |
| 1 | MINOR |
| 2 | MAJOR |
| 3 | INVALID |

## Connection Management

### Heartbeat

The server sends periodic heartbeat messages to keep connections alive:

```json
{
  "type": "heartbeat",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Reconnection

Implement reconnection logic in your client:

```javascript
function createReconnectingWebSocket(url, apiKey, onMessage) {
  let ws;
  let reconnectInterval = 1000;
  const maxInterval = 30000;

  function connect() {
    ws = new WebSocket(url, [], { headers: { 'X-API-Key': apiKey } });

    ws.onopen = () => {
      console.log('Connected');
      reconnectInterval = 1000; // Reset on successful connect
    };

    ws.onmessage = onMessage;

    ws.onclose = () => {
      console.log(`Reconnecting in ${reconnectInterval}ms...`);
      setTimeout(connect, reconnectInterval);
      reconnectInterval = Math.min(reconnectInterval * 2, maxInterval);
    };
  }

  connect();

  return {
    send: (data) => ws.send(data),
    close: () => ws.close()
  };
}
```
