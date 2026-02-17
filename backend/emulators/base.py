"""Abstract base for emulator config writers."""

from abc import ABC, abstractmethod
from typing import Optional
from controllers.device_matcher import SDLInfo


class EmulatorConfigWriter(ABC):
    @abstractmethod
    def write_config(
        self,
        config_path: str,
        controllers: list[tuple[str, Optional[SDLInfo]]],
    ) -> bool:
        """
        Write controller configuration to the emulator's config file.

        Args:
            config_path: Path to the config file
            controllers: List of (unique_id, SDLInfo) pairs in player order

        Returns:
            True on success, False on error
        """
        ...
