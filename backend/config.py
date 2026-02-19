import os
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_DIR = Path(__file__).parent
ASSETS_DIR = PROJECT_ROOT / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
SOUNDS_DIR = ASSETS_DIR / "sounds"

# DB lives in a writable user data dir (set by Electron in production,
# falls back to project root in dev).
_data_dir = Path(os.environ.get('CONTROLLER_MANAGER_DATA_DIR', PROJECT_ROOT))
_data_dir.mkdir(parents=True, exist_ok=True)
DB_PATH = _data_dir / "controllers.db"

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
