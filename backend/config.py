import os
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_DIR = Path(__file__).parent
ASSETS_DIR = PROJECT_ROOT / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
SOUNDS_DIR = ASSETS_DIR / "sounds"
DB_PATH = PROJECT_ROOT / "controllers.db"

# Default emulator config paths
DEFAULT_YUZU_CONFIG = os.path.expanduser(
    "~/.var/app/org.yuzu_emu.yuzu/config/yuzu/qt-config.ini"
)

# Polling intervals (seconds)
DEVICE_POLL_INTERVAL = 0.5
BATTERY_POLL_INTERVAL = 30.0
BLUETOOTH_SCAN_DURATION = 10.0

# Server
HOST = "127.0.0.1"
PORT = 8000
