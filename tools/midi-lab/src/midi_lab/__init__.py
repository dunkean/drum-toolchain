"""MIDI observation, matching, trace recording, and replay helpers."""

from .ports import resolve_unique_port
from .traces import MidiTrace, TraceEvent
from .ddrum4_programs import decode_ddrum4_program, program_for_kit, program_for_palette
from .latency import analyze_latency_run, prepared_run, validate_latency_run
from .sd3_reverse import (
    build_megakit_preset,
    compare_set,
    diff_files,
    megakit_markdown,
    mixer_inventory,
    preset_inventory,
    scan_binary,
)
from .sd3_edrum import build_sd3_edrum_preset

__all__ = [
    "MidiTrace", "TraceEvent", "resolve_unique_port",
    "decode_ddrum4_program", "program_for_kit", "program_for_palette",
    "analyze_latency_run", "prepared_run", "validate_latency_run",
    "scan_binary", "diff_files", "compare_set", "mixer_inventory",
    "build_sd3_edrum_preset",
]
