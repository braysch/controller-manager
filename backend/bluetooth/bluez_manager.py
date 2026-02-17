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
        appearance = properties.get("Appearance", 0)

        if appearance in GAMEPAD_APPEARANCES:
            return True

        for pattern in CONTROLLER_NAME_PATTERNS:
            if pattern in name:
                return True

        # Check device class - gamepads are in the Peripheral major class (0x0500)
        device_class = properties.get("Class", 0)
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

    async def pair_device(self, address: str) -> bool:
        """Pair and trust a Bluetooth device by address."""
        try:
            bus = self._get_bus()
            obj_manager = bus.get_proxy(
                "org.bluez",
                "/",
                "org.freedesktop.DBus.ObjectManager"
            )
            objects = obj_manager.GetManagedObjects()

            # Find the device object path
            device_path = None
            for path, interfaces in objects.items():
                if "org.bluez.Device1" not in interfaces:
                    continue
                props = interfaces["org.bluez.Device1"]
                if str(props.get("Address", "")) == address:
                    device_path = str(path)
                    break

            if not device_path:
                print(f"[BlueZ] Device {address} not found")
                return False

            device = bus.get_proxy("org.bluez", device_path, "org.bluez.Device1")

            # Trust the device
            props = bus.get_proxy("org.bluez", device_path, "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Device1", "Trusted", get_variant(Bool, True))

            # Pair if not already paired
            try:
                device.Pair()
            except Exception as e:
                error_name = getattr(e, "get_dbus_name", lambda: "")()
                if "AlreadyExists" not in str(error_name) and "AlreadyExists" not in str(e):
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
