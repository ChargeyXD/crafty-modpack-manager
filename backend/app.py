from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, os

app = Flask(__name__)
CORS(app)

CRAFTY_BASE  = os.environ.get("CRAFTY_URL",       "https://192.168.68.120:8443")
CRAFTY_TOKEN = os.environ.get("CRAFTY_API_TOKEN",  "")
CF_KEY       = os.environ.get("CURSEFORGE_API_KEY","")
CF_BASE      = "https://api.curseforge.com/v1"
MC_GAME_ID   = 432
MODPACK_CLS  = 4471

def ch():
    return {"Authorization": f"Bearer {CRAFTY_TOKEN}", "Content-Type": "application/json"}

def cfh():
    return {"x-api-key": CF_KEY, "Content-Type": "application/json"}

def cget(path):
    r = requests.get(f"{CRAFTY_BASE}{path}", headers=ch(), verify=False, timeout=15)
    return r.json()

def cpost(path, data):
    r = requests.post(f"{CRAFTY_BASE}{path}", headers=ch(), json=data, verify=False, timeout=30)
    return r.json()

def cdel(path):
    r = requests.delete(f"{CRAFTY_BASE}{path}", headers=ch(), verify=False, timeout=10)
    return r.json()

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/api/config")
def config():
    return jsonify({
        "crafty_url": CRAFTY_BASE,
        "curseforge_configured": bool(CF_KEY),
        "crafty_configured": bool(CRAFTY_TOKEN),
    })

@app.route("/api/modpacks/search")
def search_modpacks():
    q = request.args.get("q","")
    mc_version = request.args.get("mc_version","")
    page = int(request.args.get("page",0))
    params = {
        "gameId": MC_GAME_ID, "classId": MODPACK_CLS,
        "pageSize": 20, "index": page * 20,
        "sortField": 2, "sortOrder": "desc",
    }
    if q: params["searchFilter"] = q
    if mc_version: params["gameVersion"] = mc_version
    r = requests.get(f"{CF_BASE}/mods/search", headers=cfh(), params=params, timeout=15)
    return jsonify(r.json())

@app.route("/api/modpacks/<int:mod_id>")
def get_modpack(mod_id):
    r = requests.get(f"{CF_BASE}/mods/{mod_id}", headers=cfh(), timeout=10)
    return jsonify(r.json())

@app.route("/api/modpacks/<int:mod_id>/files")
def get_modpack_files(mod_id):
    r = requests.get(f"{CF_BASE}/mods/{mod_id}/files", headers=cfh(), timeout=10)
    return jsonify(r.json())

@app.route("/api/minecraft/versions")
def mc_versions():
    r = requests.get(f"{CF_BASE}/minecraft/version", headers=cfh(), timeout=10)
    return jsonify(r.json())

@app.route("/api/servers")
def list_servers():
    return jsonify(cget("/api/v2/servers"))

@app.route("/api/servers/<server_id>")
def get_server(server_id):
    return jsonify(cget(f"/api/v2/servers/{server_id}"))

@app.route("/api/servers/<server_id>/stats")
def server_stats(server_id):
    return jsonify(cget(f"/api/v2/servers/{server_id}/stats"))

@app.route("/api/servers/<server_id>/action/<action>", methods=["POST"])
def server_action(server_id, action):
    return jsonify(cpost(f"/api/v2/servers/{server_id}/action/{action}", {}))

@app.route("/api/servers/<server_id>", methods=["DELETE"])
def delete_server(server_id):
    return jsonify(cdel(f"/api/v2/servers/{server_id}"))

@app.route("/api/servers/create", methods=["POST"])
def create_server():
    body = request.json or {}
    modpack_id = body.get("modpack_id")
    modpack_file_id = body.get("modpack_file_id")
    server_name = body.get("server_name", "Modpack Server")
    min_ram = body.get("min_ram", 1024)
    max_ram = body.get("max_ram", 4096)
    port = body.get("port", 25565)
    mc_version = body.get("mc_version", "1.20.1")
    modloader = body.get("modloader", "forge")

    download_url = ""
    if modpack_id and modpack_file_id:
        dl = requests.get(
            f"{CF_BASE}/mods/{modpack_id}/files/{modpack_file_id}/download-url",
            headers=cfh(), timeout=10
        )
        download_url = dl.json().get("data","")

    if not download_url:
        download_url = body.get("download_url","")

    payload = {
        "name": server_name,
        "min_ram": str(min_ram),
        "max_ram": str(max_ram),
        "port": port,
        "server_ip": "0.0.0.0",
        "server_type": {"selection": modloader, "version": mc_version},
        "create_type": "url_import",
        "import_url": download_url,
        "agree_to_eula": True,
    }
    return jsonify(cpost("/api/v2/servers", payload))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
