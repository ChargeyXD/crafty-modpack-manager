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

# Map to the exact loader string Crafty's download_jar catalog expects.
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
    """Return True when a file entry is a dedicated server pack.

    CurseForge marks server packs in two ways:
      1. f["isServerPack"] == True  (set on files fetched via the batch endpoint)
      2. The filename starts with 'ServerFiles' (ATM, FTB, Technic convention)
    """
    name: str = f.get("fileName", "") or f.get("displayName", "")
    if name.lower().startswith("serverfiles"):
        return True
    if f.get("isServerPack") is True:
        return True
    return False


def _normalize_file(f: dict) -> dict:
    """Inject _mc_version, _loader, and _is_server_pack fields the frontend reads."""
    mc_ver = ""
    loader_str = ""
    for v in f.get("gameVersions", []):
        if v.replace(".", "").isdigit() or (("." in v) and not any(
            kw in v for kw in ("Forge", "Fabric", "Quilt", "Neo", "Loader")
        )):
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

    loader_str    = loader_str or "forge"
    crafty_loader = _CRAFTY_LOADER_MAP.get(loader_str, "forge-installer")

    f["_mc_version"]     = mc_ver
    f["_loader"]         = crafty_loader
    f["_is_server_pack"] = _is_server_pack_file(f)
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

    CurseForge does NOT expose an additional-files endpoint. Server packs are
    separate file entries whose IDs are stored in the parent file's
    serverPackFileId field. We:
      1. Fetch main file list via GET /v1/mods/{mod_id}/files
      2. Collect every non-null serverPackFileId value
      3. Batch-fetch those in a single POST /v1/mods/files call
      4. Inject each server pack above its parent in the final list,
         tagged _is_server_pack=True so the frontend auto-selects it
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

        # --- Step 2: collect serverPackFileIds ---
        sp_id_to_parent: dict[int, dict] = {}
        for f in main_files:
            sp_id = f.get("serverPackFileId")
            if sp_id:
                sp_id_to_parent[int(sp_id)] = f

        # --- Step 3: batch-fetch server pack file details ---
        server_pack_map: dict[int, dict] = {}
        if sp_id_to_parent:
            try:
                sp_resp = await c.post(
                    f"{_CF_BASE}/mods/files",
                    headers={**_headers(), "Content-Type": "application/json"},
                    json={"fileIds": list(sp_id_to_parent.keys())},
                    timeout=15,
                )
                if sp_resp.status_code == 200:
                    for sp_file in sp_resp.json().get("data", []):
                        server_pack_map[sp_file["id"]] = sp_file
            except Exception:
                pass  # Missing server packs are non-fatal

    # --- Step 4: build combined list ---
    # For each main file: if it has a resolved server pack, inject it first.
    # Deduplicate by file id.
    seen_ids: set[int] = set()
    combined: list[dict] = []

    for f in main_files:
        # Inject server pack entry before the parent file
        sp_id = f.get("serverPackFileId")
        if sp_id and int(sp_id) not in seen_ids and int(sp_id) in server_pack_map:
            sp_file = dict(server_pack_map[int(sp_id)])
            # Inherit MC version/loader from parent if server pack file lacks them
            parent_norm = _normalize_file(dict(f))
            sp_norm = _normalize_file(sp_file)
            if not sp_norm["_mc_version"]:
                sp_norm["_mc_version"] = parent_norm["_mc_version"]
                sp_norm["_loader"]     = parent_norm["_loader"]
            # Force the server pack flag regardless of what the API returned
            sp_norm["_is_server_pack"] = True
            sp_norm["isServerPack"]    = True
            seen_ids.add(int(sp_id))
            combined.append(sp_norm)

        # Add the main file itself
        fid = f.get("id")
        if fid not in seen_ids:
            seen_ids.add(fid)
            combined.append(_normalize_file(dict(f)))

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
