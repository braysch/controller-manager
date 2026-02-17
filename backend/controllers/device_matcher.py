"""Controller info container - GUID and port now come directly from evdev_monitor."""


class SDLInfo:
    """SDL-compatible controller info (guid + port + vendor/product)."""

    def __init__(self, guid: str, port: int, vendor_id: int, product_id: int):
        self.guid = guid
        self.port = port
        self.vendor_id = vendor_id
        self.product_id = product_id
