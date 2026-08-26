"""Generate the reproducible HD source-capture session for Kit_metalcore_4.

The session records each distinct source articulation in the current V1 preset.
Logical aliases used later for DDrum4 variations are not recorded twice.
"""
from __future__ import annotations

from pathlib import Path
import sys

from drum_sampler.session import CaptureRequest, CaptureSessionPlan


VELOCITIES_ACOUSTIC = (20, 36, 52, 68, 84, 104, 124)
VELOCITIES_ELECTRONIC = (24, 44, 64, 84, 104, 124)


def request(
    instrument: str, articulation: str, note: int, *, electronic: bool = False,
    controllers: tuple[tuple[int, int], ...] = (),
) -> CaptureRequest:
    return CaptureRequest(
        instrument=instrument,
        articulation=articulation,
        note=note,
        velocities=VELOCITIES_ELECTRONIC if electronic else VELOCITIES_ACOUSTIC,
        repetitions=2 if electronic else 3,
        channel=10,
        controllers=controllers,
    )


def build_session() -> CaptureSessionPlan:
    rows = [
        request("kick_metalcore", "head", 24),
        request("kick_dnb", "head", 26, electronic=True),
        request("kick_industrial", "head", 27, electronic=True),
        request("kick_trap", "head", 28, electronic=True),
        request("kick_sub", "head", 29, electronic=True),
        request("snare_metalcore", "center", 32),
        request("snare_metalcore", "mid", 33),
        request("snare_metalcore", "edge", 34),
        request("snare_metalcore", "rimshot", 35),
        request("snare_metalcore", "cross_stick", 36),
        request("snare_low_trap", "head", 47, electronic=True),
        request("snare_trap", "head", 48, electronic=True),
        request("clap", "main", 50, electronic=True),
        request("electronic_rim", "click", 51, electronic=True),
        request("tom_1", "head", 56),
        request("tom_2", "head", 57),
        request("tom_3", "head", 58),
        request("tom_4", "head", 59),
    ]
    for articulation, cc4 in (
        ("closed", 127), ("tight", 110), ("loose", 92),
        ("quarter_open", 72), ("half_open", 54),
        ("three_quarter_open", 30), ("open", 0),
    ):
        rows.append(request("hi_hat", f"tip_{articulation}", 64, controllers=((4, cc4),)))
        rows.append(request("hi_hat", f"edge_{articulation}", 65, controllers=((4, cc4),)))
    rows.extend((
        request("hi_hat", "pedal_close", 66),
        request("hi_hat", "pedal_splash", 67),
        request("electronic_hi_hat", "closed", 68, electronic=True),
        request("electronic_hi_hat", "open", 69, electronic=True),
        request("crash_1", "bow", 72),
        request("crash_2", "bow", 74),
        request("crash_ride", "edge", 76),
        request("splash", "hit", 77),
        request("china_1", "edge", 79),
        request("china_2", "edge", 81),
        request("ride", "bow", 83),
        request("ride", "bell", 84),
        request("stack", "hit", 85),
        request("metallic_hit", "hit", 88, electronic=True),
        request("glitch_noise", "hit", 89, electronic=True),
        request("electronic_tom", "low", 90, electronic=True),
        request("cowbell", "hit", 92, electronic=True),
        request("woodblock", "hit", 93, electronic=True),
        request("ride", "punch", 119),
    ))
    return CaptureSessionPlan(
        midi_output="out_WORLDE 2",
        audio_input="loopback:OUT 3-4 (BEHRINGER UMC 404HD 192k)",
        channels=("left", "right"),
        requests=tuple(rows),
        sample_rate=48000,
        preroll_ms=200,
        # Hold every MIDI note through the full recording window. Releasing
        # after 100 ms can choke instruments whose SD3 articulation honours
        # Note Off, especially cymbals and sustained electronic sources.
        gate_ms=10_500,
        tail_ms=0,
        cooldown_ms=350,
    )


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(
        "profiles/capture/kit-metalcore-4-hd-full-c1.json"
    )
    session = build_session()
    session.write(output)
    print(f"wrote {len(session.takes())} takes to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
