"""BlueZ D-Bus Bluetooth manager for controller discovery and pairing."""

import asyncio
from typing import Callable, Optional

from dasbus.connection import SystemMessageBus
from dasbus.identifier import DBusServiceIdentifier
from dasbus.typing import get_variant, Str, Bool

import config

BLUEZ_SERVICE = DBusServiceIdentifier(
    namespace=("org", "bluez"),
    message_bus=SystemMessageBus()
)

# Known controller appearance values and name patterns for filtering
GAMEPAD_APPEARANCES = {0x03C4}  # HID Gamepad
CONTROLLER_NAME_PATTERNS = [
    "xbox", "pro controller", "joy-con", "dualshock", "dualsense",
    "wireless controller", "gamepad", "game controller", "8bitdo",
    "snes", "nes", "gamecube", "wii",
]


class BlueZManager:
    def __init__(self):
        self._bus = None
        self._adapter = None
        self._scanning = False
        self._scan_task: Optional[asyncio.Task] = None
        self._on_device_found: Optional[Callable] = None
        self._on_scan_complete: Optional[Callable] = None

    def _get_bus(self):
        if self._bus is None:
            self._bus = SystemMessageBus()
        return self._bus

    def _get_adapter_path(self) -> Optional[str]:
        """Find the first Bluetooth adapter via BlueZ."""
        try:
            bus = self._get_bus()
            obj_manager = bus.get_proxy(
                "org.bluez",
                "/",
                "org.freedesktop.DBus.ObjectManager"
            )
            objects = obj_manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if "org.bluez.Adapter1" in interfaces:
                    return str(path)
        except Exception as e:
            print(f"[BlueZ] Error finding adapter: {e}")
        return None

    def _is_controller(self, properties: dict) -> bool:
        """Check if a discovered device looks like a game controller."""
        name = str(properties.get("Name", properties.get("Alias", ""))).lower()
        appearance_var = properties.get("Appearance")
        appearance = appearance_var.unpack() if appearance_var is not None else 0

        if appearance in GAMEPAD_APPEARANCES:
            return True

        for pattern in CONTROLLER_NAME_PATTERNS:
            if pattern in name:
                return True

        # Check device class - gamepads are in the Peripheral major class (0x0500)
        class_var = properties.get("Class")
        device_class = class_var.unpack() if class_var is not None else 0
        if device_class:
            major = (device_class >> 8) & 0x1F
            minor = (device_class >> 2) & 0x3F
            # Major 0x05 = Peripheral, Minor 0x01 = Joystick, 0x02 = Gamepad
            if major == 0x05 and minor in (0x01, 0x02):
                return True

        return False

    async def start_scan(self, on_device_found: Callable, on_scan_complete: Callable):
        """Start Bluetooth discovery for game controllers."""
        if self._scanning:
            return

        self._on_device_found = on_device_found
        self._on_scan_complete = on_scan_complete
        self._scanning = True

        self._scan_task = asyncio.create_task(self._run_scan())

    async def _run_scan(self):
        """Run the Bluetooth scan with auto-stop timeout."""
        adapter_path = self._get_adapter_path()
        if not adapter_path:
            print("[BlueZ] No Bluetooth adapter found")
            self._scanning = False
            if self._on_scan_complete:
                await self._on_scan_complete()
            return

        try:
            bus = self._get_bus()
            adapter = bus.get_proxy("org.bluez", adapter_path, "org.bluez.Adapter1")

            # Reset any leftover discovery session (e.g. from a previous crash)
            try:
                adapter.StopDiscovery()
            except Exception:
                pass

            # Start discovery
            try:
                adapter.StartDiscovery()
            except Exception as e:
                print(f"[BlueZ] StartDiscovery failed: {e}")
                self._scanning = False
                if self._on_scan_complete:
                    await self._on_scan_complete()
                return

            print(f"[BlueZ] Scanning for {config.BLUETOOTH_SCAN_DURATION}s...")

            # Poll for new devices during the scan duration
            seen_addresses: set[str] = set()
            elapsed = 0.0
            poll_interval = 1.0

            while elapsed < config.BLUETOOTH_SCAN_DURATION and self._scanning:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                try:
                    obj_manager = bus.get_proxy(
                        "org.bluez",
                        "/",
                        "org.freedesktop.DBus.ObjectManager"
                    )
                    objects = obj_manager.GetManagedObjects()

                    for path, interfaces in objects.items():
                        if "org.bluez.Device1" not in interfaces:
                            continue

                        props = interfaces["org.bluez.Device1"]
                        address = str(props.get("Address", ""))
                        if not address or address in seen_addresses:
                            continue

                        if self._is_controller(props):
                            seen_addresses.add(address)
                            name = str(props.get("Name", props.get("Alias", "Unknown")))
                            if self._on_device_found:
                                await self._on_device_found(name, address)

                except Exception as e:
                    print(f"[BlueZ] Error polling devices: {e}")

            # Stop discovery
            try:
                adapter.StopDiscovery()
            except Exception:
                pass

        except Exception as e:
            print(f"[BlueZ] Scan error: {e}")
        finally:
            self._scanning = False
            if self._on_scan_complete:
                await self._on_scan_complete()
            print("[BlueZ] Scan complete")

    async def stop_scan(self):
        """Stop an active Bluetooth scan."""
        self._scanning = False
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

        # Try to stop discovery on the adapter
        adapter_path = self._get_adapter_path()
        if adapter_path:
            try:
                bus = self._get_bus()
                adapter = bus.get_proxy("org.bluez", adapter_path, "org.bluez.Adapter1")
                adapter.StopDiscovery()
            except Exception:
                pass

    def _find_device_path(self, address: str) -> Optional[str]:
        """Return the D-Bus object path for a device by MAC address, or None."""
        try:
            bus = self._get_bus()
            obj_manager = bus.get_proxy("org.bluez", "/", "org.freedesktop.DBus.ObjectManager")
            objects = obj_manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if "org.bluez.Device1" not in interfaces:
                    continue
                props = interfaces["org.bluez.Device1"]
                if str(props.get("Address", "")).upper() == address.upper():
                    return str(path)
        except Exception as e:
            print(f"[BlueZ] Error searching for device {address}: {e}")
        return None

    def _remove_device(self, device_path: str) -> bool:
        """Remove a device object from BlueZ via the adapter."""
        try:
            adapter_path = self._get_adapter_path()
            if not adapter_path:
                return False
            bus = self._get_bus()
            adapter = bus.get_proxy("org.bluez", adapter_path, "org.bluez.Adapter1")
            adapter.RemoveDevice(device_path)
            print(f"[BlueZ] Removed device {device_path}")
            return True
        except Exception as e:
            print(f"[BlueZ] Failed to remove device {device_path}: {e}")
            return False

    async def force_pair_device(self, address: str) -> bool:
        """Remove the device from BlueZ then rediscover and pair from scratch."""
        # Remove existing entry if BlueZ knows about it
        existing_path = self._find_device_path(address)
        if existing_path:
            self._remove_device(existing_path)
            await asyncio.sleep(0.5)

        # Start discovery so BlueZ can rediscover the device
        adapter_path = self._get_adapter_path()
        if not adapter_path:
            return False

        bus = self._get_bus()
        adapter = bus.get_proxy("org.bluez", adapter_path, "org.bluez.Adapter1")
        try:
            adapter.StartDiscovery()
        except Exception:
            pass

        print(f"[BlueZ] Waiting for {address} to reappear for re-pairing...")

        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 15.0
            obj_manager = bus.get_proxy("org.bluez", "/", "org.freedesktop.DBus.ObjectManager")

            while loop.time() < deadline:
                await asyncio.sleep(1.0)
                objects = obj_manager.GetManagedObjects()
                for path, interfaces in objects.items():
                    if "org.bluez.Device1" not in interfaces:
                        continue
                    props = interfaces["org.bluez.Device1"]
                    if str(props.get("Address", "")).upper() == address.upper():
                        print(f"[BlueZ] {address} reappeared, pairing...")
                        try:
                            adapter.StopDiscovery()
                        except Exception:
                            pass
                        # _allow_force_retry=False prevents an infinite remove→rediscover loop
                        return await self.pair_device(address, _allow_force_retry=False)

            print(f"[BlueZ] Timeout: {address} did not reappear within 15 s")
            return False
        finally:
            try:
                adapter.StopDiscovery()
            except Exception:
                pass

    async def disconnect_device(self, address: str) -> bool:
        """Disconnect a single Bluetooth device by MAC address."""
        try:
            bus = self._get_bus()
            device_path = self._find_device_path(address)
            if not device_path:
                print(f"[BlueZ] Device {address} not found")
                return False
            device = bus.get_proxy("org.bluez", device_path, "org.bluez.Device1")
            device.Disconnect()
            print(f"[BlueZ] Disconnected: {address}")
            return True
        except Exception as e:
            print(f"[BlueZ] Failed to disconnect {address}: {e}")
            return False

    async def remove_device(self, address: str) -> bool:
        """Remove a single Bluetooth device by MAC address."""
        device_path = self._find_device_path(address)
        if not device_path:
            print(f"[BlueZ] Device {address} not found for removal")
            return False
        return self._remove_device(device_path)

    async def disconnect_all_controllers(self) -> int:
        """Disconnect all currently connected Bluetooth devices."""
        try:
            bus = self._get_bus()
            obj_manager = bus.get_proxy("org.bluez", "/", "org.freedesktop.DBus.ObjectManager")
            objects = obj_manager.GetManagedObjects()
            count = 0
            for path, interfaces in objects.items():
                if "org.bluez.Device1" not in interfaces:
                    continue
                props = interfaces["org.bluez.Device1"]
                try:
                    connected_var = props.get("Connected")
                    connected = bool(connected_var.unpack()) if hasattr(connected_var, "unpack") else bool(connected_var)
                except Exception:
                    continue
                if not connected:
                    continue
                try:
                    device = bus.get_proxy("org.bluez", str(path), "org.bluez.Device1")
                    device.Disconnect()
                    count += 1
                    print(f"[BlueZ] Disconnected {path}")
                except Exception as e:
                    print(f"[BlueZ] Failed to disconnect {path}: {e}")
            print(f"[BlueZ] Disconnected {count} device(s)")
            return count
        except Exception as e:
            print(f"[BlueZ] disconnect_all_controllers error: {e}")
            return 0

    async def remove_all_controllers(self) -> int:
        """Remove all paired Bluetooth devices from BlueZ."""
        try:
            bus = self._get_bus()
            obj_manager = bus.get_proxy("org.bluez", "/", "org.freedesktop.DBus.ObjectManager")
            objects = obj_manager.GetManagedObjects()
            to_remove = []
            for path, interfaces in objects.items():
                if "org.bluez.Device1" not in interfaces:
                    continue
                props = interfaces["org.bluez.Device1"]
                try:
                    paired_var = props.get("Paired")
                    paired = bool(paired_var.unpack()) if hasattr(paired_var, "unpack") else bool(paired_var)
                except Exception:
                    continue
                if paired:
                    to_remove.append(str(path))
            count = sum(1 for p in to_remove if self._remove_device(p))
            print(f"[BlueZ] Removed {count} device(s)")
            return count
        except Exception as e:
            print(f"[BlueZ] remove_all_controllers error: {e}")
            return 0

    async def pair_device(self, address: str, _allow_force_retry: bool = True) -> bool:
        """Pair and trust a Bluetooth device by address."""
        try:
            bus = self._get_bus()
            device_path = self._find_device_path(address)

            if not device_path:
                print(f"[BlueZ] Device {address} not found")
                return False

            device = bus.get_proxy("org.bluez", device_path, "org.bluez.Device1")

            # Trust the device
            dbus_props = bus.get_proxy("org.bluez", device_path, "org.freedesktop.DBus.Properties")
            dbus_props.Set("org.bluez.Device1", "Trusted", get_variant(Bool, True))

            # Pair if not already paired
            try:
                device.Pair()
            except Exception as e:
                error_name = getattr(e, "get_dbus_name", lambda: "")()
                is_already_exists = "AlreadyExists" in str(error_name) or "AlreadyExists" in str(e)
                if is_already_exists:
                    # Check whether BlueZ considers the device actually connected
                    try:
                        connected_var = dbus_props.Get("org.bluez.Device1", "Connected")
                        connected = connected_var.unpack() if hasattr(connected_var, "unpack") else bool(connected_var)
                    except Exception:
                        connected = False

                    if not connected and _allow_force_retry:
                        print(f"[BlueZ] {address} AlreadyExists but not connected — removing and retrying...")
                        return await self.force_pair_device(address)
                    # Already paired and connected, or retry disabled — fall through to Connect
                else:
                    raise

            # Connect
            try:
                device.Connect()
            except Exception:
                pass

            print(f"[BlueZ] Paired and connected: {address}")
            return True

        except Exception as e:
            print(f"[BlueZ] Pairing failed for {address}: {e}")
            return False
