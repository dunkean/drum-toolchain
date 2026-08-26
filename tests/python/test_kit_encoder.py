from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ddrum4_bank.auditioner import AuditionEntry, CaptureAuditionCatalog
from ddrum4_bank.kit_encoder import PlannedKitLayer, _layer_rows, _quality_profile, _variation_masks, plan_sound_layers


def _entry(note_p: int, instrument: str, velocity: int, round_robin: int = 1) -> AuditionEntry:
    name = f"{instrument}__head__v{velocity:03d}__rr{round_robin:02d}_raw.wav"
    return AuditionEntry(
        instrument, instrument, "head", f"kick.{instrument}.head", "S01 KICK",
        note_p - 1, note_p, None, velocity, round_robin, name, Path(name),
    )


def _kick_entries() -> tuple[AuditionEntry, ...]:
    acoustic = tuple(
        _entry(1, "kick_metalcore", velocity, round_robin)
        for velocity in (20, 44, 68, 92, 124)
        for round_robin in (1, 2)
    )
    electronic = tuple(
        _entry(note_p, instrument, 104)
        for note_p, instrument in (
            (3, "kick_dnb"), (4, "kick_industrial"),
            (5, "kick_trap"), (6, "kick_sub"),
        )
    )
    return acoustic + electronic


def _electronic_tom_entry() -> AuditionEntry:
    return AuditionEntry(
        "electronic_tom", "electronic_tom", "low", "perc.electronic_tom.low", "S10 PERC",
        54, 7, None, 104, 1, "electronic_tom__low__v104__rr01_raw.wav",
        Path("electronic_tom__low__v104__rr01_raw.wav"),
    )


class KitEncoderTests(unittest.TestCase):
    def test_snare_sleep_token_variation_has_an_audible_decay_target(self) -> None:
        from ddrum4_bank.capture_package import _SOUND_VARIATIONS
        sleep_token = _SOUND_VARIATIONS["S02 SNARE"][2]
        self.assertEqual(sleep_token[0], "Sleep Token")
        self.assertEqual(sleep_token[2]["decay_percent"], 200)

    def test_codec_profile_preserves_unfiltered_attacks_without_input_fade(self) -> None:
        cymbal = _quality_profile("S08 CYMBAL1")
        kick = _quality_profile("S01 KICK")
        self.assertIsNone(cymbal.lowpass_hz)
        self.assertIsNone(cymbal.highpass_hz)
        self.assertEqual(cymbal.fade_in_ms, 0.0)
        self.assertEqual(cymbal.normalize_dbfs, -2.0)
        self.assertIsNone(kick.highpass_hz)
        self.assertIsNone(kick.lowpass_hz)
        self.assertEqual(kick.fade_in_ms, 0.0)

    def test_sparse_architecture_keeps_reserved_layer_numbers_empty(self) -> None:
        layers = (
            PlannedKitLayer(1, 1, "tom", "head", 20, 1, "soft.wav"),
            PlannedKitLayer(2, 1, "tom", "head", 124, 1, "hard.wav"),
            PlannedKitLayer(9, 7, "electronic", "head", 104, 1, "electronic.wav"),
            PlannedKitLayer(10, 8, "industrial", "head", 104, 1, "industrial.wav"),
        )
        rows = [[int(value, 16) for value in row.split()] for row in _layer_rows(layers, (0, 1, 2, 3))]
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(value == 0 for row in rows[2:8] for value in row))
        self.assertEqual(rows[8][0], 2)
        self.assertEqual(rows[9][0], 3)

    def test_kick_plan_keeps_two_acoustic_velocities_and_one_electronic_tom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = CaptureAuditionCatalog(
                Path(temporary), Path(temporary), _kick_entries() + (_electronic_tom_entry(),),
            )
            layers = plan_sound_layers(catalog, "S01 KICK")
            self.assertEqual(len(layers), 4)
            self.assertEqual([layer.velocity for layer in layers[:2]], [84, 124])
            self.assertEqual([layer.note_p for layer in layers[3:]], [5])
            self.assertEqual(layers[3].instrument, "electronic_tom")
            self.assertEqual(layers[3].velocity, 104)
            rows = [[int(value, 16) for value in row.split()] for row in _layer_rows(layers)]
            self.assertEqual(rows[0][36:45], [9, 0, 6, 0, 4, 99, 50, 0, 4])
            for velocity_step in range(8):
                self.assertEqual(sum(rows[index][4 + velocity_step] > 0 for index in range(2)), 1)

    def test_kick_variations_select_their_captured_positions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = CaptureAuditionCatalog(
                Path(temporary), Path(temporary), _kick_entries() + (_electronic_tom_entry(),),
                variation_names={"S01 KICK": {1: "Metalcore", 2: "Sleep", 3: "Electronic Tom"}},
            )
            layers = plan_sound_layers(catalog, "S01 KICK")
            masks = _variation_masks(catalog, "S01 KICK", layers)
            enabled_positions = [
                {layer.note_p for layer, enabled in zip(layers, mask) if enabled}
                for mask in masks
            ]
            self.assertEqual(enabled_positions, [{1, 2}, {1, 2}, {5}])


if __name__ == "__main__":
    unittest.main()
