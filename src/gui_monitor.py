import asyncio
import tkinter as tk
from tkinter import ttk
from evdev import InputDevice, ecodes, list_devices
import select
import configparser
from PIL import Image, ImageTk
import os
import pygame

# (vendor_id, product_id) pairs where BTN_TR2 is the Start/+ button, not a trigger
_BTN_TR2_START_VID_PID: set[tuple[int, int]] = {
    (0x057E, 0x2017),  # SNES Controller
}
# Device name patterns (lowercase) for controllers with no vendor/product where BTN_TR2 is Start/+
_BTN_TR2_START_NAMES = ("lic pro controller",)


class GUIMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("Controller Monitor")
        
        # Initialize pygame mixer for audio
        pygame.mixer.init()

        # Create GUI layout
        self.connected_label = ttk.Label(root, text="Connected Devices")
        self.connected_label.pack()
        self.connected_listbox = tk.Listbox(root, height=10, width=50)
        self.connected_listbox.pack()

        self.ready_label = ttk.Label(root, text="Ready Devices")
        self.ready_label.pack()
        
        # Replace listbox with grid frame
        self.ready_frame = ttk.Frame(root)
        self.ready_frame.pack(pady=10)
        
        # Create 2x4 grid of controller slots with fixed square dimensions
        self.controller_slots = []
        slot_size = 140  # Square size in pixels
        for row in range(2):
            for col in range(4):
                slot_frame = ttk.Frame(self.ready_frame, relief="solid", borderwidth=1, width=slot_size, height=slot_size)
                slot_frame.grid(row=row, column=col, padx=5, pady=5)
                slot_frame.grid_propagate(False)
                slot_frame.pack_propagate(False)
                
                # Image label (centered, fixed size for image)
                img_label = ttk.Label(slot_frame)
                img_label.place(relx=0.5, rely=0.4, anchor="center")
                
                # Name label (at bottom, wrapped)
                name_label = ttk.Label(slot_frame, text="", wraplength=slot_size-10, anchor="center")
                name_label.place(relx=0.5, rely=0.85, anchor="center")
                
                self.controller_slots.append({
                    'frame': slot_frame,
                    'img_label': img_label,
                    'name_label': name_label,
                    'device_path': None,
                    'photo': None  # Keep reference to prevent garbage collection
                })

        # Add buttons
        self.reassign_button = ttk.Button(root, text="Reassign", command=self.reassign_ready_devices)
        self.reassign_button.pack()

        self.okay_button = ttk.Button(root, text="Okay", command=self.configure_controllers)
        self.okay_button.pack()

        # Track devices
        self.connected_devices = {}  # path -> name mapping
        self.ready_devices = {}      # path -> {'name': str, 'img_src': str, 'snd_src': str} mapping
        self.known_devices = set()   # set of paths we've seen
        self._start_buttons: dict[str, int] = {}  # path -> start button code
        
        # Database connection (you may need to add this)
        self.controller_db = {}  # path -> {'name': str, 'img_src': str, 'snd_src': str}
        
        # Controller name to default assets mapping
        # Add new mappings here: "Controller Name": "asset_name"
        # This will use ./images/{asset_name}.png and ./sounds/{asset_name}.mp3
        self.controller_defaults = {
            "Xbox Wireless Controller": "xbox-one",
            "Lic Pro Controller": "switch_gamecube",
        }

    def log_to_terminal(self, message):
        """Log a message to the terminal."""
        print(message)

    def add_connected_device(self, device_name, device_path):
        """Add a device to the connected devices list."""
        if device_path not in self.connected_devices:
            self.connected_devices[device_path] = device_name
            self.connected_listbox.insert(tk.END, device_name)
            self.log_to_terminal(f"[CONNECTED] {device_name} ({device_path})")

    def load_controller_image(self, img_src):
        """Load and resize a controller image maintaining aspect ratio."""
        try:
            if not img_src or not os.path.exists(img_src):
                img_src = "./images/default.png"
            
            image = Image.open(img_src)
            
            # Calculate size to fit in slot while maintaining aspect ratio
            max_width = 130
            max_height = 90
            
            # Get original dimensions
            original_width, original_height = image.size
            
            # Calculate scaling factors
            width_ratio = max_width / original_width
            height_ratio = max_height / original_height
            
            # Use the smaller ratio to ensure image fits within bounds
            scale_factor = min(width_ratio, height_ratio)
            
            # Calculate new dimensions
            new_width = int(original_width * scale_factor)
            new_height = int(original_height * scale_factor)
            
            # Resize maintaining aspect ratio
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image)
        except Exception as e:
            self.log_to_terminal(f"[ERROR] Failed to load image {img_src}: {e}")
            # Try to load default image
            try:
                image = Image.open("./images/default.png")
                original_width, original_height = image.size
                width_ratio = 130 / original_width
                height_ratio = 90 / original_height
                scale_factor = min(width_ratio, height_ratio)
                new_width = int(original_width * scale_factor)
                new_height = int(original_height * scale_factor)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                return ImageTk.PhotoImage(image)
            except:
                return None

    def play_controller_sound(self, snd_src):
        """Play the controller connection sound."""
        try:
            if not snd_src or not os.path.exists(snd_src):
                snd_src = "./sounds/default.mp3"
            
            if os.path.exists(snd_src):
                pygame.mixer.music.load(snd_src)
                pygame.mixer.music.play()
                self.log_to_terminal(f"[AUDIO] Playing sound: {snd_src}")
            else:
                self.log_to_terminal(f"[ERROR] Sound file not found: {snd_src}")
        except Exception as e:
            self.log_to_terminal(f"[ERROR] Failed to play sound {snd_src}: {e}")

    def update_ready_grid(self):
        """Update the grid display with current ready devices."""
        # Clear all slots
        for slot in self.controller_slots:
            slot['img_label'].config(image='')
            slot['name_label'].config(text='')
            slot['device_path'] = None
            slot['photo'] = None
        
        # Fill slots with ready devices
        for idx, (device_path, device_info) in enumerate(self.ready_devices.items()):
            if idx >= 8:  # Only 8 slots available
                break
            
            slot = self.controller_slots[idx]
            slot['device_path'] = device_path
            
            # Load image
            img_src = device_info.get('img_src', './images/default.png')
            photo = self.load_controller_image(img_src)
            
            if photo:
                slot['photo'] = photo  # Keep reference
                slot['img_label'].config(image=photo)
            
            # Set name
            slot['name_label'].config(text=device_info.get('name', 'Unknown'))

    def get_default_assets(self, device_name):
        """Get default image and sound paths based on controller name."""
        # Check if we have a specific mapping for this controller
        for controller_name, asset_name in self.controller_defaults.items():
            if controller_name.lower() in device_name.lower():
                return {
                    'img_src': f'./images/{asset_name}.png',
                    'snd_src': f'./sounds/{asset_name}.mp3'
                }
        
        # Return generic defaults if no match found
        return {
            'img_src': './images/default.png',
            'snd_src': './sounds/default.mp3'
        }

    def move_to_ready(self, device_path):
        """Move a device from connected to ready."""
        if device_path in self.connected_devices:
            device_name = self.connected_devices[device_path]
            if device_path not in self.ready_devices:
                # Get device info from database or create default
                device_info = self.controller_db.get(device_path, {})
                
                # Get default assets based on controller name
                default_assets = self.get_default_assets(device_name)
                
                # Build final device info, using database values if available, otherwise defaults
                final_device_info = {
                    'name': device_info.get('name', device_name),
                    'img_src': device_info.get('img_src', default_assets['img_src']),
                    'snd_src': device_info.get('snd_src', default_assets['snd_src'])
                }
                
                self.ready_devices[device_path] = final_device_info
                self.update_ready_grid()
                
                # Play controller connection sound
                self.play_controller_sound(final_device_info['snd_src'])
                
                # Get and log GUID
                try:
                    device = InputDevice(device_path)
                    guid = self.get_sdl_guid(device)
                    self.log_to_terminal(f"[READY] {device_name} ({device_path}) - GUID: {guid}")
                except Exception as e:
                    self.log_to_terminal(f"[READY] {device_name} ({device_path}) - GUID: Error retrieving GUID: {e}")

    def remove_disconnected_device(self, device_path):
        """Remove a device from connected and ready lists."""
        if device_path in self.connected_devices:
            device_name = self.connected_devices.pop(device_path)
            
            # Remove from connected listbox
            for i in range(self.connected_listbox.size()):
                if self.connected_listbox.get(i) == device_name:
                    self.connected_listbox.delete(i)
                    break
            
            # Remove from ready dict if present
            if device_path in self.ready_devices:
                del self.ready_devices[device_path]
                self.update_ready_grid()
            
            self.log_to_terminal(f"[DISCONNECTED] {device_name} ({device_path})")

    def reassign_ready_devices(self):
        """Clear the ready devices list."""
        self.ready_devices.clear()
        self.update_ready_grid()
        self.log_to_terminal("[ACTION] Cleared ready devices.")

    def swap_bytes(self, value):
        """Swap the two bytes of a 16-bit value."""
        return ((value & 0xFF) << 8) | ((value & 0xFF00) >> 8)

    def get_sdl_guid(self, device):
        """Generate SDL-style GUID from device info matching Yuzu's format."""
        bus = device.info.bustype
        vendor = device.info.vendor
        product = device.info.product
        version = device.info.version

        vendor_swapped = self.swap_bytes(vendor)
        product_swapped = self.swap_bytes(product)
        version_swapped = self.swap_bytes(version)
        
        # Format as 32 hex characters (16 bytes)
        # This matches SDL's format: bus(2) + 0(4) + vendor(4) + 0(4) + product(4) + 0(4) + version(4) + 0(8)
        guid = f"{bus:02x}000000{vendor_swapped:04x}0000{product_swapped:04x}0000{version_swapped:04x}0000"
        
        self.log_to_terminal(f"[DEBUG] Generated GUID: {guid} for bus={bus:02x}, vendor={vendor:04x}, product={product:04x}, version={version:04x}")
        
        return guid

    def get_controller_mappings(self, device_path, sdl_port):
        """Get complete button mappings for a controller using SDL GUID."""
        try:
            device = InputDevice(device_path)
            guid = self.get_sdl_guid(device)
            
            # Determine controller type based on vendor/product ID
            vendor = device.info.vendor
            
            # Xbox controller detection (0x045e is Microsoft vendor ID)
            is_xbox = vendor == 0x045e
            
            # Standard SDL controller button mappings
            if is_xbox:
                # Xbox controller - NO deadzone in lstick/rstick, threshold uses 0.5
                mappings = {
                    "button_a": f"button:1,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_b": f"button:0,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_x": f"button:4,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_y": f"button:3,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_lstick": f"button:13,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_rstick": f"button:14,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_l": f"button:6,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_r": f"button:7,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_zl": f"threshold:0.5,axis:5,guid:{guid},port:{sdl_port},invert:+,engine:sdl",
                    "button_zr": f"threshold:0.5,axis:4,guid:{guid},port:{sdl_port},invert:+,engine:sdl",
                    "button_plus": f"button:11,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_minus": f"button:10,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_dleft": f"hat:0,direction:left,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_dup": f"hat:0,direction:up,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_dright": f"hat:0,direction:right,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_ddown": f"hat:0,direction:down,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_slleft": f"button:6,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_srleft": f"button:7,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_home": f"button:12,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_screenshot": f"button:15,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_slright": f"button:6,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_srright": f"button:7,guid:{guid},port:{sdl_port},engine:sdl",
                    "lstick": f"invert_y:+,invert_x:+,offset_y:0.000000,axis_y:1,offset_x:-0.000000,axis_x:0,guid:{guid},port:{sdl_port},engine:sdl",
                    "rstick": f"invert_y:+,invert_x:+,offset_y:0.000000,axis_y:3,offset_x:-0.000000,axis_x:2,guid:{guid},port:{sdl_port},engine:sdl",
                    "motionleft": "[empty]",
                    "motionright": "[empty]",
                }
            else:
                # Generic controller (SNES-style) - HAS deadzone, threshold uses 0.500000
                mappings = {
                    "button_a": f"button:1,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_b": f"button:0,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_x": f"button:4,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_y": f"button:3,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_lstick": "[empty]",
                    "button_rstick": "[empty]",
                    "button_l": f"button:6,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_r": f"button:7,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_zl": f"threshold:0.500000,axis:2,guid:{guid},port:{sdl_port},invert:+,engine:sdl",
                    "button_zr": f"threshold:0.500000,axis:3,guid:{guid},port:{sdl_port},invert:+,engine:sdl",
                    "button_plus": f"button:11,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_minus": f"button:10,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_dleft": f"hat:0,direction:left,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_dup": f"hat:0,direction:up,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_dright": f"hat:0,direction:right,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_ddown": f"hat:0,direction:down,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_slleft": f"button:6,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_srleft": f"button:7,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_home": f"button:12,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_screenshot": "[empty]",
                    "button_slright": f"button:6,guid:{guid},port:{sdl_port},engine:sdl",
                    "button_srright": f"button:7,guid:{guid},port:{sdl_port},engine:sdl",
                    "lstick": f"deadzone:0.150000,invert_y:+,invert_x:+,offset_y:0.000000,axis_y:1,offset_x:-0.000000,axis_x:0,guid:{guid},port:{sdl_port},engine:sdl",
                    "rstick": f"deadzone:0.150000,invert_y:+,invert_x:+,offset_y:0.000000,axis_y:3,offset_x:-0.000000,axis_x:2,guid:{guid},port:{sdl_port},engine:sdl",
                    "motionleft": "[empty]",
                    "motionright": "[empty]",
                }
            
            return mappings
        except Exception as e:
            self.log_to_terminal(f"[ERROR] Failed to get mappings for {device_path}: {e}")
            return {}

    def configure_controllers(self):
        """Run the logic to configure controllers in yuzu."""
        try:
            config_path = "/home/brayschway/.var/app/org.yuzu_emu.yuzu/config/yuzu/qt-config.ini"
            
            # Build ready_controllers list with mappings
            # SDL port matches the order devices were detected
            ready_controllers = []
            for sdl_port, device_path in enumerate(self.ready_devices.keys()):
                mappings = self.get_controller_mappings(device_path, sdl_port)
                if mappings:
                    ready_controllers.append(mappings)
            
            # Read config using RawConfigParser to preserve formatting
            config = configparser.RawConfigParser()
            config.read(config_path)

            # Set all player_x_connected to false
            for i in range(10):
                player_key = f"player_{i}_connected"
                if "Controls" in config and player_key in config["Controls"]:
                    config.set("Controls", player_key, "false")

            # Map ready controllers to players
            for player_index, controller in enumerate(ready_controllers):
                player_key = f"player_{player_index}_connected"
                config.set("Controls", player_key, "true")

                # Update ALL button mappings with proper formatting
                for button, mapping in controller.items():
                    button_key = f"player_{player_index}_{button}"
                    # Set the value - ConfigParser will handle the quotes
                    if mapping == "[empty]":
                        config.set("Controls", button_key, mapping)
                    else:
                        # Add quotes around the value
                        config.set("Controls", button_key, f'"{mapping}"')

            # Write the updated config back to the file
            with open(config_path, "w") as config_file:
                config.write(config_file, space_around_delimiters=False)
            
            self.log_to_terminal("[ACTION] Configured controllers successfully.")
        except Exception as e:
            self.log_to_terminal(f"[ERROR] Failed to configure controllers: {e}")

    async def monitor_inputs(self):
        """Monitor inputs from connected controllers using evdev."""
        while True:
            try:
                # Get the current list of input devices
                devices = [InputDevice(path) for path in list_devices()]
                current_paths = {dev.path for dev in devices}
                
                # Add newly connected devices
                for device in devices:
                    if device.path not in self.known_devices:
                        self.known_devices.add(device.path)
                        self.add_connected_device(device.name, device.path)
                        vid, pid = device.info.vendor, device.info.product
                        tr2_is_start = (
                            (vid, pid) in _BTN_TR2_START_VID_PID
                            or any(p in device.name.lower() for p in _BTN_TR2_START_NAMES)
                        )
                        self._start_buttons[device.path] = ecodes.BTN_TR2 if tr2_is_start else ecodes.BTN_START

                # Remove disconnected devices
                disconnected = self.known_devices - current_paths
                for path in disconnected:
                    self.known_devices.remove(path)
                    self.remove_disconnected_device(path)
                    self._start_buttons.pop(path, None)
                
                # Monitor for button presses on all connected devices
                if devices:
                    device_readers = {dev.fd: dev for dev in devices}
                    
                    # Use select with a timeout to avoid blocking
                    r, _, _ = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: select.select(device_readers.keys(), [], [], 0.1)
                    )
                    
                    for fd in r:
                        device = device_readers[fd]
                        for event in device.read():
                            if event.type == ecodes.EV_KEY and event.value == 1:  # Key press
                                if event.code == self._start_buttons.get(device.path, ecodes.BTN_START):
                                    self.move_to_ready(device.path)
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                self.log_to_terminal(f"Error monitoring inputs: {e}")
                await asyncio.sleep(1)

    async def run(self):
        """Run the GUI and monitoring tasks."""
        input_task = asyncio.create_task(self.monitor_inputs())
        
        try:
            while True:
                self.root.update_idletasks()
                self.root.update()
                await asyncio.sleep(0.1)
        except tk.TclError:
            # Window was closed
            input_task.cancel()


if __name__ == "__main__":
    root = tk.Tk()
    monitor = GUIMonitor(root)
    asyncio.run(monitor.run())