#!/usr/bin/env python3
"""Listen for button/axis events on all evdev devices and print them."""

import asyncio
from evdev import InputDevice, ecodes, list_devices


async def monitor_device(dev: InputDevice):
    """Read events from a single device asynchronously."""
    try:
        async for event in dev.async_read_loop():
            if event.type == ecodes.EV_KEY:
                state = "DOWN" if event.value == 1 else "UP" if event.value == 0 else "HOLD"
                code_name = ecodes.BTN.get(event.code) or ecodes.KEY.get(event.code) or str(event.code)
                if isinstance(code_name, list):
                    code_name = code_name[0]
                print(f"[{dev.name}]  {code_name} ({event.code})  {state}")
    except OSError:
        print(f"[{dev.name}] disconnected")


async def main():
    devices = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
            devices.append(dev)
            print(f"  {path}: {dev.name}")
        except Exception:
            pass

    if not devices:
        print("No input devices found.")
        return

    print("\nPress buttons/triggers on any controller (Ctrl+C to quit)\n")

    tasks = [asyncio.create_task(monitor_device(dev)) for dev in devices]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDone.")