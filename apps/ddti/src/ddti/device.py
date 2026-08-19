"""Public safe device facade.

Writing is a hard failure by design, independent of caller flags.  This keeps
the unfinished reverse-engineering state from becoming an accidental hardware
writer through the future REST API or GUI.
"""
from __future__ import annotations

from dataclasses import dataclass

from .discovery import DeviceInfo, discover_devices


class ProtocolNotValidatedError(RuntimeError):
    pass


@dataclass(frozen=True)
class DDTi:
    info: DeviceInfo

    @classmethod
    def connect(cls) -> "DDTi":
        devices = discover_devices()
        if len(devices) != 1:
            raise RuntimeError(f"expected exactly one DDTi candidate; found {len(devices)}")
        return cls(devices[0])

    def get_info(self) -> DeviceInfo:
        return self.info

    def read_configuration(self) -> None:
        raise ProtocolNotValidatedError("DDTi configuration decoding is unavailable until a real dump is captured and validated")

    def write_configuration(self, configuration: object) -> None:
        raise ProtocolNotValidatedError("DDTi writes are disabled: no validated legacy DDTi write protocol exists")
