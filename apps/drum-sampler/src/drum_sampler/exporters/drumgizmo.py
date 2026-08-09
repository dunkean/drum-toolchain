"""DrumGizmo 2.0 kit export from a captured neutral sample library."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from ..library import SampleLibrary, SampleTake


@dataclass(frozen=True)
class DrumGizmoExport:
    drumkit: Path
    midimap: Path
    instruments: tuple[Path, ...]
    copied_audio: tuple[Path, ...]


def _identifier(value: str) -> str:
    return "".join(character if character.isalnum() or character in "_-" else "_" for character in value)


def _source_file(take: SampleTake, audio_root: Path) -> Path:
    value = take.prepared_file or take.raw_file
    path = Path(value)
    return path if path.is_absolute() else audio_root / path


def _write_xml(path: Path, element: ET.Element) -> None:
    ET.indent(element, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(element).write(path, encoding="utf-8", xml_declaration=True)
    ET.parse(path)  # Validate the file we wrote before reporting success.


def export_drumgizmo(library: SampleLibrary, *, audio_root: Path, output_directory: Path, title: str | None = None, copy_audio: bool = True) -> DrumGizmoExport:
    """Write a self-contained DrumGizmo 2.0 kit from captured WAV takes.

    No audio is altered. In copy mode files are copied to the generated kit,
    never overwritten; otherwise instrument files reference absolute sources.
    """
    if not 1 <= len(library.channel_layout) <= 4:
        raise ValueError("DrumGizmo export requires one to four named channel-layout entries")
    captured = tuple(take for take in library.takes if take.status == "captured")
    if not captured:
        raise ValueError("DrumGizmo export requires at least one captured take")
    rates = {take.sample_rate for take in captured}
    if len(rates) != 1 or None in rates:
        raise ValueError("captured takes must have one known sample rate")
    groups: dict[tuple[str, str], list[SampleTake]] = {}
    for take in captured:
        groups.setdefault((take.instrument, take.articulation), []).append(take)
    note_groups: dict[int, tuple[str, str]] = {}
    for key, takes in groups.items():
        notes = {take.note for take in takes}
        if len(notes) != 1:
            raise ValueError(f"{key}: one articulation cannot have multiple MIDI notes")
        note = next(iter(notes))
        if note in note_groups:
            raise ValueError(f"MIDI note {note} maps to both {note_groups[note]} and {key}; resolve this in a target profile")
        note_groups[note] = key

    output_directory.mkdir(parents=True, exist_ok=True)
    samples_dir = output_directory / "samples"
    instruments_dir = output_directory / "instruments"
    copied: list[Path] = []
    instruments: list[Path] = []
    title = title or library.identifier
    for (instrument, articulation), takes in sorted(groups.items()):
        name = _identifier(f"{instrument}__{articulation}")
        root = ET.Element("instrument", {"version": "2.0", "name": name, "description": f"{instrument} {articulation}"})
        channels = ET.SubElement(root, "channels")
        for channel in library.channel_layout:
            ET.SubElement(channels, "channel", {"name": channel, "main": "true"})
        samples = ET.SubElement(root, "samples")
        ordered = sorted(takes, key=lambda take: (take.velocity, take.repetition, take.raw_file))
        for index, take in enumerate(ordered, start=1):
            sample = ET.SubElement(samples, "sample", {"name": f"{name}-{index:03d}", "power": f"{take.velocity / 127:.7f}"})
            source = _source_file(take, audio_root)
            if not source.is_file():
                raise ValueError(f"captured sample is missing: {source}")
            if copy_audio:
                destination = samples_dir / f"{name}-{index:03d}{source.suffix.lower()}"
                if destination.exists():
                    if destination.read_bytes() != source.read_bytes():
                        raise FileExistsError(f"refusing to overwrite different exported audio: {destination}")
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    copied.append(destination)
                file_value = (Path("..") / "samples" / destination.name).as_posix()
            else:
                file_value = str(source.resolve())
            for channel_index, channel in enumerate(library.channel_layout, start=1):
                ET.SubElement(sample, "audiofile", {"channel": channel, "file": file_value, "filechannel": str(channel_index)})
        instrument_file = instruments_dir / f"{name}.xml"
        _write_xml(instrument_file, root)
        instruments.append(instrument_file)

    kit = ET.Element("drumkit", {"version": "2.0", "samplerate": str(next(iter(rates)))})
    metadata = ET.SubElement(kit, "metadata")
    ET.SubElement(metadata, "title").text = title
    ET.SubElement(metadata, "description").text = f"Generated from neutral sample library {library.identifier}"
    ET.SubElement(metadata, "license").text = "See neutral sample-library take metadata"
    channels = ET.SubElement(kit, "channels")
    for channel in library.channel_layout:
        ET.SubElement(channels, "channel", {"name": channel})
    kit_instruments = ET.SubElement(kit, "instruments")
    for (instrument, articulation), _takes in sorted(groups.items()):
        name = _identifier(f"{instrument}__{articulation}")
        element = ET.SubElement(kit_instruments, "instrument", {"name": name, "file": (Path("instruments") / f"{name}.xml").as_posix()})
        for channel in library.channel_layout:
            ET.SubElement(element, "channelmap", {"in": channel, "out": channel, "main": "true"})
    drumkit_path = output_directory / "drumkit.xml"
    _write_xml(drumkit_path, kit)

    midi = ET.Element("midimap")
    for note, (instrument, articulation) in sorted(note_groups.items()):
        ET.SubElement(midi, "map", {"note": str(note), "instr": _identifier(f"{instrument}__{articulation}")})
    midimap_path = output_directory / "midimap.xml"
    _write_xml(midimap_path, midi)
    return DrumGizmoExport(drumkit_path, midimap_path, tuple(instruments), tuple(copied))
