"""CurseForge REST API v1 client."""
import httpx
from app.config import CURSEFORGE_API_KEY, MINECRAFT_GAME_ID, MODPACK_CLASS_ID

_CF_BASE = "https://api.curseforge.com/v1"

# Map CurseForge numeric modLoader IDs to human-readable strings
_LOADER_MAP = {
    0: "any",
    1: "forge",
    2: "cauldron",
    3: "liteloader",
    4: "fabric",
    5: "quilt",
    6: "neoforge",
}

# Map to the loader string Crafty accepts for download_jar
_CRAFTY_LOADER_MAP = {
    "forge":    "forge-installer",
    "fabric":   "fabric",
    "quilt":    "quilt",
    "neoforge": "neoforge",
    "any":      "forge-installer",
}


def _headers() -> dict:
    return {"x-api-key": CURSEFORGE_API_KEY, "Accept": "application/json"}


def _normalize_file(f: dict) -> dict:
    """Inject _mc_version and _loader fields the frontend <option> elements read."""
    # Primary MC version comes from gameVersions list; pick the one that looks
    # like a MC release (contains dots, no 'Forge'/'Fabric' etc. in the string).
    mc_ver = ""
    loader_str = ""
    for v in f.get("gameVersions", []):
        if v.replace(".", "").isdigit() or (".") in v and not any(
            kw in v for kw in ("Forge", "Fabric", "Quilt", "Neo", "Loader")
        ):
            mc_ver = v
        elif any(kw in v for kw in ("Forge", "Fabric", "Quilt", "NeoForge")):
            loader_str = v.lower().replace("neoforge", "neoforge").replace("forge", "forge").replace("fabric", "fabric").replace("quilt", "quilt")

    # Also check modLoaders list if present
    raw_loader_id = (f.get("modLoaders") or [None])[0]
    if isinstance(raw_loader_id, int):
        loader_str = _LOADER_MAP.get(raw_loader_id, loader_str or "forge")
    elif isinstance(raw_loader_id, str):
        loader_str = raw_loader_id.lower()

    loader_str = loader_str or "forge"
    # Translate to Crafty-compatible loader string
    crafty_loader = _CRAFTY_LOADER_MAP.get(loader_str, "forge-installer")

    f["_mc_version"] = mc_ver
    f["_loader"]     = crafty_loader
    return f


async def search_modpacks(
    query: str = "",
    page: int = 0,
    page_size: int = 20,
    mc_version: str | None = None,
) -> dict:
    params: dict = {
        "gameId":       MINECRAFT_GAME_ID,
        "classId":      MODPACK_CLASS_ID,
        "searchFilter": query,
        "index":        page * page_size,
        "pageSize":     page_size,
        "sortField":    2,   # Popularity
        "sortOrder":    "desc",
    }
    if mc_version:
        params["gameVersion"] = mc_version
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
        raw = r.json()
        # Normalize each file entry so the frontend can read _mc_version and _loader
        files = raw.get("data", raw)
        if isinstance(files, list):
            raw["data"] = [_normalize_file(f) for f in files]
        return raw


async def get_file_download_url(mod_id: int, file_id: int) -> str:
    """Return the direct CDN download URL for a specific CurseForge file."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{_CF_BASE}/mods/{mod_id}/files/{file_id}/download-url",
            headers=_headers(),
        )
        r.raise_for_status()
        payload = r.json()
        url = payload.get("data")
        if not url:
            # Fallback: read downloadUrl from the file metadata
            meta_r = await c.get(
                f"{_CF_BASE}/mods/{mod_id}/files/{file_id}",
                headers=_headers(),
            )
            meta_r.raise_for_status()
            url = meta_r.json().get("data", {}).get("downloadUrl")
        if not url:
            raise ValueError(
                f"CurseForge returned no download URL for mod {mod_id} file {file_id}. "
                "The file may be distributed only via the CurseForge client."
            )
        return url
