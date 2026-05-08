import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from typing import Any, Optional

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
    ApplyConfigRequest,
)
from controllers.state_manager import StateManager
from controllers.evdev_monitor import EvdevMonitor
from controllers.device_matcher import SDLInfo
from bluetooth.bluez_manager import BlueZManager
from battery.battery_monitor import BatteryMonitor
from emulators.yuzu import YuzuConfigWriter
from emulators.dolphin import DolphinGCWriter, DolphinWiiWriter


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


_MAC_RE = re.compile(r'^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$')
_pending_bt_address: Optional[str] = None

ws_manager = ConnectionManager()
state_manager = StateManager()
evdev_monitor = EvdevMonitor()
bluez_manager = BlueZManager()
battery_monitor = BatteryMonitor()
yuzu_writer = YuzuConfigWriter()
dolphin_gc_writer = DolphinGCWriter()
dolphin_wii_writer = DolphinWiiWriter()


# --- Callbacks ---

async def on_controller_connected(device_info: dict):
    """Called by evdev_monitor when a new device is detected."""
    global _pending_bt_address
    if device_info.get("connection_type") == "bluetooth":
        uid = device_info.get("unique_id", "")
        if _MAC_RE.match(uid):
            device_info = {**device_info, "bluetooth_address": uid}
        elif _pending_bt_address:
            device_info = {**device_info, "bluetooth_address": _pending_bt_address}
            _pending_bt_address = None
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


async def on_start_pressed(device_path: str):
    """Called by evdev_monitor when the Start button is pressed."""
    await ws_manager.broadcast("start_pressed", {})


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
    evdev_monitor.on_start_pressed = on_start_pressed
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


@app.delete("/api/profiles/{unique_id}")
async def delete_profile(unique_id: str):
    # If the controller is currently connected, "deleting" it really means
    # resetting it to defaults, since StateManager/database ensure connected
    # devices always have a profile.
    device_path = state_manager.get_path_for_unique_id(unique_id)
    if device_path:
        # Reset to defaults and recreate DB entry
        await database.delete_profile(unique_id)
        profile = await state_manager.reset_profile(unique_id)
        
        # Find the updated controller in either list to broadcast
        controller = None
        if device_path in state_manager._connected:
            controller = state_manager._connected[device_path]
        elif device_path in state_manager._ready:
            controller = state_manager._ready[device_path]
            
        if controller:
            # Broadcast update so UI knows it's reset
            event_type = "controller_ready" if device_path in state_manager._ready else "controller_connected"
            await ws_manager.broadcast(event_type, controller.model_dump())
            return profile
    
    # Not connected, just delete it
    success = await database.delete_profile(unique_id)
    if success:
        return {"status": "deleted"}
    return {"error": "Profile not found"}


class StartButtonUpdate(BaseModel):
    tr2_is_start: bool


@app.put("/api/profiles/{unique_id}/start-button")
async def update_profile_start_button(unique_id: str, update: StartButtonUpdate):
    profile = await database.get_profile(unique_id)
    if not profile:
        return {"error": "Profile not found"}
    start_button = database._BTN_TR2 if update.tr2_is_start else None
    success = await database.update_type_default_start_button(
        profile.vendor_id, profile.product_id, profile.default_name, start_button
    )
    if success:
        evdev_monitor.update_start_button_for_type(
            profile.vendor_id, profile.product_id, profile.default_name, start_button
        )
        return {"status": "updated", "tr2_is_start": update.tr2_is_start}
    return {"error": "Update failed"}


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
    global _pending_bt_address
    _pending_bt_address = req.address
    success = await bluez_manager.pair_device(req.address)
    if success:
        return {"status": "paired", "address": req.address}
    _pending_bt_address = None
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


# Hardcoded SDL2 device names for Dolphin.
# SDL2 may rename controllers via HIDAPI or gamecontrollerdb, producing a name
# that differs from what evdev/kernel reports. Keyed by (vendor_id, product_id)
# or by SDL2 GUID (used when vendor/product are 0, e.g. BT-HID controllers).
_DOLPHIN_NAME_BY_VID_PID: dict[tuple[int, int], str] = {
    (0x057E, 0x2009): "Nintendo Switch Pro Controller",
    (0x045E, 0x0B13): "Xbox Series X Controller",
}
_DOLPHIN_NAME_BY_GUID: dict[str, str] = {
    # Lic Pro Controller: BT-HID reports vendor=0/product=0 in evdev, but SDL2
    # HIDAPI identifies it via this GUID as a Nintendo Switch Pro Controller.
    "030000007e0500000920000000006806": "Nintendo Switch Pro Controller",
}


def _dolphin_sdl_name(r) -> str:
    """Return the SDL2 device name Dolphin will use for this controller."""
    if r.vendor_id and r.product_id:
        name = _DOLPHIN_NAME_BY_VID_PID.get((r.vendor_id, r.product_id))
        if name:
            return name
    if r.guid:
        name = _DOLPHIN_NAME_BY_GUID.get(r.guid)
        if name:
            return name
    return r.name


def _is_wiimote(controller) -> bool:
    """Return True if this controller should be mapped as a Wiimote.

    Matches actual Wiimotes (Nintendo vendor + product) and anything whose
    evdev name contains 'wiimote' or 'wii remote'.
    """
    if controller.vendor_id == 0x057E and controller.product_id == 0x0306:
        return True
    name_lower = controller.name.lower()
    return "wiimote" in name_lower or "wii remote" in name_lower


def _build_dolphin_controllers(
    filtered: list,
    sdl_name_counts: dict[str, int],
) -> list[tuple]:
    """Build (unique_id, SDLInfo) pairs for a Dolphin writer.

    Uses the hardcoded SDL2 device name lookup rather than the evdev name, and
    computes per-SDL-name port indices to match how Dolphin/SDL2 enumerates joysticks.
    """
    result = []
    for r in filtered:
        sdl_name = _dolphin_sdl_name(r)
        port = sdl_name_counts.get(sdl_name, 0)
        sdl_name_counts[sdl_name] = port + 1
        sdl_info = SDLInfo(
            guid=r.guid or "",
            port=port,
            vendor_id=r.vendor_id or 0,
            product_id=r.product_id or 0,
            device_name=sdl_name,
        )
        result.append((r.unique_id, sdl_info))
    return result


@app.post("/api/emulators/apply")
async def apply_config(req: ApplyConfigRequest = ApplyConfigRequest()):
    """Write controller config to enabled emulators. If req.emulator is set, only that one.

    Special values for req.emulator:
      "dolphin"     – writes both GCPadNew.ini and WiimoteNew.ini, routing each
                      ready controller to the right file based on whether it is a
                      Wiimote (vendor 0x057E / product 0x0306, or name match).
      "dolphin_gc"  – writes only GCPadNew.ini with all ready controllers.
      "dolphin_wii" – writes only WiimoteNew.ini with all ready controllers.
    """
    ready = state_manager.get_ready_list()
    if not ready:
        return {"error": "No controllers ready"}

    emulators = await database.get_all_emulator_configs()
    results = {}

    for emu in emulators:
        if not emu.enabled:
            continue

        # Filter by requested emulator.
        # "dolphin" is a virtual alias that covers both dolphin_gc and dolphin_wii.
        if req.emulator is not None:
            if req.emulator == "dolphin":
                if emu.emulator_name not in ("dolphin_gc", "dolphin_wii"):
                    continue
            elif emu.emulator_name != req.emulator:
                continue

        if emu.emulator_name == "yuzu":
            # Yuzu uses GUID + per-GUID port index
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
                        device_name=r.name,
                    )
                    controllers_with_info.append((r.unique_id, sdl_info))
                else:
                    controllers_with_info.append((r.unique_id, None))
            success = yuzu_writer.write_config(emu.config_path, controllers_with_info)
            results[emu.emulator_name] = "ok" if success else "error"

        elif emu.emulator_name in ("dolphin_gc", "dolphin_wii"):
            # When called via the "dolphin" alias, route controllers by type.
            # When called directly, pass all ready controllers unchanged.
            if req.emulator == "dolphin":
                if emu.emulator_name == "dolphin_gc":
                    filtered = [r for r in ready if not _is_wiimote(r)]
                else:
                    filtered = [r for r in ready if _is_wiimote(r)]
                # Share the per-alias counter across gc/wii so SDL indices stay consistent.
                if "_dolphin_sdl_counts" not in results:
                    results["_dolphin_sdl_counts"] = {}
                sdl_counts = results["_dolphin_sdl_counts"]
            else:
                filtered = ready
                sdl_counts = {}

            controllers_with_info = _build_dolphin_controllers(filtered, sdl_counts)
            writer = dolphin_gc_writer if emu.emulator_name == "dolphin_gc" else dolphin_wii_writer
            success = writer.write_config(emu.config_path, controllers_with_info)
            results[emu.emulator_name] = "ok" if success else "error"

    # Remove internal bookkeeping key before returning
    results.pop("_dolphin_sdl_counts", None)

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


_NO_CACHE = {"Cache-Control": "no-store"}


@app.get("/assets/images/{filename}")
async def serve_image(filename: str):
    path = config.IMAGES_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(path, headers=_NO_CACHE)
    return FileResponse(config.IMAGES_DIR / "default.png", headers=_NO_CACHE)


@app.get("/assets/sounds/{filename}")
async def serve_sound(filename: str):
    path = config.SOUNDS_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(path, headers=_NO_CACHE)
    return FileResponse(config.SOUNDS_DIR / "default.mp3", headers=_NO_CACHE)


@app.get("/assets/ui-sounds/{filename}")
async def serve_ui_sound(filename: str):
    path = config.UI_SOUNDS_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(path)
