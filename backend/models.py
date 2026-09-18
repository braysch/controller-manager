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
    has_nunchuk: bool = False


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
    has_nunchuk: bool = False


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
    # Which game is about to launch and which console system it belongs to
    # (e.g. "Snes") - only used to look up a per-game custom mapping (see
    # CustomMapping) for the Mesen branch; every other system's section in
    # settings.json still gets its normal default profile regardless.
    game_name: Optional[str] = None
    system: Optional[str] = None


class CustomMapping(BaseModel):
    game_name: str
    controller_signature: str
    system: str
    # Role name (e.g. "A", "Select") -> raw physical binding captured from
    # Input Config's raw-input stream: {"label": str, "code": str, "kind": "key"}
    # - or explicitly None, meaning the role is deliberately left unmapped
    # (distinct from a role simply absent from this dict, which falls back
    # to the controller type's normal default instead).
    bindings: dict[str, Optional[dict]]


class CustomMappingUpsert(BaseModel):
    game_name: str
    controller_signature: str
    system: str
    bindings: dict[str, Optional[dict]]


class CustomMappingDelete(BaseModel):
    game_name: str
    controller_signature: str
    system: str


class ControllerTypeDefault(BaseModel):
    name_pattern: str
    img_src: str = "default.png"
    snd_src: str = "default.mp3"
    vendor_id: Optional[int] = None
    product_id: Optional[int] = None
    guid_override: Optional[str] = None
    start_button: Optional[int] = None  # None means use BTN_START; set to BTN_TR2 (313) where applicable
