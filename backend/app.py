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

CRAFTY_BASE  = os.environ.get("CRAFTY_URL",         "https://192.168.68.120:8443").rstrip("/")
CRAFTY_TOKEN = os.environ.get("CRAFTY_API_TOKEN",   "")
CF_KEY       = os.environ.get("CURSEFORGE_API_KEY", "")
CF_BASE      = "https://api.curseforge.com/v1"
MC_GAME_ID   = 432
MODPACK_CLS  = 4471

# Startup diagnostics — visible in `docker logs crafty-modpack-manager`
if not CF_KEY:
    logging.warning("CURSEFORGE_API_KEY is not set — all CurseForge calls will return 403")
else:
    logging.info("CurseForge API key loaded (len=%d, prefix=%s...)", len(CF_KEY), CF_KEY[:6])

if not CRAFTY_TOKEN:
    logging.warning("CRAFTY_API_TOKEN is not set — Crafty calls will fail")


def _ch():
    return {"Authorization": f"Bearer {CRAFTY_TOKEN}", "Content-Type": "application/json"}

def _cfh():
    return {"x-api-key": CF_KEY, "Accept": "application/json", "Content-Type": "application/json"}

def _crafty(method, path, **kwargs):
    url = f"{CRAFTY_BASE}{path}"
    try:
        r = requests.request(method, url, headers=_ch(), verify=False, timeout=20, **kwargs)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.HTTPError:
        logging.error("Crafty %s %s -> HTTP %d: %s", method, path, r.status_code, r.text[:600])
        return None, {"error": f"Crafty HTTP {r.status_code}", "detail": r.text[:600]}
    except requests.exceptions.RequestException as e:
        return None, {"error": "Could not reach Crafty", "detail": str(e)}

def _cf_get(path, **kwargs):
    if not CF_KEY:
        return None, {"error": "CurseForge API key not configured",
                      "detail": "Set the CURSEFORGE_API_KEY environment variable and restart."}
    url = f"{CF_BASE}{path}"
    try:
        r = requests.get(url, headers=_cfh(), timeout=15, **kwargs)
        if r.status_code == 403:
            logging.error("CurseForge 403 on GET %s — key prefix: %s | response: %s",
                          path, CF_KEY[:6] if CF_KEY else "(empty)", r.text[:200])
            return None, {
                "error": "CurseForge returned 403 Forbidden",
                "detail": ("Your API key is invalid, expired, or was not sent correctly. "
                           "Re-generate it at https://console.curseforge.com/ and update "
                           f"CURSEFORGE_API_KEY in your docker-compose.yml. Raw: {r.text[:200]}")
            }
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.HTTPError:
        return None, {"error": f"CurseForge HTTP {r.status_code}", "detail": r.text[:400]}
    except requests.exceptions.ConnectionError as e:
        logging.error("DNS/connection failure reaching api.curseforge.com: %s", e)
        return None, {"error": "Could not connect to api.curseforge.com",
                      "detail": f"DNS failure — add dns: [8.8.8.8] to docker-compose.yml. {e}"}
    except requests.exceptions.RequestException as e:
        return None, {"error": "Could not reach CurseForge", "detail": str(e)}

def _cf_post(path, **kwargs):
    if not CF_KEY:
        return None, {"error": "CurseForge API key not configured",
                      "detail": "Set the CURSEFORGE_API_KEY environment variable and restart."}
    url = f"{CF_BASE}{path}"
    try:
        r = requests.post(url, headers=_cfh(), timeout=15, **kwargs)
        if r.status_code == 403:
            logging.error("CurseForge 403 on POST %s — key prefix: %s | response: %s",
                          path, CF_KEY[:6] if CF_KEY else "(empty)", r.text[:200])
            return None, {
                "error": "CurseForge returned 403 Forbidden",
                "detail": f"Re-generate at https://console.curseforge.com/. Raw: {r.text[:200]}"
            }
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.HTTPError:
        return None, {"error": f"CurseForge HTTP {r.status_code}", "detail": r.text[:400]}
    except requests.exceptions.ConnectionError as e:
        return None, {"error": "Could not connect to api.curseforge.com",
                      "detail": f"DNS failure — add dns: [8.8.8.8] to docker-compose.yml. {e}"}
    except requests.exceptions.RequestException as e:
        return None, {"error": "Could not reach CurseForge", "detail": str(e)}

def ok(data):
    return jsonify({"status": "ok", "data": data})

def err(msg, detail="", code=500):
    return jsonify({"status": "error", "error": msg, "detail": detail}), code


def _cdn_url(file_id: int, file_name: str) -> str:
    fid   = str(file_id)
    part1 = fid[:4]
    part2 = str(int(fid[4:]))
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
    enriched = []
    for f in files:
        gv        = f.get("gameVersions", [])
        file_id   = f.get("id", 0)
        file_name = f.get("fileName", "modpack.zip")
        dl_url    = f.get("downloadUrl") or ""
        if not dl_url and file_id:
            dl_url = _cdn_url(file_id, file_name)
            logging.info("Built CDN fallback URL for file %d: %s", file_id, dl_url)
        enriched.append({
            **f,
            "downloadUrl": dl_url,
            "_loader":     detect_loader(file_name, gv),
            "_mc_version": pick_mc_version(gv),
        })
    enriched.sort(key=lambda x: (not x.get("isServerPack", False), x.get("releaseType", 9)))
    return enriched


# ── Health / Config ──────────────────────────────────────────────────────────

@app.route("/health")
def health():
    crafty_ok = False
    cf_ok     = False

    if CRAFTY_TOKEN:
        data, e = _crafty("GET", "/api/v2/servers")
        crafty_ok = e is None

    if CF_KEY:
        data, e = _cf_get("/games/432")
        cf_ok = e is None
        if e:
            logging.warning("CurseForge health check failed: %s — %s", e["error"], e.get("detail", ""))

    return jsonify({
        "status":                  "ok",
        "crafty_reachable":        crafty_ok,
        "curseforge_reachable":    cf_ok,
        "curseforge_configured":   bool(CF_KEY),
        "crafty_configured":       bool(CRAFTY_TOKEN),
    })

@app.route("/api/config")
def config():
    return jsonify({
        "crafty_url":            CRAFTY_BASE,
        "curseforge_configured": bool(CF_KEY),
        "crafty_configured":     bool(CRAFTY_TOKEN),
    })


# ── CurseForge ───────────────────────────────────────────────────────────────

@app.route("/api/modpacks/search")
def search_modpacks():
    q          = request.args.get("q", "").strip()
    mc_version = request.args.get("mc_version", "").strip()
    page       = max(0, int(request.args.get("page", 0)))
    params = {
        "gameId":    MC_GAME_ID,
        "classId":   MODPACK_CLS,
        "pageSize":  20,
        "index":     page * 20,
        "sortField": 2,
        "sortOrder": "desc",
    }
    if q:          params["searchFilter"] = q
    if mc_version: params["gameVersion"]  = mc_version
    data, e = _cf_get("/mods/search", params=params)
    if e: return err(e["error"], e.get("detail", ""), 502)
    return ok(data.get("data", []))

@app.route("/api/modpacks/<int:mod_id>")
def get_modpack(mod_id):
    data, e = _cf_get(f"/mods/{mod_id}")
    if e: return err(e["error"], e.get("detail", ""), 502)
    return ok(data.get("data", {}))

@app.route("/api/modpacks/<int:mod_id>/files")
def get_modpack_files(mod_id):
    first_error = None

    mod_data, mod_err = _cf_get(f"/mods/{mod_id}")
    if mod_err:
        return err(mod_err["error"], mod_err.get("detail", ""), 502)

    mod = mod_data.get("data", {})
    if mod.get("allowModDistribution") is False:
        logging.warning("Mod %d has allowModDistribution=false — using CDN fallback", mod_id)

    # Strategy 1
    data, e = _cf_get(f"/mods/{mod_id}/files", params={"pageSize": 50, "sortOrder": "desc"})
    if not e:
        files = data.get("data", [])
        if files:
            return ok(enrich_files(files))
    else:
        first_error = e
        logging.warning("Strategy 1 failed for mod %d: %s", mod_id, e["error"])

    # Strategy 2: latestFiles
    latest_files = mod.get("latestFiles", [])
    if latest_files:
        logging.info("Strategy 2 (latestFiles) for mod %d (%d files)", mod_id, len(latest_files))
        return ok(enrich_files(latest_files))

    # Strategy 3: POST /mods/files
    indexes  = mod.get("latestFilesIndexes", [])
    file_ids = list({idx["fileId"] for idx in indexes if "fileId" in idx})
    if file_ids:
        batch, batch_err = _cf_post("/mods/files", json={"fileIds": file_ids[:50]})
        if not batch_err:
            files = batch.get("data", [])
            if files:
                logging.info("Strategy 3 (POST /mods/files) for mod %d", mod_id)
                return ok(enrich_files(files))
        else:
            first_error = first_error or batch_err

    if first_error:
        return err(first_error["error"], first_error.get("detail", ""), 502)
    return ok([])

@app.route("/api/modpacks/<int:mod_id>/files/<int:file_id>/download-url")
def get_download_url(mod_id, file_id):
    data, e = _cf_get(f"/mods/{mod_id}/files/{file_id}/download-url")
    if not e:
        url = data.get("data", "")
        if url:
            return ok(url)

    fdata, fe = _cf_get(f"/mods/{mod_id}/files/{file_id}")
    if not fe:
        f  = fdata.get("data", {})
        dl = f.get("downloadUrl") or ""
        if dl:
            return ok(dl)
        cdn = _cdn_url(file_id, f.get("fileName", "modpack.zip"))
        return ok(cdn)

    return err((e or fe)["error"], (e or fe).get("detail", ""), 502)


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


# ── Crafty server creation ────────────────────────────────────────────────────
#
# Crafty v2 POST /api/v2/servers expects a FLAT payload:
#
#   {
#     "name":              "My Server",
#     "min_ram":           "2048M",
#     "max_ram":           "4096M",
#     "port":              25565,
#     "server_ip":         "0.0.0.0",
#     "server_jar_path":   "server.jar",          # relative exe name
#     "executable":        "server.jar",
#     "execution_command": "java -Xms{MIN}M -Xmx{MAX}M -jar server.jar",
#     "type":              "forge",                # flat string, NOT nested
#     "server_version":    "1.21.1",
#     "create_type":       "url_import",
#     "import_url":        "https://...",
#     "agree_to_eula":     true
#   }
#
# Fields the old code sent that Crafty rejects with 400:
#   - "server_type": { ... }   (should be flat "type" + "server_version")
#   - min_ram/max_ram as bare integers (must be strings with M suffix)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/servers/create", methods=["POST"])
def create_server():
    body            = request.get_json(force=True, silent=True) or {}
    modpack_id      = body.get("modpack_id")
    modpack_file_id = body.get("modpack_file_id")
    server_name     = (body.get("server_name") or "Modpack Server").strip()
    min_ram         = max(512,  int(body.get("min_ram",  1024)))
    max_ram         = max(1024, int(body.get("max_ram",  4096)))
    port            = int(body.get("port", 25565))
    mc_version      = (body.get("mc_version") or "1.20.1").strip()
    modloader       = (body.get("modloader") or "forge").strip().lower()

    if modloader not in ("forge", "fabric", "neoforge", "quilt"):
        modloader = "forge"

    # ── Resolve download URL ─────────────────────────────────────────────────
    download_url = ""
    if modpack_id and modpack_file_id:
        dl, e = _cf_get(f"/mods/{modpack_id}/files/{modpack_file_id}/download-url")
        if not e:
            download_url = dl.get("data", "") or ""
        if not download_url:
            fdata, fe = _cf_get(f"/mods/{modpack_id}/files/{modpack_file_id}")
            if fe:
                return err(fe["error"], fe.get("detail", ""), 502)
            f = fdata.get("data", {})
            download_url = f.get("downloadUrl") or ""
            if not download_url:
                download_url = _cdn_url(modpack_file_id, f.get("fileName", "modpack.zip"))
                logging.info("CDN fallback for file %d: %s", modpack_file_id, download_url)

    if not download_url:
        download_url = (body.get("download_url") or "").strip()

    if not download_url:
        return err("No download URL could be resolved for this modpack file.", code=400)

    # ── Build the execution command Crafty expects ───────────────────────────
    jar_name  = "server.jar"
    exec_cmd  = (
        f"java -Xms{min_ram}M -Xmx{max_ram}M "
        "-XX:+UseG1GC -XX:+ParallelRefProcEnabled "
        f"-jar {jar_name} nogui"
    )

    # ── Crafty v2 flat payload ───────────────────────────────────────────────
    # min_ram / max_ram MUST be strings with M suffix, NOT bare integers.
    payload = {
        "name":              server_name,
        "min_ram":           f"{min_ram}M",
        "max_ram":           f"{max_ram}M",
        "port":              port,
        "server_ip":         "0.0.0.0",
        "server_jar_path":   jar_name,
        "executable":        jar_name,
        "execution_command": exec_cmd,
        "type":              modloader,        # flat string
        "server_version":    mc_version,       # flat string
        "create_type":       "url_import",
        "import_url":        download_url,
        "agree_to_eula":     True,
    }

    logging.info(
        "Creating Crafty server — name=%s type=%s mc=%s ram=%sM-%sM port=%d url=%s",
        server_name, modloader, mc_version, min_ram, max_ram, port, download_url[:80]
    )
    logging.info("Crafty payload: %s", payload)

    data, e = _crafty("POST", "/api/v2/servers", json=payload)
    if e: return err(e["error"], e["detail"], 502)
    return ok(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
