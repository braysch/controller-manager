"""Mesen2 settings.json writer."""

import json
import os
from typing import Optional

from emulators.base import EmulatorConfigWriter
from controllers.device_matcher import SDLInfo


class MesenConfigWriter(EmulatorConfigWriter):
    # Mesen uses 4096 as the start of gamepad IDs.
    # On Linux/SDL, physical controllers are typically offset by 256.
    GAMEPAD_BASE = 4096
    DEVICE_OFFSET = 256

    # Precise mappings derived from user manual config files
    CONTROLLER_PROFILES = {
        "xbox": {
            "buttons": {
                "A": 1, "B": 0, "X": 4, "Y": 3, "L": 6, "R": 7,
                "Select": 8, "Start": 9,
                "Up": 17, "Down": 16, "Left": 15, "Right": 14,
                "Gba_Start": 11, "Gba_Select": 10,
                "Gba_X": 55, "Gba_Y": 56
            }
        },
        "lic": {
            "buttons": {
                "A": 1, "B": 0, "X": 3, "Y": 2, "L": 6, "R": 7,
                "Select": 8, "Start": 9,
                "Up": 17, "Down": 16, "Left": 15, "Right": 14
            }
        },
        "snes": {
            "buttons": {
                "A": 1, "B": 2, "X": 0, "Y": 3, "L": 6, "R": 7,
                "Select": 8, "Start": 9,
                "Up": 17, "Down": 16, "Left": 15, "Right": 14
            }
        }
    }

    def _get_base_id(self, physical_port: int) -> int:
        """Calculate Mesen ID base for a specific physical joystick index."""
        return self.GAMEPAD_BASE + (self.DEVICE_OFFSET * physical_port)

    def _get_mappings_for_controller(self, sdl_info: Optional[SDLInfo], system: str, tr2_is_start: bool = False) -> dict:
        """Return the button IDs (0-indexed) for Mapping1 and Mapping2."""
        name_lower = sdl_info.device_name.lower() if sdl_info else ""
        vid = sdl_info.vendor_id if sdl_info else 0
        pid = sdl_info.product_id if sdl_info else 0
        
        # Select profile
        if "lic" in name_lower or (vid == 0x057E and pid == 0x2009):
            profile = self.CONTROLLER_PROFILES["lic"]
        elif "snes" in name_lower or (vid == 0x0079 and pid == 0x0126) or (vid == 0x057E and pid == 0x2017):
            profile = self.CONTROLLER_PROFILES["snes"]
        else:
            profile = self.CONTROLLER_PROFILES["xbox"]
        
        m1 = profile["buttons"].copy()
        
        # Override start button if requested
        if tr2_is_start:
            m1["Start"] = 7
        
        if system == "Gba":
            if "Gba_Start" in m1: m1["Start"] = m1["Gba_Start"]
            if "Gba_Select" in m1: m1["Select"] = m1["Gba_Select"]
            if "Gba_X" in m1: m1["X"] = m1["Gba_X"]
            if "Gba_Y" in m1: m1["Y"] = m1["Gba_Y"]
        
        m2 = { "Up": 17, "Down": 16, "Left": 15, "Right": 14 }
        return {"m1": m1, "m2": m2}

    def _build_mapping_dict(self, base: int, ids: dict, system: str) -> dict:
        mapping = {
            "MouseButtons": None,
            "A": base + ids.get("A", 0) if "A" in ids else 0,
            "B": base + ids.get("B", 0) if "B" in ids else 0,
            "Up": base + ids.get("Up", 0) if "Up" in ids else 0,
            "Down": base + ids.get("Down", 0) if "Down" in ids else 0,
            "Left": base + ids.get("Left", 0) if "Left" in ids else 0,
            "Right": base + ids.get("Right", 0) if "Right" in ids else 0,
            "Start": base + ids.get("Start", 0) if "Start" in ids else 0,
            "Select": base + ids.get("Select", 0) if "Select" in ids else 0,
        }
        if system in ("Snes", "Gba"):
            mapping.update({
                "X": base + ids.get("X", 0) if "X" in ids else 0,
                "Y": base + ids.get("Y", 0) if "Y" in ids else 0,
                "L": base + ids.get("L", 0) if "L" in ids else 0,
                "R": base + ids.get("R", 0) if "R" in ids else 0,
            })
            if system == "Snes": mapping["SuperScopeButtons"] = None
        
        defaults = { "U": 0, "D": 0, "TurboA": 0, "TurboB": 0, "TurboX": 0, "TurboY": 0,
                    "TurboL": 0, "TurboR": 0, "TurboSelect": 0, "TurboStart": 0, "GenericKey1": 0 }
        mapping.update(defaults)
        
        if system == "Nes":
            mapping.update({
                "PowerPadButtons": None, "FamilyBasicKeyboardButtons": None, "PartyTapButtons": None,
                "PachinkoButtons": None, "ExcitingBoxingButtons": None, "JissenMahjongButtons": None,
                "SuborKeyboardButtons": None, "BandaiMicrophoneButtons": None, "VirtualBoyButtons": None,
                "KonamiHyperShotButtons": None, "ArkanoidButtons": None, "ZapperButtons": None,
                "OekakidsButtons": None, "BandaiHypershotButtons": None,
            })
        return mapping

    def write_config(
        self,
        config_path: str,
        controllers: list[tuple[str, Optional[SDLInfo], bool]],
    ) -> bool:
        try:
            config_path = os.path.expanduser(config_path)
            # Use utf-8-sig for BOTH reading and writing to handle the BOM
            with open(config_path, "r", encoding="utf-8-sig") as f:
                config = json.load(f)

            systems = ["Nes", "Snes", "Gameboy", "Gba"]
            for system in systems:
                if system not in config: continue
                
                # Clear ports/controller
                if system in ("Nes", "Snes"):
                    for i in range(1, 9):
                        pk = f"Port{i}"
                        if pk in config[system]:
                            config[system][pk]["Type"] = "None"
                            for m in range(1, 3):
                                mk = f"Mapping{m}"
                                if mk in config[system][pk]:
                                    for k in config[system][pk][mk]:
                                        if isinstance(config[system][pk][mk][k], int): config[system][pk][mk][k] = 0
                else:
                    if "Controller" in config[system]:
                        for m in range(1, 3):
                            mk = f"Mapping{m}"
                            if mk in config[system]["Controller"]:
                                for k in config[system]["Controller"][mk]:
                                    if isinstance(config[system]["Controller"][mk][k], int): config[system]["Controller"][mk][k] = 0

                # Map controllers
                for player_index, (unique_id, sdl_info, tr2_is_start) in enumerate(controllers):
                    # Logical mapping: Slot 1 -> Port1/Controller, Slot 2 -> Port2
                    if system in ("Nes", "Snes"):
                        if player_index >= 8: break
                        pk = f"Port{player_index + 1}"
                    else:
                        if player_index > 0: break # Single player systems
                        pk = "Controller"
                    
                    if pk not in config[system]: config[system][pk] = {}
                    config[system][pk]["Type"] = "NesController" if system == "Nes" else "SnesController"
                    
                    # Physical mapping: Use the actual joystick index (port) for IDs
                    mappings = self._get_mappings_for_controller(sdl_info, system, tr2_is_start)
                    # For Player 1, map Slot 1's resolved index PLUS Pad 1, 2, and 3 as fallbacks
                    base = self._get_base_id(sdl_info.port if sdl_info else 0)
                    
                    config[system][pk]["Mapping1"] = self._build_mapping_dict(base, mappings["m1"], system)
                    config[system][pk]["Mapping2"] = self._build_mapping_dict(base, mappings["m2"], system)
                    
                    if player_index == 0:
                        # Extra fallback slots for Player 1
                        config[system][pk]["Mapping3"] = self._build_mapping_dict(self.GAMEPAD_BASE, mappings["m1"], system)
                        config[system][pk]["Mapping4"] = self._build_mapping_dict(self.GAMEPAD_BASE + self.DEVICE_OFFSET, mappings["m1"], system)

            with open(config_path, "w", encoding="utf-8-sig") as f:
                json.dump(config, f, indent=2)
            return True

        except Exception as e:
            print(f"[MesenWriter] FATAL ERROR: {e}")
            return False
