"""Build a complete local audition kit from a capture package.

The builder targets the DDrum4 limit of ten samples/Layers per Sound.  It is
offline: generated MIDI Sound files are decoded again for audition, but are
never transferred to hardware.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
from pathlib import Path
import re

from drum_sampler.audio import QualityProfile, analyze_wav, process_wav

from .auditioner import AuditionEntry, CaptureAuditionCatalog
from .codec_preview import export_codec_preview
from .ddrum4edit_backend import Ddrum4EditBackend
from .ddrum4ui import discover
from .sound_config import materialize_sound_config


_SOUND_IDS = {
    "S01 KICK": "KICK_981",
    "S02 SNARE": "SNRE_981",
    "S03 RIM": "RIM_981",
    "S04 TOMS": "TOM_981",
    "S05 FLEX": "PERC_981",
    "S06 HI-HAT": "HHAT_981",
    "S07 HH EDGE": "CYMB_981",
    "S08 CYMBAL1": "CYMB_982",
    "S09 CYMBAL2": "CYMB_983",
    "S10 PERC": "PERC_982",
}

# Neutral Layer DSP defaults taken from the already hardware-approved
# SNRE_943 / HHAT_947 / CYMB_944-945 configs.  Zeroing these bytes bypasses
# part of the DDrum4 Layer engine and does not match a normal module Sound.
_VERIFIED_LAYER_DSP = {
    2: 0x02,   # HiHat/general Layer mode used by accepted non-hi-hat Sounds too
    28: 0x63,  # amplitude
    29: 0x63,  # velocity curve
    32: 0x63,  # amplitude decay
    36: 0x09,  # filter 1 frequency
    38: 0x06,  # filter 1 gain
    40: 0x04,  # filter 1 Q
    41: 0x63,  # filter 1 gain decay
    42: 0x32,  # filter 2 frequency
    44: 0x04,  # filter 2 Q
}

@dataclass(frozen=True)
class PlannedKitLayer:
    index: int
    note_p: int
    instrument: str
    articulation: str
    velocity: int
    round_robin: int
    raw_file: str
    pitch_semitones: int = 0
    variation_indexes: tuple[int, ...] = ()
    sequence: bool = False
    source_velocity: int | None = None

    @property
    def identity(self) -> tuple[int, str, str, int, tuple[int, ...], int]:
        """Layers that are deliberately alternate variants keep a full velocity map.

        Two Layers sharing a WAV can still be distinct DDrum4 Layers: this is
        how pitch variations cost configuration bytes rather than an extra
        encoded sample.  A sequenced high-velocity RR also needs both Layers
        to be eligible before the Variation sequence selects one.
        """
        return (
            self.note_p, self.instrument, self.articulation, self.pitch_semitones,
            self.variation_indexes, self.round_robin if self.sequence else 0,
        )


def _evenly_spaced(values: list[int], count: int) -> tuple[int, ...]:
    count = min(count, len(values))
    if count == 1:
        return (values[len(values) // 2],)
    indexes = [round(index * (len(values) - 1) / (count - 1)) for index in range(count)]
    return tuple(values[index] for index in indexes)


def plan_sound_layers(
    catalog: CaptureAuditionCatalog, slot: str, maximum: int = 10,
) -> tuple[PlannedKitLayer, ...]:
    """Materialize the explicit S01..S10 architecture, without filling spare Layers."""
    if maximum != 10:
        raise ValueError("the architecture planner targets the DDrum4 ten-Layer ceiling")
    planned: list[PlannedKitLayer] = []

    def add(
        note_p: int,
        instrument: str,
        articulation: str,
        *,
        count: int = 1,
        velocities: tuple[int, ...] | None = None,
        round_robin: int = 1,
        source_note_p: int | None = None,
        source_slot: str | None = None,
        layer_indexes: tuple[int, ...] | None = None,
        pitch_semitones: int = 0,
        variation_indexes: tuple[int, ...] = (),
        sequence: bool = False,
    ) -> None:
        source_position = note_p if source_note_p is None else source_note_p
        source_entries = catalog.entries_for_slot(source_slot or slot)
        pool = [
            entry for entry in source_entries
            if entry.note_p == source_position and entry.instrument == instrument and entry.articulation == articulation
        ]
        if not pool:
            raise ValueError(
                f"{slot} has no source for P{source_position} {instrument}.{articulation}"
            )
        if not -48 <= pitch_semitones <= 12:
            raise ValueError("DDrum4 coarse Layer pitch must be in -48..12 semitones")
        if any(index < 1 or index > 10 for index in variation_indexes):
            raise ValueError("Layer variation indexes must be in 1..10")
        levels = sorted({entry.velocity for entry in pool})
        requested = (
            tuple((value, value) for value in _evenly_spaced(levels, count))
            if velocities is None else tuple(
                (target, min(levels, key=lambda level: (abs(level - target), -level)))
                for target in velocities
            )
        )
        if layer_indexes is not None and len(layer_indexes) != len(requested):
            raise ValueError("one explicit Layer index is required per selected velocity")
        for offset, (velocity, source_velocity) in enumerate(requested):
            candidates = [entry for entry in pool if entry.velocity == source_velocity]
            selected = next(
                (entry for entry in sorted(candidates, key=lambda item: item.raw_file) if entry.round_robin == round_robin),
                min(candidates, key=lambda entry: (entry.round_robin, entry.raw_file)),
            )
            planned.append(PlannedKitLayer(
                layer_indexes[offset] if layer_indexes is not None else len(planned) + 1,
                note_p, instrument, articulation, velocity,
                selected.round_robin, selected.raw_file, pitch_semitones,
                variation_indexes, sequence, selected.velocity,
            ))

    if slot == "S01 KICK":
        # The two lowest acoustic captures are inaudible in this kit. Keep
        # only the two useful layers plus a hard-hit alternate. The electronic
        # tom replaces all former DnB/industrial/trap/sub kick samples.
        add(1, "kick_metalcore", "head", velocities=(84, 124), variation_indexes=(1, 2))
        add(
            2, "kick_metalcore", "head", velocities=(124,), round_robin=2,
            source_note_p=1, variation_indexes=(1, 2),
        )
        add(
            5, "electronic_tom", "low", velocities=(104,), source_slot="S10 PERC",
            source_note_p=7, variation_indexes=(3,),
        )
    elif slot == "S02 SNARE":
        add(1, "snare_metalcore", "center", velocities=(20, 68, 124))
        add(2, "snare_metalcore", "center", velocities=(124,), round_robin=2, source_note_p=1)
        add(3, "snare_metalcore", "center", velocities=(124,), round_robin=3, source_note_p=1)
        add(4, "snare_metalcore", "mid", velocities=(20, 68, 124))
        add(5, "snare_metalcore", "edge", velocities=(20, 124), layer_indexes=(9, 10))
    elif slot == "S03 RIM":
        add(1, "snare_metalcore", "rimshot", velocities=(20, 124))
        add(2, "snare_metalcore", "rimshot", velocities=(124,), round_robin=2, source_note_p=1)
        add(3, "snare_metalcore", "cross_stick", velocities=(124,))
        add(4, "snare_metalcore", "rimshot", velocities=(20, 124), source_note_p=1)
        add(5, "snare_metalcore", "rimshot", velocities=(124,), round_robin=2, source_note_p=1)
        add(6, "snare_metalcore", "cross_stick", velocities=(124,), source_note_p=3)
    elif slot == "S04 TOMS":
        # Keep the medium and second-floor captures only. Rack 1 and Floor 1
        # are DDrum4 pitch Layers that reuse those resident samples. Each
        # physical source has only useful/strong velocity Layers. Rack 1 and
        # Floor 1 remain pitch-derived positions, not extra resident WAVs.
        add(1, "tom_2", "head", velocities=(68, 124), source_note_p=2, pitch_semitones=4)
        add(2, "tom_2", "head", velocities=(68,), source_note_p=2)
        add(2, "tom_2", "head", velocities=(124,), source_note_p=2, sequence=True)
        add(
            3, "tom_4", "head", velocities=(68, 124), source_slot="S05 FLEX",
            source_note_p=1, pitch_semitones=4,
        )
        add(4, "tom_4", "head", velocities=(68,), source_slot="S05 FLEX", source_note_p=1)
        add(
            4, "tom_4", "head", velocities=(124,), source_slot="S05 FLEX",
            source_note_p=1, sequence=True,
        )
        # The two direct resident tom positions regain a high-velocity RR.
        # The pitch-derived Rack 1 and Floor 1 Layers deliberately keep the
        # first capture so this Sound remains within DDrum4's ten-Layer limit.
        add(2, "tom_2", "head", velocities=(124,), round_robin=2, source_note_p=2,
            layer_indexes=(9,), sequence=True)
        add(4, "tom_4", "head", velocities=(124,), round_robin=2, source_slot="S05 FLEX",
            source_note_p=1, layer_indexes=(10,), sequence=True)
    elif slot == "S05 FLEX":
        # Floor 2 now resides in S04 and is shared there for its pitched
        # Floor 1 Layer. FLEX retains only its two electronic one-shot snares.
        add(7, "snare_low_trap", "head", velocities=(104,))
        add(8, "snare_trap", "head", velocities=(104,))
    elif slot == "S06 HI-HAT":
        add(1, "hi_hat", "tip_closed", velocities=(68, 124))
        add(2, "hi_hat", "tip_loose", velocities=(68, 124))
        add(3, "hi_hat", "tip_quarter_open", velocities=(68, 124))
        add(4, "hi_hat", "tip_half_open", velocities=(68,))
        add(5, "hi_hat", "tip_open", velocities=(68,))
    elif slot == "S07 HH EDGE":
        add(1, "hi_hat", "edge_closed", velocities=(68, 124))
        add(2, "hi_hat", "edge_quarter_open", velocities=(68, 124))
        add(3, "hi_hat", "edge_half_open", velocities=(68, 124))
        add(4, "hi_hat", "edge_open", velocities=(68, 124))
        add(5, "hi_hat", "pedal_close", velocities=(104,))
        add(6, "hi_hat", "pedal_splash", velocities=(104,))
    elif slot == "S08 CYMBAL1":
        # One physical crash is enough. It has useful/strong velocity Layers;
        # three pitch variations share those WAVs. Splash and China remain
        # separate playable cymbal articulations; only Crash Ride is omitted.
        add(1, "crash_1", "bow", velocities=(68,), layer_indexes=(1,), variation_indexes=(1,))
        add(1, "crash_1", "bow", velocities=(124,), layer_indexes=(2,), variation_indexes=(1,))
        add(1, "crash_1", "bow", velocities=(68, 124), layer_indexes=(3, 4), pitch_semitones=3, variation_indexes=(2,))
        add(1, "crash_1", "bow", velocities=(68, 124), layer_indexes=(5, 6), pitch_semitones=-3, variation_indexes=(3,))
        add(3, "splash", "hit", velocities=(68, 124), layer_indexes=(7, 8))
        add(4, "china_1", "edge", velocities=(68, 124), layer_indexes=(9, 10))
    elif slot == "S09 CYMBAL2":
        # Crash 2 is intentionally removed: S08 owns the sole crash and its
        # encoded pitch variations. S09 stays dedicated to ride bow and bell.
        add(3, "ride", "bow", velocities=(68, 124), layer_indexes=(1, 2))
        add(4, "ride", "bell", velocities=(68, 124), layer_indexes=(3, 4))
    elif slot == "S10 PERC":
        for note_p, instrument, articulation in (
            (7, "cowbell", "hit"),
            (8, "woodblock", "hit"),
        ):
            add(note_p, instrument, articulation, velocities=(104,))
    else:
        raise ValueError(f"no architecture Layer plan for {slot}")
    return tuple(planned)


def _layer_rows(
    layers: tuple[PlannedKitLayer, ...], sample_indexes: tuple[int, ...] | None = None,
) -> tuple[str, ...]:
    """Create neutral position/velocity masks covering all eight velocity steps."""
    rows: list[str] = []
    sample_by_layer = {
        layer.index: sample_index for layer, sample_index in zip(layers, sample_indexes or range(len(layers)))
    }
    layer_by_index = {layer.index: layer for layer in layers}
    if len(layer_by_index) != len(layers) or any(not 1 <= index <= 10 for index in layer_by_index):
        raise ValueError("planned Layer indexes must be unique and in 1..10")
    maximum_index = max(layer_by_index)
    for layer_index in range(1, maximum_index + 1):
        layer = layer_by_index.get(layer_index)
        if layer is None:
            rows.append(" ".join("00" for _ in range(50)))
            continue
        peers = [item for item in layers if item.identity == layer.identity]
        centers = (8, 24, 40, 56, 72, 88, 104, 120)
        owner = [min(peers, key=lambda item: (abs(item.velocity - center), -item.velocity)).index for center in centers]
        values = [0] * 50
        for offset, value in _VERIFIED_LAYER_DSP.items():
            values[offset] = value
        values[0] = sample_by_layer[layer.index]
        values[20] = layer.pitch_semitones & 0xFF
        values[4:12] = [255 if layer.index == selected else 0 for selected in owner]
        values[12:20] = [255 if position == layer.note_p else 0 for position in range(1, 9)]
        rows.append(" ".join(f"{value:02X}" for value in values))
    return tuple(rows)


def _variation_masks(
    catalog: CaptureAuditionCatalog, slot: str, layers: tuple[PlannedKitLayer, ...],
) -> tuple[tuple[bool, ...], ...]:
    indexes = sorted(catalog.variation_names.get(slot, {})) or [1]
    masks: list[tuple[bool, ...]] = []
    s05_positions = ((7,), (8,))
    s10_choices = (
        ("cowbell", "woodblock"),
        ("electronic_tom", "woodblock"),
        ("electronic_tom", "glitch_noise"),
        ("electronic_tom", "glitch_noise"),
        ("cowbell", "glitch_noise"),
        ("cowbell", "glitch_noise"),
        ("electronic_tom", "woodblock"),
    )
    for offset, _variation_index in enumerate(indexes):
        if slot == "S05 FLEX":
            positions = s05_positions[min(offset, len(s05_positions) - 1)]
            mask = tuple(layer.note_p in positions for layer in layers)
        elif slot == "S10 PERC":
            p7, p8 = s10_choices[min(offset, len(s10_choices) - 1)]
            mask = tuple(
                layer.note_p <= 6
                or (layer.note_p == 7 and layer.instrument == p7)
                or (layer.note_p == 8 and layer.instrument == p8)
                for layer in layers
            )
        else:
            mask = tuple(True for _layer in layers)
        mask = tuple(
            enabled and (not layer.variation_indexes or _variation_index in layer.variation_indexes)
            for layer, enabled in zip(layers, mask)
        )
        enabled_by_index = {layer.index: enabled for layer, enabled in zip(layers, mask)}
        masks.append(tuple(enabled_by_index.get(index, False) for index in range(1, max(layer.index for layer in layers) + 1)))
    return tuple(masks)


def _variation_sequences(
    layers: tuple[PlannedKitLayer, ...], masks: tuple[tuple[bool, ...], ...],
) -> tuple[tuple[bool, ...], ...]:
    """Mark only enabled high-velocity round-robin Layers as sequenced."""
    layer_by_index = {layer.index: layer for layer in layers}
    return tuple(
        tuple(
            enabled and (layer_by_index[index + 1].sequence if index + 1 in layer_by_index else False)
            for index, enabled in enumerate(mask)
        )
        for mask in masks
    )


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")


def _quality_profile(slot: str) -> QualityProfile:
    dynamic_cymbal_tail = "CYMBAL" in slot or "HI-HAT" in slot or "HH EDGE" in slot
    if "CYMBAL" in slot:
        duration = 6.5
    elif "HI-HAT" in slot or "HH EDGE" in slot:
        duration = 6.5
    elif "SNARE" in slot or "RIM" in slot:
        duration = 1.8
    elif "KICK" in slot:
        duration = 3.0
    elif "TOMS" in slot or "FLEX" in slot:
        duration = 3.5
    else:
        duration = 3.0
    return QualityProfile(
        target_sample_rate=44100,
        trim_threshold_db=-80.0 if dynamic_cymbal_tail else -60.0,
        normalize_dbfs=-2.0,
        # The DD4 decoder is sensitive to the exact leading transient. Keep
        # the capture intact: the silent onset margin replaces an input fade.
        fade_in_ms=0.0,
        fade_out_ms=30.0 if dynamic_cymbal_tail else 15.0,
        highpass_hz=None,
        lowpass_hz=None,
        max_duration_seconds=duration,
        force_mono=True,
        trim_tail=dynamic_cymbal_tail,
        onset_margin_ms=5.0,
        tail_margin_ms=250.0 if dynamic_cymbal_tail else None,
    )


def build_sound(
    catalog: CaptureAuditionCatalog,
    backend: Ddrum4EditBackend,
    *,
    slot: str,
    template: Path,
    build_root: Path,
    preview_root: Path,
) -> dict[str, object]:
    """Prepare, encode and decode one complete audition Sound."""
    sound_id = _SOUND_IDS.get(slot)
    if sound_id is None:
        raise ValueError(f"no local Sound ID reserved for {slot}")
    output = build_root / _safe_name(slot)
    preview_output = preview_root / _safe_name(slot)
    report_path = output / "build.json"
    manifest_path = preview_output / "codec-preview.json"
    if report_path.is_file() and manifest_path.is_file():
        return json.loads(report_path.read_text(encoding="utf-8"))
    if output.exists() or preview_output.exists():
        raise FileExistsError(f"incomplete previous build exists for {slot}; inspect {output} and {preview_output}")
    layers = plan_sound_layers(catalog, slot)
    profile = _quality_profile(slot)
    output.mkdir(parents=True)
    sample_by_raw: dict[str, int] = {}
    sample_layers: list[PlannedKitLayer] = []
    sample_indexes: list[int] = []
    for layer in layers:
        sample_index = sample_by_raw.get(layer.raw_file)
        if sample_index is None:
            sample_index = len(sample_layers)
            sample_by_raw[layer.raw_file] = sample_index
            sample_layers.append(layer)
        sample_indexes.append(sample_index)

    # A velocity stack must retain the loudness relationships captured at the
    # source.  Normalising every hit independently turns room/noise into hiss
    # on soft Layers and makes all velocities sound equally loud.
    peaks_by_articulation: dict[tuple[str, str], list[float]] = {}
    source_facts: dict[str, dict[str, int | float | bool | str]] = {}
    for layer in sample_layers:
        raw = catalog.audio_root / layer.raw_file
        if not raw.is_file():
            raise FileNotFoundError(f"captured source is missing: {raw}")
        facts = analyze_wav(raw)
        source_facts[layer.raw_file] = facts
        peak = float(facts["peak_dbfs"])
        if peak != -float("inf"):
            peaks_by_articulation.setdefault((layer.instrument, layer.articulation), []).append(peak)
    gains = {
        identity: profile.normalize_dbfs - max(peaks)
        for identity, peaks in peaks_by_articulation.items()
    }

    prepared_names: list[str] = []
    prepared_by_raw: dict[str, tuple[str, dict[str, int | float]]] = {}
    for sample_index, layer in enumerate(sample_layers, start=1):
        raw = catalog.audio_root / layer.raw_file
        prepared_name = (
            f"S{sample_index:02d}__{_safe_name(layer.instrument)}__{_safe_name(layer.articulation)}"
            f"__v{layer.velocity:03d}__rr{layer.round_robin:02d}.wav"
        )
        gain_db = gains[(layer.instrument, layer.articulation)]
        facts = process_wav(raw, output / prepared_name, profile, gain_db=gain_db)
        prepared_names.append(prepared_name)
        prepared_by_raw[layer.raw_file] = (prepared_name, facts)

    layer_documents: list[dict[str, object]] = []
    for layer, sample_index in zip(layers, sample_indexes):
        raw = catalog.audio_root / layer.raw_file
        prepared_name, facts = prepared_by_raw[layer.raw_file]
        layer_documents.append({
            **asdict(layer),
            "sample_index": sample_index + 1,
            "prepared_file": prepared_name,
            "source_path": str(raw.resolve()),
            "source_peak_dbfs": source_facts[layer.raw_file]["peak_dbfs"],
            "shared_gain_db": gains[(layer.instrument, layer.articulation)],
            "duration_seconds": facts["duration_seconds"],
            "sample_rate": facts["sample_rate"],
            "channels": facts["channels"],
        })
    sound = output / f"{sound_id}.mid"
    variation_masks = _variation_masks(catalog, slot, layers)
    config = materialize_sound_config(
        template,
        output / f"{sound_id}.cfg",
        sound_name=sound_id,
        output_sound=sound,
        sample_files=prepared_names,
        layer_rows=_layer_rows(layers, tuple(sample_indexes)),
        variation_layers=variation_masks,
        variation_sequences=_variation_sequences(layers, variation_masks),
    )
    backend.build(config, sound)
    blocks = backend.encoded_blocks(sound)
    export_codec_preview(
        backend,
        sound=sound,
        config=config,
        output_directory=preview_output,
        sound_slot=slot,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["kit_library"] = catalog.library_name
    manifest["kit_layers"] = layer_documents
    manifest["variation_names"] = catalog.variation_names.get(slot, {})
    manifest["variation_models"] = catalog.variation_models.get(slot, {})
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "kind": "ddrum4-audition-kit-sound/v1",
        "slot": slot,
        "sound_id": sound_id,
        "sound": sound.name,
        "config": config.name,
        "encoded_blocks": blocks,
        "encoded_bytes": sound.stat().st_size,
        "layers": layer_documents,
        "variation_names": catalog.variation_names.get(slot, {}),
        "variation_models": catalog.variation_models.get(slot, {}),
        "hardware_io": "disabled",
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def build_kit(
    package: Path,
    *,
    template: Path,
    executable: Path,
    only_slot: str | None = None,
) -> tuple[dict[str, object], ...]:
    catalog = CaptureAuditionCatalog.load(package)
    slots = (only_slot,) if only_slot else catalog.sound_slots
    unknown = set(slots) - set(catalog.sound_slots)
    if unknown:
        raise ValueError(f"unknown package Sound slots: {sorted(unknown)}")
    backend = Ddrum4EditBackend(executable)
    build_root = catalog.package_directory / "encoded-kit-v12-restored-cymbals"
    preview_root = catalog.package_directory / "codec-preview" / "kit-v12-restored-cymbals"
    build_root.mkdir(exist_ok=True)
    preview_root.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, object]] = []
    for slot in slots:
        print(f"[{len(reports) + 1}/{len(slots)}] {slot}: preparing and encoding", flush=True)
        report = build_sound(
            catalog, backend, slot=slot, template=template,
            build_root=build_root, preview_root=preview_root,
        )
        reports.append(report)
        print(
            f"  {report['sound_id']}: {len(report['layers'])} Layers, "
            f"{report['encoded_blocks']} blocks, {report['encoded_bytes']} bytes",
            flush=True,
        )
    summary = {
        "kind": "ddrum4-audition-kit/v1",
        "library": catalog.library_name,
        "sound_count": len(reports),
        "encoded_blocks": sum(int(report["encoded_blocks"]) for report in reports),
        "encoded_bytes": sum(int(report["encoded_bytes"]) for report in reports),
        "sounds": reports,
        "hardware_io": "disabled",
    }
    (build_root / "kit-build.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return tuple(reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build all local DDrum4 audition Sounds from a capture package")
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--ddrum4edit", type=Path)
    parser.add_argument("--slot")
    args = parser.parse_args(argv)
    executable = args.ddrum4edit or discover().ddrum4edit
    if executable is None:
        parser.error("ddrum4edit is not installed")
    build_kit(args.package, template=args.template, executable=executable, only_slot=args.slot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
