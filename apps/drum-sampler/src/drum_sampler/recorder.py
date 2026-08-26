"""Resumable, explicit execution of a planned MIDI/audio capture session."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
from typing import Callable

from .audio import analyze_wav, capture_note
from .library import SampleLibrary, SampleTake, library_from_plan
from .session import CaptureSessionPlan, PlannedTake

CaptureFunction = Callable[..., Path]


def capture_pending(session: CaptureSessionPlan, raw_directory: Path, *, capture: CaptureFunction = capture_note) -> tuple[Path, ...]:
    """Capture only missing raw takes. Existing raw WAVs are never replaced."""
    raw_directory.mkdir(parents=True, exist_ok=True)
    captured: list[Path] = []
    pending = session.incomplete_takes(raw_directory)
    for index, take in enumerate(pending):
        print(
            f"[{index + 1}/{len(pending)}] {take.raw_filename()} "
            f"(note {take.request.note}, velocity {take.velocity})",
            flush=True,
        )
        output = raw_directory / take.raw_filename()
        path = capture(
            midi_port=session.midi_output,
            audio_input=session.audio_input,
            note=take.request.note,
            velocity=take.velocity,
            channel=take.request.channel,
            controllers=take.request.controllers,
            output=output,
            duration=(session.gate_ms + session.tail_ms) / 1000,
            gate=session.gate_ms / 1000,
            preroll=session.preroll_ms / 1000,
            sample_rate=session.sample_rate,
            channels=len(session.channels),
        )
        if path != output or not output.is_file():
            raise RuntimeError(f"capture function did not create expected raw take: {output}")
        captured.append(output)
        # Let a VST/module finish its own voice bookkeeping before the next
        # note.  This is part of the saved capture-session contract, rather
        # than an undocumented timing assumption in a one-off script.
        if index + 1 < len(pending) and session.cooldown_ms:
            time.sleep(session.cooldown_ms / 1000)
    return tuple(captured)


def library_from_captures(identifier: str, session: CaptureSessionPlan, raw_directory: Path, *, source: str, license_statement: str) -> SampleLibrary:
    """Build a neutral library and enrich each present raw take with WAV facts."""
    if not source or not license_statement:
        raise ValueError("source and license_statement are required")
    planned = library_from_plan(identifier, session.channels, session.takes())
    captured_takes: list[SampleTake] = []
    for take in planned.takes:
        raw_path = raw_directory / take.raw_file
        if not raw_path.is_file():
            captured_takes.append(replace(take, source=source, license_statement=license_statement))
            continue
        facts = analyze_wav(raw_path)
        captured_takes.append(replace(
            take,
            sample_rate=int(facts["sample_rate"]),
            frames=int(facts["frames"]),
            peak_dbfs=float(facts["peak_dbfs"]),
            rms_dbfs=float(facts["rms_dbfs"]),
            clipped=bool(facts["clipped"]),
            sha256=str(facts["sha256"]),
            capture_duration_ms=round(1000 * int(facts["frames"]) / int(facts["sample_rate"])),
            source=source,
            license_statement=license_statement,
            status="captured",
        ))
    return SampleLibrary(identifier, session.channels, tuple(captured_takes))
