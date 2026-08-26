"""Offline DDrum4 candidate packages derived from a neutral capture library.

The package deliberately keeps the complete SD3 capture set outside of the
small DDrum4 candidate.  It gives the operator an audition catalogue and a
declared return-note plan before any destructive or MIDI-facing operation is
considered.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable

import yaml

from drum_sampler.library import SampleLibrary, SampleTake


@dataclass(frozen=True)
class CaptureRoute:
    """One captured SD3 articulation and its intended DDrum4 destination."""

    instrument: str
    articulation: str
    logical_target: str
    sound_slot: str
    return_note: int
    note_p: int
    variation: str | None = None
    ddrum4_status: str = "candidate"
    required_in_capture: bool = True
    display_name: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.instrument, self.articulation


# This table transcribes the V1 destination blocks in architecture §37 and
# docs/SD3_MEGAKIT_V1_CAPTURE_LIST.md.  It is an offline simulation plan, not
# an assertion that the listed Sound IDs have been reserved in a module.
CAPTURE_ROUTES: tuple[CaptureRoute, ...] = (
    CaptureRoute("kick_metalcore", "head", "kick.metalcore", "S01 KICK", 0, 1, "P1 acoustic"),
    CaptureRoute("kick_dnb", "head", "kick.dnb", "S01 KICK", 2, 3, "P3 DnB"),
    CaptureRoute("kick_industrial", "head", "kick.industrial", "S01 KICK", 3, 4, "P4 industrial"),
    CaptureRoute("kick_trap", "head", "kick.trap", "S01 KICK", 4, 5, "P5 808/trap"),
    CaptureRoute("kick_sub", "head", "kick.sub", "S01 KICK", 5, 6, "P6 sub/body"),
    CaptureRoute("snare_metalcore", "center", "snare.metalcore.center", "S02 SNARE", 8, 1, "P1 center"),
    CaptureRoute("snare_metalcore", "mid", "snare.metalcore.mid", "S02 SNARE", 11, 4, "P4 mid"),
    CaptureRoute(
        "snare_metalcore", "edge", "snare.metalcore.edge", "S02 SNARE", 12, 5,
        "P5 edge / SD3 A0 (MIDI 33)", "candidate", False,
    ),
    CaptureRoute(
        "snare_metalcore", "edge_variant_g1", "snare.metalcore.edge", "S02 SNARE", 12, 5,
        "P5 edge / SD3 G1 candidate", "recapture-required", False,
    ),
    CaptureRoute(
        "snare_metalcore", "edge_variant_d1", "snare.metalcore.edge", "S02 SNARE", 12, 5,
        "P5 edge / SD3 D1 candidate", "recapture-required", False,
    ),
    CaptureRoute("snare_metalcore", "rimshot", "snare.metalcore.rimshot", "S03 RIM", 16, 1, "P1 rimshot"),
    CaptureRoute("snare_metalcore", "cross_stick", "snare.metalcore.cross_stick", "S03 RIM", 18, 3, "P3 cross-stick"),
    CaptureRoute("tom_1", "head", "tom.1", "S04 TOMS", 24, 1, "P1 tom 1"),
    CaptureRoute("tom_2", "head", "tom.2", "S04 TOMS", 25, 2, "P2 tom 2"),
    CaptureRoute("tom_3", "head", "tom.3", "S04 TOMS", 26, 3, "P3 tom 3"),
    CaptureRoute("tom_4", "head", "tom.4", "S05 FLEX", 32, 1, "P1 tom 4"),
    CaptureRoute("snare_low_trap", "head", "snare.electronic.dnb", "S05 FLEX", 38, 7, "P7 DnB/electro"),
    CaptureRoute("snare_trap", "head", "snare.electronic.trap", "S05 FLEX", 39, 8, "P8 industrial/trap"),
    CaptureRoute("hi_hat", "tip_tight", "hihat.tip.tight", "S06 HI-HAT", 72, 1, "P1 tight"),
    CaptureRoute("hi_hat", "tip_closed", "hihat.tip.closed", "S06 HI-HAT", 72, 1, "P1 closed alias"),
    CaptureRoute("hi_hat", "tip_loose", "hihat.tip.loose", "S06 HI-HAT", 73, 2, "P2 barely open"),
    CaptureRoute("hi_hat", "tip_quarter_open", "hihat.tip.quarter_open", "S06 HI-HAT", 74, 3, "P3 quarter open"),
    CaptureRoute("hi_hat", "tip_half_open", "hihat.tip.half_open", "S06 HI-HAT", 75, 4, "P4 half open"),
    CaptureRoute("hi_hat", "tip_three_quarter_open", "hihat.tip.three_quarter_open", "S06 HI-HAT", 76, 5, "P5 open alias"),
    CaptureRoute("hi_hat", "tip_open", "hihat.tip.open", "S06 HI-HAT", 76, 5, "P5 open"),
    CaptureRoute("hi_hat", "edge_tight", "hihat.edge.tight", "S07 HH EDGE", 40, 1, "P1 closed alias"),
    CaptureRoute("hi_hat", "edge_closed", "hihat.edge.closed", "S07 HH EDGE", 40, 1, "P1 closed"),
    CaptureRoute("hi_hat", "edge_loose", "hihat.edge.loose", "S07 HH EDGE", 41, 2, "P2 quarter alias"),
    CaptureRoute("hi_hat", "edge_quarter_open", "hihat.edge.quarter_open", "S07 HH EDGE", 41, 2, "P2 quarter open"),
    CaptureRoute("hi_hat", "edge_half_open", "hihat.edge.half_open", "S07 HH EDGE", 42, 3, "P3 half open"),
    CaptureRoute("hi_hat", "edge_three_quarter_open", "hihat.edge.three_quarter_open", "S07 HH EDGE", 43, 4, "P4 open alias"),
    CaptureRoute("hi_hat", "edge_open", "hihat.edge.open", "S07 HH EDGE", 43, 4, "P4 open"),
    CaptureRoute("hi_hat", "pedal_close", "hihat.pedal.close", "S07 HH EDGE", 44, 5, "P5 pedal close"),
    CaptureRoute("hi_hat", "pedal_splash", "hihat.pedal.splash", "S07 HH EDGE", 45, 6, "P6 pedal splash"),
    # The former Stack trigger is now an alias of the existing bow-open
    # hi-hat position. It consumes no PERC sample or extra DDrum4 Layer.
    CaptureRoute("stack", "hit", "hihat.tip.open.alias", "S06 HI-HAT", 76, 5, "P5 open bow trigger alias", "candidate", True, "Hi-hat open alias"),
    CaptureRoute("clap", "main", "perc.clap", "S10 PERC", 49, 2, "P2 clap"),
    CaptureRoute("electronic_hi_hat", "closed", "perc.electronic_hihat.closed", "S10 PERC", 50, 3, "P3 electronic hat closed"),
    CaptureRoute("electronic_hi_hat", "open", "perc.electronic_hihat.open", "S10 PERC", 51, 4, "P4 electronic hat open"),
    CaptureRoute("electronic_rim", "click", "perc.electronic_rim", "S10 PERC", 52, 5, "P5 rim click"),
    CaptureRoute("metallic_hit", "hit", "perc.metallic_hit", "S10 PERC", 53, 6, "P6 metallic hit"),
    CaptureRoute("electronic_tom", "low", "perc.electronic_tom", "S10 PERC", 54, 7, "P7 low e-tom"),
    CaptureRoute("cowbell", "hit", "perc.cowbell", "S10 PERC", 54, 7, "P7 cowbell variation"),
    CaptureRoute("glitch_noise", "hit", "perc.glitch", "S10 PERC", 55, 8, "P8 glitch"),
    CaptureRoute("woodblock", "hit", "perc.woodblock", "S10 PERC", 55, 8, "P8 woodblock variation"),
    CaptureRoute("crash_1", "bow", "cymbal.crash1.bow", "S08 CYMBAL1", 56, 1, "P1 crash 1"),
    CaptureRoute("splash", "hit", "cymbal.splash", "S08 CYMBAL1", 58, 3, "P3 shared splash"),
    CaptureRoute("china_1", "edge", "cymbal.china1.edge", "S08 CYMBAL1", 59, 4, "P4 shared china"),
    CaptureRoute("china_2", "edge", "cymbal.china2.edge", "S08 CYMBAL1", 59, 4, "P4 shared china variation"),
    CaptureRoute(
        "crash_ride", "edge", "cymbal.crash3.edge", "S08 CYMBAL1", 61, 6,
        "P6 Crash3 edge", display_name="Crash3",
    ),
    CaptureRoute("crash_2", "bow", "cymbal.crash2.bow", "S09 CYMBAL2", 64, 1, "P1 crash 2"),
    CaptureRoute("ride", "bow", "cymbal.ride.bow", "S09 CYMBAL2", 66, 3, "P3 ride bow"),
    CaptureRoute("ride", "bell", "cymbal.ride.bell", "S09 CYMBAL2", 67, 4, "P4 ride bell"),
)

# Captures are immutable evidence, while the DDrum4 kit is deliberately a
# curated subset. The owner excluded the SD3 ride-edge/punch articulation:
# retain it in the neutral library but never expose it as a module note or a
# designer-preview candidate.
EXCLUDED_CAPTURE_KEYS: frozenset[tuple[str, str]] = frozenset({("ride", "punch")})

# The c1 edge capture was made from the wrong SD3 note and is a sidestick.
# Preserve it in the capture library as evidence, but do not accidentally
# audition or package it as the requested A0 snare edge.  A later capture
# library may use the normal ``snare_metalcore/edge`` route and will be used.
KNOWN_INVALID_CAPTURE_KEYS: dict[str, frozenset[tuple[str, str]]] = {
    "kit-metalcore-4-hd-c1": frozenset({("snare_metalcore", "edge")}),
}


@dataclass(frozen=True)
class CandidateLayer:
    source: str
    raw_file: str
    velocity: int
    repetition: int
    sha256: str | None

    def to_matrix_document(self, audio_root: Path, provenance: str) -> dict[str, object]:
        return {
            # The package only references the large immutable capture library.
            # An absolute path lets Control Center's intentionally simple
            # selected-resource matrix inspect the actual source without a
            # copy or a special cross-directory resolver.
            "wav": str((audio_root / self.raw_file).resolve()),
            "source": self.source,
            "status": "raw-candidate",
            "provenance": provenance,
        }


def _captured(library: SampleLibrary, instrument: str, articulation: str) -> list[SampleTake]:
    return [
        take for take in library.takes
        if take.status == "captured" and take.instrument == instrument and take.articulation == articulation
    ]


def _representative(
    library: SampleLibrary, instrument: str, articulation: str, target_velocity: int
) -> CandidateLayer:
    takes = _captured(library, instrument, articulation)
    if not takes:
        raise ValueError(f"missing captured source {instrument}.{articulation}")
    available = sorted({take.velocity for take in takes})
    closest = min(available, key=lambda value: (abs(value - target_velocity), -value))
    choices = [take for take in takes if take.velocity == closest]
    selected = sorted(
        choices,
        key=lambda take: (
            -(take.peak_dbfs if take.peak_dbfs is not None else float("-inf")),
            take.repetition,
            take.raw_file,
        ),
    )[0]
    return CandidateLayer(
        source=f"{instrument}/{articulation}/v{selected.velocity:03d}/rr{selected.repetition:02d}",
        raw_file=selected.raw_file,
        velocity=selected.velocity,
        repetition=selected.repetition,
        sha256=selected.sha256,
    )


def _layers(library: SampleLibrary, source: tuple[str, str], velocities: Iterable[int]) -> list[CandidateLayer]:
    return [_representative(library, source[0], source[1], velocity) for velocity in velocities]


def _candidate_matrix(library: SampleLibrary, audio_root: Path) -> list[dict[str, object]]:
    """Return the ten-channel audition candidate without fabricating Sound IDs."""
    full = (20, 36, 52, 68, 84, 104, 124)
    hard = (104,)
    percussion_sources = (
        ("stack", "hit"), ("clap", "main"), ("electronic_hi_hat", "closed"),
        ("electronic_hi_hat", "open"), ("electronic_rim", "click"),
        ("metallic_hit", "hit"), ("electronic_tom", "low"), ("cowbell", "hit"),
        ("glitch_noise", "hit"), ("woodblock", "hit"),
    )
    candidates = (
        ("KICK — base acoustic", "kick_metalcore", _layers(library, ("kick_metalcore", "head"), full)),
        ("SNARE — base center", "snare_metalcore", _layers(library, ("snare_metalcore", "center"), full)),
        ("RIM — rimshot/cross-stick", "snare_metalcore", _layers(library, ("snare_metalcore", "rimshot"), (20, 124)) + _layers(library, ("snare_metalcore", "cross_stick"), (124,))),
        ("TOM HIGH — tom 1", "tom_1", _layers(library, ("tom_1", "head"), full)),
        ("TOM MID — tom 2", "tom_2", _layers(library, ("tom_2", "head"), full)),
        ("TOM LOW — tom 3", "tom_3", _layers(library, ("tom_3", "head"), full)),
        ("PERC — V1 variations", "percussion", [_representative(library, *source, 104) for source in percussion_sources]),
        ("CYMB 1 — crash 1 + HH edge", "crash_1", _layers(library, ("crash_1", "bow"), full) + [_representative(library, "hi_hat", articulation, 104) for articulation in ("edge_closed", "edge_quarter_open", "edge_open")]),
        ("CYMB 2 — crash 2 + HH edge", "crash_2", _layers(library, ("crash_2", "bow"), full) + [_representative(library, "hi_hat", articulation, 104) for articulation in ("edge_tight", "edge_half_open", "edge_three_quarter_open")]),
        ("HI-HAT — bow/pedal flagship candidate", "hi_hat", [
            _representative(library, "hi_hat", "pedal_close", 104),
            _representative(library, "hi_hat", "tip_tight", 36), _representative(library, "hi_hat", "tip_tight", 104),
            _representative(library, "hi_hat", "tip_closed", 36), _representative(library, "hi_hat", "tip_closed", 104),
            _representative(library, "hi_hat", "tip_loose", 104), _representative(library, "hi_hat", "tip_quarter_open", 104),
            _representative(library, "hi_hat", "tip_half_open", 104), _representative(library, "hi_hat", "tip_open", 104),
            _representative(library, "hi_hat", "pedal_splash", 104),
        ]),
    )
    return [
        {
            "sound_id": f"UNRESERVED-{index:02d}",
            "role": role,
            "source": source,
            "status": "audition-required",
            "provenance": library.identifier,
            "layers": [layer.to_matrix_document(audio_root, library.identifier) for layer in layers],
        }
        for index, (role, source, layers) in enumerate(candidates, 1)
    ]


_SOUND_VARIATIONS: dict[str, tuple[tuple[str, str, dict[str, object]], ...]] = {
    "S01 KICK": (
        ("Metalcore", "Kick acoustique tight; P1 prioritaire.", {"pitch_semitones": 0.0}),
        ("Sleep Token", "Même source acoustique, body/sub et decay plus longs.", {"pitch_semitones": -0.5, "decay_percent": 120}),
        ("Electronic Tom", "Tom électronique low P5 : un seul layer de vélocité, sans WAV kick 808 dédié.", {}),
    ),
    "S02 SNARE": (
        ("Metalcore", "Snare principale tight/moderne.", {"pitch_semitones": 0.0, "decay_percent": 100}),
        ("Deftones-like", "Même banque S02, plus bas et plus long; pas une seconde snare en Flash.", {"pitch_semitones": -1.25, "decay_percent": 130, "eq": "mids/body (à mesurer)"}),
        ("Sleep Token", "Même banque S02, body plus profond et decay nettement prolongé.", {"pitch_semitones": -0.75, "decay_percent": 200, "eq": "low body (à mesurer)"}),
    ),
    "S03 RIM": (
        ("Metalcore / Metalcore", "Paire Rim A/B de base.", {}),
        ("Metalcore / Deftones-like", "Rim B dérivé de S02 sans samples dédiés.", {"pitch_semitones": -1.25}),
        ("Metalcore / Sleep-like", "Rim B dérivé de S02 sans samples dédiés.", {"pitch_semitones": -0.75}),
    ),
    "S04 TOMS": (
        ("Metalcore", "Tom medium et Floor 2 résidents; Rack 1 et Floor 1 sont leurs Layers pitchés.", {"pitch_semitones": 0.0, "decay_percent": 100}),
        ("Sleep", "Même banque compacte de toms, plus bas et plus long.", {"pitch_semitones": -1.0, "decay_percent": 120}),
        ("Deftones", "Même banque compacte de toms, plus ouverte.", {"pitch_semitones": -0.5, "decay_percent": 115}),
    ),
    "S05 FLEX": (
        ("DnB e-snare", "P7 électronique, un seul layer de vélocité.", {}),
        ("Industrial/Trap e-snare", "P8 électronique, un seul layer de vélocité.", {}),
    ),
    "S06 HI-HAT": (("Bow / pedal", "Ouvertures bow et pédale; la vélocité reste dynamique.", {}),),
    "S07 HH EDGE": (("Edge / pedal", "Ouvertures edge et pédale; la vélocité reste dynamique.", {}),),
    "S08 CYMBAL1": (
        ("Crash", "Crash1 naturel; Splash et China restent directement jouables.", {}),
        ("Crash High", "Même Crash1, Layers encodés à +3 st; aucun WAV supplémentaire.", {}),
        ("Crash Low", "Même Crash1, Layers encodés à -3 st; aucun WAV supplémentaire.", {}),
    ),
    "S09 CYMBAL2": (("Metalcore", "Ride bow et ride bell. Crash2, ride edge et punch volontairement absents.", {}),),
    "S10 PERC": (("Compact", "P7 cowbell et P8 woodblock; un layer par son.", {}),),
}


def _kit_design(library: SampleLibrary, unavailable_routes: list[dict[str, object]]) -> dict[str, object]:
    """Return the editable ten-Sound design behind the audition matrix."""
    routes_by_slot: dict[str, list[CaptureRoute]] = {}
    for route in CAPTURE_ROUTES:
        routes_by_slot.setdefault(route.sound_slot, []).append(route)
    unavailable_keys = {(str(route["instrument"]), str(route["articulation"])) for route in unavailable_routes}
    sounds: list[dict[str, object]] = []
    for slot in sorted(routes_by_slot, key=lambda item: int(item[1:3])):
        routes = routes_by_slot[slot]
        positions: list[dict[str, object]] = []
        for note_p in range(1, 9):
            at_position = [route for route in routes if route.note_p == note_p]
            if not at_position:
                continue
            positions.append({
                "note_p": note_p,
                "return_note": at_position[0].return_note,
                "sources": [
                    {
                        "instrument": route.instrument,
                        "articulation": route.articulation,
                        "variation_hint": route.variation,
                        "status": "recapture-required" if route.key in unavailable_keys else route.ddrum4_status,
                    }
                    for route in at_position
                ],
            })
        variations = _SOUND_VARIATIONS.get(slot, ())
        sounds.append({
            "slot": slot,
            "sound_id": "unreserved — preview-only until module inventory is verified",
            "positions": positions,
            "variations": [
                {"index": index, "name": name, "description": description, "model": model}
                for index, (name, description, model) in enumerate(variations, 1)
            ],
        })
    return {
        "kind": "ddrum4-kit-design/v1",
        "library": library.identifier,
        "status": "recapture-required" if unavailable_routes else "design-ready-for-codec-build",
        "hardware_io": "disabled",
        "sounds": sounds,
        "notes": [
            "Variations reuse resident source samples whenever possible; they do not budget separate Deftones/Sleep sample banks.",
            "Pitch values use documented DDrum4 layer-pitch semitones. Decay/EQ directions require hardware-render comparison before being called exact.",
            "Ride edge/punch is intentionally absent from S09 and from every variation.",
        ],
    }


def _catalog(library: SampleLibrary) -> list[dict[str, object]]:
    routes = {route.key: route for route in CAPTURE_ROUTES}
    invalid_keys = KNOWN_INVALID_CAPTURE_KEYS.get(library.identifier, frozenset())
    excluded_keys = EXCLUDED_CAPTURE_KEYS | invalid_keys
    captured_keys = {
        (take.instrument, take.articulation)
        for take in library.takes
        if take.status == "captured" and (take.instrument, take.articulation) not in excluded_keys
    }
    unknown = sorted(captured_keys - set(routes))
    if unknown:
        formatted = ", ".join(f"{instrument}.{articulation}" for instrument, articulation in unknown)
        raise ValueError(f"capture has no DDrum4 simulation route: {formatted}")
    required_routes = {route.key for route in CAPTURE_ROUTES if route.required_in_capture}
    missing = sorted(required_routes - captured_keys)
    if missing:
        formatted = ", ".join(f"{instrument}.{articulation}" for instrument, articulation in missing)
        raise ValueError(f"capture is missing required simulation routes: {formatted}")
    rows: list[dict[str, object]] = []
    for take in sorted(library.takes, key=lambda item: (item.instrument, item.articulation, item.velocity, item.repetition)):
        if take.status != "captured" or (take.instrument, take.articulation) in excluded_keys:
            continue
        route = routes[take.instrument, take.articulation]
        rows.append({
            "instrument": take.instrument, "articulation": take.articulation,
            "display_name": route.display_name or take.instrument,
            "logical_target": route.logical_target, "sound_slot": route.sound_slot,
            "return_note": route.return_note, "note_p": route.note_p,
            "variation": route.variation, "ddrum4_status": route.ddrum4_status,
            "velocity": take.velocity, "round_robin": take.repetition,
            "raw_file": take.raw_file, "sha256": take.sha256,
        })
    return rows


def _unavailable_routes(library: SampleLibrary) -> list[dict[str, object]]:
    """Return explicit unavailable module notes; never substitute a bad take."""
    captured_keys = {
        (take.instrument, take.articulation)
        for take in library.takes
        if take.status == "captured"
    }
    invalid_keys = KNOWN_INVALID_CAPTURE_KEYS.get(library.identifier, frozenset())
    unavailable: list[dict[str, object]] = []
    for route in CAPTURE_ROUTES:
        if route.key not in captured_keys or route.key in invalid_keys:
            unavailable.append({
                "instrument": route.instrument,
                "articulation": route.articulation,
                "logical_target": route.logical_target,
                "sound_slot": route.sound_slot,
                "return_note": route.return_note,
                "note_p": route.note_p,
                "variation": route.variation,
                "ddrum4_status": route.ddrum4_status,
                "reason": "corrected snare edge capture is pending (A0, with G1/D1 variants)",
            })
    return unavailable


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite package artefact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _playlist(entries: list[dict[str, object]], audio_root: Path) -> str:
    lines = ["#EXTM3U"]
    for entry in entries:
        source = (audio_root / str(entry["raw_file"])).resolve()
        lines.append(f"#EXTINF:-1,{entry['instrument']} / {entry['articulation']} / v{int(entry['velocity']):03d} / rr{int(entry['round_robin']):02d}")
        lines.append(str(source))
    return "\n".join(lines) + "\n"


def _readme(library: SampleLibrary, audio_root: Path, entry_count: int) -> str:
    return f"""# Kit Metalcore 4 HD — DDrum4 candidate package

This is an offline, non-destructive candidate generated from `{library.identifier}`.
It references the immutable source capture at `{audio_root}` and does **not**
copy its {entry_count} WAV takes, open a MIDI port, invoke `ddrum4edit`, or
write to the DDrum4.

## Audition first

- `audition/all-captures.m3u8` contains all captured variations.
- `audition/by-articulation/` contains one playlist per instrument/articulation.
- `audition/catalog.json` maps every raw WAV to the intended DDrum4 return
  note, Sound block, NOTE P and Variation. These are simulation candidates.
- `kit-design.json` makes the ten-Sound plan and its sample-reuse variations
  explicit, including any note that is awaiting a corrected capture.

Open a playlist explicitly in a local audio player, for example:

```powershell
Start-Process .\\audition\\by-articulation\\hi_hat__tip_open.m3u8
```

## Candidate bank

`ddrum4-kit-matrix.yaml` exposes the 10 Sound-channel candidate to the Control
Center. `UNRESERVED-xx` values are intentional placeholders: choose unused,
verified DDrum4 Sound IDs only after listening and after inspecting the module
inventory. Its raw layers are source candidates, not encoded DDrum4 samples.

The DDrum4 matrix is a compact subset. Cymbals, alternate kicks, flex snares,
and every raw round robin remain audible in the catalogue but cannot all be
claimed to fit the module until `ddrum4edit` output and isolated `MEM.LEFT`
measurements exist.

## Simulate a selection

```powershell
ddrum4-bank-builder simulate-capture-package . --instrument stack --articulation hit --velocity 104 --round-robin 2
```

The command only resolves the declared source WAV and target return note. The
source playback is the original SD3 capture, so it is not a bit-exact emulation
of DDrum4 resampling or its encoded playback.

## Preview a real encoded Sound in the desktop app

Open this package with `ddrum4-capture-auditioner` (or the supplied launcher),
select the target matrix cell, then choose **Décoder un Sound encodé…**.  Give
it the local `.mid` generated by `ddrum4edit` and the exact `.cfg` that built
it. The app runs `ddrum4edit -e -x` locally and plays its decoded WAVs. It
does not open a MIDI port or transfer a Sound. It reports its bounded model:
codec conversion is actual, while runtime pitch/gain/layer selection comes
from the config and DDrum4 EQ/filter response is not claimed as rendered
until compared with recorded module output.

## Before any transfer

1. Record listening decisions in `selection-state.json`.
2. Reserve real Sound IDs and build each selected Sound offline with
   `ddrum4edit`; attach its config, input/output hashes and block count.
3. Inspect a verified settings backup and the live `MEM.LEFT` value.
4. Transfer one Sound only with the bank-builder explicit confirmation flag.
"""


def create_capture_package(*, library_path: Path, audio_root: Path, output_directory: Path) -> dict[str, object]:
    """Write a compact package referencing an already captured local library."""
    if output_directory.exists():
        raise FileExistsError(f"refusing to reuse package directory: {output_directory}")
    library = SampleLibrary.read(library_path)
    if not audio_root.is_dir():
        raise FileNotFoundError(f"capture audio root not found: {audio_root}")
    catalog = _catalog(library)
    unavailable_routes = _unavailable_routes(library)
    design = _kit_design(library, unavailable_routes)
    missing_files = [entry["raw_file"] for entry in catalog if not (audio_root / str(entry["raw_file"])).is_file()]
    if missing_files:
        raise FileNotFoundError(f"capture package has missing raw WAVs (first: {missing_files[0]})")
    matrix = _candidate_matrix(library, audio_root)
    output_directory.mkdir(parents=True)
    matrix_document = {
        "kind": "ddrum4-kit-candidate-matrix/v1",
        "library": library.identifier,
        "source_audio_root": str(audio_root.resolve()),
        "status": "audition-required",
        "sounds": matrix,
    }
    _write_new(output_directory / "ddrum4-kit-matrix.yaml", yaml.safe_dump(matrix_document, sort_keys=False, allow_unicode=True))
    _write_new(output_directory / "kit-design.json", json.dumps(design, indent=2, sort_keys=True) + "\n")
    simulation = {
        "kind": "ddrum4-capture-routing-simulation/v1",
        "hardware_io": "disabled",
        "library": library.identifier,
        "source_audio_root": str(audio_root.resolve()),
        "capture_entries": catalog,
        "unavailable_routes": unavailable_routes,
        "notes": [
            "Return notes and NOTE P values are the documented V1 candidate map.",
            "Unavailable routes are omitted from audition and cannot be built or uploaded.",
            "UNRESERVED Sound IDs and module-memory facts are intentionally absent.",
        ],
    }
    _write_new(output_directory / "ddrum4-routing-simulation.json", json.dumps(simulation, indent=2, sort_keys=True) + "\n")
    _write_new(output_directory / "audition" / "catalog.json", json.dumps(catalog, indent=2, sort_keys=True) + "\n")
    _write_new(output_directory / "audition" / "all-captures.m3u8", _playlist(catalog, audio_root))
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for entry in catalog:
        grouped.setdefault((str(entry["instrument"]), str(entry["articulation"])), []).append(entry)
    for (instrument, articulation), entries in grouped.items():
        _write_new(output_directory / "audition" / "by-articulation" / f"{instrument}__{articulation}.m3u8", _playlist(entries, audio_root))
    selection = {
        "kind": "ddrum4-audition-selection-state/v1",
        "library": library.identifier,
        "status": "pending-listening",
        "decisions": [
            {"instrument": instrument, "articulation": articulation, "status": "pending"}
            for instrument, articulation in sorted(grouped)
        ],
        "hardware_measurements": {"reserved_sound_ids": "unknown", "encoded_blocks": "unknown", "mem_left_delta_blocks": "unknown"},
    }
    _write_new(output_directory / "selection-state.json", json.dumps(selection, indent=2, sort_keys=True) + "\n")
    _write_new(output_directory / "README.md", _readme(library, audio_root.resolve(), len(catalog)))
    inputs = {
        "library.json": sha256(library_path.read_bytes()).hexdigest(),
        "capture_entries": len(catalog),
        "unavailable_routes": len(unavailable_routes),
        "audio_root": str(audio_root.resolve()),
    }
    _write_new(output_directory / "package-inputs.json", json.dumps(inputs, indent=2, sort_keys=True) + "\n")
    return {
        "package": str(output_directory), "library": library.identifier,
        "captured_entries": len(catalog), "articulation_playlists": len(grouped),
        "matrix_sounds": len(matrix), "hardware_io": "disabled",
    }


def resolve_capture_package(
    package_directory: Path, *, instrument: str, articulation: str, velocity: int, round_robin: int | None = None,
) -> dict[str, object]:
    """Resolve one source take and its declared DDrum4 output without playing it."""
    if not 1 <= velocity <= 127:
        raise ValueError("velocity must be in 1..127")
    path = package_directory / "audition" / "catalog.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read package audition catalogue: {error}") from error
    if not isinstance(catalog, list):
        raise ValueError("package audition catalogue must be a list")
    candidates = [
        entry for entry in catalog if isinstance(entry, dict)
        and entry.get("instrument") == instrument and entry.get("articulation") == articulation
    ]
    if not candidates:
        raise ValueError(f"package has no captured {instrument}.{articulation} source")
    velocities = sorted({int(entry["velocity"]) for entry in candidates if isinstance(entry.get("velocity"), int)})
    selected_velocity = min(velocities, key=lambda value: (abs(value - velocity), -value))
    at_velocity = [entry for entry in candidates if entry["velocity"] == selected_velocity]
    if round_robin is None:
        selected = sorted(at_velocity, key=lambda entry: int(entry["round_robin"]))[0]
    else:
        selected = next((entry for entry in at_velocity if entry["round_robin"] == round_robin), None)
        if selected is None:
            available = ", ".join(str(entry["round_robin"]) for entry in sorted(at_velocity, key=lambda entry: int(entry["round_robin"])))
            raise ValueError(f"{instrument}.{articulation} at velocity {selected_velocity} has round robins: {available}")
    source_root = json.loads((package_directory / "ddrum4-routing-simulation.json").read_text(encoding="utf-8")).get("source_audio_root")
    if not isinstance(source_root, str):
        raise ValueError("package has no source_audio_root")
    source = Path(source_root) / str(selected["raw_file"])
    return {
        "kind": "ddrum4-capture-simulation-result/v1",
        "hardware_io": "disabled",
        "request": {"instrument": instrument, "articulation": articulation, "velocity": velocity, "round_robin": round_robin},
        "resolved_capture": {**selected, "audio_path": str(source)},
        "ddrum4": {
            "sound_slot": selected["sound_slot"], "return_note": selected["return_note"],
            "note_p": selected["note_p"], "variation": selected.get("variation"),
            "status": selected["ddrum4_status"],
        },
    }
