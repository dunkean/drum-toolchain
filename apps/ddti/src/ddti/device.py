"""Public device facade with a confirmed-fields-only write boundary."""
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

    def write_configuration(
        self,
        configuration: object,
        *,
        source_raw: bytes | None = None,
        expected_sha256: str | None = None,
        confirmation: str | None = None,
    ) -> object:
        """Write only proven fields relative to an explicit source dump.

        The source bytes, reviewed candidate hash and confirmation token are
        mandatory. Omitting any of them preserves the former hard failure.
        """
        if source_raw is None or expected_sha256 is None or confirmation is None:
            raise ProtocolNotValidatedError(
                "DDTi writes require source_raw, reviewed expected_sha256, and explicit confirmation"
            )
        from .models import DDTiConfiguration
        from .transfer import send_safe_configuration

        if not isinstance(configuration, DDTiConfiguration):
            raise TypeError("configuration must be a DDTiConfiguration")
        if len(self.info.midi_outputs) != 1:
            raise RuntimeError(f"expected exactly one DDTi MIDI output; found {self.info.midi_outputs}")
        return send_safe_configuration(
            source_raw,
            configuration.raw,
            self.info.midi_outputs[0],
            expected_sha256=expected_sha256,
            confirmation=confirmation,
            inter_message_ms=50,
        )
