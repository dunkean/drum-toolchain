"""Safe, read-first access to a legacy ddrum DDTi.

The public API contains no active configuration writer until the device's
SysEx protocol is experimentally validated.
"""

from .device import DDTi, ProtocolNotValidatedError
from .discovery import DeviceInfo, discover_devices

__all__ = ["DDTi", "DeviceInfo", "ProtocolNotValidatedError", "discover_devices"]
