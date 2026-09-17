"""Mesen2 settings.json writer."""

import json
import os
from typing import Optional

from emulators.base import EmulatorConfigWriter
from controllers.device_matcher import SDLInfo

_DPAD = {"Up": ("Up",), "Down": ("Down",), "Left": ("Left",), "Right": ("Right",)}


class MesenConfigWriter(EmulatorConfigWriter):
    # Mesen uses 4096 as the start of gamepad IDs.
    # On Linux/SDL, physical controllers are typically offset by 256.
    GAMEPAD_BASE = 4096
    DEVICE_OFFSET = 256

    # Button IDs per physical controller, derived from manually-configured Mesen SNES
    # mappings (see examples/mesen/settings.*.ideal.json). These are NOT SDL joystick
    # indices — Mesen's Linux build reads gamepads via its own fixed evdev-code enum
    # (Linux/LinuxGameController.cpp IsButtonPressed: 0=BTN_A, 1=BTN_B, ..., 10=BTN_SELECT,
    # 11=BTN_START, 14-17=left-stick axes, 26-29=D-pad via ABS_HAT0/BTN_DPAD_* only), so a
    # button/direction here only works if the physical controller actually reports the
    # matching evdev code for that slot.
    # TriggerL/TriggerR are analog-trigger IDs, used where a controller has them.
    CONTROLLER_PROFILES = {
        "xbox": {
            "A": 1, "B": 0, "X": 4, "Y": 3, "L": 6, "R": 7,
            "Up": 17, "Down": 16, "Left": 15, "Right": 14,
            "Select": 10, "Start": 11,
            "TriggerL": 55, "TriggerR": 56,
        },
        "lic": {
            "A": 1, "B": 0, "X": 3, "Y": 2, "L": 6, "R": 7,
            "Up": 17, "Down": 16, "Left": 15, "Right": 14,
            "Select": 8, "Start": 9,
        },
        "snes": {
            "A": 1, "B": 2, "X": 0, "Y": 3, "L": 6, "R": 7,
            "Up": 17, "Down": 16, "Left": 15, "Right": 14,
            "Select": 8, "Start": 9,
        },
        "diswoe": {
            "A": 1, "B": 0, "X": 3, "Y": 4, "L": 8, "R": 9,
            "Up": 17, "Down": 16, "Left": 15, "Right": 14,
            "Select": 10, "Start": 11,
        },
        # Wii Remote: Mesen's Linux button IDs are NOT an SDL/enumeration index — they're
        # a fixed internal enum hardcoded to specific evdev codes (see Mesen2's
        # Linux/LinuxGameController.cpp IsButtonPressed): 0=BTN_A, 1=BTN_B, 2=BTN_C,
        # 3=BTN_X, 4=BTN_Y, 5=BTN_Z, 6=BTN_TL, 7=BTN_TR, ..., 10=BTN_SELECT, 11=BTN_START,
        # 26-29=D-pad (but only via ABS_HAT0X/Y or BTN_DPAD_LEFT/RIGHT/UP/DOWN).
        # The Wii Remote's hid-wiimote kernel driver only reports BTN_A/BTN_B as
        # standard gamepad codes natively — its D-pad is KEY_UP/DOWN/LEFT/RIGHT, and
        # "+"/"-" are KEY_NEXT/KEY_PREVIOUS, none of which Mesen's fixed enum
        # understands. EvdevMonitor (see controllers/evdev_monitor.py,
        # _create_wiimote_bridge/_WIIMOTE_TRANSLATE/_update_wiimote_dpad) works
        # around this by grabbing the real Wii Remote and re-emitting its input
        # through a synthetic virtual gamepad: BTN_SELECT/BTN_START for "-"/"+",
        # and a genuine ABS_HAT0X/Y hat switch for the D-pad (rotated 90 degrees
        # for the standard sideways NES-style hold) — BTN_DPAD_* button codes were
        # tried first but Mesen's own input listener never registered them at all,
        # confirming it only reads a D-pad via the classic hat-axis representation.
        # The Up/Down/Left/Right slot numbers below are still an unverified guess
        # (borrowed from AXIS_DPAD) pending confirmation via Mesen's own binding UI.
        "wii": {
            "A": 0, "B": 1,
            "Select": 10, "Start": 11,
            "Up": 29, "Down": 28, "Left": 27, "Right": 26,
        },
        # Keyboard uses Mesen's absolute key IDs (Core/Shared/KeyDefinitions.h),
        # not gamepad-base offsets. Layout: arrows = D-pad, Z/X = B/A, A/S = Y/X,
        # Q/W = L/R, Space = Select, Enter = Start.
        "keyboard": {
            "A": 67, "B": 69, "X": 62, "Y": 44, "L": 60, "R": 66,
            "Up": 24, "Down": 26, "Left": 23, "Right": 25,
            "Select": 18, "Start": 6,
        },
    }

    # How each virtual Mesen controller pulls its buttons from a physical profile:
    # virtual button -> profile keys, tried in order.
    VIRTUAL_LAYOUTS = {
        "Nes": {"A": ("A",), "B": ("B",), **_DPAD,
                "Select": ("Select",), "Start": ("Start",)},
        "Snes": {"A": ("A",), "B": ("B",), "X": ("X",), "Y": ("Y",),
                 "L": ("L",), "R": ("R",), **_DPAD,
                 "Select": ("Select",), "Start": ("Start",)},
        "Gameboy": {"A": ("A",), "B": ("B",), **_DPAD,
                    "Select": ("Select",), "Start": ("Start",)},
        "Gba": {"A": ("A",), "B": ("B",), "X": ("TriggerL", "X"), "Y": ("TriggerR", "Y"),
                "L": ("L",), "R": ("R",), **_DPAD,
                "Select": ("Select",), "Start": ("Start",)},
    }

    # Mapping 2: Modern D-pad fallback.
    # Many modern controllers on Linux expose the D-pad as Axis 5 & 6.
    # Up=29 (Axis 6-), Down=28 (Axis 6+), Left=27 (Axis 5-), Right=26 (Axis 5+)
    AXIS_DPAD = {"Up": 29, "Down": 28, "Left": 27, "Right": 26}

    SYSTEM_CONTROLLERS = {
        "Nes": {"style": "ports", "type": "NesController", "max_players": 8},
        "Snes": {"style": "ports", "type": "SnesController", "max_players": 8},
        "Gameboy": {"style": "single", "type": "SnesController"},
        "Gba": {"style": "single", "type": "SnesController"},
    }

    def _get_base_id(self, physical_port: int) -> int:
        """Calculate Mesen ID base for a specific physical joystick index."""
        return self.GAMEPAD_BASE + (self.DEVICE_OFFSET * physical_port)

    def _get_profile(self, sdl_info: Optional[SDLInfo]) -> dict:
        """Select the physical controller profile."""
        name_lower = sdl_info.device_name.lower() if sdl_info else ""
        vid = sdl_info.vendor_id if sdl_info else 0
        pid = sdl_info.product_id if sdl_info else 0

        if "keyboard" in name_lower:
            return self.CONTROLLER_PROFILES["keyboard"]
        # Diswoe/Switch-Lite clones report the Switch Pro VID/PID and device name,
        # so they can only be recognized by their (custom) profile name.
        if "diswoe" in name_lower:
            return self.CONTROLLER_PROFILES["diswoe"]
        if "wii remote" in name_lower or (vid == 0x057E and pid == 0x0306):
            return self.CONTROLLER_PROFILES["wii"]
        if "lic" in name_lower or (vid == 0x057E and pid == 0x2009):
            return self.CONTROLLER_PROFILES["lic"]
        if "snes" in name_lower or (vid == 0x0079 and pid == 0x0126) or (vid == 0x057E and pid == 0x2017):
            return self.CONTROLLER_PROFILES["snes"]
        return self.CONTROLLER_PROFILES["xbox"]

    def _layout_buttons(self, profile: dict, layout: str) -> dict:
        """Resolve a virtual controller layout to this profile's button IDs."""
        ids = {}
        for virtual_key, sources in self.VIRTUAL_LAYOUTS[layout].items():
            for src in sources:
                if src in profile:
                    ids[virtual_key] = profile[src]
                    break
        return ids

    def _apply_mapping(self, node: dict, mapping_key: str, base: int, ids: dict, template: Optional[dict] = None) -> None:
        """Zero every button in node[mapping_key] (preserving nulls), then set ids offset by base."""
        mapping = node.get(mapping_key)
        if not isinstance(mapping, dict):
            template = template or node.get("Mapping1")
            if isinstance(template, dict):
                mapping = {k: (None if v is None else 0) for k, v in template.items()}
            else:
                mapping = {}
            node[mapping_key] = mapping
        for k, v in mapping.items():
            if isinstance(v, int):
                mapping[k] = 0
        for k, button in ids.items():
            mapping[k] = base + button

    def _write_node(self, node: dict, layout: str, sdl_info: Optional[SDLInfo], player_index: int, template: Optional[dict] = None) -> None:
        """Write Mapping1-4 for one virtual controller node."""
        profile = self._get_profile(sdl_info)
        m1 = self._layout_buttons(profile, layout)

        if profile is self.CONTROLLER_PROFILES["keyboard"]:
            # Keyboard IDs are absolute; no axis d-pad or gamepad fallback slots
            # (Mapping2-4 were already zeroed by _clear_system).
            self._apply_mapping(node, "Mapping1", 0, m1, template)
            return

        base = self._get_base_id(sdl_info.port if sdl_info else 0)
        self._apply_mapping(node, "Mapping1", base, m1, template)
        self._apply_mapping(node, "Mapping2", base, self.AXIS_DPAD, template)
        if player_index == 0:
            # Extra fallback slots for Player 1: same buttons on Pad 1 and Pad 2
            self._apply_mapping(node, "Mapping3", self.GAMEPAD_BASE, m1, template)
            self._apply_mapping(node, "Mapping4", self.GAMEPAD_BASE + self.DEVICE_OFFSET, m1, template)

    def _clear_system(self, section: dict, info: dict) -> None:
        """Zero all mappings so removed controllers don't leave ghost inputs."""
        if info["style"] == "ports":
            nodes = [section[k] for k in section if k.startswith("Port") and isinstance(section[k], dict)]
            for node in nodes:
                node["Type"] = "None"
        elif info["style"] == "single":
            nodes = [section["Controller"]] if isinstance(section.get("Controller"), dict) else []
        else:  # ws
            nodes = [section[k] for k in ("ControllerHorizontal", "ControllerVertical") if isinstance(section.get(k), dict)]
        for node in nodes:
            for m in range(1, 5):
                mapping = node.get(f"Mapping{m}")
                if isinstance(mapping, dict):
                    for k, v in mapping.items():
                        if isinstance(v, int):
                            mapping[k] = 0

    def write_config(
        self,
        config_path: str,
        controllers: list[tuple[str, Optional[SDLInfo]]],
    ) -> bool:
        """controllers: (unique_id, sdl_info) per player slot."""
        try:
            config_path = os.path.expanduser(config_path)
            # Use utf-8-sig for BOTH reading and writing to handle the BOM
            with open(config_path, "r", encoding="utf-8-sig") as f:
                config = json.load(f)

            for system, info in self.SYSTEM_CONTROLLERS.items():
                if system not in config:
                    continue
                section = config[system]
                self._clear_system(section, info)

                for player_index, (unique_id, sdl_info) in enumerate(controllers):
                    if info["style"] == "ports":
                        if player_index >= info["max_players"]:
                            break
                        pk = f"Port{player_index + 1}"
                        if pk not in section:
                            # Only NES/SNES ports are safe to create on the fly
                            if system not in ("Nes", "Snes"):
                                break
                            section[pk] = {}
                        template = section.get("Port1", {}).get("Mapping1")
                        section[pk]["Type"] = info["type"]
                        self._write_node(section[pk], system, sdl_info, player_index, template)
                    elif info["style"] == "single":
                        if player_index > 0:
                            break
                        node = section.setdefault("Controller", {})
                        node["Type"] = info["type"]
                        self._write_node(node, system, sdl_info, player_index)
                    else:  # ws: one player, horizontal + vertical orientations
                        if player_index > 0:
                            break
                        for node_key, layout, type_name in (
                            ("ControllerHorizontal", "WsHorizontal", "WsController"),
                            ("ControllerVertical", "WsVertical", "WsControllerVertical"),
                        ):
                            node = section.setdefault(node_key, {})
                            node["Type"] = type_name
                            self._write_node(node, layout, sdl_info, player_index)

            with open(config_path, "w", encoding="utf-8-sig") as f:
                json.dump(config, f, indent=2)
            return True

        except Exception as e:
            print(f"[MesenWriter] FATAL ERROR: {e}")
            return False
