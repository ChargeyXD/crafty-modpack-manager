"""FastAPI application — Crafty Modpack Manager."""
import asyncio
import io
import json
import os
import pathlib
import zipfile

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import crafty, curseforge
from app.config import BASE_SERVER_PORT, DEFAULT_MEM_MAX, DEFAULT_MEM_MIN

app = FastAPI(
    title="Crafty Modpack Manager",
    version="1.3.0",
    docs_url="/docs",
    redoc_url=None,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CRAFTY_SERVERS_ROOT = os.environ.get("CRAFTY_SERVERS_ROOT", "/crafty-servers")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _server_dir(server_id: str) -> pathlib.Path:
    return pathlib.Path(CRAFTY_SERVERS_ROOT) / server_id


def _sse(event: str, **data) -> str:
    """Format a single Server-Sent Event line."""
    return f"data: {json.dumps({'event': event, **data})}\n\n"


async def _install_modpack_zip(
    server_dir: pathlib.Path,
    download_url: str,
) -> list[str]:
    """Download the CurseForge modpack zip and extract it into server_dir.

    Handles two layouts:
    - overrides/ present → strip prefix and extract contents to root
    - no overrides/ → extract everything as-is
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
            if member.endswith("/"):
                continue
            rel = member[len("overrides/"):] if has_overrides and member.startswith("overrides/") else (
                None if has_overrides else member
            )
            if not rel:
                continue
            dest = server_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))
            extracted.append(rel)

    return extracted


async def _deploy_stream(req: "DeployRequest"):
    """Generator that yields SSE events for the full deploy pipeline."""

    async def emit(event: str, **kw):
        yield _sse(event, **kw)

    # ── Phase 1: create server ─────────────────────────────────────────
    yield _sse("step", step="create", status="active", msg="Asking Crafty to create server instance...")
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
        yield _sse("error", step="create",
                   msg=f"Crafty returned HTTP {e.response.status_code}: {e.response.text}")
        return
    except httpx.RequestError as e:
        yield _sse("error", step="create", msg=f"Cannot reach Crafty: {e}")
        return

    server_id: str | None = (
        result.get("data", {}).get("new_server_id")
        or result.get("data", {}).get("server_id")
        or result.get("new_server_id")
    )
    yield _sse("step", step="create", status="done",
               msg=f"Server instance created (id: {server_id or 'unknown'})")

    # No modpack — done early
    if not (req.mod_id and req.file_id):
        yield _sse("done", server_id=server_id, modpack_installed=False,
                   files_extracted=0,
                   msg="Server created (no modpack selected).")
        return

    if not server_id:
        yield _sse("error", step="create",
                   msg="Crafty did not return a server ID — cannot inject modpack files. "
                       "Check Crafty logs for details.")
        return

    # ── Phase 2: poll until jar download finishes ────────────────────────
    yield _sse("step", step="wait", status="active",
               msg="Waiting for Crafty to finish the mod loader installation...")
    try:
        server_info = await crafty.poll_server_ready(server_id)
    except TimeoutError as e:
        yield _sse("error", step="wait", msg=str(e))
        return
    except httpx.RequestError as e:
        yield _sse("error", step="wait", msg=f"Poll failed: {e}")
        return

    crafty_path = server_info.get("path", "")
    uid_part = pathlib.Path(crafty_path).name if crafty_path else server_id
    server_dir = _server_dir(uid_part)
    yield _sse("step", step="wait", status="done",
               msg=f"Mod loader ready. Server directory: {server_dir}")

    # Diagnose volume mount early so the user knows immediately if it's missing
    root_exists = pathlib.Path(CRAFTY_SERVERS_ROOT).exists()
    dir_exists = server_dir.exists()
    yield _sse("log",
               msg=f"Volume check: CRAFTY_SERVERS_ROOT={CRAFTY_SERVERS_ROOT} "
                   f"exists={root_exists} | server_dir={server_dir} exists={dir_exists}")
    if not root_exists:
        yield _sse("error", step="wait",
                   msg=f"Volume not mounted! '{CRAFTY_SERVERS_ROOT}' does not exist inside "
                       "the container. Make sure docker-compose.yml has the volume mount:"
                       " /DATA/AppData/big-bear-crafty/data/servers:/crafty-servers")
        return

    # ── Phase 3: download modpack zip ─────────────────────────────────
    yield _sse("step", step="download", status="active",
               msg=f"Fetching modpack download URL from CurseForge (mod {req.mod_id} / file {req.file_id})...")
    try:
        download_url = await curseforge.get_file_download_url(req.mod_id, req.file_id)
    except (httpx.HTTPStatusError, ValueError) as e:
        yield _sse("error", step="download",
                   msg=f"Could not get download URL: {e}. "
                       "This file may be client-only or require the CurseForge launcher.")
        return

    yield _sse("log", msg=f"Download URL: {download_url}")
    yield _sse("step", step="download", status="active",
               msg="Downloading modpack zip (this can take a minute for large packs)...")

    # ── Phase 4: extract ─────────────────────────────────────────────
    try:
        extracted_files = await _install_modpack_zip(server_dir, download_url)
    except httpx.HTTPStatusError as e:
        yield _sse("error", step="download",
                   msg=f"Download failed (HTTP {e.response.status_code}). "
                       f"URL: {download_url}")
        return
    except zipfile.BadZipFile:
        yield _sse("error", step="extract",
                   msg="The downloaded file is not a valid zip. "
                       "This modpack may use a custom installer format not supported yet.")
        return
    except Exception as e:
        yield _sse("error", step="extract", msg=f"Extraction error: {e}")
        return

    yield _sse("step", step="download", status="done",
               msg=f"Downloaded and extracted {len(extracted_files)} files.")
    yield _sse("step", step="extract", status="done",
               msg=f"Modpack installed into {server_dir}")
    yield _sse("done", server_id=server_id,
               modpack_installed=True,
               files_extracted=len(extracted_files),
               server_dir=str(server_dir),
               msg=f"✓ Done! {len(extracted_files)} files written to Crafty server.")


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
    server_name: str     = Field(..., min_length=1, max_length=64)
    mod_loader:  str     = Field(...)
    mc_version:  str     = Field(...)
    mem_min:     int     = Field(default=DEFAULT_MEM_MIN, ge=1, le=64)
    mem_max:     int     = Field(default=DEFAULT_MEM_MAX, ge=1, le=64)
    port:        int     = Field(default=BASE_SERVER_PORT, ge=1024, le=65535)
    mod_id:      int | None = Field(default=None)
    file_id:     int | None = Field(default=None)


@app.post("/api/deploy", summary="Deploy modpack as Crafty server (SSE stream)")
async def deploy_server(req: DeployRequest):
    """Streams Server-Sent Events so the frontend can show live progress."""
    if req.mem_min > req.mem_max:
        raise HTTPException(status_code=422, detail="mem_min cannot exceed mem_max")
    return StreamingResponse(
        _deploy_stream(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )
