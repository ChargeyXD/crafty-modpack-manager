# Crafty Modpack Manager

> Self-hosted Minecraft modpack deployment panel for [CasaOS](https://casaos.io), integrating [Crafty Controller](https://craftycontrol.com) with the [CurseForge API](https://docs.curseforge.com).

Provides a Shockbyte-style UI to browse CurseForge modpacks, pick a server file/build, and deploy it directly as a Crafty server instance — all from your browser.

---

## Features

- **Modpack catalog** — search and browse CurseForge Minecraft modpacks with thumbnail previews
- **Smart file picker** — lists installable server files with auto-detected MC version and mod loader
- **One-click deploy** — sends a properly formed server creation request to Crafty Controller v2 API
- **Server management** — start/stop/restart existing Crafty servers from the panel
- **Live status** — shows Crafty and CurseForge connectivity at a glance
- **CasaOS native** — installs as a custom app via docker-compose manifest

---

## Architecture

```
Browser → Nginx (port 7800) ─┬─ /api/* → Flask (127.0.0.1:5000) → Crafty API v2
                              │                                    → CurseForge API
                              └─ /* → static frontend (SPA)
```

All services run in a single Docker container (nginx + gunicorn/Flask).

---

## Quick start (CasaOS)

1. In CasaOS, go to **App Store → Custom Install**.
2. Paste the contents of `docker-compose.yml`.
3. Replace the two placeholder env vars:
   - `CRAFTY_API_TOKEN` — generate in Crafty → Settings → Users → your user → API Keys tab
   - `CURSEFORGE_API_KEY` — generate at https://console.curseforge.com/
4. Install. Access on `http://192.168.68.120:7800`.

---

## Environment variables

| Variable | Description | Example |
|---|---|---|
| `CRAFTY_URL` | Crafty base URL | `https://192.168.68.120:8443` |
| `CRAFTY_API_TOKEN` | Crafty v2 API Bearer token | `eyJ…` |
| `CURSEFORGE_API_KEY` | CurseForge REST API key | `$2a$10…` |

---

## Build locally

```bash
git clone https://github.com/ChargeyXD/crafty-modpack-manager
cd crafty-modpack-manager
docker build -t crafty-modpack-manager .
docker run -p 7800:7800 \
  -e CRAFTY_URL=https://YOUR_CRAFTY_IP:8443 \
  -e CRAFTY_API_TOKEN=YOUR_TOKEN \
  -e CURSEFORGE_API_KEY=YOUR_CF_KEY \
  crafty-modpack-manager
```

---

## API reference (backend)

| Method | Path | Description |
|---|---|---|
| GET | `/api/modpacks/search?q=&mc_version=&page=` | Search CurseForge modpacks |
| GET | `/api/modpacks/:id` | Get modpack details |
| GET | `/api/modpacks/:id/files` | List files (enriched with detected loader + MC ver) |
| GET | `/api/servers` | List Crafty servers |
| POST | `/api/servers/create` | Create a new Crafty server from a modpack file |
| POST | `/api/servers/:id/action/:action` | start / stop / restart / kill |
| DELETE | `/api/servers/:id` | Delete a Crafty server |
| GET | `/health` | Health check (includes Crafty reachability) |

---

## Security notes

- **Rotate your Crafty token** if it was ever committed publicly. Regenerate at Crafty → Settings → Users → API Keys.
- Keep this panel behind Cloudflare Access or on LAN only — it proxies privileged Crafty operations.
- For external access use your Cloudflare tunnel hostname instead of the LAN IP in `CRAFTY_URL`.

---

## License

MIT
