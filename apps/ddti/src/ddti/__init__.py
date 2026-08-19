"""Safe, read-first access to a legacy ddrum DDTi.

The public API contains no active configuration writer until the device's
SysEx protocol is experimentally validated.
"""

from .device import DDTi, ProtocolNotValidatedError
from .discovery import DeviceInfo, discover_devices
from .protocol import DDTiDump, DDTiPacket, decode_dump

__all__ = ["DDTi", "DDTiDump", "DDTiPacket", "DeviceInfo", "ProtocolNotValidatedError", "decode_dump", "discover_devices"]
