"""CurseForge REST API v1 client."""
import httpx
from app.config import CURSEFORGE_API_KEY, MINECRAFT_GAME_ID, MODPACK_CLASS_ID

_CF_BASE = "https://api.curseforge.com/v1"


def _headers() -> dict:
    """Build headers at call-time so a key set after import is picked up."""
    return {"x-api-key": CURSEFORGE_API_KEY, "Accept": "application/json"}


async def search_modpacks(query: str = "", page: int = 0, page_size: int = 20) -> dict:
    params = {
        "gameId": MINECRAFT_GAME_ID,
        "classId": MODPACK_CLASS_ID,
        "searchFilter": query,
        "index": page * page_size,
        "pageSize": page_size,
        "sortField": 2,    # Popularity
        "sortOrder": "desc",
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_CF_BASE}/mods/search", headers=_headers(), params=params)
        r.raise_for_status()
        return r.json()


async def get_modpack(mod_id: int) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_CF_BASE}/mods/{mod_id}", headers=_headers())
        r.raise_for_status()
        return r.json()


async def get_modpack_files(mod_id: int, mc_version: str | None = None) -> dict:
    params: dict = {"pageSize": 50, "sortOrder": "desc"}
    if mc_version:
        params["gameVersion"] = mc_version
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_CF_BASE}/mods/{mod_id}/files", headers=_headers(), params=params)
        r.raise_for_status()
        return r.json()


async def get_file_download_url(mod_id: int, file_id: int) -> str:
    """Return the direct CDN download URL for a specific CurseForge file.

    Uses GET /v1/mods/{modId}/files/{fileId}/download-url which returns
    the signed CDN link as a plain string in data.data.
    """
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{_CF_BASE}/mods/{mod_id}/files/{file_id}/download-url",
            headers=_headers(),
        )
        r.raise_for_status()
        payload = r.json()
        url = payload.get("data") or (payload.get("data") == "" and None)
        if not url:
            # Fallback: construct from file metadata when CDN URL is absent
            # (happens for some older files that have no direct link).
            meta_r = await c.get(
                f"{_CF_BASE}/mods/{mod_id}/files/{file_id}",
                headers=_headers(),
            )
            meta_r.raise_for_status()
            file_data = meta_r.json().get("data", {})
            url = file_data.get("downloadUrl")
        if not url:
            raise ValueError(
                f"CurseForge returned no download URL for mod {mod_id} file {file_id}. "
                "The file may be distributed only via the CurseForge client."
            )
        return url
