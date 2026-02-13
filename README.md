Attribtues for USB device

name - "Controller"
device_type - "joystick"
protocol - "usb"
read_size - 1
manager - DeviceManager object
leds - []

read() - Read events from the device
set_vibration() - Control vibration/rumble
get_char_device_path() - Get character device path
get_char_name() - Get character device name
get_number() - Get device number

_device_path - "/dev/input/by-id/usb-0079_Controller-event-joystick"
_character_device_path - "/dev/input/event3"
_GamePad__device_number - 0

Attributes for BT device

address - MAC address of the Bluetooth device (e.g., "AA:BB:CC:DD:EE:FF")
name - Device name (e.g., "DualShock 4 Wireless Controller")
details - Additional device information (platform-specific metadata)
__str__, __repr__ - String representations
__eq__, __hash__ - Comparison and hashing
__init__ - Constructor

A Button for

keyboard - player_0_button_a="engine:keyboard,code:67,toggle:0"

xbox - player_0_button_a="button:1,guid:050000005e040000130b000023050000,port:0,engine:sdl"

snes - player_0_button_a="button:1,guid:03000000790000002601000011010000,port:0,engine:sdl"