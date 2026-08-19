"""Safe, read-first access to a legacy ddrum DDTi.

The public API contains no active configuration writer until the device's
SysEx protocol is experimentally validated.
"""

from .device import DDTi, ProtocolNotValidatedError
from .discovery import DeviceInfo, discover_devices
from .models import DDTiConfiguration, DDTiGlobalTriggerRecord, DDTiInput, DDTiKit, DDTiZone, decode_configuration, encode_configuration
from .protocol import DDTiDump, DDTiPacket, decode_dump

__all__ = [
    "DDTi", "DDTiConfiguration", "DDTiDump", "DDTiGlobalTriggerRecord", "DDTiInput", "DDTiKit", "DDTiPacket", "DDTiZone", "DeviceInfo",
    "ProtocolNotValidatedError", "decode_configuration", "decode_dump", "discover_devices", "encode_configuration",
]
