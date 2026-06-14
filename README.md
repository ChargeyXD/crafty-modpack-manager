# Crafty Modpack Manager

A CasaOS Docker app that lets you browse CurseForge Minecraft modpacks and deploy them as Crafty Controller server instances with one click — like Shockbyte, but self-hosted.

## Features

- Browse & search thousands of CurseForge modpacks
- Pick a specific modpack file/version
- Configure RAM, port, and mod loader
- Deploys directly to your local Crafty Controller via its v2 API
- Light/Dark mode, responsive UI

## Quick Install (CasaOS)

1. Open CasaOS → App Store → **Custom Install**
2. Paste the contents of `docker-compose.yml`
3. Fill in the required environment variables (see below)
4. Click Install

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `CURSEFORGE_API_KEY` | ✅ | API key from https://console.curseforge.com |
| `CRAFTY_TOKEN` | ✅ | Crafty JWT token (Settings → API Tokens) |
| `CRAFTY_URL` | ✅ | Crafty base URL e.g. `https://192.168.68.120:8443` |
| `CRAFTY_VERIFY_SSL` | ❌ | `false` for self-signed certs (default) |
| `DEFAULT_MEM_MIN` | ❌ | Default min RAM in GB (default: 2) |
| `DEFAULT_MEM_MAX` | ❌ | Default max RAM in GB (default: 6) |
| `BASE_SERVER_PORT` | ❌ | Default Minecraft port (default: 25565) |

## Getting a CurseForge API Key

1. Go to https://console.curseforge.com
2. Sign in and create an API key (free tier covers personal use)

## Getting your Crafty JWT Token

1. Open Crafty → Settings → API Tokens
2. Create a token with Server Create permissions
3. Paste the token value as `CRAFTY_TOKEN`

## How Deploy Works

When you click **Deploy to Crafty**, the app sends the exact payload that the Crafty UI itself sends (captured from network traces):

```json
{
  "name": "My Server",
  "roles": [],
  "monitoring_type": "minecraft_java",
  "minecraft_java_monitoring_data": {"host": "127.0.0.1", "port": 25565},
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

## Build Locally

```bash
git clone https://github.com/ChargeyXD/crafty-modpack-manager
cd crafty-modpack-manager
cp .env.example .env
# Fill in your .env
docker compose up --build
# Open http://localhost:7800
```
