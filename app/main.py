"""FastAPI application — Crafty Modpack Manager."""
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import httpx
from app import curseforge, crafty
from app.config import DEFAULT_MEM_MIN, DEFAULT_MEM_MAX, BASE_SERVER_PORT

app = FastAPI(
    title="Crafty Modpack Manager",
    version="1.1.0",
    docs_url="/docs",
    redoc_url=None,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ── CurseForge ───────────────────────────────────────────────────────────────
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


# ── Crafty ───────────────────────────────────────────────────────────────────
@app.get("/api/servers", summary="List Crafty servers")
async def list_servers():
    try:
        return await crafty.list_servers()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Crafty unreachable: {e}")


class DeployRequest(BaseModel):
    server_name: str            = Field(..., min_length=1, max_length=64)
    mod_loader:  str            = Field(..., description="e.g. forge-installer, fabric, neoforge")
    mc_version:  str            = Field(..., description="e.g. 1.20.1")
    mem_min:     int            = Field(default=DEFAULT_MEM_MIN, ge=1, le=64)
    mem_max:     int            = Field(default=DEFAULT_MEM_MAX, ge=1, le=64)
    port:        int            = Field(default=BASE_SERVER_PORT, ge=1024, le=65535)


@app.post("/api/deploy", status_code=201, summary="Deploy modpack as Crafty server")
async def deploy_server(req: DeployRequest):
    if req.mem_min > req.mem_max:
        raise HTTPException(status_code=422, detail="mem_min cannot exceed mem_max")
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
            detail=f"Crafty error {e.response.status_code}: {e.response.text}",
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach Crafty: {e}")
