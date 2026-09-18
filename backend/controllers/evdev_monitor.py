"""Async evdev device monitoring for controller connect/disconnect and button presses."""

import asyncio
import os
import struct
import select
import time
from typing import Callable, Optional

from evdev import AbsInfo, InputDevice, UInput, ecodes, list_devices
from database import get_type_default

# Wii Remote (hid-wiimote) VID/PID.
_WIIMOTE_VENDOR = 0x057E
_WIIMOTE_PRODUCT = 0x0306

# Identity every synthetic bridge device reports (see _create_bridge's
# docstring for why this is a fixed ID rather than each bridge's own real
# device's VID/PID) - reuses the Wii Remote's own, since it's confirmed both
# to get proper non-root read permissions AND to produce correct, unscrambled
# button numbering (Xbox 360's ID also got permissions, but produced visibly
# scrambled compass-button results for the Joy-Con (L) bridge - Mesen or
# something underneath it likely applies known-controller-specific button
# position handling for a recognized ID like that, rather than reading the
# raw codes directly).
_BRIDGE_VENDOR = _WIIMOTE_VENDOR
_BRIDGE_PRODUCT = _WIIMOTE_PRODUCT

# Evdev codes the synthetic Wii Remote bridge device exposes. The D-pad is
# reported as a genuine ABS_HAT0X/Y hat switch, not BTN_DPAD_* - Mesen's fixed
# evdev enum (and most emulators generally) only recognizes D-pads reported the
# classic way every real gamepad has used for decades; BTN_DPAD_* is a newer,
# much less universally-supported kernel addition that Mesen doesn't read at all
# (confirmed: it didn't register in Mesen's own input listener).
_WIIMOTE_BRIDGE_KEY_CAPS = [
    ecodes.BTN_A, ecodes.BTN_B, ecodes.BTN_C, ecodes.BTN_Y, ecodes.BTN_Z, ecodes.BTN_TL,
    ecodes.BTN_MODE, ecodes.BTN_SELECT, ecodes.BTN_START,
]
_WIIMOTE_BRIDGE_ABS_CAPS = [
    (ecodes.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
    (ecodes.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
]

# hid-wiimote reports A/B/Home as normal gamepad codes (passed straight through),
# but "+"/"-" as media keys, which Mesen's fixed evdev enum doesn't understand.
# Translate them into codes it does. The D-pad is handled separately (see
# _update_dpad_axis) since it becomes an analog hat, not simple button
# passthrough.
#
# 1/2 are the only two buttons reachable in the standard sideways hold, but
# they need to mean different things on a 2-button console (Nes/Gameboy) vs. a
# 4-button one (Snes): 1=B/2=A for the former, 1=Y/2=B for the latter (see
# mesen.py CONTROLLER_PROFILES["wii"]'s per_system tables and the "button
# evolution" discussion that motivated it). Rather than have the bridge guess
# which console is active, each press emits BOTH codes at once - each system's
# profile only reads the pair meant for it, so the other pair is simply never
# looked at and never causes an unwanted double-input.
#
# The real A/B buttons pass straight through for Nes/Gameboy (as before), and
# additionally each emits one more, exclusive code so Snes games - which use
# all four face buttons - can use them to fill in X/A (SNES has no use for a
# fifth/sixth input, so no third code is needed here): real B -> East (SNES A),
# real A -> North (SNES X).
_WIIMOTE_TRANSLATE: dict[int, tuple[int, ...]] = {
    ecodes.BTN_A: (ecodes.BTN_A, ecodes.BTN_Z),  # Nes/Gameboy: A, Snes: X (North)
    ecodes.BTN_B: (ecodes.BTN_B, ecodes.BTN_TL),  # Nes/Gameboy: B, Snes: A (East)
    ecodes.BTN_MODE: (ecodes.BTN_MODE,),
    ecodes.BTN_1: (ecodes.BTN_B, ecodes.BTN_Y),  # Nes/Gameboy: B, Snes: Y
    ecodes.BTN_2: (ecodes.BTN_A, ecodes.BTN_C),  # Nes/Gameboy: A, Snes: B
    ecodes.KEY_PREVIOUS: (ecodes.BTN_SELECT,),  # "-"
    ecodes.KEY_NEXT: (ecodes.BTN_START,),  # "+"
}

# D-pad keys that feed the synthetic hat, rotated 90 degrees for the standard
# sideways hold: physical Up -> NES Left, Right -> NES Up, Down -> NES Right,
# Left -> NES Down. Each entry is (axis, value-when-held).
_WIIMOTE_DPAD_AXES: dict[int, tuple[int, int]] = {
    ecodes.KEY_UP: (ecodes.ABS_HAT0X, -1),
    ecodes.KEY_DOWN: (ecodes.ABS_HAT0X, 1),
    ecodes.KEY_RIGHT: (ecodes.ABS_HAT0Y, -1),
    ecodes.KEY_LEFT: (ecodes.ABS_HAT0Y, 1),
}

# Joy-Con (used solo). Left is 0x2006, Right is 0x2007 (also used in
# state_manager.py's combined-Joy-Con detection and mesen.py's joycon_r profile).
_JOYCON_VENDOR = 0x057E
_JOYCON_L_PRODUCT = 0x2006

# Joy-Con (L)'s four "diamond" buttons are semantically a D-pad, so hid_nintendo
# reports them as BTN_DPAD_UP/DOWN/LEFT/RIGHT - but here they're used as action
# buttons (jump/speed/paddles/select), not movement (the stick handles that), so
# unlike the Wii Remote's D-pad this needs a plain button remap, not a hat axis.
# Mesen's fixed evdev enum doesn't read BTN_DPAD_* at all (confirmed: same as
# the Wii Remote, it didn't register in Mesen's own input listener), so they're
# translated to fresh, arithmetic-safe slots nothing else on this device uses
# (it has no round face buttons of its own, so slots 0/1/3/4 are free) - which
# of these ends up meaning what (jump vs. paddle vs. select) is then decided
# per-system in mesen.py's per_system tables, same as every other profile.
_JOYCON_L_TRANSLATE: dict[int, tuple[int, ...]] = {
    ecodes.BTN_DPAD_UP: (ecodes.BTN_A,),
    ecodes.BTN_DPAD_DOWN: (ecodes.BTN_B,),
    ecodes.BTN_DPAD_LEFT: (ecodes.BTN_X,),
    ecodes.BTN_DPAD_RIGHT: (ecodes.BTN_Y,),
}

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
    frozenset({ecodes.BTN_A, ecodes.BTN_B}),          # Wii Remote/Classic: A + B
]


class EvdevMonitor:
    def __init__(self):
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        self.on_button_press: Optional[Callable] = None
        self.on_input: Optional[Callable] = None
        self.on_start_pressed: Optional[Callable] = None
        self.on_raw_input: Optional[Callable] = None
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
        # Device path currently streaming every raw key/axis event (for the
        # Input Config screen) plus its cached axis ranges.
        self._focus_path: Optional[str] = None
        self._focus_abs_info: dict[int, tuple[int, int]] = {}
        # Bridge bookkeeping (see _create_bridge): real device path -> synthetic
        # UInput device, its per-device event-handling config, and the path
        # translation between real and bridge paths. Everywhere else in this
        # class, "path" always means the real device path; only callbacks out to
        # the rest of the app use the public (bridge) path.
        self._bridges: dict[str, UInput] = {}
        self._bridge_configs: dict[str, dict] = {}
        self._real_to_bridge: dict[str, str] = {}
        self._bridge_to_real: dict[str, str] = {}
        # real device path -> {evdev key code -> held?} for a bridge's D-pad-as-
        # hat keys (e.g. the Wii Remote's), used to compute the current axis value.
        self._dpad_axis_held: dict[str, dict[int, bool]] = {}

    def stop(self):
        self._running = False

    def to_public_path(self, path: str) -> str:
        return self._real_to_bridge.get(path, path)

    def to_real_path(self, path: Optional[str]) -> Optional[str]:
        if path is None:
            return None
        return self._bridge_to_real.get(path, path)

    def set_focus(self, path: Optional[str]):
        """Stream every raw EV_KEY/EV_ABS event for this device path via on_raw_input."""
        path = self.to_real_path(path)
        self._focus_path = path
        self._focus_abs_info = {}
        device = self._devices.get(path) if path else None
        if device is not None:
            try:
                for code, info in device.capabilities(absinfo=True).get(ecodes.EV_ABS, []):
                    self._focus_abs_info[code] = (info.min, info.max)
            except Exception:
                pass

    @staticmethod
    def _code_names(kind: str, code: int) -> list[str]:
        table = ecodes.keys if kind == "key" else ecodes.ABS
        name = table.get(code, str(code))
        return list(name) if isinstance(name, tuple) else [name]

    def update_start_button_for_path(self, path: str, tr2_is_start: bool, start_button_override: Optional[int] = None):
        """Update the start button for a specific device path."""
        path = self.to_real_path(path)
        if start_button_override is not None:
            self._start_button[path] = start_button_override
        else:
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

    @staticmethod
    def _is_wiimote_info(info: dict) -> bool:
        return info.get("vendor_id") == _WIIMOTE_VENDOR and info.get("product_id") == _WIIMOTE_PRODUCT

    @staticmethod
    def _is_joycon_l_info(info: dict) -> bool:
        return info.get("vendor_id") == _JOYCON_VENDOR and info.get("product_id") == _JOYCON_L_PRODUCT

    def _create_bridge(
        self, real_path: str, device: InputDevice, *,
        name: str, key_caps: list[int], abs_caps: list[tuple],
        translate: Optional[dict[int, tuple[int, ...]]] = None,
        dpad_axes: Optional[dict[int, tuple[int, int]]] = None,
        passthrough_keys: Optional[set[int]] = None,
        passthrough_abs: Optional[set[int]] = None,
    ) -> None:
        """Create a synthetic gamepad that translates/passes through a real
        device's input, then exclusively grab the real device so nothing
        downstream ever reads its raw codes directly.

        Requires write access to /dev/uinput (e.g. membership in the "input"
        group plus a udev rule granting it, or root). If that's unavailable,
        this silently falls back to the device's un-bridged behavior.

        Deliberately reports itself as a generic Xbox 360 controller (see
        _BRIDGE_VENDOR/_BRIDGE_PRODUCT) rather than the real device's own
        vendor/product: confirmed empirically that udev on this system (likely
        because joycond expects exclusive access to raw Joy-Cons) never grants
        a synthetic device non-root read access under a Joy-Con's own PID, even
        with identical capabilities - while a well-known, universally-whitelisted
        PID like the Xbox 360 controller's reliably does. This has no effect on
        Mesen (which reads capabilities, not device identity, matching how our
        own _resolve_mesen_ports counts pads) or on this app's own controller
        tracking (which uses the real device's info, not the bridge's).
        """
        try:
            bridge = UInput(
                {ecodes.EV_KEY: key_caps, ecodes.EV_ABS: abs_caps},
                name=name, vendor=_BRIDGE_VENDOR, product=_BRIDGE_PRODUCT,
                version=1, bustype=device.info.bustype,
            )
        except Exception as e:
            print(f"[EvdevMonitor] Could not create bridge for {name} (check /dev/uinput permissions): {e}")
            return
        try:
            device.grab()
        except Exception as e:
            print(f"[EvdevMonitor] Could not grab {name} for bridging: {e}")
            bridge.close()
            return
        bridge_path = bridge.device.path
        self._known_paths.add(bridge_path)
        self._bridges[real_path] = bridge
        self._bridge_configs[real_path] = {
            "translate": translate or {},
            "dpad_axes": dpad_axes or {},
            "passthrough_keys": passthrough_keys or set(),
            "passthrough_abs": passthrough_abs or set(),
        }
        self._real_to_bridge[real_path] = bridge_path
        self._bridge_to_real[bridge_path] = real_path
        if dpad_axes:
            self._dpad_axis_held[real_path] = {}
        print(f"[EvdevMonitor] Bridged {name}: {real_path} -> {bridge_path}")

    def _create_wiimote_bridge(self, real_path: str, device: InputDevice) -> None:
        self._create_bridge(
            real_path, device,
            name="Nintendo Wii Remote (Bridge)",
            key_caps=_WIIMOTE_BRIDGE_KEY_CAPS, abs_caps=_WIIMOTE_BRIDGE_ABS_CAPS,
            translate=_WIIMOTE_TRANSLATE, dpad_axes=_WIIMOTE_DPAD_AXES,
        )

    def _create_joycon_l_bridge(self, real_path: str, device: InputDevice) -> None:
        """Unlike the Wii Remote, only the diamond buttons need translating -
        everything else (stick, SL/SR, -, capture, stick click) already works
        and just needs to keep working, so it's passed through unchanged rather
        than needing every one of its codes hand-enumerated."""
        try:
            caps = device.capabilities(absinfo=True)
        except Exception as e:
            print(f"[EvdevMonitor] Could not read Joy-Con (L) capabilities: {e}")
            return
        real_keys = set(caps.get(ecodes.EV_KEY, []))
        passthrough_keys = real_keys - set(_JOYCON_L_TRANSLATE.keys())
        translate_targets = {t for targets in _JOYCON_L_TRANSLATE.values() for t in targets}
        abs_caps = caps.get(ecodes.EV_ABS, [])
        passthrough_abs = {code for code, _ in abs_caps}
        self._create_bridge(
            real_path, device,
            name="Joy-Con (L) (Bridge)",
            key_caps=list(passthrough_keys | translate_targets), abs_caps=abs_caps,
            translate=_JOYCON_L_TRANSLATE,
            passthrough_keys=passthrough_keys, passthrough_abs=passthrough_abs,
        )

    def _update_dpad_axis(self, real_path: str, bridge: UInput, dpad_axes: dict[int, tuple[int, int]], code: int, value: int) -> None:
        """Recompute a synthetic hat's axis values from which D-pad keys are
        currently held, and write whichever axis this key affects."""
        axis, held_value = dpad_axes[code]
        held = self._dpad_axis_held.setdefault(real_path, {})
        held[code] = bool(value)
        # The two keys sharing this axis are always adjacent in dpad_axes'
        # iteration; find the other one to resolve the axis to 0/±1.
        other_code = next(
            c for c, (a, _) in dpad_axes.items() if a == axis and c != code
        )
        if held.get(code):
            new_value = held_value
        elif held.get(other_code):
            new_value = dpad_axes[other_code][1]
        else:
            new_value = 0
        bridge.write(ecodes.EV_ABS, axis, new_value)
        bridge.syn()

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
                        if self._is_wiimote_info(info):
                            self._create_wiimote_bridge(path, device)
                        elif self._is_joycon_l_info(info):
                            self._create_joycon_l_bridge(path, device)
                        if path in self._real_to_bridge:
                            info = {**info, "device_path": self._real_to_bridge[path]}
                        if self.on_connected: await self.on_connected(info)
                        print(f"[EvdevMonitor] Connected: {device.name} ({path}) GUID={info['guid']} port={info['port']}")
                    except Exception as e: print(f"[EvdevMonitor] Error reading new device {path}: {e}")

                removed_paths = self._known_paths - current_paths
                for path in removed_paths:
                    if path in self._bridge_to_real:
                        # Cleanup happens below when the real device is removed.
                        continue
                    self._known_paths.discard(path)
                    self._devices.pop(path, None); self._held_buttons.pop(path, None)
                    self._trigger_values.pop(path, None); self._last_fired.pop(path, None)
                    self._trigger_max.pop(path, None); self._ignore_until.pop(path, None)
                    self._button_press_time.pop(path, None); self._input_axis_triggered.pop(path, None)
                    self._start_button.pop(path, None)
                    if self._focus_path == path: self.set_focus(None)
                    # Resolve and notify before tearing down the bridge mapping, so
                    # callbacks can still translate the public path back to this
                    # real one (e.g. to unregister the real path from battery monitoring).
                    public_path = self.to_public_path(path)
                    if self.on_disconnected: await self.on_disconnected(public_path)
                    bridge = self._bridges.pop(path, None)
                    if bridge is not None:
                        self._bridge_configs.pop(path, None)
                        self._real_to_bridge.pop(path, None)
                        self._bridge_to_real.pop(public_path, None)
                        self._known_paths.discard(public_path)
                        self._dpad_axis_held.pop(path, None)
                        try: bridge.close()
                        except Exception: pass
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
        # A device being tested in the Input Config screen shouldn't be readied
        # by combo presses - that screen is for inspecting raw input, not play.
        if path == self._focus_path: return
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
                if self.on_button_press: await self.on_button_press(self.to_public_path(path), 0)
                return
        trigger_max = self._trigger_max.get(path)
        if trigger_max:
            if all(triggers.get(axis, 0) >= trigger_max[axis] * TRIGGER_THRESHOLD_FRACTION for axis in trigger_max):
                self._last_fired[path] = now
                if self.on_button_press: await self.on_button_press(self.to_public_path(path), 0)

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
                    if path == self._focus_path and self.on_raw_input:
                        if event.type == ecodes.EV_KEY:
                            await self.on_raw_input(self.to_public_path(path), "key", self._code_names("key", event.code), event.value, None, None)
                        elif event.type == ecodes.EV_ABS:
                            mn, mx = self._focus_abs_info.get(event.code, (None, None))
                            await self.on_raw_input(self.to_public_path(path), "abs", self._code_names("abs", event.code), event.value, mn, mx)
                    bridge = self._bridges.get(path)
                    if bridge is not None:
                        config = self._bridge_configs[path]
                        if event.type == ecodes.EV_KEY:
                            if event.code in config["dpad_axes"]:
                                self._update_dpad_axis(path, bridge, config["dpad_axes"], event.code, event.value)
                            elif event.code in config["translate"]:
                                for target in config["translate"][event.code]:
                                    bridge.write(ecodes.EV_KEY, target, event.value)
                                bridge.syn()
                            elif event.code in config["passthrough_keys"]:
                                bridge.write(ecodes.EV_KEY, event.code, event.value)
                                bridge.syn()
                        elif event.type == ecodes.EV_ABS and event.code in config["passthrough_abs"]:
                            bridge.write(ecodes.EV_ABS, event.code, event.value)
                            bridge.syn()
                    if event.type == ecodes.EV_KEY:
                        held = self._held_buttons.setdefault(path, set())
                        if event.value == 1:
                            held.add(event.code)
                            self._button_press_time.setdefault(path, {})[event.code] = time.monotonic()
                            if self.on_input: await self.on_input(self.to_public_path(path))
                            if (
                                path != self._focus_path
                                and event.code == self._start_button.get(path, ecodes.BTN_START)
                                and self.on_start_pressed
                            ): await self.on_start_pressed(self.to_public_path(path))
                        elif event.value == 0: held.discard(event.code)
                    elif event.type == ecodes.EV_ABS and event.code in self._trigger_max.get(path, {}):
                        axis_map = self._trigger_values.setdefault(path, {})
                        axis_map[event.code] = event.value
                        triggered = self._input_axis_triggered.setdefault(path, set())
                        tmax = self._trigger_max[path][event.code]
                        if event.value >= tmax * 0.75 and event.code not in triggered:
                            triggered.add(event.code)
                            if self.on_input: await self.on_input(self.to_public_path(path))
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
