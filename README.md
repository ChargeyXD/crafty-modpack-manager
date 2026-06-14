# Crafty Modpack Manager

Self-hosted modpack installer for Crafty Controller, designed for CasaOS.

## Features
- Search CurseForge Minecraft modpacks
- Pick an installable file/build
- Create Crafty server instances from the panel UI
- Start/stop existing Crafty servers
- Single Docker image for CasaOS custom app installs

## Environment variables
- `CRAFTY_URL` - Example: `https://192.168.68.120:8443`
- `CRAFTY_API_TOKEN` - Crafty Controller API token
- `CURSEFORGE_API_KEY` - CurseForge API key

## CasaOS
Use the included `docker-compose.yml` as a custom app or repo manifest.

## Notes
This project assumes Crafty API v2 and CurseForge REST API access.
Rotate tokens before production if they were ever shared publicly.
