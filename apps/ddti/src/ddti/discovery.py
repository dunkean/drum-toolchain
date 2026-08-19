"""Read-only Windows/Python MIDI discovery for the connected DDTi."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import platform
import subprocess


DDTI_USB_VID = "13B2"
DDTI_USB_PID = "0021"
DDTI_PORT_NAME = "TriggerIO"


@dataclass(frozen=True)
class DeviceInfo:
    """Facts reported by the operating system; no inferred protocol facts."""

    vid: str
    pid: str
    pnp_instance_id: str | None
    usb_parent_name: str | None
    midi_inputs: tuple[str, ...]
    midi_outputs: tuple[str, ...]
    serial: str | None = None
    manufacturer: str | None = None
    product: str | None = None

    def to_document(self) -> dict[str, object]:
        return asdict(self)


def _midi_ports() -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        import mido
    except ImportError as error:  # pragma: no cover - runtime dependency
        raise RuntimeError("mido and python-rtmidi are required for MIDI discovery") from error
    return tuple(mido.get_input_names()), tuple(mido.get_output_names())


def _windows_pnp_device() -> dict[str, str | None]:
    """Ask Windows for the composite parent without opening any device endpoint."""
    if platform.system() != "Windows":
        return {"instance_id": None, "name": None}
    script = (
        "$OutputEncoding=[System.Text.UTF8Encoding]::new(); $d=Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match "
        "'VID_13B2&PID_0021'} | Where-Object {$_.Class -eq 'USB'} | Select-Object -First 1 "
        "InstanceId,FriendlyName; if($d){$d|ConvertTo-Json -Compress}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=15,
    )
    if result.returncode or not result.stdout.strip():
        return {"instance_id": None, "name": None}
    value = json.loads(result.stdout)
    return {"instance_id": value.get("InstanceId"), "name": value.get("FriendlyName")}


def discover_devices() -> tuple[DeviceInfo, ...]:
    """Return matching legacy DDTi candidates based only on known USB/MIDI IDs."""
    inputs, outputs = _midi_ports()
    matches_in = tuple(name for name in inputs if DDTI_PORT_NAME.casefold() in name.casefold())
    matches_out = tuple(name for name in outputs if DDTI_PORT_NAME.casefold() in name.casefold())
    pnp = _windows_pnp_device()
    if not (matches_in or matches_out or pnp["instance_id"]):
        return ()
    return (DeviceInfo(
        vid=DDTI_USB_VID,
        pid=DDTI_USB_PID,
        pnp_instance_id=pnp["instance_id"],
        usb_parent_name=pnp["name"],
        midi_inputs=matches_in,
        midi_outputs=matches_out,
        # The legacy module serial printed on the chassis is not a USB descriptor.
        serial=None,
        manufacturer=None,
        product=DDTI_PORT_NAME if matches_in or matches_out else None,
    ),)
