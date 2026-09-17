from pydantic import BaseModel
from typing import Optional


class ControllerProfile(BaseModel):
    unique_id: str
    default_name: str
    custom_name: Optional[str] = None
    img_src: str = "default.png"
    snd_src: str = "default.mp3"
    vendor_id: Optional[int] = None
    product_id: Optional[int] = None
    guid_override: Optional[str] = None
    bluetooth_address: Optional[str] = None
    start_button: Optional[int] = None
    tr2_is_start: bool = False
    start_button_override: Optional[int] = None


class ControllerProfileUpdate(BaseModel):
    custom_name: Optional[str] = None
    img_src: Optional[str] = None
    snd_src: Optional[str] = None
    guid_override: Optional[str] = None


class ConnectedController(BaseModel):
    unique_id: str
    name: str
    custom_name: Optional[str] = None
    img_src: str = "default.png"
    snd_src: str = "default.mp3"
    connection_type: str = "usb"  # "usb" or "bluetooth"
    battery_percent: Optional[int] = None
    vendor_id: Optional[int] = None
    product_id: Optional[int] = None
    paired_but_disconnected: bool = False
    guid: Optional[str] = None
    port: Optional[int] = None
    # Identical pads (e.g. twin dongle receivers with no serial) share a
    # unique_id, so the evdev path is the only reliable per-device handle.
    device_path: Optional[str] = None
    tr2_is_start: bool = False
    start_button_override: Optional[int] = None


class ReadyController(BaseModel):
    unique_id: str
    name: str
    custom_name: Optional[str] = None
    img_src: str = "default.png"
    snd_src: str = "default.mp3"
    connection_type: str = "usb"
    battery_percent: Optional[int] = None
    slot_index: int = 0
    guid: Optional[str] = None
    port: Optional[int] = None
    vendor_id: Optional[int] = None
    product_id: Optional[int] = None
    component_unique_ids: Optional[list[str]] = None
    component_names: Optional[list[str]] = None
    component_imgs: Optional[list[str]] = None
    device_path: Optional[str] = None
    tr2_is_start: bool = False
    start_button_override: Optional[int] = None


class MoveToReadyRequest(BaseModel):
    unique_id: str


class EmulatorConfig(BaseModel):
    id: int
    emulator_name: str
    config_path: str
    enabled: bool = True


class EmulatorConfigUpdate(BaseModel):
    config_path: Optional[str] = None
    enabled: Optional[bool] = None


class ApplyConfigRequest(BaseModel):
    emulator: Optional[str] = None
    force: bool = False


class ControllerTypeDefault(BaseModel):
    name_pattern: str
    img_src: str = "default.png"
    snd_src: str = "default.mp3"
    vendor_id: Optional[int] = None
    product_id: Optional[int] = None
    guid_override: Optional[str] = None
    start_button: Optional[int] = None  # None means use BTN_START; set to BTN_TR2 (313) where applicable
