"""Mesen2 settings.json writer."""

import json
import os
from typing import Optional

from emulators.base import EmulatorConfigWriter
from controllers.device_matcher import SDLInfo


class MesenConfigWriter(EmulatorConfigWriter):
    # Base offset for Gamepad 1 (Mesen2 uses 4096 for Gamepad 1, 8192 for Gamepad 2, etc.)
    GAMEPAD_BASE = 4096

    def _get_base_id(self, player_index: int) -> int:
        return self.GAMEPAD_BASE * (player_index + 1)

    def _get_mappings_for_controller(self, sdl_info: Optional[SDLInfo], system: str) -> dict:
        """Return the button IDs (0-indexed) for the given controller and system."""
        
        # Default modern (Xbox/Switch) layout
        is_modern = True
        if sdl_info:
            # Check for known retro vendors/patterns
            name_lower = sdl_info.device_name.lower()
            if "snes" in name_lower or "nes" in name_lower or "8bitdo" in name_lower:
                is_modern = False
        
        if system == "Snes":
            if is_modern:
                # Modern (Xbox/Switch) mapping to SNES
                return {
                    "A": 1, "B": 0, "X": 3, "Y": 2,
                    "L": 9, "R": 10,
                    "Up": 11, "Down": 12, "Left": 13, "Right": 14,
                    "Select": 4, "Start": 6
                }
            else:
                # SNES-style (Generic/8BitDo)
                return {
                    "A": 1, "B": 2, "X": 0, "Y": 3,
                    "L": 6, "R": 7,
                    "Up": 17, "Down": 16, "Left": 15, "Right": 14,
                    "Select": 8, "Start": 9
                }
        else: # NES
            if is_modern:
                return {
                    "A": 1, "B": 0,
                    "Up": 11, "Down": 12, "Left": 13, "Right": 14,
                    "Select": 4, "Start": 6
                }
            else:
                return {
                    "A": 1, "B": 0,
                    "Up": 29, "Down": 28, "Left": 27, "Right": 26,
                    "Select": 8, "Start": 9
                }

    def _map_controller(self, player_index: int, system: str, sdl_info: Optional[SDLInfo]) -> dict:
        base = self._get_base_id(player_index)
        ids = self._get_mappings_for_controller(sdl_info, system)
        
        mapping = {
            "MouseButtons": None,
            "SuperScopeButtons": None,
            "A": base + ids["A"],
            "B": base + ids["B"],
            "Up": base + ids["Up"],
            "Down": base + ids["Down"],
            "Left": base + ids["Left"],
            "Right": base + ids["Right"],
            "Start": base + ids["Start"],
            "Select": base + ids["Select"],
        }
        
        if system == "Snes":
            mapping.update({
                "X": base + ids["X"],
                "Y": base + ids["Y"],
                "L": base + ids["L"],
                "R": base + ids["R"],
            })
        
        # Fill in defaults for missing fields
        defaults = {
            "U": 0, "D": 0, "TurboA": 0, "TurboB": 0, "TurboX": 0, "TurboY": 0,
            "TurboL": 0, "TurboR": 0, "TurboSelect": 0, "TurboStart": 0, "GenericKey1": 0
        }
        mapping.update(defaults)
        
        if system == "Nes":
            mapping.update({
                "X": 0, "Y": 0, "L": 0, "R": 0,
                "PowerPadButtons": None,
                "FamilyBasicKeyboardButtons": None,
                "PartyTapButtons": None,
                "PachinkoButtons": None,
                "ExcitingBoxingButtons": None,
                "JissenMahjongButtons": None,
                "SuborKeyboardButtons": None,
                "BandaiMicrophoneButtons": None,
                "VirtualBoyButtons": None,
                "KonamiHyperShotButtons": None,
                "ArkanoidButtons": None,
                "ZapperButtons": None,
                "OekakidsButtons": None,
                "BandaiHypershotButtons": None,
            })
            
        return mapping

    def write_config(
        self,
        config_path: str,
        controllers: list[tuple[str, Optional[SDLInfo]]],
    ) -> bool:
        try:
            config_path = os.path.expanduser(config_path)
            if not os.path.exists(config_path):
                print(f"[MesenWriter] Config file not found: {config_path}")
                return False

            with open(config_path, "r") as f:
                config = json.load(f)

            for system in ["Nes", "Snes"]:
                if system not in config:
                    continue
                
                # Clear all ports first
                for i in range(1, 9):
                    port_key = f"Port{i}"
                    if port_key in config[system]:
                        config[system][port_key]["Type"] = "None"
                        for m in range(1, 5):
                            mapping_key = f"Mapping{m}"
                            if mapping_key in config[system][port_key]:
                                # Clear mapping (set int values to 0)
                                for k in config[system][port_key][mapping_key]:
                                    if isinstance(config[system][port_key][mapping_key][k], int):
                                        config[system][port_key][mapping_key][k] = 0

                # Map ready controllers
                for player_index, (unique_id, sdl_info) in enumerate(controllers):
                    if player_index >= 8: break
                    
                    port_key = f"Port{player_index + 1}"
                    if port_key not in config[system]:
                        config[system][port_key] = {}
                    
                    config[system][port_key]["Type"] = "NesController" if system == "Nes" else "StandardController"
                    config[system][port_key]["Mapping1"] = self._map_controller(player_index, system, sdl_info)

            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)

            print(f"[MesenWriter] Configured {len(controllers)} controllers successfully")
            return True

        except Exception as e:
            print(f"[MesenWriter] Error writing config: {e}")
            return False
