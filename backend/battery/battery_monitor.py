"""Battery monitoring via /sys/class/power_supply/ sysfs polling."""

import asyncio
import os
from typing import Callable, Optional

import config


class BatteryMonitor:
    def __init__(self):
        self.on_update: Optional[Callable] = None  # async callback(device_path: str, percent: int)
        self._running = False
        # device_path -> last known battery percent
        self._devices: dict[str, Optional[int]] = {}
        # device_path -> power_supply sysfs path (cached)
        self._battery_paths: dict[str, Optional[str]] = {}

    def stop(self):
        self._running = False

    def register_device(self, device_path: str):
        """Register a device for battery monitoring."""
        self._devices[device_path] = None
        # Clear cached battery path so it gets re-discovered
        self._battery_paths.pop(device_path, None)

    def unregister_device(self, device_path: str):
        """Unregister a device from battery monitoring."""
        self._devices.pop(device_path, None)
        self._battery_paths.pop(device_path, None)

    def _find_battery_for_device(self, device_path: str) -> Optional[str]:
        """Find the power_supply sysfs path for an input device.

        Walks the sysfs device tree to find a power_supply entry that shares
        a parent with the input device (scope=Device, type=Battery).
        """
        # device_path is like /dev/input/event23
        event_name = os.path.basename(device_path)
        event_sysfs = f"/sys/class/input/{event_name}/device"

        try:
            device_real = os.path.realpath(event_sysfs)
        except OSError:
            return None

        # Check all power_supply entries
        ps_base = "/sys/class/power_supply"
        if not os.path.isdir(ps_base):
            return None

        for ps_name in os.listdir(ps_base):
            ps_path = os.path.join(ps_base, ps_name)

            # Check if this is a device battery (not system battery)
            scope_file = os.path.join(ps_path, "scope")
            if os.path.exists(scope_file):
                try:
                    with open(scope_file) as f:
                        scope = f.read().strip()
                    if scope != "Device":
                        continue
                except OSError:
                    continue

            # Check type is Battery
            type_file = os.path.join(ps_path, "type")
            if os.path.exists(type_file):
                try:
                    with open(type_file) as f:
                        ps_type = f.read().strip()
                    if ps_type != "Battery":
                        continue
                except OSError:
                    continue

            # Check if this power_supply shares a parent device with our input device
            try:
                ps_device_real = os.path.realpath(os.path.join(ps_path, "device"))
                # Walk up the input device's parent chain to find a match
                parent = device_real
                for _ in range(5):  # Walk up to 5 levels
                    if ps_device_real == parent:
                        return ps_path
                    parent = os.path.dirname(parent)
                    if parent == "/":
                        break
            except OSError:
                continue

        return None

    @staticmethod
    def _read_battery_percent(power_supply_path: str) -> Optional[int]:
        """Read battery capacity percentage from sysfs."""
        capacity_file = os.path.join(power_supply_path, "capacity")
        try:
            with open(capacity_file) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    async def run(self):
        """Main polling loop."""
        self._running = True
        print("[BatteryMonitor] Starting battery monitoring")

        while self._running:
            try:
                for device_path in list(self._devices.keys()):
                    # Find battery path if not cached
                    if device_path not in self._battery_paths:
                        self._battery_paths[device_path] = self._find_battery_for_device(device_path)

                    battery_path = self._battery_paths.get(device_path)
                    if not battery_path:
                        continue

                    percent = self._read_battery_percent(battery_path)
                    if percent is None:
                        continue

                    # Only notify on change
                    last = self._devices.get(device_path)
                    if percent != last:
                        self._devices[device_path] = percent
                        if self.on_update:
                            await self.on_update(device_path, percent)

                await asyncio.sleep(config.BATTERY_POLL_INTERVAL)

            except Exception as e:
                print(f"[BatteryMonitor] Error: {e}")
                await asyncio.sleep(config.BATTERY_POLL_INTERVAL)
