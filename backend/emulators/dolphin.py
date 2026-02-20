"""Dolphin emulator config writers for GCPad (GameCube) and Wiimote (Wii)."""

import configparser
import os
from typing import Optional

from emulators.base import EmulatorConfigWriter
from controllers.device_matcher import SDLInfo

MAX_PLAYERS = 4


def _read_config(config_path: str) -> configparser.RawConfigParser:
    config = configparser.RawConfigParser()
    config.optionxform = str  # preserve key case (Dolphin uses mixed-case keys)
    config.read(config_path)
    return config


def _write_config(config: configparser.RawConfigParser, config_path: str) -> None:
    with open(config_path, "w") as f:
        config.write(f)


class DolphinGCWriter(EmulatorConfigWriter):
    """Updates the Device line in GCPadNew.ini for each ready controller slot."""

    def write_config(
        self,
        config_path: str,
        controllers: list[tuple[str, Optional[SDLInfo]]],
    ) -> bool:
        try:
            config_path = os.path.expanduser(config_path)
            if not os.path.exists(config_path):
                print(f"[DolphinGCWriter] Config not found: {config_path}")
                return False

            config = _read_config(config_path)

            for slot_index, (unique_id, sdl_info) in enumerate(controllers[:MAX_PLAYERS]):
                section = f"GCPad{slot_index + 1}"
                if sdl_info is None:
                    print(f"[DolphinGCWriter] No SDL info for {unique_id}, skipping slot {slot_index + 1}")
                    continue
                if section not in config:
                    config.add_section(section)
                config.set(section, "Device", f"SDL/{sdl_info.port}/{sdl_info.device_name}")

            _write_config(config, config_path)
            print(f"[DolphinGCWriter] Configured {len(controllers[:MAX_PLAYERS])} GCPad slots")
            return True

        except Exception as e:
            print(f"[DolphinGCWriter] Error: {e}")
            return False


class DolphinWiiWriter(EmulatorConfigWriter):
    """Updates Device and Source in WiimoteNew.ini for each ready controller slot."""

    def write_config(
        self,
        config_path: str,
        controllers: list[tuple[str, Optional[SDLInfo]]],
    ) -> bool:
        try:
            config_path = os.path.expanduser(config_path)
            if not os.path.exists(config_path):
                print(f"[DolphinWiiWriter] Config not found: {config_path}")
                return False

            config = _read_config(config_path)

            for slot_index in range(MAX_PLAYERS):
                section = f"Wiimote{slot_index + 1}"
                if section not in config:
                    config.add_section(section)

                if slot_index < len(controllers):
                    unique_id, sdl_info = controllers[slot_index]
                    if sdl_info is None:
                        print(f"[DolphinWiiWriter] No SDL info for {unique_id}, disabling slot {slot_index + 1}")
                        config.set(section, "Source", "0")
                        continue
                    config.set(section, "Device", f"SDL/{sdl_info.port}/{sdl_info.device_name}")
                    config.set(section, "Source", "1")  # Emulated Wiimote
                else:
                    config.set(section, "Source", "0")  # Disabled

            _write_config(config, config_path)
            print(f"[DolphinWiiWriter] Configured {len(controllers[:MAX_PLAYERS])} Wiimote slots")
            return True

        except Exception as e:
            print(f"[DolphinWiiWriter] Error: {e}")
            return False
