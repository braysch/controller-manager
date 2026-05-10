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

ws_manager = None
state_manager = StateManager()
evdev_monitor = EvdevMonitor()
bluez_manager = BlueZManager()
battery_monitor = BatteryMonitor()
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
    """Predict Mesen Pad IDs by sorting all active joysticks LIFO and accounting for ghost pads."""
    import subprocess
    js_devices_info = []
    input_dir = "/dev/input"
    if os.path.exists(input_dir):
        for entry in os.listdir(input_dir):
            if entry.startswith("event"):
                node_path = os.path.join(input_dir, entry)
                try:
                    out = subprocess.check_output(["udevadm", "info", "--query=property", "--name=" + node_path], text=True)
                    if "ID_INPUT_JOYSTICK=1" in out or "ID_INPUT_GAMEPAD=1" in out:
                        event_num = int(entry.replace("event", ""))
                        name = ""
                        for line in out.splitlines():
                            if line.startswith("ID_MODEL="):
                                name = line.split("=")[1].lower()
                                break
                        js_devices_info.append({"num": event_num, "path": node_path, "name": name})
                except Exception:
                    pass
    
    # Sort LIFO: Newest (Highest event number) is Pad 1
    js_devices_info.sort(key=lambda x: x["num"], reverse=True)
    
    # Map each device to its Mesen Pad Index
    js_index_map = {}
    current_pad = 0
    for dev_info in js_devices_info:
        # Find if this physical path matches a connected/ready controller to get its pad_length
        uid = state_manager.get_unique_id_for_path(dev_info["path"])
        pad_len = 1
        if uid:
            c = state_manager._connected.get(dev_info["path"]) or state_manager._ready.get(dev_info["path"])
            if c:
                pad_len = c.pad_length
        
        if pad_len > 1:
            # Actual gamepad is the LAST pad in the block (offset by pad_len - 1)
            js_index_map[dev_info["path"]] = current_pad + (pad_len - 1)
            current_pad += pad_len
        else:
            js_index_map[dev_info["path"]] = current_pad
            current_pad += 1

    # Attach the predicted Pad index (0-based) to each controller
    for r in ready_list:
        device_path = state_manager.get_path_for_unique_id(r.unique_id)
        r.port = js_index_map.get(device_path, 0) if device_path else 0
        
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
        
        # Re-resolve Pad IDs for all ready controllers and broadcast updates
        ready = state_manager.get_ready_list()
        updated_ready = _resolve_mesen_ports(ready)
        for r in updated_ready:
            await ws_manager.broadcast("controller_ready", r.model_dump())

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
            
        # Re-resolve Pad IDs for all ready controllers and broadcast updates
        ready = state_manager.get_ready_list()
        updated_ready = _resolve_mesen_ports(ready)
        for r in updated_ready:
            await ws_manager.broadcast("controller_ready", r.model_dump())

async def on_button_press(device_path: str, button_code: int):
    """Called by evdev_monitor on START/TR2 press."""
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
        pad_length=update.pad_length,
        tr2_is_start=update.tr2_is_start,
    )
    if profile:
        # Update in-memory state
        state_manager.refresh_profile(unique_id, profile)
        
        # Update start button in evdev_monitor
        device_path = state_manager.get_path_for_unique_id(unique_id)
        if device_path:
            evdev_monitor.update_start_button_for_path(device_path, profile.tr2_is_start)
        
        # New: Re-resolve Pad IDs for all ready controllers if pad_length changed
        # and broadcast updates so GUI labels refresh immediately
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

class StartButtonUpdate(BaseModel):
    tr2_is_start: bool

@app.put("/api/profiles/{unique_id}/start-button")
async def update_profile_start_button(unique_id: str, update: StartButtonUpdate):
    profile = await database.update_profile_fields(unique_id, tr2_is_start=update.tr2_is_start)
    if profile:
        state_manager.refresh_profile(unique_id, profile)
        return {"status": "updated", "tr2_is_start": profile.tr2_is_start}
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
    if not ready:
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

        if emu.emulator_name == "yuzu":
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
            results["yuzu"] = "ok" if success else "error"

        elif emu.emulator_name in ("dolphin_gc", "dolphin_wii"):
            if "_dolphin_sdl_counts" not in results:
                results["_dolphin_sdl_counts"] = {}
            sdl_counts = results["_dolphin_sdl_counts"]
            
            filtered = ready
            if req.emulator == "dolphin":
                if emu.emulator_name == "dolphin_gc":
                    filtered = [r for r in ready if not _is_wiimote(r)]
                else:
                    filtered = [r for r in ready if _is_wiimote(r)]

            controllers_with_info = _build_dolphin_controllers(filtered, sdl_counts)
            writer = dolphin_gc_writer if emu.emulator_name == "dolphin_gc" else dolphin_wii_writer
            success = writer.write_config(emu.config_path, controllers_with_info)
            results[emu.emulator_name] = "ok" if success else "error"

        elif emu.emulator_name == "mesen":
            controllers_with_info = []
            for r in ready:
                sdl_info = SDLInfo(
                    guid=r.guid or "",
                    port=r.port if r.port is not None else 0,
                    vendor_id=r.vendor_id or 0,
                    product_id=r.product_id or 0,
                    device_name=r.name,
                )
                # We can reuse the device_name field or similar to pass extra flags, 
                # but better to update SDLInfo or just use another way.
                # Let's add tr2_is_start to SDLInfo in device_matcher.py
                controllers_with_info.append((r.unique_id, sdl_info, r.tr2_is_start))
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
