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

def _cf(path, **kwargs):
    url = f"{CF_BASE}{path}"
    try:
        r = requests.get(url, headers=_cfh(), timeout=15, **kwargs)
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


# Health / Config
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


# CurseForge
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
    data, e = _cf("/mods/search", params=params)
    if e: return err(e["error"], e["detail"], 502)
    return ok(data.get("data", []))

@app.route("/api/modpacks/<int:mod_id>")
def get_modpack(mod_id):
    data, e = _cf(f"/mods/{mod_id}")
    if e: return err(e["error"], e["detail"], 502)
    return ok(data.get("data", {}))

@app.route("/api/modpacks/<int:mod_id>/files")
def get_modpack_files(mod_id):
    data, e = _cf(f"/mods/{mod_id}/files", params={"pageSize": 50, "sortOrder": "desc"})
    if e: return err(e["error"], e["detail"], 502)
    files = data.get("data", [])
    enriched = []
    for f in files:
        gv = f.get("gameVersions", [])
        enriched.append({
            **f,
            "_loader":     detect_loader(f.get("fileName", ""), gv),
            "_mc_version": pick_mc_version(gv),
        })
    return ok(enriched)

@app.route("/api/modpacks/<int:mod_id>/files/<int:file_id>/download-url")
def get_download_url(mod_id, file_id):
    data, e = _cf(f"/mods/{mod_id}/files/{file_id}/download-url")
    if e: return err(e["error"], e["detail"], 502)
    return ok(data.get("data", ""))


# Crafty servers
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
        dl, e = _cf(f"/mods/{modpack_id}/files/{modpack_file_id}/download-url")
        if e:
            return err("Could not fetch download URL from CurseForge", e["detail"], 502)
        download_url = dl.get("data", "") or ""

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
    logging.info("Creating Crafty server: %s loader=%s mc=%s", server_name, modloader, mc_version)

    data, e = _crafty("POST", "/api/v2/servers", json=payload)
    if e: return err(e["error"], e["detail"], 502)
    return ok(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
