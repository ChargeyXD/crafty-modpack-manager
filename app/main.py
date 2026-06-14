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
from app.config import BASE_SERVER_PORT, DEFAULT_MEM_MAX, DEFAULT_MEM_MIN

app = FastAPI(
    title="Crafty Modpack Manager",
    version="1.2.0",
    docs_url="/docs",
    redoc_url=None,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Root of the Crafty servers directory as seen *inside* the container.
# docker-compose mounts /DATA/AppData/big-bear-crafty/data/servers → this path.
CRAFTY_SERVERS_ROOT = os.environ.get(
    "CRAFTY_SERVERS_ROOT", "/crafty-servers"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _server_dir(server_id: str) -> pathlib.Path:
    """Return the absolute path to a Crafty server's working directory."""
    return pathlib.Path(CRAFTY_SERVERS_ROOT) / server_id


async def _install_modpack_zip(server_dir: pathlib.Path, download_url: str) -> list[str]:
    """Download *download_url* (a CurseForge modpack zip) and extract the
    relevant directories into *server_dir*.

    A CurseForge server-pack zip typically contains:
      • overrides/   — config, scripts, resourcepacks, etc.
      • mods/        — the actual mod JARs
      • manifest.json

    Some packs bundle everything at root level without an overrides/ folder.
    We handle both layouts:
      1. If overrides/ exists → extract its contents into server_dir root.
      2. mods/ at any level → extract into server_dir/mods/.
      3. config/ at any level → extract into server_dir/config/.
    """
    server_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
        resp = await client.get(download_url)
        resp.raise_for_status()
        zip_bytes = resp.content

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        has_overrides = any(n.startswith("overrides/") for n in names)

        for member in names:
            # Always skip directories themselves
            if member.endswith("/"):
                continue

            if has_overrides:
                # Strip the leading "overrides/" prefix
                if not member.startswith("overrides/"):
                    continue
                rel = member[len("overrides/"):]
            else:
                rel = member

            # Skip empty rel paths (shouldn't happen but be safe)
            if not rel:
                continue

            dest = server_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))
            extracted.append(rel)

    return extracted


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ── CurseForge ────────────────────────────────────────────────────────────────

@app.get("/api/modpacks", summary="Search CurseForge modpacks")
async def search_modpacks(
    q: str = Query(default="", description="Search query"),
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=20, ge=1, le=50),
):
    try:
        return await curseforge.search_modpacks(query=q, page=page, page_size=page_size)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"CurseForge unreachable: {e}")


@app.get("/api/modpacks/{mod_id}", summary="Get modpack details")
async def get_modpack(mod_id: int):
    try:
        return await curseforge.get_modpack(mod_id)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


@app.get("/api/modpacks/{mod_id}/files", summary="List modpack files")
async def get_modpack_files(
    mod_id: int,
    mc_version: str = Query(default=None, description="Filter by Minecraft version"),
):
    try:
        return await curseforge.get_modpack_files(mod_id, mc_version)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


# ── Crafty ────────────────────────────────────────────────────────────────────

@app.get("/api/servers", summary="List Crafty servers")
async def list_servers():
    try:
        return await crafty.list_servers()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Crafty unreachable: {e}")


class DeployRequest(BaseModel):
    server_name: str = Field(..., min_length=1, max_length=64)
    mod_loader:  str = Field(..., description="e.g. forge-installer, fabric, neoforge")
    mc_version:  str = Field(..., description="e.g. 1.20.1")
    mem_min:     int = Field(default=DEFAULT_MEM_MIN, ge=1, le=64)
    mem_max:     int = Field(default=DEFAULT_MEM_MAX, ge=1, le=64)
    port:        int = Field(default=BASE_SERVER_PORT, ge=1024, le=65535)
    # CurseForge identifiers — both required for modpack file injection.
    # mod_id  : the CurseForge project ID (e.g. 238222 for ATM9)
    # file_id : the specific file/release ID chosen by the user
    mod_id:  int | None = Field(default=None, description="CurseForge project ID")
    file_id: int | None = Field(default=None, description="CurseForge file ID")


@app.post("/api/deploy", status_code=201, summary="Deploy modpack as Crafty server")
async def deploy_server(req: DeployRequest):
    """Three-phase deploy:

    1. Ask Crafty to create the server (downloads the mod loader jar).
    2. Poll Crafty until the server directory exists and is in a stopped state.
    3. Download the CurseForge modpack zip and extract it into the server dir
       via the shared volume mount.
    """
    if req.mem_min > req.mem_max:
        raise HTTPException(status_code=422, detail="mem_min cannot exceed mem_max")

    # ── Phase 1: create server in Crafty ─────────────────────────────────────
    try:
        result = await crafty.create_server(
            name=req.server_name,
            mod_loader=req.mod_loader,
            mc_version=req.mc_version,
            mem_min=req.mem_min,
            mem_max=req.mem_max,
            port=req.port,
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Crafty error {e.response.status_code}: {e.response.text}",
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach Crafty: {e}")

    server_id: str | None = (
        result.get("data", {}).get("new_server_id")
        or result.get("data", {}).get("server_id")
        or result.get("new_server_id")
    )

    # If no modpack file was specified, we're done — vanilla/loader-only deploy.
    if not (req.mod_id and req.file_id):
        return {
            "status": "created",
            "server_id": server_id,
            "modpack_installed": False,
            "crafty_response": result,
        }

    if not server_id:
        # Crafty created the server but didn't return an ID — can't inject files.
        return {
            "status": "created_no_id",
            "warning": "Crafty did not return a server ID; modpack files were NOT installed.",
            "crafty_response": result,
        }

    # ── Phase 2: wait for Crafty to finish the jar download ───────────────────
    try:
        server_info = await crafty.poll_server_ready(server_id)
    except TimeoutError as e:
        return {
            "status": "timeout_waiting_for_server",
            "server_id": server_id,
            "warning": str(e) + " — modpack files were NOT installed.",
            "crafty_response": result,
        }
    except httpx.RequestError as e:
        return {
            "status": "poll_error",
            "server_id": server_id,
            "warning": f"Could not poll server state: {e} — modpack files were NOT installed.",
            "crafty_response": result,
        }

    # Crafty stores the server's working directory in the "path" field.
    # It is an absolute path *inside the Crafty container*, which maps to
    # /DATA/AppData/big-bear-crafty/data/servers/<uid> on the host and to
    # /crafty-servers/<uid> inside this container via the shared volume.
    crafty_path = server_info.get("path", "")
    if crafty_path:
        # Crafty returns something like /var/opt/minecraft/crafty/servers/<uid>
        # We only need the final path component (the UID) to build our own path.
        uid_part = pathlib.Path(crafty_path).name
        server_dir = _server_dir(uid_part)
    else:
        # Fallback: use the server_id directly as the directory name.
        server_dir = _server_dir(server_id)

    # ── Phase 3: download and extract modpack into server directory ───────────
    try:
        download_url = await curseforge.get_file_download_url(req.mod_id, req.file_id)
    except (httpx.HTTPStatusError, ValueError) as e:
        return {
            "status": "created_no_modpack_url",
            "server_id": server_id,
            "warning": f"Server created but modpack download URL unavailable: {e}",
            "crafty_response": result,
        }

    try:
        extracted_files = await _install_modpack_zip(server_dir, download_url)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to download modpack zip from CurseForge: {e.response.status_code}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Modpack extraction failed: {e}",
        )

    return {
        "status": "created_with_modpack",
        "server_id": server_id,
        "server_dir": str(server_dir),
        "modpack_installed": True,
        "files_extracted": len(extracted_files),
        "crafty_response": result,
    }
