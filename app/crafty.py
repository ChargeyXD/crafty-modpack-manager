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
even though the body is valid JSON — this matches browser behaviour.
"""
import json
import httpx
from app.config import CRAFTY_URL, CRAFTY_TOKEN, CRAFTY_VERIFY_SSL

_HEADERS = {
    "Authorization": f"Bearer {CRAFTY_TOKEN}",
    "Content-Type": "text/plain; charset=UTF-8",
    "Accept": "application/json",
}


async def list_servers() -> dict:
    async with httpx.AsyncClient(verify=CRAFTY_VERIFY_SSL, timeout=10) as c:
        r = await c.get(f"{CRAFTY_URL}/api/v2/servers", headers=_HEADERS)
        r.raise_for_status()
        return r.json()


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
            headers=_HEADERS,
            content=json.dumps(payload),
        )
        r.raise_for_status()
        return r.json()
