"""Runtime configuration — all values come from environment variables.
Secrets are injected by Docker / CasaOS at runtime via the environment section
of docker-compose.yml. No .env file is used or required.
"""
import os
import logging

log = logging.getLogger(__name__)


def _warn_if_missing(key: str, default: str = "") -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        log.warning(
            "Environment variable '%s' is not set. "
            "Set it in the docker-compose.yml environment section and restart the container.",
            key,
        )
        return default
    return val


CURSEFORGE_API_KEY: str = _warn_if_missing("CURSEFORGE_API_KEY")
CRAFTY_TOKEN: str       = _warn_if_missing("CRAFTY_TOKEN")
CRAFTY_URL: str         = os.getenv("CRAFTY_URL", "https://192.168.68.120:8443").rstrip("/")
CRAFTY_VERIFY_SSL: bool = os.getenv("CRAFTY_VERIFY_SSL", "false").lower() == "true"
DEFAULT_MEM_MIN: int   = int(os.getenv("DEFAULT_MEM_MIN", "2"))
DEFAULT_MEM_MAX: int   = int(os.getenv("DEFAULT_MEM_MAX", "6"))
BASE_SERVER_PORT: int   = int(os.getenv("BASE_SERVER_PORT", "25565"))

# CurseForge constants
MINECRAFT_GAME_ID = 432
MODPACK_CLASS_ID  = 4471
