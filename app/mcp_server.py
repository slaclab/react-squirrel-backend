"""
Squirrel MCP Server

Exposes Squirrel's save/restore operations as MCP tools so an LLM
can take snapshots, restore PV values, search PVs, and manage tags.

The server communicates with the Squirrel REST API via HTTP — it does
not connect to the database or EPICS directly.

Usage:
    python -m app.mcp_server

Configuration (environment variables):
    SQUIRREL_MCP_API_URL   Base URL of the Squirrel REST API  (default: http://localhost:8080)
    SQUIRREL_MCP_API_KEY   API key token for authentication   (required)
"""

import asyncio
import logging
import os

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

logger = logging.getLogger(__name__)

API_URL = os.environ.get("SQUIRREL_MCP_API_URL", "http://localhost:8080").rstrip("/")
API_KEY = os.environ.get("SQUIRREL_MCP_API_KEY", "")

server = Server("squirrel")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


async def _get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_URL}{path}", headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_snapshots",
            description="List all snapshots, optionally filtered by title or tag.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Filter by title (partial match)"},
                    "tag_id": {"type": "integer", "description": "Filter by tag ID"},
                },
            },
        ),
        types.Tool(
            name="get_snapshot",
            description="Get a snapshot by ID, including all saved PV values.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Snapshot ID"},
                },
                "required": ["id"],
            },
        ),
        types.Tool(
            name="compare_snapshots",
            description="Compare two snapshots and return the differences between PV values.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id1": {"type": "integer", "description": "First snapshot ID"},
                    "id2": {"type": "integer", "description": "Second snapshot ID"},
                },
                "required": ["id1", "id2"],
            },
        ),
        types.Tool(
            name="get_job_status",
            description="Check the status and progress of a background job (e.g. snapshot creation).",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Job ID"},
                },
                "required": ["id"],
            },
        ),
        types.Tool(
            name="search_pvs",
            description="Search for process variables (PVs) by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "PV name to search (partial match)"},
                    "limit": {"type": "integer", "description": "Max results to return (default 50)"},
                },
            },
        ),
        types.Tool(
            name="get_live_pv_values",
            description="Get the current live values of PVs from the Redis cache.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pv_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of PV names to fetch",
                    },
                },
                "required": ["pv_names"],
            },
        ),
        types.Tool(
            name="list_tags",
            description="List all tag groups and their tags.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        result = await _dispatch(name, arguments)
    except httpx.HTTPStatusError as e:
        result = {"error": f"HTTP {e.response.status_code}", "detail": e.response.text}
    except Exception as e:
        result = {"error": str(e)}

    import json
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def _dispatch(name: str, args: dict) -> dict:
    if name == "list_snapshots":
        params = {}
        if "title" in args:
            params["title"] = args["title"]
        if "tag_id" in args:
            params["tag_id"] = args["tag_id"]
        return await _get("/v1/snapshots", params=params or None)

    if name == "get_snapshot":
        return await _get(f"/v1/snapshots/{args['id']}")

    if name == "compare_snapshots":
        return await _get(f"/v1/snapshots/{args['id1']}/compare/{args['id2']}")

    if name == "get_job_status":
        return await _get(f"/v1/jobs/{args['id']}")

    if name == "search_pvs":
        params: dict = {}
        if "name" in args:
            params["name"] = args["name"]
        if "limit" in args:
            params["limit"] = args["limit"]
        return await _get("/v1/pvs", params=params or None)

    if name == "get_live_pv_values":
        return await _get("/v1/pvs/live", params={"pv_names": args["pv_names"]})

    if name == "list_tags":
        return await _get("/v1/tags")

    return {"error": f"Unknown tool: {name}"}

async def main():
    logging.basicConfig(level=logging.INFO)
    if not API_KEY:
        logger.warning("SQUIRREL_MCP_API_KEY is not set — requests may be rejected by the API")
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
