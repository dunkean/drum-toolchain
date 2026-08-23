"""Offline-only preparation, merge, and compiler-artifact export helpers."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
from typing import Any
import xml.etree.ElementTree as ElementTree

from scipy.io import wavfile

from .audio import QualityProfile, process_wav
from .library import SampleLibrary, SampleTake, merge_libraries


def validate_drumgizmo_kit(kit_directory: Path) -> dict[str, int]:
    """Validate the inter-file references consumed by DrumGizmo's XML loader."""
    drumkit_path = kit_directory / "drumkit.xml"
    midimap_path = kit_directory / "midimap.xml"
    for document_path in (drumkit_path, midimap_path):
        if not document_path.is_file():
            raise FileNotFoundError(f"DrumGizmo kit document is missing: {document_path}")
        try:
            ElementTree.parse(document_path)
        except ElementTree.ParseError as error:
            raise ValueError(f"invalid DrumGizmo XML: {document_path}") from error
    drumkit = ElementTree.parse(drumkit_path).getroot()
    if drumkit.tag != "drumkit" or drumkit.get("version") is None:
        raise ValueError("DrumGizmo drumkit.xml needs a drumkit root with version")
    try:
        if int(drumkit.get("samplerate", "0")) <= 0:
            raise ValueError
    except ValueError as error:
        raise ValueError("DrumGizmo drumkit samplerate must be a positive integer") from error
    channels = {node.get("name") for node in drumkit.findall("./channels/channel")}
    if not channels or None in channels or "" in channels:
        raise ValueError("DrumGizmo drumkit needs named output channels")
    if len(channels) != len(drumkit.findall("./channels/channel")):
        raise ValueError("DrumGizmo drumkit output channel names must be unique")
    instruments: set[str] = set()
    sample_count = 0
    audio_channels: dict[Path, int] = {}
    for reference in drumkit.findall("./instruments/instrument"):
        name, filename = reference.get("name"), reference.get("file")
        if not name or not filename or name in instruments:
            raise ValueError("DrumGizmo instrument references need unique name and file")
        instruments.add(name)
        instrument_path = Path(filename)
        if not instrument_path.is_absolute():
            instrument_path = drumkit_path.parent / instrument_path
        if not instrument_path.is_file():
            raise FileNotFoundError(f"DrumGizmo instrument is missing: {instrument_path}")
        try:
            instrument = ElementTree.parse(instrument_path).getroot()
        except ElementTree.ParseError as error:
            raise ValueError(f"invalid DrumGizmo instrument XML: {instrument_path}") from error
        if instrument.tag != "instrument" or instrument.get("name") != name or instrument.get("version") is None:
            raise ValueError(f"invalid DrumGizmo instrument declaration: {instrument_path}")
        for sample in instrument.findall("./samples/sample"):
            if not sample.get("name") or sample.get("power") is None:
                raise ValueError(f"DrumGizmo sample needs name and power: {instrument_path}")
            try:
                float(sample.get("power", ""))
            except ValueError as error:
                raise ValueError(f"DrumGizmo sample power is invalid: {instrument_path}") from error
            audiofiles = sample.findall("audiofile")
            if not audiofiles:
                raise ValueError(f"DrumGizmo sample has no audio files: {instrument_path}")
            for audiofile in audiofiles:
                channel, filename, filechannel = audiofile.get("channel"), audiofile.get("file"), audiofile.get("filechannel")
                if channel not in channels or not filename:
                    raise ValueError(f"DrumGizmo audiofile has an unknown channel or no file: {instrument_path}")
                try:
                    if int(filechannel or "0") < 1:
                        raise ValueError
                except ValueError as error:
                    raise ValueError(f"DrumGizmo audiofile channel is invalid: {instrument_path}") from error
                source = Path(filename)
                if not source.is_absolute():
                    source = instrument_path.parent / source
                if not source.is_file():
                    raise FileNotFoundError(f"DrumGizmo audiofile is missing: {source}")
                if source not in audio_channels:
                    try:
                        sample_rate, audio = wavfile.read(source)
                    except (OSError, ValueError) as error:
                        raise ValueError(f"DrumGizmo audiofile is not a readable WAV: {source}") from error
                    if sample_rate <= 0 or audio.size == 0 or audio.ndim not in (1, 2):
                        raise ValueError(f"DrumGizmo audiofile has no valid PCM frames: {source}")
                    audio_channels[source] = 1 if audio.ndim == 1 else int(audio.shape[1])
                if int(filechannel or "0") > audio_channels[source]:
                    raise ValueError(f"DrumGizmo audiofile channel exceeds WAV channels: {source}")
            sample_count += 1
    if not instruments or sample_count == 0:
        raise ValueError("DrumGizmo drumkit needs instruments with samples")
    midimap = ElementTree.parse(midimap_path).getroot()
    if midimap.tag != "midimap":
        raise ValueError("DrumGizmo midimap.xml needs a midimap root")
    notes: set[int] = set()
    for mapping in midimap.findall("map"):
        try:
            note = int(mapping.get("note", ""))
        except ValueError as error:
            raise ValueError("DrumGizmo map note is invalid") from error
        if not 0 <= note <= 127 or note in notes or mapping.get("instr") not in instruments:
            raise ValueError("DrumGizmo midimap has an invalid, duplicate, or unknown instrument mapping")
        notes.add(note)
    if not notes:
        raise ValueError("DrumGizmo midimap needs at least one mapping")
    return {"channels": len(channels), "instruments": len(instruments), "samples": sample_count, "mappings": len(notes)}


def drumgizmo_note_overrides(path: Path) -> dict[tuple[str, str], int]:
    """Read the rig compiler's ``drum-note-map/v1`` artifact without MIDI I/O."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("format") != "drum-note-map/v1" or document.get("target") != "drumgizmo":
        raise ValueError("expected a drumgizmo drum-note-map/v1 artifact")
    result: dict[tuple[str, str], int] = {}
    for entry in document.get("mappings", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("logical_target"), str) or not isinstance(entry.get("note"), int):
            raise ValueError("invalid DrumGizmo note-map entry")
        if "instrument" in entry or "articulation" in entry:
            instrument, articulation = entry.get("instrument"), entry.get("articulation")
            if not isinstance(instrument, str) or not isinstance(articulation, str):
                raise ValueError("invalid explicit DrumGizmo instrument or articulation")
        else:
            target = entry["logical_target"].replace("__", ".")
            if "." not in target:
                raise ValueError(f"logical_target must be instrument.articulation: {target!r}")
            instrument, articulation = target.rsplit(".", 1)
        if not instrument or not articulation or not 0 <= entry["note"] <= 127:
            raise ValueError("invalid DrumGizmo note-map target or note")
        key = (instrument, articulation)
        if key in result and result[key] != entry["note"]:
            raise ValueError(f"conflicting DrumGizmo note overrides for {key}")
        result[key] = entry["note"]
    return result


def prepare_selected_takes(library: SampleLibrary, *, audio_root: Path, output_root: Path,
                           profile: QualityProfile, selected: set[tuple[str, str]] | None = None) -> SampleLibrary:
    """Prepare selected captured takes into a new root; never changes raw WAVs."""
    updated: list[SampleTake] = []
    for take in library.takes:
        key = (take.instrument, take.articulation)
        if take.status != "captured" or (selected is not None and key not in selected):
            updated.append(take)
            continue
        source = audio_root / take.raw_file
        destination = output_root / take.raw_file
        if not source.is_file():
            raise FileNotFoundError(f"captured raw take is missing: {source}")
        if not destination.exists():
            process_wav(source, destination, profile)
        updated.append(replace(take, prepared_file=destination.relative_to(audio_root).as_posix() if destination.is_relative_to(audio_root) else str(destination),
                               processing_history=take.processing_history + ("offline-quality-profile",)))
    return SampleLibrary(library.identifier, library.channel_layout, tuple(updated))


def merge_library_files(identifier: str, sources: tuple[tuple[Path, str], ...]) -> SampleLibrary:
    return merge_libraries(identifier, tuple((SampleLibrary.read(path), prefix) for path, prefix in sources))


def export_report(library: SampleLibrary, *, overrides: dict[tuple[str, str], int], output_directory: Path) -> dict[str, Any]:
    """Portable report for an offline DrumGizmo handoff."""
    return {"kind": "drumgizmo-export-report", "schema_version": 1,
            "library": library.identifier, "channel_layout": list(library.channel_layout),
            "captured_takes": sum(t.status == "captured" for t in library.takes),
            "note_overrides": {f"{key[0]}.{key[1]}": note for key, note in sorted(overrides.items())},
            "output_directory": str(output_directory), "hardware_io": "disabled"}


def verify_drumgizmo_kit(kit_directory: Path, report_path: Path, *, executable: str = "drumgizmo",
                         backend: str = "jackmidi") -> dict[str, Any]:
    """Record an offline DrumGizmo kit and executable preflight without starting audio."""
    validation = validate_drumgizmo_kit(kit_directory)
    drumkit = kit_directory / "drumkit.xml"
    midimap = kit_directory / "midimap.xml"
    try:
        completed = subprocess.run((executable, "--version"), capture_output=True, text=True,
                                   check=False, timeout=10)
    except FileNotFoundError as error:
        raise RuntimeError(f"DrumGizmo executable is unavailable: {executable}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"DrumGizmo version probe failed: {detail}")
    report = {
        "kind": "drumgizmo-smoke-report",
        "schema_version": 1,
        "kit_directory": str(kit_directory),
        "documents": {"drumkit": str(drumkit), "midimap": str(midimap)},
        "kit": validation,
        "backend": backend,
        "drumgizmo": {"executable": executable, "version": completed.stdout.strip()},
        "audio_load": "not_executed",
        "hardware_io": "disabled",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def run_offline_recipe(recipe_path: Path, report_path: Path) -> dict[str, Any]:
    """Execute a declarative offline handoff recipe; it has no capture fields."""
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    if recipe.get("kind") != "drum-sampler-offline-recipe" or recipe.get("schema_version") != 1:
        raise ValueError("expected drum-sampler-offline-recipe/v1")
    base = recipe_path.parent
    def resolve(value: object, name: str) -> Path:
        if not isinstance(value, str) or not value: raise ValueError(f"recipe {name} is required")
        return base / value
    library = SampleLibrary.read(resolve(recipe.get("library"), "library"))
    overrides = drumgizmo_note_overrides(resolve(recipe.get("drumgizmo_note_map"), "drumgizmo_note_map"))
    report = export_report(library, overrides=overrides, output_directory=resolve(recipe.get("output_directory"), "output_directory"))
    report["recipe"] = str(recipe_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
