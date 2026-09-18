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
    #
    # Each profile has a "default" table (console-invariant: D-pad, Select/Start,
    # analog triggers - the same physical buttons regardless of what's running)
    # and a "per_system" table for the face buttons (A/B/X/Y/L/R), which DO need
    # to vary: Nintendo's own "which button is jump vs. run/fire" convention
    # shifted across generations (NES: A=jump, B=run; SNES: B=jump, Y=run), so
    # the same physical controller should feed different consoles' A/B/X/Y from
    # different physical buttons to keep that feel natural. A system with no
    # entry of its own falls back to a related one via _SYSTEM_FALLBACK (Gameboy
    # -> Nes, Gba -> Snes) rather than repeating an identical table.
    CONTROLLER_PROFILES = {
        "xbox": {
            "default": {
                "Select": 10, "Start": 11, "Up": 17, "Down": 16, "Left": 15, "Right": 14,
                "TriggerL": 55, "TriggerR": 56,
            },
            "per_system": {
                "Nes": {"A": 1, "B": 0},
                "Snes": {"A": 1, "B": 0, "X": 4, "Y": 3, "L": 6, "R": 7},
            },
        },
        "lic": {
            "default": {"Select": 8, "Start": 9, "Up": 17, "Down": 16, "Left": 15, "Right": 14},
            "per_system": {
                "Nes": {"A": 1, "B": 0},
                "Snes": {"A": 1, "B": 0, "X": 3, "Y": 2, "L": 6, "R": 7},
            },
        },
        "snes": {
            "default": {"Select": 8, "Start": 9, "Up": 17, "Down": 16, "Left": 15, "Right": 14},
            "per_system": {
                # A physical SNES pad's own A/B are the "wrong" natural fit for a
                # 2-button NES game - Nintendo's own convention uses the pad's B
                # (jump) and Y (run/fire) instead, since those sit where a 2-button
                # controller's buttons naturally would.
                "Nes": {"A": 2, "B": 3},
                "Snes": {"A": 1, "B": 2, "X": 0, "Y": 3, "L": 6, "R": 7},
            },
        },
        "diswoe": {
            "default": {"Select": 10, "Start": 11, "Up": 17, "Down": 16, "Left": 15, "Right": 14},
            "per_system": {
                "Nes": {"A": 1, "B": 0},
                "Snes": {"A": 1, "B": 0, "X": 3, "Y": 4, "L": 8, "R": 9},
            },
        },
        # Joy-Con (R) used solo, held sideways ("horizontal", one-Joy-Con retro
        # style). Held upright it reports the standard Nintendo layout - A=East(1),
        # B=South(0), X=North(3), Y=West(4) - but physically rotating it 90
        # degrees clockwise for the sideways grip shifts which SNES-diamond
        # position each button now sits in: A(East)->South, B(South)->West,
        # X(North)->East, Y(West)->North. So each button feeds whichever SNES
        # role normally occupies its new position: Snes A<-X(3), B<-A(1), X<-Y(4),
        # Y<-B(0). For 2-button consoles, the two that land in the natural
        # resting spots - physical A (now South) and B (now West) - are jump/run,
        # same convention as a SNES pad used for NES games.
        #
        # The stick is reported as a SECOND axis pair, not the "left-stick axes"
        # (14-17) every other profile above uses for its D-pad - that guess did
        # nothing at all, confirmed via Mesen's own binding UI, which captured
        # 21/20/22/23 instead (tilting the stick in the rotated direction for
        # each of Mesen's Up/Down/Left/Right prompts, per the sideways rotation).
        # L/R/Select were likewise captured directly rather than guessed.
        "joycon_r": {
            "default": {"Start": 11, "Up": 21, "Down": 20, "Left": 22, "Right": 23},
            "per_system": {
                "Nes": {"A": 1, "B": 0},
                "Snes": {"A": 3, "B": 1, "X": 4, "Y": 0, "L": 6, "R": 8, "Select": 9},
            },
        },
        # Joy-Con (L) used solo, held sideways. Unlike the R, its "diamond"
        # (four D-pad-shaped) buttons are semantically a D-pad, so hid_nintendo
        # reports them as BTN_DPAD_UP/DOWN/LEFT/RIGHT - but here they're used as
        # action buttons (jump/speed/paddles/select), not movement. Mesen's fixed
        # evdev enum doesn't read BTN_DPAD_* at all (confirmed empirically, same
        # as the Wii Remote's D-pad), so EvdevMonitor (_create_joycon_l_bridge/
        # _JOYCON_L_TRANSLATE) translates them into fresh slots (0/1/3/4) nothing
        # else on this device uses, passing every other button and the stick
        # through unchanged. Movement is the stick instead (also on the 14-17
        # "left-stick axes" slots, unlike the R's stick, which needed a second
        # axis pair - the two Joy-Cons apparently keep their own natural L/R
        # stick identity even used solo). "-" (BTN_SELECT/314, passed through
        # unchanged) serves as Start since there's no "+" on this side.
        # All numbers here were captured directly via Mesen's own binding UI,
        # not derived - see the conversation that produced this profile for the
        # exact prompts used (which physical button was pressed for which role).
        "joycon_l": {
            "default": {"Select": 8, "Start": 10, "Up": 14, "Down": 15, "Left": 17, "Right": 16},
            "per_system": {
                "Nes": {"A": 3, "B": 0},
                "Snes": {"A": 1, "B": 3, "X": 4, "Y": 0, "L": 7, "R": 9},
            },
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
        #
        # The Wii Remote only has two buttons reachable in the sideways hold (1/2),
        # so the bridge emits BOTH a 2-button-console code and a 4-button-console
        # code for each of them simultaneously (see _WIIMOTE_TRANSLATE): 1 -> B and
        # Y, 2 -> A and C. Which pair actually gets read depends entirely on which
        # of these two per-system tables is in effect - so pressing 1/2 during an
        # NES game never also fires anything from the Snes table and vice versa.
        # Snes also fills in the remaining two face buttons (X/A) from the real
        # Wii Remote A/B buttons, each of which similarly emits both its
        # Nes/Gameboy code and its own exclusive Snes-only code.
        "wii": {
            "default": {"Select": 10, "Start": 11, "Up": 29, "Down": 28, "Left": 27, "Right": 26},
            "per_system": {
                "Nes": {"A": 0, "B": 1},
                "Snes": {"Y": 4, "B": 2, "A": 6, "X": 5},
            },
        },
        # Keyboard uses Mesen's absolute key IDs (Core/Shared/KeyDefinitions.h),
        # not gamepad-base offsets, and doesn't vary by system. Layout: arrows =
        # D-pad, Z/X = B/A, A/S = Y/X, Q/W = L/R, Space = Select, Enter = Start.
        "keyboard": {
            "default": {
                "A": 67, "B": 69, "X": 62, "Y": 44, "L": 60, "R": 66,
                "Up": 24, "Down": 26, "Left": 23, "Right": 25,
                "Select": 18, "Start": 6,
            },
        },
    }

    # A system with no per_system entry of its own reuses a related system's
    # face-button table instead of repeating it verbatim.
    SYSTEM_FALLBACK = {"Gameboy": "Nes", "Gba": "Snes"}

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
        """Select the physical controller profile spec (unresolved: default + per_system)."""
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
        # Joy-Con (R)/(L), used solo and held sideways - product_ids match
        # state_manager.py's own combined-Joy-Con detection.
        if (name_lower.endswith("(r)") and "joy-con" in name_lower) or (vid == 0x057E and pid == 0x2007):
            return self.CONTROLLER_PROFILES["joycon_r"]
        if (name_lower.endswith("(l)") and "joy-con" in name_lower) or (vid == 0x057E and pid == 0x2006):
            return self.CONTROLLER_PROFILES["joycon_l"]
        if "lic" in name_lower or (vid == 0x057E and pid == 0x2009):
            return self.CONTROLLER_PROFILES["lic"]
        if "snes" in name_lower or (vid == 0x0079 and pid == 0x0126) or (vid == 0x057E and pid == 0x2017):
            return self.CONTROLLER_PROFILES["snes"]
        return self.CONTROLLER_PROFILES["xbox"]

    def _resolve_profile(self, spec: dict, layout: str) -> dict:
        """Merge a profile spec's console-invariant defaults with the face-button
        table for this specific system (falling back per SYSTEM_FALLBACK if the
        profile has no table of its own for it)."""
        per_system = spec.get("per_system", {})
        face = per_system.get(layout)
        if face is None:
            face = per_system.get(self.SYSTEM_FALLBACK.get(layout, layout), {})
        return {**spec.get("default", {}), **face}

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
        spec = self._get_profile(sdl_info)
        profile = self._resolve_profile(spec, layout)
        m1 = self._layout_buttons(profile, layout)

        if spec is self.CONTROLLER_PROFILES["keyboard"]:
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
