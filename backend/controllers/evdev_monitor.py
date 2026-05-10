"""Async evdev device monitoring for controller connect/disconnect and button presses."""

import asyncio
import os
import struct
import select
import time
from typing import Callable, Optional

from evdev import InputDevice, ecodes, list_devices
from database import get_type_default

# Fraction of an axis's maximum value that both triggers must reach to fire the combo.
TRIGGER_THRESHOLD_FRACTION = 0.5
# Seconds before the same device can fire the combo again
COMBO_COOLDOWN = 1.5
# How long after a button press it still counts toward a combo, even if released.
COMBO_WINDOW = 2.0

# Bumper/trigger button codes used for debug output
_BUMPER_TRIGGER_BTNS: dict[int, str] = {
    ecodes.BTN_TL:  "BTN_TL  (L bumper)",
    ecodes.BTN_TR:  "BTN_TR  (R bumper)",
    ecodes.BTN_TL2: "BTN_TL2 (ZL trigger)",
    ecodes.BTN_TR2: "BTN_TR2 (ZR trigger)",
}

# Button combos: every button in a frozenset must be held simultaneously.
_BUTTON_COMBOS: list[frozenset] = [
    frozenset({ecodes.BTN_TL, ecodes.BTN_TR}),        # both bumpers
    frozenset({ecodes.BTN_TL2, ecodes.BTN_TR2}),      # both digital triggers
    frozenset({ecodes.BTN_TR, ecodes.BTN_TR2}),       # Left Joy-Con alone (SL + SR)
    frozenset({ecodes.BTN_TL, ecodes.BTN_TL2}),       # Right Joy-Con alone (SL + SR)
    frozenset({ecodes.BTN_WEST, ecodes.BTN_Z}),       # SNES: BTN_WEST + BTN_Z
    frozenset({ecodes.BTN_Y, ecodes.BTN_Z}),          # SNES: BTN_Y + BTN_Z
]


class EvdevMonitor:
    def __init__(self):
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        self.on_button_press: Optional[Callable] = None
        self.on_input: Optional[Callable] = None
        self.on_start_pressed: Optional[Callable] = None
        self._running = False
        self._known_paths: set[str] = set()
        self._devices: dict[str, InputDevice] = {}
        self._held_buttons: dict[str, set[int]] = {}
        self._trigger_values: dict[str, dict[int, int]] = {}
        self._last_fired: dict[str, float] = {}
        self._trigger_max: dict[str, dict[int, int]] = {}
        self._ignore_until: dict[str, float] = {}
        self._button_press_time: dict[str, dict[int, float]] = {}
        self._input_axis_triggered: dict[str, set[int]] = {}
        self._start_button: dict[str, int] = {}

    def stop(self):
        self._running = False

    def update_start_button_for_path(self, path: str, tr2_is_start: bool):
        """Update the start button for a specific device path."""
        self._start_button[path] = ecodes.BTN_TR2 if tr2_is_start else ecodes.BTN_START

    def update_start_button_for_type(
        self,
        vendor_id: Optional[int],
        product_id: Optional[int],
        default_name: str,
        start_button: Optional[int],
    ) -> None:
        """Refresh the cached start button for all currently connected devices of a given type."""
        btn = start_button if start_button is not None else ecodes.BTN_START
        for path, device in list(self._devices.items()):
            try:
                info = self._get_device_info(device)
                if vendor_id is not None and product_id is not None:
                    if info["vendor_id"] == vendor_id and info["product_id"] == product_id:
                        self._start_button[path] = btn
                else:
                    if default_name.lower() in device.name.lower():
                        self._start_button[path] = btn
            except Exception: pass

    @staticmethod
    def _compute_sdl_guid(device: InputDevice) -> str:
        bus = device.info.bustype
        vendor = device.info.vendor
        product = device.info.product
        version = device.info.version
        raw = struct.pack('<HHHHHHHH', bus, 0, vendor, 0, product, 0, version, 0)
        return raw.hex()

    @staticmethod
    def _get_js_index(device_path: str) -> int:
        event_name = os.path.basename(device_path)
        try:
            event_sysfs = f"/sys/class/input/{event_name}/device"
            event_real = os.path.realpath(event_sysfs)
            input_class = "/sys/class/input"
            if os.path.isdir(input_class):
                for entry in os.listdir(input_class):
                    if entry.startswith("js"):
                        js_sysfs = f"{input_class}/{entry}/device"
                        if os.path.exists(js_sysfs):
                            js_real = os.path.realpath(js_sysfs)
                            if js_real == event_real: return int(entry[2:])
        except (OSError, ValueError): pass
        try: return int(event_name.replace("event", ""))
        except ValueError: return 0

    def _get_device_info(self, device: InputDevice) -> dict:
        uniq = device.uniq or ""
        vendor = device.info.vendor
        product = device.info.product
        bus = device.info.bustype
        connection_type = "bluetooth" if bus == 0x05 else "usb"
        if uniq and uniq.strip(): unique_id = uniq.strip()
        else: unique_id = f"{vendor:04x}:{product:04x}:{device.name}"
        guid = self._compute_sdl_guid(device)
        port = self._get_js_index(device.path)
        return {
            "device_path": device.path, "name": device.name, "unique_id": unique_id,
            "vendor_id": vendor, "product_id": product, "connection_type": connection_type,
            "bus_type": bus, "guid": guid, "port": port,
        }

    async def run(self):
        self._running = True
        print("[EvdevMonitor] Starting device monitoring")
        while self._running:
            try:
                current_paths = set(list_devices())
                new_paths = current_paths - self._known_paths
                for path in new_paths:
                    try:
                        device = InputDevice(path)
                        if not self._is_gamepad(device):
                            self._known_paths.add(path); continue
                        info = self._get_device_info(device)
                        self._known_paths.add(path)
                        self._devices[path] = device
                        self._held_buttons[path] = set()
                        self._trigger_values[path] = {}
                        self._ignore_until[path] = time.monotonic() + 1.0
                        self._trigger_max[path] = self._detect_analog_triggers(device) or {}
                        self._button_press_time[path] = {}
                        self._input_axis_triggered[path] = set()
                        try:
                            type_default = await get_type_default(device.name, info["vendor_id"], info["product_id"])
                            self._start_button[path] = type_default.start_button if (type_default and type_default.start_button) else ecodes.BTN_START
                        except Exception: self._start_button[path] = ecodes.BTN_START
                        if self.on_connected: await self.on_connected(info)
                        print(f"[EvdevMonitor] Connected: {device.name} ({path}) GUID={info['guid']} port={info['port']}")
                    except Exception as e: print(f"[EvdevMonitor] Error reading new device {path}: {e}")

                removed_paths = self._known_paths - current_paths
                for path in removed_paths:
                    self._known_paths.discard(path)
                    self._devices.pop(path, None); self._held_buttons.pop(path, None)
                    self._trigger_values.pop(path, None); self._last_fired.pop(path, None)
                    self._trigger_max.pop(path, None); self._ignore_until.pop(path, None)
                    self._button_press_time.pop(path, None); self._input_axis_triggered.pop(path, None)
                    self._start_button.pop(path, None)
                    if self.on_disconnected: await self.on_disconnected(path)
                    print(f"[EvdevMonitor] Disconnected: {path}")

                await self._poll_buttons()
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"[EvdevMonitor] Error in monitor loop: {e}")
                await asyncio.sleep(1)

    @staticmethod
    def _is_gamepad(device: InputDevice) -> bool:
        try:
            caps = device.capabilities()
            keys = caps.get(ecodes.EV_KEY, [])
            return any(0x120 <= code <= 0x13f for code in keys)
        except Exception: return False

    @staticmethod
    def _detect_analog_triggers(device: InputDevice) -> Optional[dict[int, int]]:
        try:
            caps = device.capabilities()
            abs_axes = dict(caps.get(ecodes.EV_ABS, []))
            def real_trigger_max(axis: int) -> Optional[int]:
                if axis not in abs_axes: return None
                info = abs_axes[axis]
                return info.max if info.min >= 0 and info.max > 0 else None
            for left, right in ((ecodes.ABS_GAS, ecodes.ABS_BRAKE), (ecodes.ABS_Z, ecodes.ABS_RZ)):
                l_max = real_trigger_max(left); r_max = real_trigger_max(right)
                if l_max is not None and r_max is not None: return {left: l_max, right: r_max}
            return None
        except Exception: return None

    async def _check_combo(self, path: str):
        now = time.monotonic()
        if now < self._ignore_until.get(path, 0.0): return
        if now - self._last_fired.get(path, 0.0) < COMBO_COOLDOWN: return
        held = self._held_buttons.get(path, set())
        triggers = self._trigger_values.get(path, {})
        press_time = self._button_press_time.get(path, {})
        def recently_pressed(code: int) -> bool:
            if code in held: return True
            t = press_time.get(code)
            return t is not None and (now - t) <= COMBO_WINDOW
        for combo in _BUTTON_COMBOS:
            if all(recently_pressed(code) for code in combo):
                self._last_fired[path] = now
                if self.on_button_press: await self.on_button_press(path, 0)
                return
        trigger_max = self._trigger_max.get(path)
        if trigger_max:
            if all(triggers.get(axis, 0) >= trigger_max[axis] * TRIGGER_THRESHOLD_FRACTION for axis in trigger_max):
                self._last_fired[path] = now
                if self.on_button_press: await self.on_button_press(path, 0)

    async def _poll_buttons(self):
        if not self._devices: return
        fd_map: dict[int, tuple[str, InputDevice]] = {}
        stale: list[str] = []
        for path, dev in self._devices.items():
            try: fd_map[dev.fd] = (path, dev)
            except Exception: stale.append(path)
        for path in stale:
            self._devices.pop(path, None); self._held_buttons.pop(path, None)
            self._trigger_values.pop(path, None); self._trigger_max.pop(path, None)
            self._ignore_until.pop(path, None); self._button_press_time.pop(path, None)
            self._input_axis_triggered.pop(path, None); self._start_button.pop(path, None)
        if not fd_map: return
        loop = asyncio.get_event_loop()
        try:
            readable, _, _ = await loop.run_in_executor(None, lambda: select.select(list(fd_map.keys()), [], [], 0.05))
        except Exception: return
        readable_paths: set[str] = set()
        for fd in readable:
            entry = fd_map.get(fd)
            if not entry: continue
            path, device = entry
            readable_paths.add(path)
            try:
                for event in device.read():
                    if event.type == ecodes.EV_KEY:
                        held = self._held_buttons.setdefault(path, set())
                        if event.value == 1:
                            held.add(event.code)
                            self._button_press_time.setdefault(path, {})[event.code] = time.monotonic()
                            if self.on_input: await self.on_input(path)
                            if event.code == self._start_button.get(path, ecodes.BTN_START) and self.on_start_pressed: await self.on_start_pressed(path)
                        elif event.value == 0: held.discard(event.code)
                    elif event.type == ecodes.EV_ABS and event.code in self._trigger_max.get(path, {}):
                        axis_map = self._trigger_values.setdefault(path, {})
                        axis_map[event.code] = event.value
                        triggered = self._input_axis_triggered.setdefault(path, set())
                        tmax = self._trigger_max[path][event.code]
                        if event.value >= tmax * 0.75 and event.code not in triggered:
                            triggered.add(event.code)
                            if self.on_input: await self.on_input(path)
                        elif event.value < tmax * 0.25 and event.code in triggered: triggered.discard(event.code)
                await self._check_combo(path)
            except OSError:
                self._devices.pop(path, None); self._held_buttons.pop(path, None)
                self._trigger_values.pop(path, None); self._trigger_max.pop(path, None)
                self._ignore_until.pop(path, None); self._button_press_time.pop(path, None)
                self._input_axis_triggered.pop(path, None); self._start_button.pop(path, None)
            except Exception: pass
        for path, held in list(self._held_buttons.items()):
            if held and path not in readable_paths: await self._check_combo(path)
