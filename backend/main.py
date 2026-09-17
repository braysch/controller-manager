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
from battery.battery_monitor import BatteryMonitor
from bluetooth.bluez_manager import BlueZManager
from controllers.evdev_monitor import EvdevMonitor
from controllers.state_manager import StateManager
from emulators.dolphin import DolphinGCWriter, DolphinWiiWriter
from emulators.mesen import MesenConfigWriter
from emulators.eden import EdenConfigWriter
from emulators.yuzu import YuzuConfigWriter
from models import (
    ApplyConfigRequest,
    ControllerProfileUpdate,
    EmulatorConfigUpdate,
    MoveToReadyRequest,
    ReadyController,
)
from controllers.device_matcher import SDLInfo

# --- Global state ---

_MAC_RE = re.compile(r'^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$')
_pending_bt_address: Optional[str] = None

# Set once the game has launched and Controller Manager's window is hidden.
# Config is already written by that point, so connect/ready/sound handling is
# pointless noise from then on - but the Wii Remote bridge (EvdevMonitor's own
# per-event translate-and-forward loop) runs independently of these callbacks
# and keeps working regardless of this flag.
_game_session_active = False

# The keyboard is exposed as a virtual controller under this fixed identity.
KEYBOARD_UNIQUE_ID = "keyboard"

ws_manager = None
state_manager = StateManager()
evdev_monitor = EvdevMonitor()
bluez_manager = BlueZManager()
battery_monitor = BatteryMonitor()
eden_writer = EdenConfigWriter()
yuzu_writer = YuzuConfigWriter()
dolphin_gc_writer = DolphinGCWriter()
dolphin_wii_writer = DolphinWiiWriter()
mesen_writer = MesenConfigWriter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event_type: str, data: Any):
        message = json.dumps({"type": event_type, "data": data})
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

ws_manager = ConnectionManager()

# --- Helpers ---

def _resolve_mesen_ports(ready_list: list[ReadyController]) -> list[ReadyController]:
    """Predict Mesen Pad IDs by replicating Mesen's own device enumeration.

    Mesen2 (Linux/LinuxKeyManager.cpp) walks /dev/input in raw readdir order
    (no sorting) and counts every event device it can open that has BTN_GAMEPAD
    or an ABS_X axis — including ghost devices like the IMU/motion nodes that
    Switch-style controllers expose. Since Mesen runs as the same user, devices
    we can't open are skipped by Mesen too.
    """
    from evdev import InputDevice, ecodes

    pad_index_by_path = {}
    pad = 0
    input_dir = "/dev/input"
    if os.path.exists(input_dir):
        for entry in os.listdir(input_dir):  # keep readdir order — Mesen does not sort
            if not entry.startswith("event"):
                continue
            try:
                int(entry[5:])
            except ValueError:
                continue
            node_path = os.path.join(input_dir, entry)
            try:
                dev = InputDevice(node_path)
            except Exception:
                continue
            try:
                caps = dev.capabilities()
                has_gamepad_btn = ecodes.BTN_GAMEPAD in caps.get(ecodes.EV_KEY, [])
                abs_codes = [c[0] if isinstance(c, tuple) else c for c in caps.get(ecodes.EV_ABS, [])]
                has_abs_x = ecodes.ABS_X in abs_codes
            except Exception:
                continue
            finally:
                dev.close()
            if has_gamepad_btn or has_abs_x:
                pad_index_by_path[node_path] = pad
                pad += 1

    # Attach the predicted Pad index (0-based) to each controller. Use the
    # controller's own device path: twin pads with no serial share a unique_id,
    # so a unique_id lookup can return the sibling's path.
    for r in ready_list:
        if r.unique_id == KEYBOARD_UNIQUE_ID:
            r.port = None  # keyboard isn't a gamepad; Mesen uses absolute key IDs
            continue
        device_path = r.device_path or state_manager.get_path_for_unique_id(r.unique_id)
        r.port = pad_index_by_path.get(device_path, 0) if device_path else 0

    return ready_list

# Hardcoded SDL2 device names for Dolphin.
_DOLPHIN_NAME_BY_VID_PID: dict[tuple[int, int], str] = {
    (0x057E, 0x2009): "Nintendo Switch Pro Controller",
    (0x045E, 0x0B13): "Xbox Series X Controller",
}
_DOLPHIN_NAME_BY_GUID: dict[str, str] = {
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
    if controller.vendor_id == 0x057E and controller.product_id == 0x0306:
        return True
    name_lower = controller.name.lower()
    return "wiimote" in name_lower or "wii remote" in name_lower

def _build_dolphin_controllers(filtered: list, sdl_name_counts: dict[str, int]) -> list[tuple]:
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

# --- Callbacks ---

async def on_controller_connected(device_info: dict):
    """Called by evdev_monitor when a new device is detected."""
    global _pending_bt_address
    if _game_session_active:
        return
    if device_info.get("connection_type") == "bluetooth":
        uid = device_info.get("unique_id", "")
        if _MAC_RE.match(uid):
            device_info = {**device_info, "bluetooth_address": uid}
        elif _pending_bt_address:
            device_info = {**device_info, "bluetooth_address": _pending_bt_address}
            _pending_bt_address = None
    controller = await state_manager.add_connected(device_info)
    if controller:
        # Apply the saved profile's start-button choice (the monitor's connect-time
        # default only knows type defaults, not per-controller settings)
        evdev_monitor.update_start_button_for_path(device_info["device_path"], controller.tr2_is_start, controller.start_button_override)
        # Register with battery monitor. For a bridged Wii Remote, device_path here
        # is the synthetic bridge device (no real sysfs battery info) - use the
        # real device path instead so battery reporting still works.
        battery_monitor.register_device(evdev_monitor.to_real_path(device_info["device_path"]))
        await ws_manager.broadcast("controller_connected", controller.model_dump())
        
        # Re-resolve Pad IDs for all ready controllers and broadcast updates
        ready = state_manager.get_ready_list()
        updated_ready = _resolve_mesen_ports(ready)
        for r in updated_ready:
            await ws_manager.broadcast("controller_ready", r.model_dump())

async def on_controller_disconnected(device_path: str):
    """Called by evdev_monitor when a device is removed."""
    if _game_session_active:
        return
    # Unregister from battery monitor. For a bridged Wii Remote, device_path here
    # is the synthetic bridge device - it was registered under the real path (see
    # on_controller_connected), so translate back to unregister the right one.
    battery_monitor.unregister_device(evdev_monitor.to_real_path(device_path))

    unique_id = state_manager.get_unique_id_for_path(device_path)
    if unique_id:
        was_ready = await state_manager.remove_connected(device_path)
        await ws_manager.broadcast("controller_disconnected", {"unique_id": unique_id})
        if was_ready:
            await ws_manager.broadcast("controller_unready", {"unique_id": unique_id})
            
        # Re-resolve Pad IDs for all ready controllers and broadcast updates
        ready = state_manager.get_ready_list()
        updated_ready = _resolve_mesen_ports(ready)
        for r in updated_ready:
            await ws_manager.broadcast("controller_ready", r.model_dump())

async def on_button_press(device_path: str, button_code: int):
    """Called by evdev_monitor on START/TR2 press."""
    if _game_session_active:
        return
    controller = await state_manager.move_to_ready(device_path)
    if controller:
        # Resolve ports before broadcasting
        ready = state_manager.get_ready_list()
        updated_ready = _resolve_mesen_ports(ready)
        # Find this specific controller in the updated list
        this_controller = next((c for c in updated_ready if c.unique_id == controller.unique_id), controller)
        await ws_manager.broadcast("controller_ready", this_controller.model_dump())

async def on_input(device_path: str):
    """Called by evdev_monitor on any significant input."""
    if _game_session_active:
        return
    unique_id = state_manager.get_unique_id_for_path(device_path)
    if unique_id:
        await ws_manager.broadcast("controller_input", {"unique_id": unique_id})

async def on_start_pressed(device_path: str):
    """Called by evdev_monitor when the Start button is pressed."""
    if _game_session_active:
        return
    await ws_manager.broadcast("start_pressed", {})

async def on_battery_update(device_path: str, percent: int):
    """Called by battery_monitor on change."""
    unique_id = state_manager.get_unique_id_for_path(device_path)
    if unique_id:
        state_manager.update_battery(unique_id, percent)
        await ws_manager.broadcast("battery_update", {"unique_id": unique_id, "battery_percent": percent})

async def on_raw_input(device_path: str, kind: str, codes: list[str], value: int, min_val: Optional[int], max_val: Optional[int]):
    """Called by evdev_monitor for every key/axis event on the focused Input Config device."""
    unique_id = state_manager.get_unique_id_for_path(device_path)
    if not unique_id:
        return
    payload: dict[str, Any] = {"unique_id": unique_id, "kind": kind, "codes": codes, "value": value}
    if min_val is not None:
        payload["min"] = min_val
    if max_val is not None:
        payload["max"] = max_val
    await ws_manager.broadcast("raw_input", payload)

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
    evdev_monitor.on_raw_input = on_raw_input
    battery_monitor.on_update = on_battery_update

    # Register the keyboard as an always-connected virtual controller.
    # The frontend readies it when both Shift keys are pressed together.
    await state_manager.add_connected({
        "device_path": KEYBOARD_UNIQUE_ID,
        "unique_id": KEYBOARD_UNIQUE_ID,
        "name": "Keyboard",
        "connection_type": "usb",
        "guid": None,
        "port": None,
    })

    asyncio.create_task(evdev_monitor.run())
    asyncio.create_task(battery_monitor.run())

    yield

    # Shutdown
    evdev_monitor.stop()

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
        # Resolve ports in snapshot
        snapshot["ready"] = _resolve_mesen_ports([ReadyController(**c) for c in snapshot["ready"]])
        snapshot["ready"] = [c.model_dump() for c in snapshot["ready"]]
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
    # Get current ready list and resolve their physical Pad IDs
    ready = state_manager.get_ready_list()
    return _resolve_mesen_ports(ready)

@app.post("/api/controllers/ready")
async def move_to_ready(req: MoveToReadyRequest):
    device_path = state_manager.get_path_for_unique_id(req.unique_id)
    if not device_path:
        return {"error": "Controller not found"}
    controller = await state_manager.move_to_ready(device_path)
    if controller:
        # Resolve ports before returning
        ready = state_manager.get_ready_list()
        updated_ready = _resolve_mesen_ports(ready)
        this_controller = next((c for c in updated_ready if c.unique_id == controller.unique_id), controller)
        await ws_manager.broadcast("controller_ready", this_controller.model_dump())
        return this_controller
    return {"error": "Controller already ready or not connected"}

@app.post("/api/session/launched")
async def session_launched():
    """Called once the game has actually launched: silence connect/ready/sound
    handling for the rest of this run (the Wii Remote bridge keeps working)."""
    global _game_session_active
    _game_session_active = True
    return {"status": "ok"}

class InputConfigFocusRequest(BaseModel):
    unique_id: Optional[str] = None

@app.post("/api/input-config/focus")
async def set_input_config_focus(req: InputConfigFocusRequest):
    """Stream every raw button/axis event for one controller (Input Config screen)."""
    path = state_manager.get_path_for_unique_id(req.unique_id) if req.unique_id else None
    evdev_monitor.set_focus(path)
    return {"status": "ok", "focused": req.unique_id}

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

        # Broadcast updates so GUI labels refresh immediately
        ready = state_manager.get_ready_list()
        updated_ready = _resolve_mesen_ports(ready)
        for r in updated_ready:
            await ws_manager.broadcast("controller_ready", r.model_dump())

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
        controller = state_manager._connected.get(device_path) or state_manager._ready.get(device_path)
            
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

class ForceConnectRequest(BaseModel):
    unique_id: str

@app.post("/api/bluetooth/force-connect")
async def force_connect_controller(req: ForceConnectRequest):
    """Connect to a profiled controller by its stored MAC, even if it isn't discoverable."""
    global _pending_bt_address
    profile = await database.get_profile(req.unique_id)
    if not profile:
        return {"error": "Profile not found"}
    address = profile.bluetooth_address or (req.unique_id if _MAC_RE.match(req.unique_id) else None)
    if not address:
        return {"error": "No Bluetooth address stored for this controller"}
    _pending_bt_address = address
    success = await bluez_manager.connect_device(address)
    if success:
        return {"status": "connected", "address": address}
    _pending_bt_address = None
    return {"error": "Connect failed", "address": address}

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
async def apply_config(req: ApplyConfigRequest = ApplyConfigRequest()):
    """Write controller config to enabled emulators. If req.emulator is set, only that one."""
    ready = state_manager.get_ready_list()
    if not ready and not req.force:
        return {"error": "No controllers ready"}

    # Resolve ports before applying
    ready = _resolve_mesen_ports(ready)

    emulators = await database.get_all_emulator_configs()
    results = {}

    for emu in emulators:
        if not emu.enabled:
            continue

        if req.emulator is not None:
            if req.emulator == "dolphin":
                if emu.emulator_name not in ("dolphin_gc", "dolphin_wii"):
                    continue
            elif emu.emulator_name != req.emulator:
                continue

        if emu.emulator_name in ("yuzu", "eden"):
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
            writer = eden_writer if emu.emulator_name == "eden" else yuzu_writer
            success = writer.write_config(emu.config_path, controllers_with_info)
            results[emu.emulator_name] = "ok" if success else "error"

        elif emu.emulator_name in ("dolphin_gc", "dolphin_wii"):
            if "_dolphin_sdl_counts" not in results:
                results["_dolphin_sdl_counts"] = {}
            sdl_counts = results["_dolphin_sdl_counts"]
            
            # Keyboard isn't an SDL device — Dolphin can't use it
            filtered = [r for r in ready if r.unique_id != KEYBOARD_UNIQUE_ID]
            if req.emulator == "dolphin":
                if emu.emulator_name == "dolphin_gc":
                    filtered = [r for r in filtered if not _is_wiimote(r)]
                else:
                    filtered = [r for r in filtered if _is_wiimote(r)]

            controllers_with_info = _build_dolphin_controllers(filtered, sdl_counts)
            writer = dolphin_gc_writer if emu.emulator_name == "dolphin_gc" else dolphin_wii_writer
            success = writer.write_config(emu.config_path, controllers_with_info)
            results[emu.emulator_name] = "ok" if success else "error"

        elif emu.emulator_name == "mesen":
            controllers_with_info = []
            for r in ready:
                # Include the custom name so name-based profile matching works for
                # controllers that are otherwise indistinguishable (e.g. a Diswoe
                # reports the same VID/PID and device name as a real Switch Pro).
                sdl_info = SDLInfo(
                    guid=r.guid or "",
                    port=r.port if r.port is not None else 0,
                    vendor_id=r.vendor_id or 0,
                    product_id=r.product_id or 0,
                    device_name=" ".join(filter(None, [r.custom_name, r.name])),
                )
                controllers_with_info.append((r.unique_id, sdl_info))
            success = mesen_writer.write_config(emu.config_path, controllers_with_info)
            results["mesen"] = "ok" if success else "error"

    results.pop("_dolphin_sdl_counts", None)
    return {"results": results}

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
