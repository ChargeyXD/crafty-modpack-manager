"""CurseForge REST API v1 client."""
import asyncio
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

# Map to the exact loader string Crafty's download_jar catalog expects.
# ALL loaders need the -installer suffix (Crafty stores the jar URL in
# servers.executable_update_url; omitting -installer leaves it NULL).
_CRAFTY_LOADER_MAP = {
    "forge":    "forge-installer",
    "fabric":   "fabric-installer",
    "quilt":    "quilt-installer",
    "neoforge": "neoforge-installer",
    "any":      "forge-installer",
}


def _headers() -> dict:
    return {"x-api-key": CURSEFORGE_API_KEY, "Accept": "application/json"}


def _is_server_pack_file(f: dict) -> bool:
    """Heuristic: return True when a file entry is a dedicated server pack.

    CurseForge marks server packs in two ways:
      1. fileType == 1 on the *additional* file record (server pack type).
      2. The filename starts with 'ServerFiles' (used by ATM, FTB, Technic packs).
    Either indicator is sufficient.
    """
    name: str = f.get("fileName", "") or f.get("displayName", "")
    if name.lower().startswith("serverfiles"):
        return True
    # CurseForge fileType: 0=release,1=beta,2=alpha -- NOT server flag.
    # The server-pack flag lives in the parent file's serverPackFileId OR in
    # the additionalFiles list where isServerPack may be set.
    if f.get("isServerPack") is True:
        return True
    return False


def _normalize_file(f: dict) -> dict:
    """Inject _mc_version, _loader, and _is_server_pack fields the frontend reads."""
    mc_ver = ""
    loader_str = ""
    for v in f.get("gameVersions", []):
        if v.replace(".", "").isdigit() or (".") in v and not any(
            kw in v for kw in ("Forge", "Fabric", "Quilt", "Neo", "Loader")
        ):
            mc_ver = v
        elif any(kw in v for kw in ("Forge", "Fabric", "Quilt", "NeoForge")):
            loader_str = (
                v.lower()
                .replace("neoforge", "neoforge")
                .replace("forge", "forge")
                .replace("fabric", "fabric")
                .replace("quilt", "quilt")
            )

    raw_loader_id = (f.get("modLoaders") or [None])[0]
    if isinstance(raw_loader_id, int):
        loader_str = _LOADER_MAP.get(raw_loader_id, loader_str or "forge")
    elif isinstance(raw_loader_id, str):
        loader_str = raw_loader_id.lower()

    loader_str   = loader_str or "forge"
    crafty_loader = _CRAFTY_LOADER_MAP.get(loader_str, "forge-installer")

    f["_mc_version"]    = mc_ver
    f["_loader"]        = crafty_loader
    f["_is_server_pack"] = _is_server_pack_file(f)
    return f


async def _fetch_additional_files(client: httpx.AsyncClient, mod_id: int, file_id: int) -> list[dict]:
    """Return the additional-files list for a given (mod_id, file_id) pair.

    These are the files listed under the 'Additional Files' tab on CurseForge,
    which is where server packs like ServerFiles-*.zip appear.
    Silently returns [] on any error so a missing additional-files list never
    prevents the main file list from rendering.
    """
    try:
        r = await client.get(
            f"{_CF_BASE}/mods/{mod_id}/files/{file_id}/additional-files",
            headers=_headers(),
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception:
        pass
    return []


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
        "sortField":    2,
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
    """Return normalized file list with server pack files sorted to the top.

    For each main file we also fetch its additional-files list (in parallel)
    and splice in any server-pack entries found there.  Server pack files are
    marked with _is_server_pack=True and floated to the beginning of the list
    so the frontend auto-selects them.
    """
    params: dict = {"pageSize": 50, "sortOrder": "desc"}
    if mc_version:
        params["gameVersion"] = mc_version

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{_CF_BASE}/mods/{mod_id}/files", headers=_headers(), params=params)
        r.raise_for_status()
        raw = r.json()
        main_files: list[dict] = raw.get("data", raw)
        if not isinstance(main_files, list):
            return raw

        # Fetch additional-files for every main file entry in parallel
        tasks = [
            _fetch_additional_files(c, mod_id, f["id"])
            for f in main_files
        ]
        additional_batches: list[list[dict]] = await asyncio.gather(*tasks)

    # Build the combined file list:
    #  - server pack additional files go first (deduplicated by id)
    #  - then main files
    seen_ids: set[int] = set()
    server_packs: list[dict] = []
    normal_files: list[dict] = []

    # Collect server pack additional files first
    for main_f, add_files in zip(main_files, additional_batches):
        for af in add_files:
            fid = af.get("id")
            if fid in seen_ids:
                continue
            seen_ids.add(fid)
            norm = _normalize_file(dict(af))
            # Inherit MC version / loader from parent if the additional file
            # doesn't carry its own gameVersions list
            if not norm["_mc_version"]:
                parent = _normalize_file(dict(main_f))
                norm["_mc_version"] = parent["_mc_version"]
                norm["_loader"]     = parent["_loader"]
            if norm["_is_server_pack"]:
                server_packs.append(norm)
            # Non-server additional files are intentionally excluded --
            # they are typically language packs / patch files, not useful here.

    # Collect main files
    for f in main_files:
        fid = f.get("id")
        if fid in seen_ids:
            continue
        seen_ids.add(fid)
        norm = _normalize_file(dict(f))
        normal_files.append(norm)

    combined = server_packs + normal_files
    raw["data"] = combined
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
