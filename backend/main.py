import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
import database
from models import (
    ControllerProfileUpdate,
    EmulatorConfigUpdate,
    MoveToReadyRequest,
)
from controllers.state_manager import StateManager
from controllers.evdev_monitor import EvdevMonitor
from controllers.device_matcher import SDLInfo
from bluetooth.bluez_manager import BlueZManager
from battery.battery_monitor import BatteryMonitor
from emulators.yuzu import YuzuConfigWriter


# --- WebSocket connection manager ---

class ConnectionManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, event_type: str, data: Any):
        message = json.dumps({"type": event_type, "data": data})
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()
state_manager = StateManager()
evdev_monitor = EvdevMonitor()
bluez_manager = BlueZManager()
battery_monitor = BatteryMonitor()
yuzu_writer = YuzuConfigWriter()


# --- Callbacks ---

async def on_controller_connected(device_info: dict):
    """Called by evdev_monitor when a new device is detected."""
    controller = await state_manager.add_connected(device_info)
    if controller:
        # Register with battery monitor
        battery_monitor.register_device(device_info["device_path"])
        await ws_manager.broadcast("controller_connected", controller.model_dump())


async def on_controller_disconnected(device_path: str):
    """Called by evdev_monitor when a device is removed."""
    # Unregister from battery monitor
    battery_monitor.unregister_device(device_path)

    unique_id = state_manager.get_unique_id_for_path(device_path)
    if unique_id:
        was_ready = await state_manager.remove_connected(device_path)
        await ws_manager.broadcast("controller_disconnected", {"unique_id": unique_id})
        if was_ready:
            await ws_manager.broadcast("controller_unready", {"unique_id": unique_id})


async def on_button_press(device_path: str, button_code: int):
    """Called by evdev_monitor on START/TR2 press."""
    controller = await state_manager.move_to_ready(device_path)
    if controller:
        await ws_manager.broadcast("controller_ready", controller.model_dump())


async def on_input(device_path: str):
    """Called by evdev_monitor on any significant input."""
    unique_id = state_manager.get_unique_id_for_path(device_path)
    if unique_id:
        await ws_manager.broadcast("controller_input", {"unique_id": unique_id})


async def on_battery_update(device_path: str, percent: int):
    """Called by battery_monitor on change."""
    unique_id = state_manager.get_unique_id_for_path(device_path)
    if unique_id:
        state_manager.update_battery(unique_id, percent)
        await ws_manager.broadcast("battery_update", {"unique_id": unique_id, "battery_percent": percent})


# --- App lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await database.init_db()

    evdev_monitor.on_connected = on_controller_connected
    evdev_monitor.on_disconnected = on_controller_disconnected
    evdev_monitor.on_button_press = on_button_press
    evdev_monitor.on_input = on_input
    battery_monitor.on_update = on_battery_update

    monitor_task = asyncio.create_task(evdev_monitor.run())
    battery_task = asyncio.create_task(battery_monitor.run())

    yield

    # Shutdown
    evdev_monitor.stop()
    battery_monitor.stop()
    monitor_task.cancel()
    battery_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    try:
        await battery_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Controller Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health ---

@app.get("/health")
async def health():
    return {"status": "ok"}


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # Send initial state snapshot
        snapshot = state_manager.get_snapshot()
        await ws.send_text(json.dumps({"type": "state_snapshot", "data": snapshot}))

        while True:
            # Keep connection alive; client doesn't need to send anything
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)


# --- Controller endpoints ---

@app.get("/api/controllers/connected")
async def get_connected():
    return state_manager.get_connected_list()


@app.get("/api/controllers/ready")
async def get_ready():
    return state_manager.get_ready_list()


@app.post("/api/controllers/ready")
async def move_to_ready(req: MoveToReadyRequest):
    device_path = state_manager.get_path_for_unique_id(req.unique_id)
    if not device_path:
        return {"error": "Controller not found"}
    controller = await state_manager.move_to_ready(device_path)
    if controller:
        await ws_manager.broadcast("controller_ready", controller.model_dump())
        return controller
    return {"error": "Controller already ready or not connected"}


@app.delete("/api/controllers/ready")
async def clear_ready():
    controllers = await state_manager.clear_ready()
    for c in controllers:
        await ws_manager.broadcast("controller_unready", {"unique_id": c.unique_id})
        await ws_manager.broadcast("controller_connected", c.model_dump())
    return {"cleared": len(controllers)}


# --- Profile endpoints ---

@app.get("/api/profiles")
async def get_profiles():
    return await database.get_all_profiles()


@app.put("/api/profiles/{unique_id}")
async def update_profile(unique_id: str, update: ControllerProfileUpdate):
    profile = await database.update_profile_fields(
        unique_id,
        custom_name=update.custom_name if update.custom_name is not None else ...,
        img_src=update.img_src,
        snd_src=update.snd_src,
        guid_override=update.guid_override if update.guid_override is not None else ...,
    )
    if profile:
        # Update in-memory state
        state_manager.refresh_profile(unique_id, profile)
        return profile
    return {"error": "Profile not found"}


# --- Bluetooth endpoints ---

@app.post("/api/bluetooth/scan")
async def start_bluetooth_scan():
    async def on_device_found(name: str, address: str):
        await ws_manager.broadcast("bluetooth_device_found", {"name": name, "address": address})

    async def on_scan_complete():
        await ws_manager.broadcast("bluetooth_scan_complete", {})

    await bluez_manager.start_scan(on_device_found, on_scan_complete)
    await ws_manager.broadcast("bluetooth_scan_started", {})
    return {"status": "scanning"}


@app.post("/api/bluetooth/stop-scan")
async def stop_bluetooth_scan():
    await bluez_manager.stop_scan()
    return {"status": "stopped"}


class PairRequest(BaseModel):
    address: str


@app.post("/api/bluetooth/pair")
async def pair_bluetooth_device(req: PairRequest):
    success = await bluez_manager.pair_device(req.address)
    if success:
        return {"status": "paired", "address": req.address}
    return {"error": "Pairing failed", "address": req.address}


@app.post("/api/bluetooth/disconnect")
async def disconnect_bluetooth_device(req: PairRequest):
    success = await bluez_manager.disconnect_device(req.address)
    if success:
        return {"status": "disconnected", "address": req.address}
    return {"error": "Device not found or disconnect failed", "address": req.address}


@app.post("/api/bluetooth/remove")
async def remove_bluetooth_device(req: PairRequest):
    success = await bluez_manager.remove_device(req.address)
    if success:
        return {"status": "removed", "address": req.address}
    return {"error": "Device not found or removal failed", "address": req.address}


@app.post("/api/controllers/disconnect-all")
async def disconnect_all_controllers():
    count = await bluez_manager.disconnect_all_controllers()
    return {"disconnected": count}


@app.post("/api/controllers/remove-all")
async def remove_all_controllers():
    count = await bluez_manager.remove_all_controllers()
    return {"removed": count}


# --- Emulator endpoints ---

@app.get("/api/emulators")
async def get_emulators():
    return await database.get_all_emulator_configs()


@app.put("/api/emulators/{name}")
async def update_emulator(name: str, update: EmulatorConfigUpdate):
    result = await database.update_emulator_config(
        name, config_path=update.config_path, enabled=update.enabled
    )
    if result:
        return result
    return {"error": "Emulator not found"}


@app.post("/api/emulators/apply")
async def apply_config():
    """Write controller config to all enabled emulators."""
    ready = state_manager.get_ready_list()
    if not ready:
        return {"error": "No controllers ready"}

    emulators = await database.get_all_emulator_configs()
    results = {}

    for emu in emulators:
        if not emu.enabled:
            continue

        if emu.emulator_name == "yuzu":
            # Build SDLInfo from the ready controllers' stored guid
            # Port = per-GUID index (position among devices sharing the same GUID)
            guid_counts: dict[str, int] = {}
            controllers_with_info = []
            for r in ready:
                if r.guid:
                    port = guid_counts.get(r.guid, 0)
                    guid_counts[r.guid] = port + 1
                    sdl_info = SDLInfo(
                        guid=r.guid,
                        port=port,
                        vendor_id=r.vendor_id or 0,
                        product_id=r.product_id or 0,
                    )
                    controllers_with_info.append((r.unique_id, sdl_info))
                else:
                    controllers_with_info.append((r.unique_id, None))

            success = yuzu_writer.write_config(emu.config_path, controllers_with_info)
            results[emu.emulator_name] = "ok" if success else "error"

    return {"results": results}


# --- Asset endpoints ---

@app.get("/api/assets/images")
async def list_images():
    if config.IMAGES_DIR.exists():
        return sorted(f.name for f in config.IMAGES_DIR.iterdir() if f.is_file())
    return []


@app.get("/api/assets/sounds")
async def list_sounds():
    if config.SOUNDS_DIR.exists():
        return sorted(f.name for f in config.SOUNDS_DIR.iterdir() if f.is_file())
    return []


@app.get("/assets/images/{filename}")
async def serve_image(filename: str):
    path = config.IMAGES_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(path)
    return FileResponse(config.IMAGES_DIR / "default.png")


@app.get("/assets/sounds/{filename}")
async def serve_sound(filename: str):
    path = config.SOUNDS_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(path)
    return FileResponse(config.SOUNDS_DIR / "default.mp3")


@app.get("/assets/ui-sounds/{filename}")
async def serve_ui_sound(filename: str):
    path = config.UI_SOUNDS_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(path)
