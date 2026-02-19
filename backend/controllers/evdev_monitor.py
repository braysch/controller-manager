"""Async evdev device monitoring for controller connect/disconnect and button presses."""

import asyncio
import os
import struct
import select
import time
from typing import Callable, Optional

from evdev import InputDevice, ecodes, list_devices

# Fraction of an axis's maximum value that counts as "pressed" for combo detection
TRIGGER_THRESHOLD_FRACTION = 0.5
# Seconds before the same device can fire the combo again
COMBO_COOLDOWN = 1.5

# Button combos: every button in a frozenset must be held simultaneously.
# Listed in order of precedence; first match wins.
_BUTTON_COMBOS: list[frozenset] = [
    frozenset({ecodes.BTN_TL, ecodes.BTN_TR}),        # both bumpers (standard / paired Joy-Cons)
    frozenset({ecodes.BTN_TL2, ecodes.BTN_TR2}),      # both digital triggers (standard / paired Joy-Cons)
    frozenset({ecodes.BTN_TR, ecodes.BTN_TR2}),       # Left Joy-Con alone (SL + SR)
    frozenset({ecodes.BTN_TL, ecodes.BTN_TL2}),       # Right Joy-Con alone (SL + SR)
    frozenset({ecodes.BTN_WEST, ecodes.BTN_Z}),       # SNES: BTN_WEST + BTN_Z
    frozenset({ecodes.BTN_Y, ecodes.BTN_Z}),          # SNES: BTN_Y + BTN_Z
]


class EvdevMonitor:
    def __init__(self):
        self.on_connected: Optional[Callable] = None  # async callback(device_info: dict)
        self.on_disconnected: Optional[Callable] = None  # async callback(device_path: str)
        self.on_button_press: Optional[Callable] = None  # async callback(device_path: str, button_code: int)
        self._running = False
        self._known_paths: set[str] = set()
        # Persistent device handles for button polling (path -> InputDevice)
        self._devices: dict[str, InputDevice] = {}
        # Currently held buttons per device
        self._held_buttons: dict[str, set[int]] = {}
        # Latest analog trigger axis values per device {path: {axis_code: value}}
        self._trigger_values: dict[str, dict[int, int]] = {}
        # monotonic timestamp of last combo fire per device (for cooldown)
        self._last_fired: dict[str, float] = {}
        # Per-device analog trigger axis maxima: path -> {axis_code: max_val}
        # Empty dict means the device has no real analog triggers.
        self._trigger_max: dict[str, dict[int, int]] = {}
        # Ignore combo events until this monotonic time (skips init state sync)
        self._ignore_until: dict[str, float] = {}

    def stop(self):
        self._running = False

    @staticmethod
    def _compute_sdl_guid(device: InputDevice) -> str:
        """Compute SDL2-format GUID from evdev device info.

        SDL2 computes Linux joystick GUIDs as:
        bustype(le16) 0000 vendor(le16) 0000 product(le16) 0000 version(le16) 0000
        encoded as a 32-char lowercase hex string.
        """
        bus = device.info.bustype
        vendor = device.info.vendor
        product = device.info.product
        version = device.info.version

        # Pack as little-endian uint16 values with zero padding between each
        raw = struct.pack('<HHHHHHHH',
                          bus, 0,
                          vendor, 0,
                          product, 0,
                          version, 0)
        return raw.hex()

    @staticmethod
    def _get_js_index(device_path: str) -> int:
        """Resolve the /dev/input/jsN index for a given event device.

        Walks sysfs to find the js device that shares the same input parent.
        Falls back to event device number if no js device is found.
        """
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
                            if js_real == event_real:
                                return int(entry[2:])
        except (OSError, ValueError):
            pass

        try:
            return int(event_name.replace("event", ""))
        except ValueError:
            return 0

    def _get_device_info(self, device: InputDevice) -> dict:
        """Extract device info from an evdev InputDevice."""
        uniq = device.uniq or ""
        vendor = device.info.vendor
        product = device.info.product

        bus = device.info.bustype
        connection_type = "bluetooth" if bus == 0x05 else "usb"

        if uniq and uniq.strip():
            unique_id = uniq.strip()
        else:
            unique_id = f"{vendor:04x}:{product:04x}:{device.name}"

        guid = self._compute_sdl_guid(device)
        port = self._get_js_index(device.path)

        return {
            "device_path": device.path,
            "name": device.name,
            "unique_id": unique_id,
            "vendor_id": vendor,
            "product_id": product,
            "connection_type": connection_type,
            "bus_type": bus,
            "guid": guid,
            "port": port,
        }

    async def run(self):
        """Main monitoring loop."""
        self._running = True
        print("[EvdevMonitor] Starting device monitoring")

        while self._running:
            try:
                current_paths = set(list_devices())

                # Detect new devices
                new_paths = current_paths - self._known_paths
                for path in new_paths:
                    try:
                        device = InputDevice(path)
                        if not self._is_gamepad(device):
                            self._known_paths.add(path)  # mark seen so we don't recheck every loop
                            continue
                        info = self._get_device_info(device)
                        self._known_paths.add(path)
                        # Keep a persistent handle for button polling
                        self._devices[path] = device
                        self._held_buttons[path] = set()
                        self._trigger_values[path] = {}
                        self._ignore_until[path] = time.monotonic() + 1.0
                        self._trigger_max[path] = self._detect_analog_triggers(device) or {}

                        if self.on_connected:
                            await self.on_connected(info)

                        print(f"[EvdevMonitor] Connected: {device.name} ({path}) GUID={info['guid']} port={info['port']}")
                    except Exception as e:
                        print(f"[EvdevMonitor] Error reading new device {path}: {e}")

                # Detect removed devices
                removed_paths = self._known_paths - current_paths
                for path in removed_paths:
                    self._known_paths.discard(path)
                    self._devices.pop(path, None)
                    self._held_buttons.pop(path, None)
                    self._trigger_values.pop(path, None)
                    self._last_fired.pop(path, None)
                    self._trigger_max.pop(path, None)
                    self._ignore_until.pop(path, None)
                    if self.on_disconnected:
                        await self.on_disconnected(path)
                    print(f"[EvdevMonitor] Disconnected: {path}")

                # Monitor button presses on known devices
                await self._poll_buttons()

                await asyncio.sleep(0.1)

            except Exception as e:
                print(f"[EvdevMonitor] Error in monitor loop: {e}")
                await asyncio.sleep(1)

    @staticmethod
    def _is_gamepad(device: InputDevice) -> bool:
        """Return True only if the device has at least one gamepad/joystick button.

        This filters out IMU nodes (accelerometer/gyroscope only — no EV_KEY),
        keyboards, mice, and other non-controller devices that share the same
        /dev/input/ namespace.  Gamepad and joystick button codes live in the
        range 0x120–0x13f (BTN_JOYSTICK through BTN_THUMBR).
        """
        try:
            caps = device.capabilities()
            keys = caps.get(ecodes.EV_KEY, [])
            return any(0x120 <= code <= 0x13f for code in keys)
        except Exception:
            return False

    @staticmethod
    def _detect_analog_triggers(device: InputDevice) -> Optional[dict[int, int]]:
        """Return {axis_code: max_value} for all real analog trigger axes on this device, else None.

        Checks both ABS_Z/ABS_RZ (DS4, Switch Pro, xpadneo) and ABS_BRAKE/ABS_GAS
        (Xbox via hid-xbox/xpad).  Real triggers always have min == 0; IMU/gyro axes
        have negative minimums (e.g. -32767).  Requires at least two qualifying axes
        to form a usable left+right combo.
        """
        try:
            caps = device.capabilities()
            abs_axes = dict(caps.get(ecodes.EV_ABS, []))
            result = {}
            for axis in (ecodes.ABS_Z, ecodes.ABS_RZ, ecodes.ABS_BRAKE, ecodes.ABS_GAS):
                if axis in abs_axes:
                    info = abs_axes[axis]
                    if info.min >= 0:
                        result[axis] = max(info.max, 1)
            return result if len(result) >= 2 else None
        except Exception:
            return None

    async def _check_combo(self, path: str):
        """Fire on_button_press if the current held state matches any combo."""
        now = time.monotonic()
        # Skip events fired during the post-connect initialization window
        if now < self._ignore_until.get(path, 0.0):
            return
        if now - self._last_fired.get(path, 0.0) < COMBO_COOLDOWN:
            return

        held = self._held_buttons.get(path, set())
        triggers = self._trigger_values.get(path, {})

        # Check digital button combos (first match wins)
        for combo in _BUTTON_COMBOS:
            if combo.issubset(held):
                self._last_fired[path] = now
                if self.on_button_press:
                    await self.on_button_press(path, 0)
                return

        # Check analog triggers only for devices with real trigger axes
        trigger_max = self._trigger_max.get(path)
        if trigger_max:
            if all(
                triggers.get(axis, 0) >= trigger_max[axis] * TRIGGER_THRESHOLD_FRACTION
                for axis in trigger_max
            ):
                self._last_fired[path] = now
                if self.on_button_press:
                    await self.on_button_press(path, 0)

    async def _poll_buttons(self):
        """Poll all persistent device handles for button events."""
        if not self._devices:
            return

        # Build fd -> (path, device) mapping from persistent handles
        fd_map: dict[int, tuple[str, InputDevice]] = {}
        stale: list[str] = []
        for path, dev in self._devices.items():
            try:
                fd_map[dev.fd] = (path, dev)
            except Exception:
                stale.append(path)

        for path in stale:
            self._devices.pop(path, None)
            self._held_buttons.pop(path, None)
            self._trigger_values.pop(path, None)
            self._trigger_max.pop(path, None)
            self._ignore_until.pop(path, None)

        if not fd_map:
            return

        loop = asyncio.get_event_loop()
        try:
            readable, _, _ = await loop.run_in_executor(
                None, lambda: select.select(list(fd_map.keys()), [], [], 0.05)
            )
        except Exception:
            return

        for fd in readable:
            entry = fd_map.get(fd)
            if not entry:
                continue
            path, device = entry

            try:
                combo_check_needed = False
                for event in device.read():
                    if event.type == ecodes.EV_KEY:
                        held = self._held_buttons.setdefault(path, set())
                        if event.value == 1:   # key down
                            held.add(event.code)
                            combo_check_needed = True
                        elif event.value == 0:  # key up
                            held.discard(event.code)
                    elif event.type == ecodes.EV_ABS and event.code in self._trigger_max.get(path, {}):
                        axis_map = self._trigger_values.setdefault(path, {})
                        prev = axis_map.get(event.code, 0)
                        axis_map[event.code] = event.value
                        # Only re-check when the axis crosses the per-device activation threshold
                        axis_max = self._trigger_max.get(path, {}).get(event.code, 255)
                        threshold = axis_max * TRIGGER_THRESHOLD_FRACTION
                        if event.value >= threshold and prev < threshold:
                            combo_check_needed = True

                if combo_check_needed:
                    await self._check_combo(path)

            except OSError:
                # Device was removed mid-read
                self._devices.pop(path, None)
                self._held_buttons.pop(path, None)
                self._trigger_values.pop(path, None)
                self._trigger_max.pop(path, None)
                self._ignore_until.pop(path, None)
            except Exception:
                pass
