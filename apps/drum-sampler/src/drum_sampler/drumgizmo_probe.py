"""Deterministic MIDI/audio proof for DrumGizmo poly-aftertouch chokes."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ElementTree

import numpy as np
from scipy.io import wavfile


def _variable_length(value: int) -> bytes:
    if value < 0:
        raise ValueError("MIDI delta time cannot be negative")
    result = [value & 0x7F]
    value >>= 7
    while value:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(result))


def write_probe_midi(path: Path, *, note: int, pressure: int, channel: int = 10) -> None:
    """Write a type-0 MIDI file with one hit and one poly-aftertouch event."""
    if not 0 <= note <= 127 or not 0 <= pressure <= 127 or not 1 <= channel <= 16:
        raise ValueError("probe note/pressure/channel is outside the MIDI range")
    status_channel = channel - 1
    track = bytearray()
    track.extend(b"\x00\xff\x51\x03\x07\xa1\x20")  # 120 BPM
    track.extend(bytes((0, 0x90 | status_channel, note, 120)))
    track.extend(_variable_length(240))  # 250 ms
    track.extend(bytes((0xA0 | status_channel, note, pressure)))
    track.extend(_variable_length(240))
    track.extend(bytes((0x80 | status_channel, note, 0)))
    track.extend(b"\x00\xff\x2f\x00")
    payload = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
    payload += b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def prepare_probe(midimap: Path, output_directory: Path, *, instrument: str) -> dict[str, object]:
    """Resolve one exported instrument and create control/choke MIDI inputs."""
    root = ElementTree.parse(midimap).getroot()
    matches = [int(node.get("note", "-1")) for node in root.findall("map")
               if node.get("instr") == instrument]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one MIDI note for DrumGizmo instrument {instrument!r}")
    note = matches[0]
    control = output_directory / "control.mid"
    choke = output_directory / "choke.mid"
    write_probe_midi(control, note=note, pressure=0)
    write_probe_midi(choke, note=note, pressure=127)
    document = {
        "format": "drumgizmo-aftertouch-probe-input/v1",
        "instrument": instrument,
        "note": note,
        "channel": 10,
        "aftertouch_at_ms": 250,
        "control": {"path": str(control.resolve()), "pressure": 0,
                    "sha256": hashlib.sha256(control.read_bytes()).hexdigest()},
        "choke": {"path": str(choke.resolve()), "pressure": 127,
                  "sha256": hashlib.sha256(choke.read_bytes()).hexdigest()},
    }
    (output_directory / "input.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return document


def _normalized_audio(path: Path) -> tuple[int, np.ndarray]:
    sample_rate, audio = wavfile.read(path)
    samples = np.asarray(audio)
    if np.issubdtype(samples.dtype, np.integer):
        scale = float(max(abs(np.iinfo(samples.dtype).min), np.iinfo(samples.dtype).max))
        values = samples.astype(np.float64) / scale
    else:
        values = samples.astype(np.float64)
    if values.ndim == 2:
        values = np.mean(values, axis=1)
    return int(sample_rate), values


def _window_rms(paths: tuple[Path, ...], start: float, end: float) -> float:
    squares: list[np.ndarray] = []
    for path in paths:
        sample_rate, audio = _normalized_audio(path)
        window = audio[int(start * sample_rate):min(len(audio), int(end * sample_rate))]
        if len(window) < max(1, int((end - start) * sample_rate * 0.8)):
            raise ValueError(f"render is too short for the {start:.3f}..{end:.3f}s proof window: {path}")
        squares.append(np.square(window))
    return float(math.sqrt(np.mean(np.concatenate(squares))))


def analyze_probe(output_directory: Path, report: Path, *, maximum_tail_ratio_db: float = -12.0) -> dict[str, object]:
    """Prove that positive aftertouch attenuates the same rendered cymbal."""
    control = tuple(sorted(output_directory.glob("control*.wav")))
    choke = tuple(sorted(output_directory.glob("choke*.wav")))
    if not control or len(control) != len(choke):
        raise ValueError("control/choke DrumGizmo renders are missing or have different channel counts")
    pre_control = _window_rms(control, 0.05, 0.20)
    pre_choke = _window_rms(choke, 0.05, 0.20)
    tail_control = _window_rms(control, 0.65, 0.695)
    tail_choke = _window_rms(choke, 0.65, 0.695)
    if min(pre_control, pre_choke, tail_control) <= 1e-8:
        raise ValueError("probe control render has no measurable cymbal signal")
    pre_ratio_db = 20.0 * math.log10(pre_choke / pre_control)
    tail_ratio_db = 20.0 * math.log10(max(tail_choke, 1e-15) / tail_control)
    passed = abs(pre_ratio_db) <= 6.0 and tail_ratio_db <= maximum_tail_ratio_db
    document = {
        "format": "drumgizmo-aftertouch-audio-proof/v1",
        "status": "pass" if passed else "fail",
        "method": "same note/velocity; poly-aftertouch 0 control versus 127 choke at 250 ms",
        "windows_seconds": {"pre": [0.05, 0.20], "tail": [0.65, 0.695]},
        "thresholds_db": {"maximum_pre_difference": 6.0,
                          "maximum_choke_to_control_tail": maximum_tail_ratio_db},
        "measurements": {
            "pre_control_rms": pre_control, "pre_choke_rms": pre_choke,
            "pre_ratio_db": pre_ratio_db, "tail_control_rms": tail_control,
            "tail_choke_rms": tail_choke, "tail_ratio_db": tail_ratio_db,
        },
        "control_files": [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                          for path in control],
        "choke_files": [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                        for path in choke],
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    temporary = report.with_suffix(report.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report)
    if not passed:
        raise ValueError(f"DrumGizmo aftertouch choke proof failed: tail ratio {tail_ratio_db:.2f} dB")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drumgizmo-choke-probe")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--midimap", required=True, type=Path)
    prepare.add_argument("--output-directory", required=True, type=Path)
    prepare.add_argument("--instrument", default="crash1__bow")
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--output-directory", required=True, type=Path)
    analyze.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        document = prepare_probe(args.midimap, args.output_directory, instrument=args.instrument)
        print(f"wrote DrumGizmo choke probe for note {document['note']}")
    else:
        document = analyze_probe(args.output_directory, args.report)
        print(f"DrumGizmo aftertouch choke proof {document['status']}: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
