"""Crafty Controller API v2 client.

All POST bodies are sent as plain text/JSON matching the exact schema
captured from the Crafty UI HAR trace:
  POST /api/v2/servers  → 201 Created
"""
import httpx
from app.config import CRAFTY_URL, CRAFTY_TOKEN, CRAFTY_VERIFY_SSL

HEADERS = {
    "Authorization": f"Bearer {CRAFTY_TOKEN}",
    "Content-Type": "text/plain; charset=UTF-8",
    "Accept": "application/json",
}


async def list_servers() -> dict:
    async with httpx.AsyncClient(verify=CRAFTY_VERIFY_SSL) as client:
        r = await client.get(f"{CRAFTY_URL}/api/v2/servers", headers=HEADERS)
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
    """
    Create a Minecraft Java server in Crafty via download_jar.

    Exact schema from HAR capture (POST /api/v2/servers → 201):
    {
      "name": "Server Name",
      "roles": [],
      "monitoring_type": "minecraft_java",
      "minecraft_java_monitoring_data": {"host": "127.0.0.1", "port": <port>},
      "create_type": "minecraft_java",
      "minecraft_java_create_data": {
        "create_type": "download_jar",
        "download_jar_create_data": {
          "category": "mc_java_servers",
          "type": "<mod_loader>",   # e.g. "forge-installer", "fabric", "vanilla"
          "version": "<mc_version>",
          "mem_min": <int>,
          "mem_max": <int>,
          "server_properties_port": <port>
        }
      }
    }
    """
    import json
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
    async with httpx.AsyncClient(verify=CRAFTY_VERIFY_SSL) as client:
        r = await client.post(
            f"{CRAFTY_URL}/api/v2/servers",
            headers=HEADERS,
            content=json.dumps(payload),
        )
        r.raise_for_status()
        return r.json()
