"""FastAPI application — Crafty Modpack Manager."""
import asyncio
import io
import os
import pathlib
import zipfile

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import crafty, curseforge
from app.config import (
    BASE_SERVER_PORT, CRAFTY_URL, CRAFTY_VERIFY_SSL,
    CURSEFORGE_API_KEY, DEFAULT_MEM_MAX, DEFAULT_MEM_MIN,
)

app = FastAPI(
    title="Crafty Modpack Manager",
    version="1.4.0",
    docs_url="/docs",
    redoc_url=None,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Root of Crafty servers dir as seen inside this container.
# docker-compose mounts /DATA/AppData/big-bear-crafty/data/servers -> here.
CRAFTY_SERVERS_ROOT = os.environ.get("CRAFTY_SERVERS_ROOT", "/crafty-servers")


# -- Helpers ------------------------------------------------------------------

def _server_dir(server_id: str) -> pathlib.Path:
    return pathlib.Path(CRAFTY_SERVERS_ROOT) / server_id


async def _install_modpack_zip(server_dir: pathlib.Path, download_url: str) -> list[str]:
    """Download a CurseForge modpack zip and extract it into server_dir.

    Handles both layouts:
      * overrides/ layout  -- standard CF server pack
      * flat layout        -- everything at root level

    Also skips manifest.json / modlist.html / installer metadata so only
    actual server files (mods, configs, scripts, kubejs, etc.) are written.
    """
    server_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []

    # Skip these top-level metadata files that are never needed on the server
    _SKIP_FILES = {"manifest.json", "modlist.html", "minecraftinstance.json"}

    async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
        resp = await client.get(download_url)
        resp.raise_for_status()
        zip_bytes = resp.content

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        has_overrides = any(n.startswith("overrides/") for n in names)

        for member in names:
            if member.endswith("/"):
                continue

            if has_overrides:
                if not member.startswith("overrides/"):
                    continue
                rel = member[len("overrides/"):]
            else:
                rel = member

            if not rel:
                continue

            # Skip top-level installer metadata
            top = rel.split("/")[0]
            if top in _SKIP_FILES:
                continue

            dest = server_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))
            extracted.append(rel)

    return extracted


async def _run_deploy(req_data: dict) -> dict:
    """Core three-phase deploy logic.

    Phase 1 -- Crafty creates the server record and starts the jar download.
    Phase 2 -- Poll the shared volume until Crafty finishes writing the server
               directory (filesystem check, not just API status).
    Phase 3 -- Download the CurseForge modpack zip and extract it into the
               server directory via the shared volume mount.
    """
    server_name = req_data["server_name"]
    mod_loader  = req_data["mod_loader"]
    mc_version  = req_data["mc_version"]
    # RAM: frontend sends MB, Crafty expects GB -- convert here.
    mem_min_mb  = req_data["mem_min"]
    mem_max_mb  = req_data["mem_max"]
    mem_min_gb  = max(1, round(mem_min_mb / 1024))
    mem_max_gb  = max(mem_min_gb, round(mem_max_mb / 1024))
    port        = req_data["port"]
    mod_id      = req_data.get("mod_id")
    file_id     = req_data.get("file_id")

    # -- Phase 1: create server -----------------------------------------------
    result = await crafty.create_server(
        name=server_name,
        mod_loader=mod_loader,
        mc_version=mc_version,
        mem_min=mem_min_gb,
        mem_max=mem_max_gb,
        port=port,
    )

    server_id: str | None = (
        result.get("data", {}).get("new_server_id")
        or result.get("data", {}).get("server_id")
        or result.get("new_server_id")
    )

    # No modpack selected -- vanilla/loader-only deploy.
    if not (mod_id and file_id):
        return {
            "status": "created",
            "server_id": server_id,
            "modpack_installed": False,
            "crafty_response": result,
        }

    if not server_id:
        return {
            "status": "created_no_id",
            "warning": "Crafty did not return a server ID; modpack files were NOT installed.",
            "crafty_response": result,
        }

    # -- Phase 2: wait for Crafty to finish writing the server dir ------------
    # poll_server_ready now does a FILESYSTEM check via the shared volume
    # mount rather than trusting the API running-flag alone.  It returns
    # an augmented server dict that contains _resolved_dir.
    try:
        server_info = await crafty.poll_server_ready(server_id)
    except TimeoutError as e:
        return {
            "status": "timeout_waiting_for_server",
            "server_id": server_id,
            "warning": str(e),
            "modpack_installed": False,
            "crafty_response": result,
        }

    # Prefer the pre-resolved path set by poll_server_ready, then fall back
    # to deriving it from the path field Crafty returned.
    resolved_dir: str = server_info.get("_resolved_dir", "")
    if not resolved_dir:
        crafty_path = server_info.get("path", "") or ""
        uid_part    = pathlib.Path(crafty_path).name if crafty_path else server_id
        resolved_dir = str(_server_dir(uid_part))

    server_dir = pathlib.Path(resolved_dir)

    # -- Phase 3: download + extract modpack zip ------------------------------
    try:
        download_url = await curseforge.get_file_download_url(mod_id, file_id)
    except (httpx.HTTPStatusError, ValueError) as e:
        return {
            "status": "created_no_modpack_url",
            "server_id": server_id,
            "server_dir": resolved_dir,
            "warning": f"Server created but modpack download URL unavailable: {e}",
            "modpack_installed": False,
            "crafty_response": result,
        }

    extracted_files = await _install_modpack_zip(server_dir, download_url)

    return {
        "status": "created_with_modpack",
        "server_id": server_id,
        "server_dir": resolved_dir,
        "modpack_installed": True,
        "files_extracted": len(extracted_files),
        "crafty_response": result,
    }


# -- Health / config ----------------------------------------------------------

@app.get("/health", include_in_schema=False)
async def health():
    """Basic health probe + Crafty reachability check used by the UI status dots."""
    crafty_ok = False
    try:
        async with httpx.AsyncClient(verify=CRAFTY_VERIFY_SSL, timeout=4) as c:
            r = await c.get(
                f"{CRAFTY_URL}/api/v2/crafty/announcements",
                headers={"Authorization": f"Bearer {os.environ.get('CRAFTY_TOKEN', '')}"},
            )
            crafty_ok = r.status_code < 500
    except Exception:
        pass
    return {"status": "ok", "crafty_reachable": crafty_ok}


@app.get("/api/config", include_in_schema=False)
async def get_config():
    """Surface non-secret config to the frontend status bar."""
    return {
        "crafty_url": CRAFTY_URL,
        "curseforge_configured": bool(CURSEFORGE_API_KEY),
    }


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# -- CurseForge ---------------------------------------------------------------

@app.get("/api/modpacks", summary="Search CurseForge modpacks (canonical)")
@app.get("/api/modpacks/search", summary="Search CurseForge modpacks (frontend alias)", include_in_schema=False)
async def search_modpacks(
    q: str = Query(default="", description="Search query"),
    mc_version: str = Query(default="", description="Filter by MC version"),
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=20, ge=1, le=50),
):
    try:
        raw = await curseforge.search_modpacks(
            query=q,
            page=page,
            page_size=page_size,
            mc_version=mc_version or None,
        )
        return raw.get("data", raw)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"CurseForge unreachable: {e}")


@app.get("/api/modpacks/{mod_id}", summary="Get modpack details")
async def get_modpack(mod_id: int):
    try:
        raw = await curseforge.get_modpack(mod_id)
        return raw.get("data", raw)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


@app.get("/api/modpacks/{mod_id}/files", summary="List modpack files")
async def get_modpack_files(
    mod_id: int,
    mc_version: str = Query(default=None),
):
    try:
        raw = await curseforge.get_modpack_files(mod_id, mc_version)
        return raw.get("data", raw)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


# -- Crafty -------------------------------------------------------------------

@app.get("/api/servers", summary="List Crafty servers")
async def list_servers():
    try:
        raw = await crafty.list_servers()
        return raw.get("data", raw)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Crafty unreachable: {e}")


@app.post("/api/servers/{server_id}/action/{action}", summary="Send action to Crafty server")
async def server_action(server_id: str, action: str):
    allowed = {"start", "stop", "restart"}
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"Action must be one of: {allowed}")
    try:
        async with httpx.AsyncClient(verify=CRAFTY_VERIFY_SSL, timeout=10) as c:
            from app.crafty import _headers
            r = await c.post(
                f"{CRAFTY_URL}/api/v2/servers/{server_id}/action/{action}",
                headers=_headers(),
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach Crafty: {e}")


class DeployRequest(BaseModel):
    server_name: str = Field(..., min_length=1, max_length=64)
    mod_loader:  str = Field(..., description="forge-installer | fabric | neoforge | quilt")
    mc_version:  str = Field(...)
    # RAM in MB (frontend sends MB, we convert to GB before Crafty call)
    mem_min:     int = Field(default=2048, ge=512,  le=65536, description="Min RAM in MB")
    mem_max:     int = Field(default=6144, ge=1024, le=65536, description="Max RAM in MB")
    port:        int = Field(default=BASE_SERVER_PORT, ge=1024, le=65535)
    # CurseForge file references -- both needed for modpack injection
    mod_id:      int | None = Field(default=None)
    file_id:     int | None = Field(default=None)
    # Frontend-name aliases (accepted transparently)
    modpack_id:       int | None = Field(default=None, exclude=True)
    modpack_file_id:  int | None = Field(default=None, exclude=True)
    modloader:        str | None = Field(default=None, exclude=True)
    min_ram:          int | None = Field(default=None, exclude=True)
    max_ram:          int | None = Field(default=None, exclude=True)

    def model_post_init(self, __context):
        if self.modpack_id is not None and self.mod_id is None:
            self.mod_id = self.modpack_id
        if self.modpack_file_id is not None and self.file_id is None:
            self.file_id = self.modpack_file_id
        if self.modloader is not None:
            self.mod_loader = self.modloader
        if self.min_ram is not None:
            self.mem_min = self.min_ram
        if self.max_ram is not None:
            self.mem_max = self.max_ram


async def _handle_deploy(req: DeployRequest):
    if req.mem_min > req.mem_max:
        raise HTTPException(status_code=422, detail="mem_min cannot exceed mem_max")
    try:
        return await _run_deploy({
            "server_name": req.server_name,
            "mod_loader":  req.mod_loader,
            "mc_version":  req.mc_version,
            "mem_min":     req.mem_min,
            "mem_max":     req.mem_max,
            "port":        req.port,
            "mod_id":      req.mod_id,
            "file_id":     req.file_id,
        })
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Crafty error {e.response.status_code}: {e.response.text}",
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach Crafty: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deploy failed: {e}")


# Two URL aliases
@app.post("/api/deploy",         status_code=201, summary="Deploy modpack as Crafty server")
@app.post("/api/servers/create", status_code=201, summary="Deploy (frontend alias)", include_in_schema=False)
async def deploy_server(req: DeployRequest):
    return await _handle_deploy(req)
