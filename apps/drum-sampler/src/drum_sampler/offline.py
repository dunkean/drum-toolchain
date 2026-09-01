"""Offline-only preparation, merge, and compiler-artifact export helpers."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any
import xml.etree.ElementTree as ElementTree

import numpy as np
from scipy.io import wavfile
import yaml

from .audio import QualityProfile, analyze_wav, capture_chord, process_wav
from .library import SampleLibrary, SampleTake, merge_libraries
from .quality import CaptureQualityPolicy, assess_wav
from .session import CaptureSessionPlan


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
    metadata = drumkit.find("metadata")
    required_metadata = ("author", "email", "version")
    if metadata is None or any(not (metadata.findtext(name) or "").strip() for name in required_metadata):
        raise ValueError("DrumGizmo metadata needs non-empty author, email, and version fields")
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
        if "capture_instrument" in entry or "capture_articulation" in entry:
            instrument, articulation = entry.get("capture_instrument"), entry.get("capture_articulation")
            if not isinstance(instrument, str) or not isinstance(articulation, str):
                raise ValueError("invalid explicit DrumGizmo capture identity")
        elif "instrument" in entry or "articulation" in entry:
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


def drumgizmo_capture_note_overrides(path: Path) -> tuple[dict[tuple[str, str], int], set[tuple[str, str]]]:
    """Read capture-only DrumGizmo zones from an SD3 MegaKit plan.

    A continuous SD3 hi-hat is captured at reviewed CC4 positions.  Each
    position becomes a distinct DrumGizmo articulation/note, while the base
    ``hh.bow``/``hh.edge`` entry from the logical renderer map is replaced.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("kind") != "sd3-megakit-plan":
        raise ValueError("expected an sd3-megakit-plan")
    result: dict[tuple[str, str], int] = {}
    replaced: set[tuple[str, str]] = set()
    for item in document.get("articulations", []):
        if not isinstance(item, dict) or "capture_variants" not in item:
            continue
        logical, variants = item.get("logical"), item.get("capture_variants")
        if not isinstance(logical, str) or logical.count(".") != 1 or not isinstance(variants, list) or not variants:
            raise ValueError("capture variants need one instrument.articulation logical target")
        instrument, base_articulation = logical.split(".", 1)
        replaced.add((instrument, base_articulation))
        for variant in variants:
            if not isinstance(variant, dict):
                raise ValueError(f"invalid capture variant for {logical}")
            articulation, note = variant.get("articulation"), variant.get("drumgizmo_note")
            if not isinstance(articulation, str) or not articulation or not isinstance(note, int) or not 0 <= note <= 127:
                raise ValueError(f"capture variant for {logical} needs articulation and DrumGizmo note")
            key = (instrument, articulation)
            if key in result or note in result.values():
                raise ValueError(f"duplicate DrumGizmo capture zone in {logical}")
            result[key] = note
    return result, replaced


def drumgizmo_instrument_groups(path: Path) -> dict[tuple[str, str], str]:
    """Read explicit DrumGizmo choke groups from an SD3 MegaKit plan."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("kind") != "sd3-megakit-plan":
        raise ValueError("expected an sd3-megakit-plan")
    groups = document.get("drumgizmo_instrument_groups", {})
    if not isinstance(groups, dict):
        raise ValueError("drumgizmo_instrument_groups must be a mapping")
    result: dict[tuple[str, str], str] = {}
    for group, members in groups.items():
        if not isinstance(group, str) or not group.strip() or not isinstance(members, list) or not members:
            raise ValueError("each DrumGizmo instrument group needs a non-empty name and member list")
        for logical in members:
            if not isinstance(logical, str) or "." not in logical:
                raise ValueError(f"invalid DrumGizmo group member: {logical!r}")
            key = tuple(logical.rsplit(".", 1))
            if key in result:
                raise ValueError(f"DrumGizmo articulation belongs to multiple groups: {logical}")
            result[key] = group.strip()
    return result


def resolved_drumgizmo_note_overrides(note_map: Path | None, megakit_plan: Path | None = None) -> dict[tuple[str, str], int]:
    """Merge the compiled logical map with capture-only zone replacements."""
    overrides = drumgizmo_note_overrides(note_map) if note_map is not None else {}
    if megakit_plan is None:
        return overrides
    capture_overrides, replaced = drumgizmo_capture_note_overrides(megakit_plan)
    for key in replaced:
        overrides.pop(key, None)
    collisions = set(overrides) & set(capture_overrides)
    conflicting = {key for key in collisions if overrides[key] != capture_overrides[key]}
    if conflicting:
        raise ValueError(f"DrumGizmo capture zones collide with renderer mappings: {sorted(conflicting)}")
    # A forced logical route may deliberately address an exact captured hi-hat
    # zone (for example edge_half). Let the capture-owned entry win when both
    # contracts name the same articulation and the same note.
    for key in collisions:
        overrides.pop(key)
    used_notes = {note: key for key, note in overrides.items()}
    for key, note in capture_overrides.items():
        if note in used_notes:
            raise ValueError(f"DrumGizmo note {note} maps to both {used_notes[note]} and {key}")
        overrides[key] = note
        used_notes[note] = key
    return overrides


def expand_shared_variations(library: SampleLibrary, plan_path: Path) -> SampleLibrary:
    """Add metadata-only logical aliases which reuse already captured WAVs."""
    document = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("kind") != "sd3-megakit-plan":
        raise ValueError("expected an sd3-megakit-plan")
    articulations = document.get("articulations")
    if not isinstance(articulations, list):
        raise ValueError("SD3 MegaKit plan needs articulations")
    takes = list(library.takes)
    existing = {(take.instrument, take.articulation) for take in takes}
    for item in articulations:
        if not isinstance(item, dict) or item.get("capture") is not False:
            continue
        logical, shared_with, note = item.get("logical"), item.get("shared_with"), item.get("note")
        if (not isinstance(logical, str) or logical.count(".") != 1 or
                not isinstance(shared_with, str) or shared_with.count(".") != 1 or
                not isinstance(note, int)):
            raise ValueError("shared variation needs logical, shared_with, and note")
        target = tuple(logical.split(".", 1))
        source = tuple(shared_with.split(".", 1))
        if target in existing:
            raise ValueError(f"shared variation already exists in captured library: {logical}")
        source_takes = [take for take in takes if (take.instrument, take.articulation) == source]
        if not source_takes:
            raise ValueError(f"shared variation source is missing from captured library: {shared_with}")
        takes.extend(replace(
            take,
            instrument=target[0],
            articulation=target[1],
            note=note,
            processing_history=take.processing_history + (f"shared-variation:{shared_with}",),
        ) for take in source_takes)
        existing.add(target)
    return SampleLibrary(library.identifier, library.channel_layout, tuple(takes))


def _wav_as_float(samples: np.ndarray) -> np.ndarray:
    """Convert readable WAV PCM to float without changing channel geometry."""
    if np.issubdtype(samples.dtype, np.floating):
        return samples.astype(np.float32, copy=False)
    if np.issubdtype(samples.dtype, np.signedinteger):
        scale = float(max(abs(np.iinfo(samples.dtype).min), np.iinfo(samples.dtype).max))
        return samples.astype(np.float32) / scale
    if np.issubdtype(samples.dtype, np.unsignedinteger):
        info = np.iinfo(samples.dtype)
        midpoint = (info.max + 1) / 2.0
        return (samples.astype(np.float32) - midpoint) / midpoint
    raise ValueError(f"unsupported WAV sample type for layer composition: {samples.dtype}")


def compose_drumgizmo_layers(library: SampleLibrary, *, audio_root: Path,
                             output_root: Path, plan_path: Path) -> SampleLibrary:
    """Render phase-approved SD3 note stacks into immutable DrumGizmo WAVs.

    SD3 can emit several simultaneous notes for one logical articulation,
    whereas a portable DrumGizmo midimap resolves one note to one instrument.
    The plan therefore declares exact source articulations. Matching
    velocity/RR cells are summed with no normalization so the exported attack
    and balance remain identical to the approved SD3 chord.
    """
    document = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("kind") != "sd3-megakit-plan":
        raise ValueError("expected an sd3-megakit-plan")
    specifications = document.get("drumgizmo_composites", [])
    if not isinstance(specifications, list):
        raise ValueError("drumgizmo_composites must be a list")
    if not specifications:
        return library
    indexed: dict[tuple[str, str, int, int], SampleTake] = {}
    for take in library.takes:
        key = (take.instrument, take.articulation, take.velocity, take.repetition)
        if key in indexed:
            raise ValueError(f"duplicate capture cell prevents layer composition: {key}")
        indexed[key] = take
    replacements: dict[tuple[str, str, int, int], SampleTake] = {}
    declared_targets: set[tuple[str, str]] = set()
    output_root.mkdir(parents=True, exist_ok=True)
    for specification in specifications:
        if not isinstance(specification, dict):
            raise ValueError("each DrumGizmo composite must be an object")
        target_value, source_values = specification.get("target"), specification.get("sources")
        if (not isinstance(target_value, str) or target_value.count(".") != 1 or
                not isinstance(source_values, list) or len(source_values) < 2 or
                not all(isinstance(value, str) and value.count(".") == 1 for value in source_values)):
            raise ValueError("DrumGizmo composite needs target and at least two instrument.articulation sources")
        target = tuple(target_value.split(".", 1))
        sources = [tuple(value.split(".", 1)) for value in source_values]
        if sources[0] != target or target in declared_targets or len(set(sources)) != len(sources):
            raise ValueError("DrumGizmo composite target must be its first unique source and may be declared once")
        declared_targets.add(target)
        target_takes = [take for take in library.takes if (take.instrument, take.articulation) == target]
        if not target_takes:
            raise ValueError(f"DrumGizmo composite target has no captured takes: {target_value}")
        for target_take in target_takes:
            source_takes: list[SampleTake] = []
            arrays: list[np.ndarray] = []
            sample_rate: int | None = None
            shape: tuple[int, ...] | None = None
            for source in sources:
                cell = (*source, target_take.velocity, target_take.repetition)
                take = indexed.get(cell)
                if take is None or take.status != "captured":
                    raise ValueError(f"DrumGizmo composite source cell is missing or uncaptured: {cell}")
                path = Path(take.prepared_file or take.raw_file)
                source_path = path if path.is_absolute() else audio_root / path
                if not source_path.is_file():
                    raise FileNotFoundError(f"DrumGizmo composite source WAV is missing: {source_path}")
                rate, samples = wavfile.read(source_path)
                converted = _wav_as_float(samples)
                if sample_rate is None:
                    sample_rate, shape = int(rate), converted.shape
                elif rate != sample_rate or converted.shape != shape:
                    raise ValueError(f"DrumGizmo composite sources differ in rate or shape for {target_value}")
                source_takes.append(take)
                arrays.append(converted)
            mixed = np.sum(np.stack(arrays, axis=0), axis=0, dtype=np.float64).astype(np.float32)
            peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
            if not np.isfinite(mixed).all() or peak >= 1.0:
                raise ValueError(
                    f"DrumGizmo composite {target_value} v{target_take.velocity} rr{target_take.repetition} "
                    f"would clip (peak={peak:.6f}); adjust the approved SD3 layer balance instead of normalizing"
                )
            destination = output_root / (
                f"{target_take.instrument}__{target_take.articulation}__v{target_take.velocity:03d}"
                f"__rr{target_take.repetition:02d}_composite.wav"
            )
            if destination.exists():
                existing_rate, existing = wavfile.read(destination)
                if existing_rate != sample_rate or not np.array_equal(_wav_as_float(existing), mixed):
                    raise FileExistsError(f"refusing to overwrite a different DrumGizmo composite: {destination}")
            else:
                wavfile.write(destination, sample_rate, mixed)
            facts = analyze_wav(destination)
            history = target_take.processing_history + (
                "layer-composite:" + "+".join(source_values),
                "no-normalization",
            )
            replacements[(target_take.instrument, target_take.articulation,
                          target_take.velocity, target_take.repetition)] = replace(
                target_take,
                prepared_file=str(destination.resolve()),
                sample_rate=sample_rate,
                frames=int(facts["frames"]),
                peak_dbfs=float(facts["peak_dbfs"]),
                rms_dbfs=float(facts["rms_dbfs"]),
                clipped=bool(facts["clipped"]),
                sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                processing_history=history,
            )
    return SampleLibrary(library.identifier, library.channel_layout, tuple(
        replacements.get((take.instrument, take.articulation, take.velocity, take.repetition), take)
        for take in library.takes
    ))


def _drumgizmo_composite_specs(plan_path: Path) -> list[tuple[tuple[str, str], tuple[tuple[str, str], ...]]]:
    document = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("kind") != "sd3-megakit-plan":
        raise ValueError("expected an sd3-megakit-plan")
    result: list[tuple[tuple[str, str], tuple[tuple[str, str], ...]]] = []
    seen: set[tuple[str, str]] = set()
    for specification in document.get("drumgizmo_composites", []):
        if not isinstance(specification, dict):
            raise ValueError("each DrumGizmo composite must be an object")
        target_value, source_values = specification.get("target"), specification.get("sources")
        if (not isinstance(target_value, str) or target_value.count(".") != 1 or
                not isinstance(source_values, list) or len(source_values) < 2 or
                not all(isinstance(value, str) and value.count(".") == 1 for value in source_values)):
            raise ValueError("DrumGizmo composite needs target and at least two instrument.articulation sources")
        target = tuple(target_value.split(".", 1))
        sources = tuple(tuple(value.split(".", 1)) for value in source_values)
        if sources[0] != target or target in seen or len(set(sources)) != len(sources):
            raise ValueError("DrumGizmo composite target must be its first unique source and may be declared once")
        seen.add(target)
        result.append((target, sources))
    return result


def _composite_filename(target: tuple[str, str], velocity: int, repetition: int) -> str:
    return (f"{target[0]}__{target[1]}__v{velocity:03d}"
            f"__rr{repetition:02d}_composite.wav")


def capture_drumgizmo_composites(session: CaptureSessionPlan, *, plan_path: Path,
                                  output_root: Path, capture=capture_chord) -> tuple[Path, ...]:
    """Capture simultaneous SD3 layer chords for exact DrumGizmo attacks."""
    requests = {(request.instrument, request.articulation): request for request in session.requests}
    output_root.mkdir(parents=True, exist_ok=True)
    captured: list[Path] = []
    for target, sources in _drumgizmo_composite_specs(plan_path):
        source_requests = []
        for source in sources:
            request = requests.get(source)
            if request is None:
                raise ValueError(f"DrumGizmo composite source is absent from the capture session: {source}")
            source_requests.append(request)
        primary = source_requests[0]
        for request in source_requests[1:]:
            if request.velocities != primary.velocities or request.repetitions != primary.repetitions:
                raise ValueError(f"DrumGizmo composite sources need identical velocity/RR grids: {target}")
            if request.channel != primary.channel or request.controllers != primary.controllers:
                raise ValueError(f"DrumGizmo composite sources need one channel/controller contract: {target}")
        notes = tuple(request.note for request in source_requests)
        if len(set(notes)) != len(notes):
            raise ValueError(f"DrumGizmo composite MIDI notes must be unique: {target}")
        for velocity in primary.velocities:
            for repetition in range(1, primary.repetitions + 1):
                output = output_root / _composite_filename(target, velocity, repetition)
                if output.is_file():
                    continue
                print(
                    f"[{target[0]}.{target[1]} v{velocity} rr{repetition}] chord={notes}",
                    flush=True,
                )
                path = capture(
                    midi_port=session.midi_output,
                    audio_input=session.audio_input,
                    notes=notes,
                    velocity=velocity,
                    output=output,
                    channel=primary.channel,
                    controllers=primary.controllers,
                    duration=(session.gate_ms + session.tail_ms) / 1000,
                    gate=session.gate_ms / 1000,
                    preroll=session.preroll_ms / 1000,
                    sample_rate=session.sample_rate,
                    channels=len(session.channels),
                )
                if path != output or not output.is_file():
                    raise RuntimeError(f"composite capture did not create expected WAV: {output}")
                captured.append(output)
                if session.cooldown_ms:
                    time.sleep(session.cooldown_ms / 1000)
    return tuple(captured)


def apply_captured_drumgizmo_composites(library: SampleLibrary, *, composite_root: Path,
                                        plan_path: Path) -> SampleLibrary:
    """Point target takes at approved simultaneous chord WAVs after strict QC."""
    targets = {target: sources for target, sources in _drumgizmo_composite_specs(plan_path)}
    updated: list[SampleTake] = []
    for take in library.takes:
        key = (take.instrument, take.articulation)
        sources = targets.get(key)
        if sources is None:
            updated.append(take)
            continue
        path = composite_root / _composite_filename(key, take.velocity, take.repetition)
        if not path.is_file():
            raise FileNotFoundError(f"simultaneous DrumGizmo composite is missing: {path}")
        quality = assess_wav(path, CaptureQualityPolicy(
            expected_sample_rate=take.sample_rate,
            expected_channels=len(library.channel_layout),
        ))
        if quality["automatic_status"] != "accepted":
            raise ValueError(f"DrumGizmo composite failed quality gates: {path}: {quality['findings']}")
        facts = quality["facts"]
        updated.append(replace(
            take,
            prepared_file=str(path.resolve()),
            sample_rate=int(facts["sample_rate"]),
            frames=int(facts["frames"]),
            peak_dbfs=float(facts["peak_dbfs"]),
            rms_dbfs=float(facts["rms_dbfs"]),
            clipped=bool(facts["clipped"]),
            sha256=str(facts["sha256"]),
            processing_history=take.processing_history + (
                "simultaneous-layer-capture:" + "+".join(".".join(source) for source in sources),
            ),
        ))
    return SampleLibrary(library.identifier, library.channel_layout, tuple(updated))


def audit_drumgizmo_composites(session: CaptureSessionPlan, *, composite_root: Path,
                                plan_path: Path) -> dict[str, Any]:
    """Audit the complete simultaneous-layer grid against its capture session."""
    requests = {(request.instrument, request.articulation): request for request in session.requests}
    policy = CaptureQualityPolicy(
        expected_sample_rate=session.sample_rate,
        expected_channels=len(session.channels),
    )
    records: list[dict[str, Any]] = []
    for target, _sources in _drumgizmo_composite_specs(plan_path):
        request = requests.get(target)
        if request is None:
            raise ValueError(f"DrumGizmo composite target is absent from the capture session: {target}")
        for velocity in request.velocities:
            for repetition in range(1, request.repetitions + 1):
                path = composite_root / _composite_filename(target, velocity, repetition)
                record: dict[str, Any] = {
                    "instrument": target[0], "articulation": target[1],
                    "velocity": velocity, "repetition": repetition, "path": str(path),
                }
                if path.is_file():
                    record.update(assess_wav(path, policy))
                else:
                    record.update({
                        "automatic_status": "missing", "findings": ["missing_composite"],
                        "audition_status": "pending",
                    })
                records.append(record)
    counts = {status: sum(record["automatic_status"] == status for record in records)
              for status in ("accepted", "rejected", "missing")}
    rr_groups: dict[tuple[str, str, int], list[str]] = {}
    for record in records:
        digest = record.get("variation_fingerprint_sha256")
        if record.get("automatic_status") == "accepted" and isinstance(digest, str):
            key = (str(record["instrument"]), str(record["articulation"]), int(record["velocity"]))
            rr_groups.setdefault(key, []).append(digest)
    duplicate_round_robins = [
        {"instrument": key[0], "articulation": key[1], "velocity": key[2],
         "repetitions": len(hashes), "unique_audio_fingerprints": len(set(hashes))}
        for key, hashes in sorted(rr_groups.items())
        if len(hashes) > 1 and len(set(hashes)) < len(hashes)
    ]
    counts["round_robin_duplicate_cells"] = len(duplicate_round_robins)
    return {
        "kind": "drumgizmo-composite-quality-report", "schema_version": 1,
        "megakit_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "policy": {
            "minimum_duration_ms": policy.minimum_duration_ms,
            "silence_rms_dbfs": policy.silence_rms_dbfs,
            "reject_clipped": policy.reject_clipped,
            "expected_sample_rate": policy.expected_sample_rate,
            "expected_channels": policy.expected_channels,
        },
        "summary": counts, "round_robin_duplicates": duplicate_round_robins,
        "takes": records,
    }


def validate_drumgizmo_composite_report(report_path: Path, *, session_path: Path,
                                         composite_root: Path, plan_path: Path) -> dict[str, Any]:
    """Reject stale, incomplete, modified, or duplicate simultaneous layer takes."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("a valid simultaneous-layer quality report is required") from error
    session_sha256 = hashlib.sha256(session_path.read_bytes()).hexdigest()
    plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    if (report.get("kind") != "drumgizmo-composite-quality-report"
            or report.get("session_sha256") != session_sha256
            or report.get("megakit_plan_sha256") != plan_sha256):
        raise ValueError("the simultaneous-layer quality report is stale for the session or MegaKit plan")
    fresh = audit_drumgizmo_composites(
        CaptureSessionPlan.read(session_path), composite_root=composite_root, plan_path=plan_path,
    )
    expected_summary = fresh["summary"]
    if (report.get("summary") != expected_summary
            or expected_summary.get("rejected") != 0
            or expected_summary.get("missing") != 0
            or expected_summary.get("round_robin_duplicate_cells") != 0):
        raise ValueError("the simultaneous-layer quality report failed or no longer matches the WAV files")

    def indexed(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        takes = document.get("takes")
        if not isinstance(takes, list):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for take in takes:
            if not isinstance(take, dict) or not isinstance(take.get("path"), str):
                return {}
            name = Path(take["path"]).name
            if name in result:
                return {}
            result[name] = take
        return result

    recorded, current = indexed(report), indexed(fresh)
    if set(recorded) != set(current) or not recorded:
        raise ValueError("the simultaneous-layer report does not cover the exact composite grid")
    for name in recorded:
        recorded_facts, current_facts = recorded[name].get("facts"), current[name].get("facts")
        if (not isinstance(recorded_facts, dict) or not isinstance(current_facts, dict)
                or recorded_facts.get("sha256") != current_facts.get("sha256")
                or recorded[name].get("variation_fingerprint_sha256")
                != current[name].get("variation_fingerprint_sha256")):
            raise ValueError(f"simultaneous-layer WAV changed after quality review: {name}")
    return report


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


def write_drumgizmo_validation_report(kit_directory: Path, report_path: Path) -> dict[str, Any]:
    """Validate the self-contained kit and fingerprint every exported file."""
    validation = validate_drumgizmo_kit(kit_directory)
    files = []
    report_resolved = report_path.resolve()
    for path in sorted(item for item in kit_directory.rglob("*")
                       if item.is_file() and item.resolve() != report_resolved):
        files.append({
            "path": path.relative_to(kit_directory).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    report = {
        "kind": "drumgizmo-kit-validation-report", "schema_version": 1,
        "status": "pass", "kit_directory": str(kit_directory.resolve()),
        "kit": validation, "files": files, "hardware_io": "disabled",
        "external_audio_load": "not_executed",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def verify_drumgizmo_validation_report(kit_directory: Path, report_path: Path) -> dict[str, Any]:
    """Verify that every kit byte still matches one exact validation manifest."""
    kit_root = kit_directory.resolve()
    report_resolved = report_path.resolve()
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid DrumGizmo validation report: {report_path}") from error
    if (report.get("kind") != "drumgizmo-kit-validation-report"
            or report.get("schema_version") != 1 or report.get("status") != "pass"):
        raise ValueError("DrumGizmo validation report is not a passing v1 manifest")
    declared_root = report.get("kit_directory")
    if not isinstance(declared_root, str) or Path(declared_root).resolve() != kit_root:
        raise ValueError("DrumGizmo validation report belongs to another kit")
    records = report.get("files")
    if not isinstance(records, list):
        raise ValueError("DrumGizmo validation report has no file manifest")
    declared: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("DrumGizmo validation report contains an invalid file record")
        relative = Path(record["path"])
        path = (kit_root / relative).resolve()
        try:
            path.relative_to(kit_root)
        except ValueError as error:
            raise ValueError(f"DrumGizmo validation path escapes the kit: {relative.as_posix()}") from error
        key = relative.as_posix()
        if relative.is_absolute() or key in declared:
            raise ValueError(f"DrumGizmo validation path is invalid or duplicated: {key}")
        declared[key] = record
    for required in ("drumkit.xml", "midimap.xml"):
        if required not in declared:
            raise ValueError(f"DrumGizmo validation manifest is missing {required}")
    current = {
        path.relative_to(kit_root).as_posix(): path
        for path in kit_root.rglob("*")
        if path.is_file() and path.resolve() != report_resolved
    }
    if set(current) != set(declared):
        missing = sorted(set(declared) - set(current))
        extra = sorted(set(current) - set(declared))
        raise ValueError(f"DrumGizmo kit file set changed after validation; missing={missing}, extra={extra}")
    for relative, path in current.items():
        record = declared[relative]
        expected_bytes = record.get("bytes")
        expected_sha256 = record.get("sha256")
        actual_bytes = path.stat().st_size
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_bytes != actual_bytes or expected_sha256 != actual_sha256:
            raise ValueError(
                f"DrumGizmo file changed after validation: {relative}; "
                f"expected bytes={expected_bytes}, sha256={expected_sha256}; "
                f"got bytes={actual_bytes}, sha256={actual_sha256}"
            )
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
