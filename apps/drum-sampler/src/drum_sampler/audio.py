"""Local, explicit audio capture and non-destructive WAV preparation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
import threading
import warnings
from math import gcd
from hashlib import sha256

import mido
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, resample_poly, sosfiltfilt
import yaml


# The UMC404HD WASAPI loopback reports intermittent packet discontinuities
# with SoundCard's endpoint-minimum buffer and still did so during full-length
# captures at 2048/4096 frames.  This buffer affects recording only, never the
# renderer/MIDI latency; 32768 frames proved stable on the reference rig.
WASAPI_LOOPBACK_BLOCKSIZE = 32768


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
    onset_margin_ms: float = 3.0
    tail_margin_ms: float | None = None


def _sounddevice():
    """Import PortAudio bindings only for operations that actually need them."""
    try:
        import sounddevice as sd
    except OSError as error:
        raise RuntimeError("PortAudio is required for live audio device access") from error
    return sd


def load_quality_profile(path: Path, name: str) -> QualityProfile:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read quality profile {path}: {error}") from error
    profiles = document.get("profiles", {}) if isinstance(document, dict) else {}
    values = profiles.get(name)
    if not isinstance(values, dict):
        raise ValueError(f"quality profile {name!r} not found in {path}")
    keys = {"target_sample_rate", "trim_threshold_db", "normalize_dbfs", "fade_in_ms", "fade_out_ms", "highpass_hz", "lowpass_hz", "max_duration_seconds", "force_mono", "trim_tail", "onset_margin_ms", "tail_margin_ms"}
    unknown = set(values) - keys
    if unknown:
        raise ValueError(f"unknown quality profile fields: {sorted(unknown)}")
    return QualityProfile(**values)


def devices() -> list[str]:
    sd = _sounddevice()
    return [f"{index}: {item['name']} ({item['max_input_channels']} in / {item['max_output_channels']} out)"
            for index, item in enumerate(sd.query_devices())]


def resolve_device(query: str) -> int | str:
    sd = _sounddevice()
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
    audio capture device. The generated WAV is an immutable 32-bit-float raw
    take, so later target preparation never starts from a 16-bit reduction.
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
    if audio_input.startswith("loopback:"):
        return _capture_loopback(
            midi_port=midi_port, query=audio_input.split(":", 1)[1], note=note,
            velocity=velocity, output=output, channel=channel,
            controllers=controllers, frames=frames, duration=duration, gate=gate,
            preroll=preroll, sample_rate=sample_rate, channels=channels,
        )
    sd = _sounddevice()
    recording = sd.rec(frames, samplerate=sample_rate, channels=channels, dtype="float32",
                       device=resolve_device(audio_input))
    time.sleep(preroll)
    _emit_note(midi_port, note, velocity, channel, controllers, gate, duration)
    sd.wait()
    _write_raw_master(output, sample_rate, recording)
    return output


def capture_chord(*, midi_port: str, audio_input: str, notes: tuple[int, ...], velocity: int,
                  output: Path, channel: int = 1,
                  controllers: tuple[tuple[int, int], ...] = (),
                  duration: float = 3.0, gate: float = 0.1, preroll: float = 0.1,
                  sample_rate: int = 44100, channels: int = 1) -> Path:
    """Record one simultaneous, velocity-matched MIDI chord."""
    if not notes or len(set(notes)) != len(notes) or any(not 0 <= note <= 127 for note in notes):
        raise ValueError("notes must be a non-empty tuple of unique MIDI notes in 0..127")
    if not 1 <= velocity <= 127 or not 1 <= channel <= 16:
        raise ValueError("velocity must be 1..127 and channel 1..16")
    if duration <= 0 or gate < 0 or preroll < 0 or not 1 <= channels <= 4:
        raise ValueError("invalid capture duration, gate, preroll or channel count")
    if any(not 0 <= control <= 127 or not 0 <= value <= 127 for control, value in controllers):
        raise ValueError("controller numbers and values must be in 0..127")
    if output.exists():
        raise FileExistsError(f"raw capture already exists and will not be overwritten: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    frames = round((duration + preroll) * sample_rate)
    if not audio_input.startswith("loopback:"):
        raise ValueError("composite capture currently requires an explicit loopback: audio endpoint")
    return _capture_loopback_chord(
        midi_port=midi_port, query=audio_input.split(":", 1)[1], notes=notes,
        velocity=velocity, output=output, channel=channel,
        controllers=controllers, frames=frames, duration=duration, gate=gate,
        preroll=preroll, sample_rate=sample_rate, channels=channels,
    )


def _emit_note(
    midi_port: str, note: int, velocity: int, channel: int,
    controllers: tuple[tuple[int, int], ...], gate: float, duration: float,
) -> None:
    with mido.open_output(midi_port) as port:
        for control, value in controllers:
            port.send(mido.Message("control_change", channel=channel - 1, control=control, value=value))
        if controllers:
            time.sleep(0.01)
        port.send(mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity))
        time.sleep(min(gate, duration))
        port.send(mido.Message("note_off", channel=channel - 1, note=note, velocity=0))


def _emit_chord(
    midi_port: str, notes: tuple[int, ...], velocity: int, channel: int,
    controllers: tuple[tuple[int, int], ...], gate: float, duration: float,
) -> None:
    with mido.open_output(midi_port) as port:
        for control, value in controllers:
            port.send(mido.Message("control_change", channel=channel - 1, control=control, value=value))
        if controllers:
            time.sleep(0.01)
        for note in notes:
            port.send(mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity))
        time.sleep(min(gate, duration))
        for note in reversed(notes):
            port.send(mido.Message("note_off", channel=channel - 1, note=note, velocity=0))


def _capture_loopback(
    *, midi_port: str, query: str, note: int, velocity: int, output: Path,
    channel: int, controllers: tuple[tuple[int, int], ...], frames: int,
    duration: float, gate: float, preroll: float, sample_rate: int, channels: int,
) -> Path:
    """Capture a Windows playback endpoint digitally through WASAPI loopback."""
    import soundcard as sc

    matches = [
        microphone for microphone in sc.all_microphones(include_loopback=True)
        if microphone.isloopback and query.lower() in microphone.name.lower()
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one loopback device containing {query!r}, found {[item.name for item in matches]}")
    trigger_error: list[BaseException] = []
    recorder_ready = threading.Event()
    recorder_cancelled = threading.Event()

    def trigger() -> None:
        try:
            recorder_ready.wait()
            if recorder_cancelled.is_set():
                return
            time.sleep(preroll)
            _emit_note(midi_port, note, velocity, channel, controllers, gate, duration)
        except BaseException as error:  # propagate a worker failure on the caller thread
            trigger_error.append(error)

    worker = threading.Thread(target=trigger, name="drum-sampler-midi-trigger")
    worker.start()
    try:
        with warnings.catch_warnings(record=True) as capture_warnings:
            warnings.simplefilter("always", sc.SoundcardRuntimeWarning)
            with matches[0].recorder(
                samplerate=sample_rate,
                channels=list(range(channels)),
                blocksize=WASAPI_LOOPBACK_BLOCKSIZE,
            ) as recorder:
                # Entering the recorder starts the WASAPI client.  Only now may
                # the preroll clock and MIDI trigger begin.
                recorder_ready.set()
                recording = recorder.record(numframes=frames)
    except BaseException:
        recorder_cancelled.set()
        recorder_ready.set()
        raise
    finally:
        worker.join()
    if trigger_error:
        raise RuntimeError("MIDI trigger failed during loopback capture") from trigger_error[0]
    discontinuities = [
        item for item in capture_warnings
        if issubclass(item.category, sc.SoundcardRuntimeWarning)
    ]
    if discontinuities:
        details = "; ".join(str(item.message) for item in discontinuities)
        raise RuntimeError(
            f"WASAPI loopback reported {len(discontinuities)} audio discontinuity warning(s); "
            f"the raw take was rejected instead of writing a potentially cracked WAV ({details})"
        )
    _write_raw_master(output, sample_rate, recording)
    return output


def _capture_loopback_chord(
    *, midi_port: str, query: str, notes: tuple[int, ...], velocity: int, output: Path,
    channel: int, controllers: tuple[tuple[int, int], ...], frames: int,
    duration: float, gate: float, preroll: float, sample_rate: int, channels: int,
) -> Path:
    """Capture a simultaneous MIDI chord through a Windows WASAPI loopback."""
    import soundcard as sc

    matches = [
        microphone for microphone in sc.all_microphones(include_loopback=True)
        if microphone.isloopback and query.lower() in microphone.name.lower()
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one loopback device containing {query!r}, found {[item.name for item in matches]}")
    trigger_error: list[BaseException] = []
    recorder_ready = threading.Event()
    recorder_cancelled = threading.Event()

    def trigger() -> None:
        try:
            recorder_ready.wait()
            if recorder_cancelled.is_set():
                return
            time.sleep(preroll)
            _emit_chord(midi_port, notes, velocity, channel, controllers, gate, duration)
        except BaseException as error:
            trigger_error.append(error)

    worker = threading.Thread(target=trigger, name="drum-sampler-midi-chord-trigger")
    worker.start()
    try:
        with warnings.catch_warnings(record=True) as capture_warnings:
            warnings.simplefilter("always", sc.SoundcardRuntimeWarning)
            with matches[0].recorder(
                samplerate=sample_rate,
                channels=list(range(channels)),
                blocksize=WASAPI_LOOPBACK_BLOCKSIZE,
            ) as recorder:
                recorder_ready.set()
                recording = recorder.record(numframes=frames)
    except BaseException:
        recorder_cancelled.set()
        recorder_ready.set()
        raise
    finally:
        worker.join()
    if trigger_error:
        raise RuntimeError("MIDI chord trigger failed during loopback capture") from trigger_error[0]
    discontinuities = [
        item for item in capture_warnings
        if issubclass(item.category, sc.SoundcardRuntimeWarning)
    ]
    if discontinuities:
        details = "; ".join(str(item.message) for item in discontinuities)
        raise RuntimeError(
            f"WASAPI loopback reported {len(discontinuities)} audio discontinuity warning(s); "
            f"the raw chord take was rejected ({details})"
        )
    _write_raw_master(output, sample_rate, recording)
    return output


def _write_raw_master(output: Path, sample_rate: int, samples: np.ndarray) -> None:
    """Write an unprocessed capture in a float32 WAV container.

    This preserves the precision supplied by the capture backend. The actual
    converter resolution remains determined by the connected interface.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    wavfile.write(partial, sample_rate, np.asarray(samples, dtype=np.float32))
    partial.replace(output)


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


def process_wav(
    source: Path, output: Path, profile: QualityProfile, *, gain_db: float | None = None,
) -> dict[str, int | float]:
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
        if profile.onset_margin_ms < 0:
            raise ValueError("onset_margin_ms cannot be negative")
        onset_margin = round(rate * profile.onset_margin_ms / 1000.0)
        tail_margin_ms = profile.onset_margin_ms if profile.tail_margin_ms is None else profile.tail_margin_ms
        if tail_margin_ms < 0:
            raise ValueError("tail_margin_ms cannot be negative")
        tail_margin = round(rate * tail_margin_ms / 1000.0)
        start = max(0, active[0] - onset_margin)
        end = min(len(samples), active[-1] + tail_margin + 1) if profile.trim_tail else len(samples)
        samples = samples[start:end]
    for kind, cutoff in (("highpass", profile.highpass_hz), ("lowpass", profile.lowpass_hz)):
        if cutoff is not None:
            if not 10 < cutoff < rate / 2:
                raise ValueError(f"{kind}_hz must be between 10 and Nyquist")
            samples = sosfiltfilt(butter(4, cutoff, btype="highpass" if kind == "highpass" else "lowpass", fs=rate, output="sos"), samples, axis=0)
    peak_value = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak_value:
        if gain_db is None:
            samples *= (10 ** (profile.normalize_dbfs / 20.0)) / peak_value
        else:
            samples *= 10 ** (gain_db / 20.0)
    if profile.target_sample_rate != rate:
        divisor = gcd(rate, profile.target_sample_rate)
        samples = resample_poly(samples, profile.target_sample_rate // divisor, rate // divisor, axis=0)
        rate = profile.target_sample_rate
    if profile.force_mono and samples.shape[1] > 1:
        samples = np.mean(samples, axis=1, keepdims=True)
    # Guarantee the requested silent lead-in on the final signal. Resampling,
    # filtering, gain and mono conversion can all move the first detectable
    # sample, so measuring the input before those operations is insufficient.
    if samples.size:
        final_peak = np.max(np.abs(samples), axis=1)
        final_active = np.flatnonzero(final_peak >= threshold)
        if final_active.size:
            onset_margin = round(rate * profile.onset_margin_ms / 1000.0)
            missing_preroll = max(0, onset_margin - int(final_active[0]))
            if missing_preroll:
                samples = np.pad(samples, ((missing_preroll, 0), (0, 0)))
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
