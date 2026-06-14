"""CurseForge REST API v1 client."""
import httpx
from app.config import CURSEFORGE_API_KEY, MINECRAFT_GAME_ID, MODPACK_CLASS_ID

_CF_BASE = "https://api.curseforge.com/v1"
_HEADERS = {"x-api-key": CURSEFORGE_API_KEY, "Accept": "application/json"}


async def search_modpacks(query: str = "", page: int = 0, page_size: int = 20) -> dict:
    params = {
        "gameId": MINECRAFT_GAME_ID,
        "classId": MODPACK_CLASS_ID,
        "searchFilter": query,
        "index": page * page_size,
        "pageSize": page_size,
        "sortField": 2,   # Popularity
        "sortOrder": "desc",
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_CF_BASE}/mods/search", headers=_HEADERS, params=params)
        r.raise_for_status()
        return r.json()


async def get_modpack(mod_id: int) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_CF_BASE}/mods/{mod_id}", headers=_HEADERS)
        r.raise_for_status()
        return r.json()


async def get_modpack_files(mod_id: int, mc_version: str | None = None) -> dict:
    params: dict = {"pageSize": 50, "sortOrder": "desc"}
    if mc_version:
        params["gameVersion"] = mc_version
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_CF_BASE}/mods/{mod_id}/files", headers=_HEADERS, params=params)
        r.raise_for_status()
        return r.json()
