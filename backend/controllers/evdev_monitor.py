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
# e.g. 0.5 means each trigger must be pressed at least halfway (512/1023 for Xbox).
TRIGGER_THRESHOLD_FRACTION = 0.5
# Seconds before the same device can fire the combo again
COMBO_COOLDOWN = 1.5
# How long after a button press it still counts toward a combo, even if released.
# Covers hardware latency between paired Joy-Cons (~1 s on the right Joy-Con).
COMBO_WINDOW = 2.0

# Bumper/trigger button codes used for debug output
_BUMPER_TRIGGER_BTNS: dict[int, str] = {
    ecodes.BTN_TL:  "BTN_TL  (L bumper)",
    ecodes.BTN_TR:  "BTN_TR  (R bumper)",
    ecodes.BTN_TL2: "BTN_TL2 (ZL trigger)",
    ecodes.BTN_TR2: "BTN_TR2 (ZR trigger)",
}

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
        self.on_input: Optional[Callable] = None  # async callback(device_path: str)
        self.on_start_pressed: Optional[Callable] = None  # async callback(device_path: str)
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
        # Monotonic timestamp of the last press for each button per device
        self._button_press_time: dict[str, dict[int, float]] = {}
        # Analog axes that have already crossed the input threshold (rising-edge only)
        self._input_axis_triggered: dict[str, set[int]] = {}
        # Start button code per device (defaults to BTN_START; overridden per profile)
        self._start_button: dict[str, int] = {}

    def stop(self):
        self._running = False

    def update_start_button_for_type(
        self,
        vendor_id: Optional[int],
        product_id: Optional[int],
        default_name: str,
        start_button: Optional[int],
    ) -> None:
        """Refresh the cached start button for all currently connected devices of a given type.

        Called immediately after a user changes the setting in the GUI so the
        change takes effect without requiring a reconnect.
        """
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
            except Exception:
                pass

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
                        self._button_press_time[path] = {}
                        self._input_axis_triggered[path] = set()

                        # Look up the start button for this controller type
                        try:
                            type_default = await get_type_default(device.name, info["vendor_id"], info["product_id"])
                            self._start_button[path] = type_default.start_button if (type_default and type_default.start_button) else ecodes.BTN_START
                        except Exception:
                            self._start_button[path] = ecodes.BTN_START

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
                    self._button_press_time.pop(path, None)
                    self._input_axis_triggered.pop(path, None)
                    self._start_button.pop(path, None)
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
        """Return {left_axis: max, right_axis: max} for the best real analog trigger pair,
        or None if no usable pair is found.

        Some controllers expose multiple trigger axis pairs simultaneously (e.g. Xbox reports
        both ABS_Z/ABS_RZ and ABS_GAS/ABS_BRAKE).  Collecting all of them and requiring
        every one to be above threshold breaks detection because the unused pair never
        updates.  Instead we pick exactly one pair in priority order:
          1. ABS_GAS / ABS_BRAKE  (Xbox via hid-xbox, 0-1023)
          2. ABS_Z  / ABS_RZ     (DS4, Switch Pro, xpadneo)

        A pair qualifies only when both axes have min == 0 and max > 0 (real triggers).
        IMU/gyro axes always have a negative minimum and are excluded.
        """
        try:
            caps = device.capabilities()
            abs_axes = dict(caps.get(ecodes.EV_ABS, []))

            def real_trigger_max(axis: int) -> Optional[int]:
                """Return the axis max if it looks like a real trigger, else None."""
                if axis not in abs_axes:
                    return None
                info = abs_axes[axis]
                return info.max if info.min >= 0 and info.max > 0 else None

            for left, right in (
                (ecodes.ABS_GAS, ecodes.ABS_BRAKE),
                (ecodes.ABS_Z,   ecodes.ABS_RZ),
            ):
                l_max = real_trigger_max(left)
                r_max = real_trigger_max(right)
                if l_max is not None and r_max is not None:
                    return {left: l_max, right: r_max}

            return None
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
        press_time = self._button_press_time.get(path, {})

        def recently_pressed(code: int) -> bool:
            """True if the button is currently held OR was pressed within COMBO_WINDOW seconds.

            Covers hardware latency between Joy-Con pairs: the right Joy-Con can
            lag ~1 s behind the left, so its button event arrives well after the
            left button was pressed and possibly released.
            """
            if code in held:
                return True
            t = press_time.get(code)
            return t is not None and (now - t) <= COMBO_WINDOW

        # Check digital button combos (first match wins)
        for combo in _BUTTON_COMBOS:
            if all(recently_pressed(code) for code in combo):
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
            self._button_press_time.pop(path, None)
            self._input_axis_triggered.pop(path, None)
            self._start_button.pop(path, None)

        if not fd_map:
            return

        loop = asyncio.get_event_loop()
        try:
            readable, _, _ = await loop.run_in_executor(
                None, lambda: select.select(list(fd_map.keys()), [], [], 0.05)
            )
        except Exception:
            return

        readable_paths: set[str] = set()

        for fd in readable:
            entry = fd_map.get(fd)
            if not entry:
                continue
            path, device = entry
            readable_paths.add(path)

            try:
                for event in device.read():
                    if event.type == ecodes.EV_KEY:
                        held = self._held_buttons.setdefault(path, set())
                        if event.value == 1:   # key down
                            held.add(event.code)
                            self._button_press_time.setdefault(path, {})[event.code] = time.monotonic()
                            if self.on_input:
                                await self.on_input(path)
                            if event.code == self._start_button.get(path, ecodes.BTN_START) and self.on_start_pressed:
                                await self.on_start_pressed(path)
                        elif event.value == 0:  # key up
                            held.discard(event.code)
                        if event.code in _BUMPER_TRIGGER_BTNS:
                            state = "DOWN" if event.value == 1 else "UP"
                            print(f"[{device.name}] {_BUMPER_TRIGGER_BTNS[event.code]} {state}")
                    elif event.type == ecodes.EV_ABS and event.code in self._trigger_max.get(path, {}):
                        axis_map = self._trigger_values.setdefault(path, {})
                        prev = axis_map.get(event.code, 0)
                        axis_map[event.code] = event.value
                        # Print analog trigger value changes
                        if event.value != prev:
                            axis_name = ecodes.ABS.get(event.code, str(event.code))
                            if isinstance(axis_name, list):
                                axis_name = axis_name[0]
                            tmax = self._trigger_max[path][event.code]
                            print(f"[{device.name}] {axis_name} ({event.code}) value={event.value}/{tmax}")
                        # Fire on_input on rising edge past 75% of max
                        triggered = self._input_axis_triggered.setdefault(path, set())
                        tmax = self._trigger_max[path][event.code]
                        if event.value >= tmax * 0.75 and event.code not in triggered:
                            triggered.add(event.code)
                            if self.on_input:
                                await self.on_input(path)
                        elif event.value < tmax * 0.25 and event.code in triggered:
                            triggered.discard(event.code)

                # Always check combo state after reading events.  Previously this was
                # gated on combo_check_needed (set only on key-down or threshold
                # crossing), which meant that if the user pressed a combo during the
                # post-connect ignore window and kept holding, no new events would
                # re-set the flag and the combo would never fire.  Calling unconditionally
                # ensures it fires within one poll cycle after the ignore window expires.
                await self._check_combo(path)

            except OSError:
                # Device was removed mid-read
                self._devices.pop(path, None)
                self._held_buttons.pop(path, None)
                self._trigger_values.pop(path, None)
                self._trigger_max.pop(path, None)
                self._ignore_until.pop(path, None)
                self._button_press_time.pop(path, None)
                self._input_axis_triggered.pop(path, None)
                self._start_button.pop(path, None)
            except Exception:
                pass

        # For quiet devices (no constant ABS noise) that weren't readable this cycle
        # but still have inputs held, check the combo so a hold pressed during the
        # ignore window fires as soon as the window expires.
        for path, held in list(self._held_buttons.items()):
            if held and path not in readable_paths:
                await self._check_combo(path)
