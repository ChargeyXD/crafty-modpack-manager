"""Crafty Controller API v2 client.

The POST /api/v2/servers payload exactly matches the schema captured
from a live Crafty UI HAR trace (HTTP 201 Created confirmed):

  {
    "name": "...",
    "roles": [],
    "monitoring_type": "minecraft_java",
    "minecraft_java_monitoring_data": {"host": "127.0.0.1", "port": <int>},
    "create_type": "minecraft_java",
    "minecraft_java_create_data": {
      "create_type": "download_jar",
      "download_jar_create_data": {
        "category": "mc_java_servers",
        "type": "<loader>",
        "version": "<mc_version>",
        "mem_min": <int>,
        "mem_max": <int>,
        "server_properties_port": <int>
      }
    }
  }

Crafty requires Content-Type: text/plain (not application/json)
even though the body is valid JSON.
"""
import asyncio
import json
import httpx
from app.config import CRAFTY_URL, CRAFTY_TOKEN, CRAFTY_VERIFY_SSL

# How long to wait (seconds) for Crafty to finish the jar download before
# we attempt modpack injection.  Large modpacks + slow connections may need
# this increased, but 300 s is enough for almost all forge/neoforge installs.
READY_TIMEOUT = 300
POLL_INTERVAL = 5


def _headers() -> dict:
    """Build headers at call-time so a token set after import is picked up."""
    return {
        "Authorization": f"Bearer {CRAFTY_TOKEN}",
        "Content-Type": "text/plain; charset=UTF-8",
        "Accept": "application/json",
    }


async def list_servers() -> dict:
    async with httpx.AsyncClient(verify=CRAFTY_VERIFY_SSL, timeout=10) as c:
        r = await c.get(f"{CRAFTY_URL}/api/v2/servers", headers=_headers())
        r.raise_for_status()
        return r.json()


async def get_server(server_id: str) -> dict:
    """Return the full server object from Crafty for *server_id*."""
    async with httpx.AsyncClient(verify=CRAFTY_VERIFY_SSL, timeout=10) as c:
        r = await c.get(
            f"{CRAFTY_URL}/api/v2/servers/{server_id}",
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()


async def poll_server_ready(server_id: str) -> dict:
    """Poll GET /api/v2/servers/{id} until Crafty marks the server as *stopped*
    (meaning the jar-download / installer run has completed) or until
    READY_TIMEOUT seconds have elapsed.

    Returns the final server dict on success, raises TimeoutError otherwise.
    """
    elapsed = 0
    while elapsed < READY_TIMEOUT:
        data = await get_server(server_id)
        # Crafty stores running state in data["data"]["running"]; after setup
        # the server is not running yet, and the server path is populated.
        server = data.get("data", {})
        path = server.get("path", "")
        # Consider ready when Crafty has written the server directory path and
        # the server is in a stopped (not "Downloading") state.
        if path and not server.get("running", False):
            return server
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    raise TimeoutError(
        f"Server {server_id} did not become ready within {READY_TIMEOUT}s"
    )


async def create_server(
    name: str,
    mod_loader: str,
    mc_version: str,
    mem_min: int,
    mem_max: int,
    port: int,
) -> dict:
    payload = {
        "name": name,
        "roles": [],
        "monitoring_type": "minecraft_java",
        "minecraft_java_monitoring_data": {"host": "127.0.0.1", "port": port},
        "create_type": "minecraft_java",
        "minecraft_java_create_data": {
            "create_type": "download_jar",
            "download_jar_create_data": {
                "category": "mc_java_servers",
                "type": mod_loader,
                "version": mc_version,
                "mem_min": mem_min,
                "mem_max": mem_max,
                "server_properties_port": port,
            },
        },
    }
    async with httpx.AsyncClient(verify=CRAFTY_VERIFY_SSL, timeout=60) as c:
        r = await c.post(
            f"{CRAFTY_URL}/api/v2/servers",
            headers=_headers(),
            content=json.dumps(payload),
        )
        r.raise_for_status()
        return r.json()
