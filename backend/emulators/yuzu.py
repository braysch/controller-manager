"""Yuzu qt-config.ini writer - uses GUID/port from evdev-computed values."""

import configparser
import os
from typing import Optional

from emulators.base import EmulatorConfigWriter
from controllers.device_matcher import SDLInfo


class YuzuConfigWriter(EmulatorConfigWriter):
    # Microsoft vendor ID for Xbox controllers
    XBOX_VENDOR = 0x045E

    def _get_controller_mappings(
        self, sdl_info: SDLInfo
    ) -> dict[str, str]:
        """Get complete button mappings for a controller."""
        guid = sdl_info.guid
        port = sdl_info.port
        is_xbox = sdl_info.vendor_id == self.XBOX_VENDOR

        if is_xbox:
            # Xbox controller - NO deadzone in lstick/rstick, threshold uses 0.5
            return {
                "button_a": f"button:1,guid:{guid},port:{port},engine:sdl",
                "button_b": f"button:0,guid:{guid},port:{port},engine:sdl",
                "button_x": f"button:4,guid:{guid},port:{port},engine:sdl",
                "button_y": f"button:3,guid:{guid},port:{port},engine:sdl",
                "button_lstick": f"button:13,guid:{guid},port:{port},engine:sdl",
                "button_rstick": f"button:14,guid:{guid},port:{port},engine:sdl",
                "button_l": f"button:6,guid:{guid},port:{port},engine:sdl",
                "button_r": f"button:7,guid:{guid},port:{port},engine:sdl",
                "button_zl": f"threshold:0.5,axis:5,guid:{guid},port:{port},invert:+,engine:sdl",
                "button_zr": f"threshold:0.5,axis:4,guid:{guid},port:{port},invert:+,engine:sdl",
                "button_plus": f"button:11,guid:{guid},port:{port},engine:sdl",
                "button_minus": f"button:10,guid:{guid},port:{port},engine:sdl",
                "button_dleft": f"hat:0,direction:left,guid:{guid},port:{port},engine:sdl",
                "button_dup": f"hat:0,direction:up,guid:{guid},port:{port},engine:sdl",
                "button_dright": f"hat:0,direction:right,guid:{guid},port:{port},engine:sdl",
                "button_ddown": f"hat:0,direction:down,guid:{guid},port:{port},engine:sdl",
                "button_slleft": f"button:6,guid:{guid},port:{port},engine:sdl",
                "button_srleft": f"button:7,guid:{guid},port:{port},engine:sdl",
                "button_home": f"button:12,guid:{guid},port:{port},engine:sdl",
                "button_screenshot": f"button:15,guid:{guid},port:{port},engine:sdl",
                "button_slright": f"button:6,guid:{guid},port:{port},engine:sdl",
                "button_srright": f"button:7,guid:{guid},port:{port},engine:sdl",
                "lstick": f"invert_y:+,invert_x:+,offset_y:0.000000,axis_y:1,offset_x:-0.000000,axis_x:0,guid:{guid},port:{port},engine:sdl",
                "rstick": f"invert_y:+,invert_x:+,offset_y:0.000000,axis_y:3,offset_x:-0.000000,axis_x:2,guid:{guid},port:{port},engine:sdl",
                "motionleft": "[empty]",
                "motionright": "[empty]",
            }
        else:
            # Generic controller (SNES-style) - HAS deadzone, threshold uses 0.500000
            return {
                "button_a": f"button:1,guid:{guid},port:{port},engine:sdl",
                "button_b": f"button:0,guid:{guid},port:{port},engine:sdl",
                "button_x": f"button:4,guid:{guid},port:{port},engine:sdl",
                "button_y": f"button:3,guid:{guid},port:{port},engine:sdl",
                "button_lstick": "[empty]",
                "button_rstick": "[empty]",
                "button_l": f"button:6,guid:{guid},port:{port},engine:sdl",
                "button_r": f"button:7,guid:{guid},port:{port},engine:sdl",
                "button_zl": f"threshold:0.500000,axis:2,guid:{guid},port:{port},invert:+,engine:sdl",
                "button_zr": f"threshold:0.500000,axis:3,guid:{guid},port:{port},invert:+,engine:sdl",
                "button_plus": f"button:11,guid:{guid},port:{port},engine:sdl",
                "button_minus": f"button:10,guid:{guid},port:{port},engine:sdl",
                "button_dleft": f"hat:0,direction:left,guid:{guid},port:{port},engine:sdl",
                "button_dup": f"hat:0,direction:up,guid:{guid},port:{port},engine:sdl",
                "button_dright": f"hat:0,direction:right,guid:{guid},port:{port},engine:sdl",
                "button_ddown": f"hat:0,direction:down,guid:{guid},port:{port},engine:sdl",
                "button_slleft": f"button:6,guid:{guid},port:{port},engine:sdl",
                "button_srleft": f"button:7,guid:{guid},port:{port},engine:sdl",
                "button_home": f"button:12,guid:{guid},port:{port},engine:sdl",
                "button_screenshot": "[empty]",
                "button_slright": f"button:6,guid:{guid},port:{port},engine:sdl",
                "button_srright": f"button:7,guid:{guid},port:{port},engine:sdl",
                "lstick": f"deadzone:0.150000,invert_y:+,invert_x:+,offset_y:0.000000,axis_y:1,offset_x:-0.000000,axis_x:0,guid:{guid},port:{port},engine:sdl",
                "rstick": f"deadzone:0.150000,invert_y:+,invert_x:+,offset_y:0.000000,axis_y:3,offset_x:-0.000000,axis_x:2,guid:{guid},port:{port},engine:sdl",
                "motionleft": "[empty]",
                "motionright": "[empty]",
            }

    def write_config(
        self,
        config_path: str,
        controllers: list[tuple[str, Optional[SDLInfo]]],
    ) -> bool:
        """Write controller configuration to Yuzu's qt-config.ini."""
        try:
            config_path = os.path.expanduser(config_path)

            if not os.path.exists(config_path):
                print(f"[YuzuWriter] Config file not found: {config_path}")
                return False

            # Read config preserving formatting
            config = configparser.RawConfigParser()
            config.read(config_path)

            if "Controls" not in config:
                print("[YuzuWriter] No [Controls] section in config")
                return False

            # Disconnect all players first
            for i in range(10):
                player_key = f"player_{i}_connected"
                if player_key in config["Controls"]:
                    config.set("Controls", player_key, "false")
                    # Also handle \default=false lines
                    default_key = f"player_{i}_connected\\default"
                    if default_key in config["Controls"]:
                        config.set("Controls", default_key, "false")

            # Map ready controllers to players
            for player_index, (unique_id, sdl_info) in enumerate(controllers):
                if sdl_info is None:
                    print(f"[YuzuWriter] No SDL info for {unique_id}, skipping player {player_index}")
                    continue

                mappings = self._get_controller_mappings(sdl_info)

                # Set connected
                config.set("Controls", f"player_{player_index}_connected", "true")
                default_key = f"player_{player_index}_connected\\default"
                if default_key in config["Controls"]:
                    config.set("Controls", default_key, "false")

                # Write button mappings
                for button, mapping in mappings.items():
                    button_key = f"player_{player_index}_{button}"
                    if mapping == "[empty]":
                        config.set("Controls", button_key, mapping)
                    else:
                        config.set("Controls", button_key, f'"{mapping}"')

                    # Handle \default keys
                    default_button_key = f"{button_key}\\default"
                    if default_button_key in config["Controls"]:
                        config.set("Controls", default_button_key, "false")

            # Write back
            with open(config_path, "w") as f:
                config.write(f, space_around_delimiters=False)

            print(f"[YuzuWriter] Configured {len(controllers)} controllers successfully")
            return True

        except Exception as e:
            print(f"[YuzuWriter] Error writing config: {e}")
            return False
