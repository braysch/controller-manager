import ctypes
import os
import sys

# Attempt to find the system SDL2 library
_lib_paths = [
    "libSDL2-2.0.so.0",
    "libSDL2.so",
    "/usr/lib/x86_64-linux-gnu/libSDL2-2.0.so.0",
    "/usr/lib/libSDL2-2.0.so.0"
]

_sdl = None
for path in _lib_paths:
    try:
        _sdl = ctypes.CDLL(path)
        break
    except Exception:
        continue

def get_sdl_joystick_index(device_name: str) -> int:
    """
    Query the system SDL2 library directly to find the current index of a joystick by its name.
    This ensures we match exactly what Mesen sees.
    """
    if not _sdl:
        return -1
    
    try:
        _sdl.SDL_Init(0x00000200) # SDL_INIT_JOYSTICK
        num_joysticks = _sdl.SDL_NumJoysticks()
        
        # SDL2 returns a pointer for names, we need to handle that
        _sdl.SDL_JoystickNameForIndex.restype = ctypes.c_char_p
        
        for i in range(num_joysticks):
            name_ptr = _sdl.SDL_JoystickNameForIndex(i)
            if name_ptr:
                name = name_ptr.decode('utf-8', errors='ignore')
                if name == device_name:
                    return i
                    
        # Optional: Try a fuzzy match if exact name fails
        for i in range(num_joysticks):
            name_ptr = _sdl.SDL_JoystickNameForIndex(i)
            if name_ptr:
                name = name_ptr.decode('utf-8', errors='ignore')
                if device_name in name or name in device_name:
                    return i

    except Exception:
        pass
    finally:
        try:
            _sdl.SDL_QuitSubSystem(0x00000200)
        except Exception:
            pass
            
    return -1

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(get_sdl_joystick_index(sys.argv[1]))
