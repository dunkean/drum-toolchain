"""Local, explicit audio capture and non-destructive WAV preparation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from math import gcd
from hashlib import sha256

import mido
import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from scipy.signal import butter, resample_poly, sosfiltfilt
import yaml


@dataclass(frozen=True)
class QualityProfile:
    target_sample_rate: int = 44100
    trim_threshold_db: float = -55.0
    normalize_dbfs: float = -1.0
    fade_in_ms: float = 2.0
    fade_out_ms: float = 8.0
    highpass_hz: float | None = None
    lowpass_hz: float | None = None
    max_duration_seconds: float | None = None
    force_mono: bool = False
    trim_tail: bool = True


def load_quality_profile(path: Path, name: str) -> QualityProfile:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read quality profile {path}: {error}") from error
    profiles = document.get("profiles", {}) if isinstance(document, dict) else {}
    values = profiles.get(name)
    if not isinstance(values, dict):
        raise ValueError(f"quality profile {name!r} not found in {path}")
    keys = {"target_sample_rate", "trim_threshold_db", "normalize_dbfs", "fade_in_ms", "fade_out_ms", "highpass_hz", "lowpass_hz", "max_duration_seconds", "force_mono", "trim_tail"}
    unknown = set(values) - keys
    if unknown:
        raise ValueError(f"unknown quality profile fields: {sorted(unknown)}")
    return QualityProfile(**values)


def devices() -> list[str]:
    return [f"{index}: {item['name']} ({item['max_input_channels']} in / {item['max_output_channels']} out)"
            for index, item in enumerate(sd.query_devices())]


def resolve_device(query: str) -> int | str:
    if query.split(":", 1)[0].isdigit():
        return int(query.split(":", 1)[0])
    matches = [index for index, item in enumerate(sd.query_devices()) if query.lower() in item["name"].lower()]
    if len(matches) != 1:
        raise ValueError(f"expected one audio device containing {query!r}, found {matches}")
    return matches[0]


def capture_note(*, midi_port: str, audio_input: str, note: int, velocity: int, output: Path,
                 channel: int = 1,
                 controllers: tuple[tuple[int, int], ...] = (),
                 duration: float = 3.0, gate: float = 0.1, preroll: float = 0.1,
                 sample_rate: int = 44100, channels: int = 1) -> Path:
    """Record a VST/audio loopback while issuing exactly one MIDI note.

    No input/output routing is guessed: callers choose both the MIDI output and
    audio capture device.  The generated WAV is an immutable raw take.
    """
    if not 0 <= note <= 127 or not 1 <= velocity <= 127 or not 1 <= channel <= 16:
        raise ValueError("note must be 0..127, velocity 1..127 and channel 1..16")
    if duration <= 0 or gate < 0 or preroll < 0 or not 1 <= channels <= 4:
        raise ValueError("invalid capture duration, gate, preroll or channel count")
    if any(not 0 <= control <= 127 or not 0 <= value <= 127 for control, value in controllers):
        raise ValueError("controller numbers and values must be in 0..127")
    if output.exists():
        raise FileExistsError(f"raw capture already exists and will not be overwritten: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    frames = round((duration + preroll) * sample_rate)
    recording = sd.rec(frames, samplerate=sample_rate, channels=channels, dtype="float32",
                       device=resolve_device(audio_input))
    time.sleep(preroll)
    with mido.open_output(midi_port) as port:
        for control, value in controllers:
            port.send(mido.Message("control_change", channel=channel - 1, control=control, value=value))
        if controllers:
            time.sleep(0.01)
        port.send(mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity))
        time.sleep(min(gate, duration))
        port.send(mido.Message("note_off", channel=channel - 1, note=note, velocity=0))
    sd.wait()
    wavfile.write(output, sample_rate, _float_to_pcm(recording))
    return output


def _float_to_pcm(samples: np.ndarray) -> np.ndarray:
    return np.round(np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)


def _to_float(data: np.ndarray) -> np.ndarray:
    if np.issubdtype(data.dtype, np.integer):
        return data.astype(np.float32) / max(abs(np.iinfo(data.dtype).min), np.iinfo(data.dtype).max)
    return data.astype(np.float32)


def analyze_wav(path: Path) -> dict[str, int | float | bool | str]:
    """Return reproducible audio facts for a raw or prepared WAV file."""
    rate, raw = wavfile.read(path)
    samples = _to_float(raw)
    if samples.ndim == 1:
        samples = samples[:, None]
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
    def dbfs(value: float) -> float:
        return -float("inf") if value == 0 else float(20 * np.log10(value))
    return {
        "sample_rate": int(rate),
        "frames": int(samples.shape[0]),
        "channels": int(samples.shape[1]),
        "peak_dbfs": dbfs(peak),
        "rms_dbfs": dbfs(rms),
        "clipped": bool(peak >= 0.999),
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def process_wav(source: Path, output: Path, profile: QualityProfile) -> dict[str, int | float]:
    """Apply transparent preparation effects and write a new WAV, never source."""
    rate, raw = wavfile.read(source)
    samples = _to_float(raw)
    if samples.ndim == 1:
        samples = samples[:, None]
    peak = np.max(np.abs(samples), axis=1)
    threshold = 10 ** (profile.trim_threshold_db / 20.0)
    active = np.flatnonzero(peak >= threshold)
    if active.size:
        # Preserve a tiny attack margin; cue-marker decisions remain manual.
        margin = round(rate * 0.003)
        start = max(0, active[0] - margin)
        end = min(len(samples), active[-1] + margin + 1) if profile.trim_tail else len(samples)
        samples = samples[start:end]
    for kind, cutoff in (("highpass", profile.highpass_hz), ("lowpass", profile.lowpass_hz)):
        if cutoff is not None:
            if not 10 < cutoff < rate / 2:
                raise ValueError(f"{kind}_hz must be between 10 and Nyquist")
            samples = sosfiltfilt(butter(4, cutoff, btype="highpass" if kind == "highpass" else "lowpass", fs=rate, output="sos"), samples, axis=0)
    peak_value = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak_value:
        samples *= (10 ** (profile.normalize_dbfs / 20.0)) / peak_value
    if profile.target_sample_rate != rate:
        divisor = gcd(rate, profile.target_sample_rate)
        samples = resample_poly(samples, profile.target_sample_rate // divisor, rate // divisor, axis=0)
        rate = profile.target_sample_rate
    if profile.force_mono and samples.shape[1] > 1:
        samples = np.mean(samples, axis=1, keepdims=True)
    if profile.max_duration_seconds is not None:
        if profile.max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be positive when supplied")
        maximum_frames = max(1, round(profile.max_duration_seconds * rate))
        samples = samples[:maximum_frames]
    for duration_ms, at_start in ((profile.fade_in_ms, True), (profile.fade_out_ms, False)):
        count = min(len(samples), round(rate * duration_ms / 1000.0))
        if count:
            ramp = np.linspace(0.0, 1.0, count, dtype=np.float32)
            if at_start:
                samples[:count] *= ramp[:, None]
            else:
                samples[-count:] *= ramp[::-1, None]
    output.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(output, rate, _float_to_pcm(samples))
    return {"sample_rate": rate, "frames": len(samples), "channels": samples.shape[1],
            "duration_seconds": len(samples) / rate}
