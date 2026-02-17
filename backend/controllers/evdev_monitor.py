"""Async evdev device monitoring for controller connect/disconnect and button presses."""

import asyncio
import os
import struct
import select
from typing import Callable, Optional, Any

from evdev import InputDevice, ecodes, list_devices


class EvdevMonitor:
    def __init__(self):
        self.on_connected: Optional[Callable] = None  # async callback(device_info: dict)
        self.on_disconnected: Optional[Callable] = None  # async callback(device_path: str)
        self.on_button_press: Optional[Callable] = None  # async callback(device_path: str, button_code: int)
        self._running = False
        self._known_paths: set[str] = set()
        # Persistent device handles for button polling (path -> InputDevice)
        self._devices: dict[str, InputDevice] = {}

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
                        info = self._get_device_info(device)
                        self._known_paths.add(path)
                        # Keep a persistent handle for button polling
                        self._devices[path] = device

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
                    if self.on_disconnected:
                        await self.on_disconnected(path)
                    print(f"[EvdevMonitor] Disconnected: {path}")

                # Monitor button presses on known devices
                await self._poll_buttons()

                await asyncio.sleep(0.1)

            except Exception as e:
                print(f"[EvdevMonitor] Error in monitor loop: {e}")
                await asyncio.sleep(1)

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
                for event in device.read():
                    if event.type == ecodes.EV_KEY and event.value == 1:
                        if event.code in (ecodes.BTN_START, ecodes.BTN_TR2):
                            if self.on_button_press:
                                await self.on_button_press(path, event.code)
            except OSError:
                # Device was removed mid-read
                self._devices.pop(path, None)
            except Exception:
                pass
