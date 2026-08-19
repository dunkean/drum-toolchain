"""Safe access to a legacy ddrum DDTi with confirmed-fields-only writes."""

from .device import DDTi, ProtocolNotValidatedError
from .discovery import DeviceInfo, discover_devices
from .models import DDTiConfiguration, DDTiGlobalTriggerRecord, DDTiHiHatKitSettings, DDTiInput, DDTiKit, DDTiZone, decode_configuration, encode_configuration
from .protocol import DDTiDump, DDTiPacket, decode_dump
from .state import DDTiStateStore
from .transfer import DDTiSafeWritePlan, DDTiTransferPlan, DDTiTransferResult, build_safe_write_plan, build_transfer_plan, send_safe_configuration, send_reviewed_transfer

__all__ = [
    "DDTi", "DDTiConfiguration", "DDTiDump", "DDTiGlobalTriggerRecord", "DDTiHiHatKitSettings", "DDTiInput", "DDTiKit", "DDTiPacket", "DDTiStateStore", "DDTiZone", "DeviceInfo",
    "ProtocolNotValidatedError", "DDTiSafeWritePlan", "DDTiTransferPlan", "DDTiTransferResult", "build_safe_write_plan", "build_transfer_plan", "send_safe_configuration", "send_reviewed_transfer", "decode_configuration", "decode_dump", "discover_devices", "encode_configuration",
]
