# Crafty Modpack Manager

> Browse CurseForge Minecraft modpacks and deploy them as Crafty Controller servers — self-hosted, Shockbyte-style.

## Quick Install on CasaOS

1. **CasaOS → App Store → Custom Install**
2. Paste the `docker-compose.yml` from this repo
3. Fill in the three required environment variables (see table below)
4. Click **Install** — opens at `http://<your-ip>:7800`

---

## Environment Variables

All configuration is done through environment variables in `docker-compose.yml`. **No `.env` file is used** — secrets are injected by CasaOS/Docker at runtime.

| Variable | Required | Default | Description |
|---|---|---|---|
| `CURSEFORGE_API_KEY` | ✅ | — | Free key from [console.curseforge.com](https://console.curseforge.com) |
| `CRAFTY_TOKEN` | ✅ | — | Crafty JWT — Settings ▸ API Tokens |
| `CRAFTY_URL` | ✅ | — | e.g. `https://192.168.68.120:8443` |
| `CRAFTY_VERIFY_SSL` | ❌ | `false` | Set `true` if Crafty has a valid TLS cert |
| `DEFAULT_MEM_MIN` | ❌ | `2` | Default min RAM (GB) for new servers |
| `DEFAULT_MEM_MAX` | ❌ | `6` | Default max RAM (GB) for new servers |
| `BASE_SERVER_PORT` | ❌ | `25565` | Default Minecraft port |

### Where to find your Crafty token

1. Open Crafty Controller UI
2. Navigate to **Settings → API Tokens**
3. Create a new token — it needs **Server Create** permission
4. Copy the JWT value into `CRAFTY_TOKEN`

---

## How the Deploy Works

The deploy button sends the exact payload the Crafty UI itself sends (verified from network capture, HTTP 201 confirmed):

```json
{
  "name": "My Server",
  "roles": [],
  "monitoring_type": "minecraft_java",
  "minecraft_java_monitoring_data": { "host": "127.0.0.1", "port": 25565 },
  "create_type": "minecraft_java",
  "minecraft_java_create_data": {
    "create_type": "download_jar",
    "download_jar_create_data": {
      "category": "mc_java_servers",
      "type": "forge-installer",
      "version": "1.20.1",
      "mem_min": 6,
      "mem_max": 6,
      "server_properties_port": 25565
    }
  }
}
```

Crafty requires `Content-Type: text/plain` (not `application/json`) even though the body is JSON — this matches what the browser sends.

---

## Build & Run Locally

```bash
git clone https://github.com/ChargeyXD/crafty-modpack-manager
cd crafty-modpack-manager

# Set secrets as real environment variables — no .env needed
export CURSEFORGE_API_KEY=your_key
export CRAFTY_TOKEN=your_crafty_jwt
export CRAFTY_URL=https://192.168.68.120:8443
export CRAFTY_VERIFY_SSL=false

docker compose up --build
# Open http://localhost:7800
```

---

## Supported Mod Loaders

| Loader | `type` value sent to Crafty |
|---|---|
| Forge | `forge-installer` |
| Fabric | `fabric` |
| NeoForge | `neoforge` |
| Quilt | `quilt` |
| Vanilla | `vanilla` |

## Project Structure

```
crafty-modpack-manager/
├── Dockerfile
├── docker-compose.yml       ← CasaOS-ready (x-casaos metadata included)
├── requirements.txt
└── app/
    ├── config.py            ← reads env vars, fails fast if missing
    ├── curseforge.py        ← CurseForge API v1 client
    ├── crafty.py            ← Crafty API v2 client (exact HAR schema)
    ├── main.py              ← FastAPI routes + /health endpoint
    └── static/
        └── index.html       ← full UI (search, file picker, deploy panel)
```
