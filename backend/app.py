import os
import re
import logging
import urllib3
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

CRAFTY_BASE  = os.environ.get("CRAFTY_URL",        "https://192.168.68.120:8443").rstrip("/")
CRAFTY_TOKEN = os.environ.get("CRAFTY_API_TOKEN",  "")
CF_KEY       = os.environ.get("CURSEFORGE_API_KEY","")
CF_BASE      = "https://api.curseforge.com/v1"
MC_GAME_ID   = 432
MODPACK_CLS  = 4471


def _ch():
    return {"Authorization": f"Bearer {CRAFTY_TOKEN}", "Content-Type": "application/json"}

def _cfh():
    return {"x-api-key": CF_KEY, "Content-Type": "application/json"}

def _crafty(method, path, **kwargs):
    url = f"{CRAFTY_BASE}{path}"
    try:
        r = requests.request(method, url, headers=_ch(), verify=False, timeout=20, **kwargs)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.HTTPError:
        return None, {"error": f"Crafty HTTP {r.status_code}", "detail": r.text[:400]}
    except requests.exceptions.RequestException as e:
        return None, {"error": "Could not reach Crafty", "detail": str(e)}

def _cf_get(path, **kwargs):
    url = f"{CF_BASE}{path}"
    try:
        r = requests.get(url, headers=_cfh(), timeout=15, **kwargs)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.HTTPError:
        return None, {"error": f"CurseForge HTTP {r.status_code}", "detail": r.text[:400]}
    except requests.exceptions.RequestException as e:
        return None, {"error": "Could not reach CurseForge", "detail": str(e)}

def _cf_post(path, **kwargs):
    url = f"{CF_BASE}{path}"
    try:
        r = requests.post(url, headers=_cfh(), timeout=15, **kwargs)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.HTTPError:
        return None, {"error": f"CurseForge HTTP {r.status_code}", "detail": r.text[:400]}
    except requests.exceptions.RequestException as e:
        return None, {"error": "Could not reach CurseForge", "detail": str(e)}

def ok(data):
    return jsonify({"status": "ok", "data": data})

def err(msg, detail="", code=500):
    return jsonify({"status": "error", "error": msg, "detail": detail}), code


def _cdn_url(file_id: int, file_name: str) -> str:
    """
    Build the forgecdn.net fallback URL for a file whose downloadUrl is null.
    CurseForge CDN path format: /files/{first4digits}/{remaining_no_leading_zeros}/{fileName}
    e.g. fileId=6262770 → /files/6262/770/filename.zip
         fileId=4567089 → /files/4567/89/filename.zip  (leading zero stripped)
    """
    fid = str(file_id)
    part1 = fid[:4]
    part2 = str(int(fid[4:]))  # int() strips any leading zeros
    return f"https://edge.forgecdn.net/files/{part1}/{part2}/{file_name}"


_LOADER_RE = re.compile(r"\b(forge|fabric|neoforge|neo|quilt)\b", re.IGNORECASE)
def detect_loader(filename, game_versions):
    for v in (game_versions or []):
        m = _LOADER_RE.search(v)
        if m:
            raw = m.group(1).lower()
            return "neoforge" if raw == "neo" else raw
    m = _LOADER_RE.search(filename or "")
    if m:
        raw = m.group(1).lower()
        return "neoforge" if raw == "neo" else raw
    return "forge"

_MC_VER_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")
def pick_mc_version(versions):
    for v in (versions or []):
        if _MC_VER_RE.match(v):
            return v
    return ""

def enrich_files(files):
    """
    Enrich file entries with loader/version detection and resolve any null
    downloadUrl values using the forgecdn.net CDN fallback URL.
    Files with isServerPack=True are sorted to the top.
    """
    enriched = []
    for f in files:
        gv = f.get("gameVersions", [])
        file_id   = f.get("id", 0)
        file_name = f.get("fileName", "modpack.zip")

        # Resolve download URL — null means author disabled redistribution via API
        # but the file is still publicly hosted on the CDN
        dl_url = f.get("downloadUrl") or ""
        if not dl_url and file_id:
            dl_url = _cdn_url(file_id, file_name)
            logging.info("Built CDN fallback URL for file %d: %s", file_id, dl_url)

        enriched.append({
            **f,
            "downloadUrl":   dl_url,
            "_loader":       detect_loader(file_name, gv),
            "_mc_version":   pick_mc_version(gv),
        })

    # Server packs first, then by release type (1=release preferred)
    enriched.sort(key=lambda x: (not x.get("isServerPack", False), x.get("releaseType", 9)))
    return enriched


# ── Health / Config ──────────────────────────────────────────────────────────

@app.route("/health")
def health():
    crafty_ok = False
    if CRAFTY_TOKEN:
        data, e = _crafty("GET", "/api/v2/servers")
        crafty_ok = e is None
    return jsonify({
        "status": "ok",
        "crafty_reachable": crafty_ok,
        "curseforge_configured": bool(CF_KEY),
        "crafty_configured": bool(CRAFTY_TOKEN),
    })

@app.route("/api/config")
def config():
    return jsonify({
        "crafty_url": CRAFTY_BASE,
        "curseforge_configured": bool(CF_KEY),
        "crafty_configured": bool(CRAFTY_TOKEN),
    })


# ── CurseForge ───────────────────────────────────────────────────────────────

@app.route("/api/modpacks/search")
def search_modpacks():
    q          = request.args.get("q", "").strip()
    mc_version = request.args.get("mc_version", "").strip()
    page       = max(0, int(request.args.get("page", 0)))
    params = {
        "gameId": MC_GAME_ID, "classId": MODPACK_CLS,
        "pageSize": 20, "index": page * 20,
        "sortField": 2, "sortOrder": "desc",
    }
    if q:          params["searchFilter"] = q
    if mc_version: params["gameVersion"]  = mc_version
    data, e = _cf_get("/mods/search", params=params)
    if e: return err(e["error"], e["detail"], 502)
    return ok(data.get("data", []))

@app.route("/api/modpacks/<int:mod_id>")
def get_modpack(mod_id):
    data, e = _cf_get(f"/mods/{mod_id}")
    if e: return err(e["error"], e["detail"], 502)
    return ok(data.get("data", {}))

@app.route("/api/modpacks/<int:mod_id>/files")
def get_modpack_files(mod_id):
    """
    CurseForge often returns 403 on GET /mods/{id}/files for restricted packs.
    Strategy:
      1. Try GET /mods/{id}/files (standard)
      2. On 403/error, fall back to the latestFiles array from GET /mods/{id}
      3. Also try POST /mods/files with the file IDs from latestFilesIndexes
    downloadUrl values of null are resolved via _cdn_url() in enrich_files().
    """
    # Check distribution rights — warn but do not block (CDN URLs still work)
    mod_data, mod_err = _cf_get(f"/mods/{mod_id}")
    allow_dist = True
    mod = {}
    if not mod_err:
        mod = mod_data.get("data", {})
        allow_dist = mod.get("allowModDistribution", True)
        if allow_dist is False:
            logging.warning("Mod %d has allowModDistribution=false; downloadUrls will be null, using CDN fallback", mod_id)

    # Strategy 1: standard files endpoint
    data, e = _cf_get(f"/mods/{mod_id}/files", params={"pageSize": 50, "sortOrder": "desc"})
    if not e:
        files = data.get("data", [])
        if files:
            return ok(enrich_files(files))

    # Strategy 2: pull latestFiles from the mod detail object (always returned)
    if mod_err:
        mod_data, mod_err = _cf_get(f"/mods/{mod_id}")
        if mod_err:
            orig = e or mod_err
            return err(orig["error"], orig["detail"], 502)
        mod = mod_data.get("data", {})

    latest_files = mod.get("latestFiles", [])
    if latest_files:
        logging.info("Used latestFiles fallback for mod %d (%d files)", mod_id, len(latest_files))
        return ok(enrich_files(latest_files))

    # Strategy 3: POST /mods/files with IDs from latestFilesIndexes
    indexes  = mod.get("latestFilesIndexes", [])
    file_ids = list({idx["fileId"] for idx in indexes if "fileId" in idx})
    if file_ids:
        batch, batch_err = _cf_post("/mods/files", json={"fileIds": file_ids[:50]})
        if not batch_err:
            files = batch.get("data", [])
            if files:
                logging.info("Used POST /mods/files fallback for mod %d", mod_id)
                return ok(enrich_files(files))

    return ok([])

@app.route("/api/modpacks/<int:mod_id>/files/<int:file_id>/download-url")
def get_download_url(mod_id, file_id):
    # Try the dedicated endpoint first
    data, e = _cf_get(f"/mods/{mod_id}/files/{file_id}/download-url")
    if not e:
        url = data.get("data", "")
        if url:
            return ok(url)

    # Fallback: get the file detail and use downloadUrl or build CDN URL
    fdata, fe = _cf_get(f"/mods/{mod_id}/files/{file_id}")
    if not fe:
        f = fdata.get("data", {})
        dl = f.get("downloadUrl") or ""
        if dl:
            return ok(dl)
        # downloadUrl is null — build CDN fallback URL
        cdn = _cdn_url(file_id, f.get("fileName", "modpack.zip"))
        logging.info("Resolved CDN fallback for file %d: %s", file_id, cdn)
        return ok(cdn)

    return err(e["error"] if e else fe["error"], "", 502)


# ── Crafty servers ────────────────────────────────────────────────────────────

@app.route("/api/servers")
def list_servers():
    data, e = _crafty("GET", "/api/v2/servers")
    if e: return err(e["error"], e["detail"], 502)
    return ok(data.get("data", data))

@app.route("/api/servers/<server_id>")
def get_server(server_id):
    data, e = _crafty("GET", f"/api/v2/servers/{server_id}")
    if e: return err(e["error"], e["detail"], 502)
    return ok(data.get("data", data))

@app.route("/api/servers/<server_id>/stats")
def server_stats(server_id):
    data, e = _crafty("GET", f"/api/v2/servers/{server_id}/stats")
    if e: return err(e["error"], e["detail"], 502)
    return ok(data.get("data", data))

@app.route("/api/servers/<server_id>/action/<action>", methods=["POST"])
def server_action(server_id, action):
    if action not in ("start", "stop", "restart", "kill"):
        return err("Invalid action", code=400)
    data, e = _crafty("POST", f"/api/v2/servers/{server_id}/action/{action}")
    if e: return err(e["error"], e["detail"], 502)
    return ok(data)

@app.route("/api/servers/<server_id>", methods=["DELETE"])
def delete_server(server_id):
    data, e = _crafty("DELETE", f"/api/v2/servers/{server_id}")
    if e: return err(e["error"], e["detail"], 502)
    return ok(data)

@app.route("/api/servers/create", methods=["POST"])
def create_server():
    body = request.get_json(force=True, silent=True) or {}
    modpack_id      = body.get("modpack_id")
    modpack_file_id = body.get("modpack_file_id")
    server_name     = (body.get("server_name") or "Modpack Server").strip()
    min_ram         = max(512,  int(body.get("min_ram", 1024)))
    max_ram         = max(1024, int(body.get("max_ram", 4096)))
    port            = int(body.get("port", 25565))
    mc_version      = (body.get("mc_version") or "1.20.1").strip()
    modloader       = (body.get("modloader") or "forge").strip().lower()

    if modloader not in ("forge", "fabric", "neoforge", "quilt"):
        modloader = "forge"

    download_url = ""
    if modpack_id and modpack_file_id:
        # Try dedicated endpoint
        dl, e = _cf_get(f"/mods/{modpack_id}/files/{modpack_file_id}/download-url")
        if not e:
            download_url = dl.get("data", "") or ""

        if not download_url:
            # Get file detail and resolve URL
            fdata, _ = _cf_get(f"/mods/{modpack_id}/files/{modpack_file_id}")
            if fdata:
                f = fdata.get("data", {})
                download_url = f.get("downloadUrl") or ""
                if not download_url:
                    # null downloadUrl — build CDN fallback with correct segment math
                    download_url = _cdn_url(modpack_file_id, f.get("fileName", "modpack.zip"))
                    logging.info("Using CDN fallback for server creation, file %d: %s",
                                 modpack_file_id, download_url)

    if not download_url:
        download_url = (body.get("download_url") or "").strip()

    if not download_url:
        return err("No download URL could be resolved for this modpack file.", code=400)

    payload = {
        "name": server_name,
        "min_ram": str(min_ram),
        "max_ram": str(max_ram),
        "port": port,
        "server_ip": "0.0.0.0",
        "server_type": {
            "selection": modloader,
            "version": mc_version,
        },
        "create_type": "url_import",
        "import_url": download_url,
        "agree_to_eula": True,
    }
    logging.info("Creating Crafty server: %s loader=%s mc=%s url=%s",
                 server_name, modloader, mc_version, download_url[:80])

    data, e = _crafty("POST", "/api/v2/servers", json=payload)
    if e: return err(e["error"], e["detail"], 502)
    return ok(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
