"""CurseForge API client (v1)."""
import httpx
from app.config import CURSEFORGE_API_KEY, MINECRAFT_GAME_ID, MODPACK_CLASS_ID

CF_BASE = "https://api.curseforge.com/v1"
HEADERS = {"x-api-key": CURSEFORGE_API_KEY, "Accept": "application/json"}


async def search_modpacks(query: str = "", page: int = 0, page_size: int = 20) -> dict:
    """Search CurseForge for Minecraft modpacks."""
    params = {
        "gameId": MINECRAFT_GAME_ID,
        "classId": MODPACK_CLASS_ID,
        "searchFilter": query,
        "index": page * page_size,
        "pageSize": page_size,
        "sortField": 2,  # Popularity
        "sortOrder": "desc",
    }
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CF_BASE}/mods/search", headers=HEADERS, params=params)
        r.raise_for_status()
        return r.json()


async def get_modpack(mod_id: int) -> dict:
    """Get full modpack details."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CF_BASE}/mods/{mod_id}", headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def get_modpack_files(mod_id: int, mc_version: str | None = None) -> dict:
    """List files for a modpack, optionally filtered by Minecraft version."""
    params = {"pageSize": 50, "sortOrder": "desc"}
    if mc_version:
        params["gameVersion"] = mc_version
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CF_BASE}/mods/{mod_id}/files", headers=HEADERS, params=params)
        r.raise_for_status()
        return r.json()


async def get_file(mod_id: int, file_id: int) -> dict:
    """Get a specific modpack file."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CF_BASE}/mods/{mod_id}/files/{file_id}", headers=HEADERS)
        r.raise_for_status()
        return r.json()
