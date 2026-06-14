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
import os
import pathlib
import httpx
from app.config import CRAFTY_URL, CRAFTY_TOKEN, CRAFTY_VERIFY_SSL

# How long to wait (seconds) for Crafty to finish the jar download before
# we attempt modpack injection.  Large modpacks + slow connections may need
# this increased, but 300 s is enough for almost all forge/neoforge installs.
READY_TIMEOUT = 300
POLL_INTERVAL = 5

# Root of Crafty servers dir as seen inside this container.
CRAFTY_SERVERS_ROOT = os.environ.get("CRAFTY_SERVERS_ROOT", "/crafty-servers")

# Minimum number of files that must exist in a server dir before we
# consider it "ready" for modpack injection.  A fully initialised
# Crafty server directory always has at least: the server jar, eula.txt,
# and server.properties — so 3 is a safe lower bound.
_MIN_FILES_READY = 3


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


def _server_dir_ready(server_dir: pathlib.Path) -> bool:
    """Return True when the server directory exists on disk AND contains
    enough files to indicate Crafty has finished its initial setup.

    We check the filesystem directly (via the shared volume mount) rather
    than trusting the Crafty API alone, because:
      - Crafty sets path= and running=False immediately after creating the DB
        record, BEFORE the jar download has finished.
      - The only reliable signal that setup is truly complete is the presence
        of the server jar and supporting files on disk.
    """
    if not server_dir.exists():
        return False
    files = list(server_dir.rglob("*"))
    file_count = sum(1 for f in files if f.is_file())
    return file_count >= _MIN_FILES_READY


async def poll_server_ready(server_id: str) -> dict:
    """Poll until the server directory on disk is fully populated by Crafty.

    Strategy (dual-check for maximum reliability):
      1. Ask Crafty API for the server's path field.
      2. Check that path on the shared volume for >= _MIN_FILES_READY files.

    Both conditions must be true before we proceed to modpack injection.
    Raises TimeoutError if READY_TIMEOUT seconds elapse without success.
    """
    elapsed = 0
    last_path = ""

    while elapsed < READY_TIMEOUT:
        try:
            data = await get_server(server_id)
        except Exception:
            # Crafty may be briefly busy right after creation — keep polling
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            continue

        server = data.get("data", {})
        crafty_path = server.get("path", "") or ""

        if crafty_path:
            last_path = crafty_path
            # Derive the UID component from the path Crafty reports
            uid_part = pathlib.Path(crafty_path).name
            server_dir = pathlib.Path(CRAFTY_SERVERS_ROOT) / uid_part

            if _server_dir_ready(server_dir):
                # Augment the server dict so the caller has the resolved dir
                server["_resolved_dir"] = str(server_dir)
                return server

        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(
        f"Server {server_id} directory was not ready within {READY_TIMEOUT}s "
        f"(last reported path: {last_path!r}). "
        "Check the CRAFTY_SERVERS_ROOT volume mount in docker-compose.yml."
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
