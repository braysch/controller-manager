"""Manages connected and ready controller state, bridges evdev detection with DB profiles."""

from typing import Optional
from collections import OrderedDict

import database
from models import ConnectedController, ReadyController, ControllerProfile


class StateManager:
    def __init__(self):
        # device_path -> ConnectedController
        self._connected: dict[str, ConnectedController] = {}
        # device_path -> ReadyController (ordered by insertion = slot order)
        self._ready: OrderedDict[str, ReadyController] = OrderedDict()
        # unique_id -> device_path mapping
        self._uid_to_path: dict[str, str] = {}
        # device_path -> unique_id mapping
        self._path_to_uid: dict[str, str] = {}

    async def add_connected(self, device_info: dict) -> Optional[ConnectedController]:
        """Add a newly detected device. Returns ConnectedController or None if duplicate."""
        device_path = device_info["device_path"]
        unique_id = device_info["unique_id"]

        # Skip if already tracked
        if device_path in self._connected or device_path in self._ready:
            return None

        # Look up or create DB profile
        profile = await database.upsert_profile(
            unique_id=unique_id,
            default_name=device_info["name"],
            vendor_id=device_info.get("vendor_id"),
            product_id=device_info.get("product_id"),
        )

        # Use guid_override from DB profile if set, otherwise use evdev-computed GUID
        effective_guid = profile.guid_override or device_info.get("guid")

        controller = ConnectedController(
            unique_id=unique_id,
            name=profile.default_name,
            custom_name=profile.custom_name,
            img_src=profile.img_src,
            snd_src=profile.snd_src,
            connection_type=device_info.get("connection_type", "usb"),
            vendor_id=device_info.get("vendor_id"),
            product_id=device_info.get("product_id"),
            guid=effective_guid,
            port=device_info.get("port"),
        )

        self._connected[device_path] = controller
        self._uid_to_path[unique_id] = device_path
        self._path_to_uid[device_path] = unique_id

        return controller

    async def remove_connected(self, device_path: str) -> bool:
        """Remove a device. Returns True if it was in the ready list."""
        unique_id = self._path_to_uid.get(device_path)
        was_ready = False

        if device_path in self._ready:
            del self._ready[device_path]
            was_ready = True

        if device_path in self._connected:
            del self._connected[device_path]

        if unique_id:
            self._uid_to_path.pop(unique_id, None)
        self._path_to_uid.pop(device_path, None)

        return was_ready

    @staticmethod
    def _combined_joycon_components(controller: "ConnectedController") -> tuple[list[str], list[str], list[str]] | None:
        """Return (component_unique_ids, component_names, component_imgs) if this is a combined
        Joy-Con pair, or None if it's a standalone/non-Joy-Con device."""
        name_lower = controller.name.lower()
        if "joy-con" not in name_lower:
            return None
        # Standalone Joy-Cons have known product IDs or explicit (L)/(R) suffixes
        if controller.product_id in (0x2006, 0x2007):
            return None
        if name_lower.endswith("(l)") or name_lower.endswith("(r)"):
            return None
        uid = controller.unique_id
        return (
            [uid + "_L", uid + "_R"],
            ["Joy-Con (L)", "Joy-Con (R)"],
            ["joycon_l.png", "joycon_r.png"],
        )

    async def move_to_ready(self, device_path: str) -> Optional[ReadyController]:
        """Move controller from connected to ready. Returns ReadyController or None."""
        if device_path not in self._connected:
            return None
        if device_path in self._ready:
            return None

        connected = self._connected.pop(device_path)
        slot_index = len(self._ready)

        components = self._combined_joycon_components(connected)
        component_unique_ids, component_names, component_imgs = components if components else (None, None, None)

        ready = ReadyController(
            unique_id=connected.unique_id,
            name=connected.name,
            custom_name=connected.custom_name,
            img_src=connected.img_src,
            snd_src=connected.snd_src,
            connection_type=connected.connection_type,
            battery_percent=connected.battery_percent,
            slot_index=slot_index,
            guid=connected.guid,
            port=connected.port,
            vendor_id=connected.vendor_id,
            product_id=connected.product_id,
            component_unique_ids=component_unique_ids,
            component_names=component_names,
            component_imgs=component_imgs,
        )

        self._ready[device_path] = ready
        return ready

    async def clear_ready(self) -> list[ConnectedController]:
        """Move all ready controllers back to connected. Returns list of ConnectedControllers."""
        moved = []
        for device_path, ready in list(self._ready.items()):
            connected = ConnectedController(
                unique_id=ready.unique_id,
                name=ready.name,
                custom_name=ready.custom_name,
                img_src=ready.img_src,
                snd_src=ready.snd_src,
                connection_type=ready.connection_type,
                battery_percent=ready.battery_percent,
                vendor_id=ready.vendor_id,
                product_id=ready.product_id,
                guid=ready.guid,
                port=ready.port,
            )
            self._connected[device_path] = connected
            moved.append(connected)

        self._ready.clear()
        return moved

    def get_connected_list(self) -> list[ConnectedController]:
        return list(self._connected.values())

    def get_ready_list(self) -> list[ReadyController]:
        return list(self._ready.values())

    def get_snapshot(self) -> dict:
        return {
            "connected": [c.model_dump() for c in self._connected.values()],
            "ready": [r.model_dump() for r in self._ready.values()],
        }

    def get_unique_id_for_path(self, device_path: str) -> Optional[str]:
        return self._path_to_uid.get(device_path)

    def get_path_for_unique_id(self, unique_id: str) -> Optional[str]:
        return self._uid_to_path.get(unique_id)

    def update_battery(self, unique_id: str, percent: int):
        """Update battery percent for a controller in either list."""
        device_path = self._uid_to_path.get(unique_id)
        if not device_path:
            return

        if device_path in self._connected:
            self._connected[device_path].battery_percent = percent
        if device_path in self._ready:
            self._ready[device_path].battery_percent = percent

    def refresh_profile(self, unique_id: str, profile: ControllerProfile):
        """Update in-memory state when a profile is edited."""
        device_path = self._uid_to_path.get(unique_id)
        if not device_path:
            return

        if device_path in self._connected:
            c = self._connected[device_path]
            c.custom_name = profile.custom_name
            c.img_src = profile.img_src
            c.snd_src = profile.snd_src

        if device_path in self._ready:
            r = self._ready[device_path]
            r.custom_name = profile.custom_name
            r.img_src = profile.img_src
            r.snd_src = profile.snd_src
