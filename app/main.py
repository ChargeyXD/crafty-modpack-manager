"""FastAPI application — Crafty Modpack Manager."""
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx
from app import curseforge, crafty
from app.config import DEFAULT_MEM_MIN, DEFAULT_MEM_MAX, BASE_SERVER_PORT
import os

app = FastAPI(title="Crafty Modpack Manager", version="1.0.0")

# ─── Static frontend ────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ─── CurseForge routes ───────────────────────────────────────────────────────
@app.get("/api/modpacks")
async def search_modpacks(
    q: str = Query(default="", description="Search query"),
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=20, ge=1, le=50),
):
    try:
        return await curseforge.search_modpacks(query=q, page=page, page_size=page_size)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


@app.get("/api/modpacks/{mod_id}")
async def get_modpack(mod_id: int):
    try:
        return await curseforge.get_modpack(mod_id)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


@app.get("/api/modpacks/{mod_id}/files")
async def get_modpack_files(mod_id: int, mc_version: str = Query(default=None)):
    try:
        return await curseforge.get_modpack_files(mod_id, mc_version)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


# ─── Crafty routes ────────────────────────────────────────────────────────────
@app.get("/api/servers")
async def list_servers():
    try:
        return await crafty.list_servers()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))


class DeployRequest(BaseModel):
    server_name: str
    mod_id: int
    file_id: int
    mod_loader: str          # e.g. "forge-installer", "fabric", "vanilla"
    mc_version: str          # e.g. "1.20.1"
    mem_min: int = DEFAULT_MEM_MIN
    mem_max: int = DEFAULT_MEM_MAX
    port: int = BASE_SERVER_PORT


@app.post("/api/deploy")
async def deploy_server(req: DeployRequest):
    """
    Deploy a modpack as a new Crafty server.
    Uses the exact schema captured from the Crafty UI (HAR trace).
    """
    try:
        result = await crafty.create_server(
            name=req.server_name,
            mod_loader=req.mod_loader,
            mc_version=req.mc_version,
            mem_min=req.mem_min,
            mem_max=req.mem_max,
            port=req.port,
        )
        return {"status": "created", "crafty_response": result}
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Crafty error: {e.response.text}",
        )
