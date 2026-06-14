"""Runtime configuration — all values come from environment variables.
No .env file is used; secrets are injected by Docker / CasaOS at runtime.
"""
import os

def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(
            f"Required environment variable '{key}' is not set. "
            "Set it in the docker-compose.yml environment section."
        )
    return val

CURSEFORGE_API_KEY: str = _require("CURSEFORGE_API_KEY")
CRAFTY_URL: str        = os.getenv("CRAFTY_URL", "https://192.168.68.120:8443").rstrip("/")
CRAFTY_TOKEN: str      = _require("CRAFTY_TOKEN")
CRAFTY_VERIFY_SSL: bool = os.getenv("CRAFTY_VERIFY_SSL", "false").lower() == "true"
DEFAULT_MEM_MIN: int  = int(os.getenv("DEFAULT_MEM_MIN", "2"))
DEFAULT_MEM_MAX: int  = int(os.getenv("DEFAULT_MEM_MAX", "6"))
BASE_SERVER_PORT: int  = int(os.getenv("BASE_SERVER_PORT", "25565"))

# CurseForge constants
MINECRAFT_GAME_ID  = 432
MODPACK_CLASS_ID   = 4471
