import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.redis_service import get_redis_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.subscriptions: dict[str, set[str]] = {}  # client_id -> pv_names

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.subscriptions[client_id] = set()
        logger.info(f"WebSocket client {client_id} connected")

    async def disconnect(self, client_id: str) -> None:
        """Remove a client connection."""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.subscriptions:
            del self.subscriptions[client_id]
        logger.info(f"WebSocket client {client_id} disconnected")

    async def subscribe(self, client_id: str, pv_names: list[str]) -> None:
        """Subscribe a client to PV updates."""
        if client_id in self.subscriptions:
            self.subscriptions[client_id].update(pv_names)
            logger.debug(f"Client {client_id} subscribed to {len(pv_names)} PVs")

    async def unsubscribe(self, client_id: str, pv_names: list[str]) -> None:
        """Unsubscribe a client from PV updates."""
        if client_id in self.subscriptions:
            self.subscriptions[client_id] -= set(pv_names)
            logger.debug(f"Client {client_id} unsubscribed from {len(pv_names)} PVs")

    async def broadcast_pv_update(self, pv_name: str, value: dict) -> None:
        """Broadcast a PV update to subscribed clients."""
        message = json.dumps({
            "type": "pv_update",
            "pvName": pv_name,
            "value": value
        })

        disconnected = []
        for client_id, subscribed_pvs in self.subscriptions.items():
            if pv_name in subscribed_pvs or len(subscribed_pvs) == 0:
                # Send to clients subscribed to this PV or all updates
                websocket = self.active_connections.get(client_id)
                if websocket:
                    try:
                        await websocket.send_text(message)
                    except Exception as e:
                        logger.error(f"Error sending to client {client_id}: {e}")
                        disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            await self.disconnect(client_id)

    async def send_personal_message(self, message: str, client_id: str) -> None:
        """Send a message to a specific client."""
        websocket = self.active_connections.get(client_id)
        if websocket:
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.error(f"Error sending to client {client_id}: {e}")

    def get_connection_count(self) -> int:
        """Get the number of active connections."""
        return len(self.active_connections)


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws/pvs")
async def websocket_pvs(websocket: WebSocket):
    """
    WebSocket endpoint for real-time PV updates.

    Message format:
    - Subscribe: {"type": "subscribe", "pvNames": ["PV1", "PV2"]}
    - Unsubscribe: {"type": "unsubscribe", "pvNames": ["PV1"]}
    - Get all: {"type": "get_all"}

    Server sends:
    - PV update: {"type": "pv_update", "pvName": "PV1", "value": {...}}
    - Initial values: {"type": "initial_values", "values": {...}}
    """
    client_id = str(uuid.uuid4())
    await manager.connect(websocket, client_id)

    try:
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "subscribe":
                pv_names = data.get("pvNames", [])
                await manager.subscribe(client_id, pv_names)

                # Send current values for subscribed PVs
                try:
                    redis = get_redis_service()
                    current_values = await redis.get_pv_values_bulk(pv_names)
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "initial_values",
                            "values": current_values
                        }),
                        client_id
                    )
                except Exception as e:
                    logger.error(f"Error getting initial values: {e}")

            elif message_type == "unsubscribe":
                pv_names = data.get("pvNames", [])
                await manager.unsubscribe(client_id, pv_names)

            elif message_type == "get_all":
                # Send all cached values
                try:
                    redis = get_redis_service()
                    all_values = await redis.get_all_pv_values()
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "all_values",
                            "values": all_values,
                            "count": len(all_values)
                        }),
                        client_id
                    )
                except Exception as e:
                    logger.error(f"Error getting all values: {e}")
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "error",
                            "message": str(e)
                        }),
                        client_id
                    )

            elif message_type == "ping":
                await manager.send_personal_message(
                    json.dumps({"type": "pong"}),
                    client_id
                )

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
        await manager.disconnect(client_id)


@router.get("/ws/status", response_model=dict)
async def websocket_status():
    """Get WebSocket connection status."""
    return {
        "activeConnections": manager.get_connection_count(),
        "subscriptions": {
            client_id: list(pvs)
            for client_id, pvs in manager.subscriptions.items()
        }
    }


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager."""
    return manager
