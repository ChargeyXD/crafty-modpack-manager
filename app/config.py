import os
from dotenv import load_dotenv

load_dotenv()

CURSEFORGE_API_KEY = os.environ["CURSEFORGE_API_KEY"]
CRAFTY_URL = os.getenv("CRAFTY_URL", "https://192.168.68.120:8443").rstrip("/")
CRAFTY_TOKEN = os.environ["CRAFTY_TOKEN"]
CRAFTY_VERIFY_SSL = os.getenv("CRAFTY_VERIFY_SSL", "false").lower() == "true"
DEFAULT_MEM_MIN = int(os.getenv("DEFAULT_MEM_MIN", "2"))
DEFAULT_MEM_MAX = int(os.getenv("DEFAULT_MEM_MAX", "6"))
BASE_SERVER_PORT = int(os.getenv("BASE_SERVER_PORT", "25565"))

# CurseForge Minecraft game ID
MINECRAFT_GAME_ID = 432
# CurseForge modpack class ID
MODPACK_CLASS_ID = 4471
