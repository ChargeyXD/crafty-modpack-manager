# Crafty Modpack Manager

A self-hosted CasaOS app that lets you browse CurseForge Minecraft modpacks and deploy them as Crafty Controller server instances — like Shockbyte, but running on your own hardware.

## Requirements

- [CasaOS](https://casaos.io) running on your server
- [Crafty Controller](https://craftycontrol.com) installed and accessible
- A free [CurseForge API key](https://console.curseforge.com)

## Quick Install (CasaOS)

1. In CasaOS, go to **App Store → Custom Install**
2. Paste the raw URL of `docker-compose.yml` from this repo
3. Fill in the two required environment variables before confirming:
   - `CURSEFORGE_API_KEY` — from https://console.curseforge.com
   - `CRAFTY_TOKEN` — Crafty UI ▸ Settings ▸ API Tokens
4. `CRAFTY_URL` defaults to `https://192.168.68.120:8443` — change if your Crafty is elsewhere
5. Click Install. The UI is available on **port 7800**.

## Manual Docker Install

```bash
git clone https://github.com/ChargeyXD/crafty-modpack-manager
cd crafty-modpack-manager

# Edit docker-compose.yml and fill in CURSEFORGE_API_KEY, CRAFTY_TOKEN, CRAFTY_URL
docker compose up -d --build
```

Then open http://192.168.68.120:7800

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `CURSEFORGE_API_KEY` | ✅ | — | Free key from https://console.curseforge.com |
| `CRAFTY_TOKEN` | ✅ | — | JWT from Crafty UI ▸ Settings ▸ API Tokens |
| `CRAFTY_URL` | — | `https://192.168.68.120:8443` | Crafty base URL |
| `CRAFTY_VERIFY_SSL` | — | `false` | Set `true` if Crafty has a valid cert |
| `DEFAULT_MEM_MIN` | — | `2` | Default min RAM for new servers (GB) |
| `DEFAULT_MEM_MAX` | — | `6` | Default max RAM for new servers (GB) |
| `BASE_SERVER_PORT` | — | `25565` | Default Minecraft port |

## How It Works

1. **Search** CurseForge for any Minecraft modpack
2. **Pick a version** from the file list modal
3. **Configure** server name, RAM, port
4. **Deploy** — the app calls Crafty's API to create and start the server

## Architecture

```
browser → FastAPI (port 7800) → CurseForge API (modpack data)
                              → Crafty API     (server creation)
```

All configuration is done via environment variables in `docker-compose.yml`. No `.env` file is needed or used.

## Troubleshooting

**403 Forbidden from CurseForge**  
Your `CURSEFORGE_API_KEY` is missing or invalid. Generate a new one at https://console.curseforge.com and update `docker-compose.yml`, then `docker compose up -d`.

**Cannot reach Crafty**  
Check that `CRAFTY_URL` matches your Crafty address and `CRAFTY_VERIFY_SSL=false` is set if you're using Crafty's default self-signed certificate.

**DNS issues inside container**  
The compose file includes `dns: [8.8.8.8, 1.1.1.1]` to ensure `api.curseforge.com` resolves inside the container on networks with restrictive DNS.
