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
    def _is_combined_joycon(controller: "ConnectedController") -> bool:
        """Return True if this device is a combined Joy-Con pair (not standalone L or R)."""
        name_lower = controller.name.lower()
        if "joy-con" not in name_lower:
            return False
        if controller.product_id in (0x2006, 0x2007):
            return False
        if name_lower.endswith("(l)") or name_lower.endswith("(r)"):
            return False
        return True

    async def _combined_joycon_components(
        self, controller: "ConnectedController"
    ) -> tuple[list[str], list[str], list[str], str] | None:
        """Return (component_unique_ids, component_names, component_imgs, snd_src) for a
        combined Joy-Con pair.

        Searches connected/ready controllers for individual Joy-Con L (0x2006) and R (0x2007)
        profiles and uses their image, name, and sound directly.  Falls back to DB type
        defaults only when the individual Joy-Cons are not currently tracked.
        """
        if not self._is_combined_joycon(controller):
            return None

        uid = controller.unique_id

        joycon_l = (
            next((c for c in self._connected.values() if c.product_id == 0x2006), None)
            or next((c for c in self._ready.values() if c.product_id == 0x2006), None)
        )
        joycon_r = (
            next((c for c in self._connected.values() if c.product_id == 0x2007), None)
            or next((c for c in self._ready.values() if c.product_id == 0x2007), None)
        )

        if joycon_l:
            l_uid = joycon_l.unique_id
            l_name = joycon_l.custom_name or joycon_l.name
            l_img = joycon_l.img_src
            l_snd = joycon_l.snd_src
        else:
            type_l = await database.get_type_default("Joy-Con (L)", 0x057E, 0x2006)
            l_uid = uid + "_L"
            l_name = type_l.name_pattern if type_l else "Joy-Con (L)"
            l_img = type_l.img_src if type_l else "joycon_l.png"
            l_snd = type_l.snd_src if type_l else "switch.mp3"

        if joycon_r:
            r_uid = joycon_r.unique_id
            r_name = joycon_r.custom_name or joycon_r.name
            r_img = joycon_r.img_src
        else:
            type_r = await database.get_type_default("Joy-Con (R)", 0x057E, 0x2007)
            r_uid = uid + "_R"
            r_name = type_r.name_pattern if type_r else "Joy-Con (R)"
            r_img = type_r.img_src if type_r else "joycon_r.png"

        return (
            [l_uid, r_uid],
            [l_name, r_name],
            [l_img, r_img],
            l_snd,
        )

    async def move_to_ready(self, device_path: str) -> Optional[ReadyController]:
        """Move controller from connected to ready. Returns ReadyController or None."""
        if device_path not in self._connected:
            return None
        if device_path in self._ready:
            return None

        connected = self._connected.pop(device_path)
        slot_index = len(self._ready)

        components = await self._combined_joycon_components(connected)
        if components:
            component_unique_ids, component_names, component_imgs, derived_snd = components
        else:
            component_unique_ids = component_names = component_imgs = derived_snd = None

        ready = ReadyController(
            unique_id=connected.unique_id,
            name=connected.name,
            custom_name=connected.custom_name,
            img_src=connected.img_src,
            snd_src=derived_snd or connected.snd_src,
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
