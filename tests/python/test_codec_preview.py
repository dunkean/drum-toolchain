from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from ddrum4_bank.codec_preview import active_layers, load_codec_preview, render_preview
from ddrum4_bank.auditioner import (
    CaptureAuditionCatalog, active_layers_for_position, discover_codec_attachments, encoded_layers,
    prepare_guarded_playback,
)


def _config() -> str:
    row_one = "00 00 00 00 FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
    row_two = "01 00 00 00 FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF 0C 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
    disabled = "00 00 00 00 00 00 00 00 00 00"
    return "\n".join((
        "-Begin-Layers-", f"L01 {row_one}", f"L02 {row_two}", "-End-Layers-",
        "-Begin-Variations-",
        "VL1 01 01 00 00 00 00 00 00 00 00",
        "VS1 00 01 00 00 00 00 00 00 00 00",
        "VL2 01 00 00 00 00 00 00 00 00 00",
        "VS2 " + disabled,
        "VLA " + disabled, "VSA " + disabled,
        "-End-Variations-",
        "-Begin-Sample-Files-", "S01 source-one.wav", "S02 source-two.wav", "-End-Sample-Files-",
        "-Begin-Sample-Name-", "TEST_001", "-End-Sample-Name-",
    )) + "\n"


class CodecPreviewTests(unittest.TestCase):
    def test_guarded_playback_hides_player_startup_without_touching_attack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "encoded.wav"
            output = root / "guarded.wav"
            attack = np.array([12000, -8000, 4000, 0], dtype=np.int16)
            wavfile.write(source, 44100, attack)
            prepare_guarded_playback(source, output, preroll_ms=250.0)
            rate, guarded = wavfile.read(output)
            self.assertEqual(rate, 44100)
            self.assertTrue(np.all(guarded[:11025] == 0))
            np.testing.assert_array_equal(guarded[11025:], attack)

    def test_parses_variation_and_renders_codec_decoded_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decoded = root / "decoded"; decoded.mkdir()
            wavfile.write(decoded / "TEST_001_s1.wav", 44100, np.full(4410, 2000, dtype=np.int16))
            wavfile.write(decoded / "TEST_001_s2.wav", 44100, np.full(4410, 2000, dtype=np.int16))
            config = root / "TEST_001.cfg"; config.write_text(_config(), encoding="utf-8")
            preview = load_codec_preview(config, decoded)
            self.assertEqual(preview.available_variations, (1, 2))
            self.assertEqual(preview.sample_file_names[:2], ("source-one.wav", "source-two.wav"))
            self.assertEqual(preview.layers[1].pitch_semitones, 12)
            self.assertEqual(tuple(layer.index for layer in encoded_layers(preview)), (1, 2))
            self.assertEqual(tuple(layer.index for layer in active_layers_for_position(preview, 1, 1)), (1, 2))
            # V1 explicitly sequences Layer 2, so its RR model selects only it.
            self.assertEqual(
                tuple(layer.index for layer in active_layers(preview, variation=1, velocity=100, note_p=1)),
                (2,),
            )
            rendered = render_preview(
                preview, root / "listen.wav", variation=1, velocity=100, note_p=1,
            )
            self.assertTrue(rendered.path.is_file())
            self.assertEqual(rendered.active_layers, (2,))
            rate, audio = wavfile.read(rendered.path)
            self.assertEqual(rate, 44100)
            # +12 semitones makes the decoded one-tenth-second source half as long.
            self.assertLess(len(audio), 3000)
            modelled = render_preview(
                preview, root / "modelled.wav", variation=2, velocity=100, note_p=1,
                variation_pitch_semitones=-12.0, decay_percent=130.0,
            )
            _, modelled_audio = wavfile.read(modelled.path)
            self.assertGreater(len(modelled_audio), 8000)
            self.assertIn("decay 130 %", modelled.mode)

    def test_rejects_empty_variation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decoded = root / "decoded"; decoded.mkdir()
            wavfile.write(decoded / "TEST_001_s1.wav", 44100, np.full(44, 2000, dtype=np.int16))
            wavfile.write(decoded / "TEST_001_s2.wav", 44100, np.full(44, 2000, dtype=np.int16))
            config = root / "TEST_001.cfg"; config.write_text(_config(), encoding="utf-8")
            preview = load_codec_preview(config, decoded)
            with self.assertRaisesRegex(ValueError, "V3 has no enabled"):
                active_layers(preview, variation=3, velocity=100, note_p=1)

    def test_prefers_ddrum4edit_layer_dsp_render_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decoded = root / "decoded"; decoded.mkdir()
            decoded_layers = root / "decoded-layers"; decoded_layers.mkdir()
            wavfile.write(decoded / "TEST_001_s1.wav", 44100, np.full(4410, 1000, dtype=np.int16))
            wavfile.write(decoded / "TEST_001_s2.wav", 44100, np.full(4410, 1000, dtype=np.int16))
            wavfile.write(decoded_layers / "TEST_001_s1_l1.wav", 44100, np.full(2205, 2000, dtype=np.int16))
            config = root / "TEST_001.cfg"; config.write_text(_config(), encoding="utf-8")
            preview = load_codec_preview(config, decoded, decoded_layer_directory=decoded_layers)
            self.assertEqual(preview.layer_samples[0], (decoded_layers / "TEST_001_s1_l1.wav").resolve())
            rendered = render_preview(preview, root / "dsp.wav", variation=2, velocity=100, note_p=1)
            _, audio = wavfile.read(rendered.path)
            self.assertEqual(len(audio), 2205)
            self.assertIn("DSP Layer ddrum4edit", rendered.mode)

    def test_discovers_package_codec_preview_by_explicit_sound_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"; package.mkdir()
            preview_root = package / "codec-preview" / "S01-KICK-01"
            decoded = preview_root / "decoded"; decoded.mkdir(parents=True)
            wavfile.write(decoded / "TEST_001_s1.wav", 44100, np.full(44, 2000, dtype=np.int16))
            wavfile.write(decoded / "TEST_001_s2.wav", 44100, np.full(44, 2000, dtype=np.int16))
            (preview_root / "TEST_001.cfg").write_text(_config(), encoding="utf-8")
            (preview_root / "codec-preview.json").write_text(
                '{"kind":"ddrum4-codec-preview/v1","sound_slot":"S01 KICK",'
                '"preview_config":"TEST_001.cfg","decoded_directory":"decoded",'
                '"encoded_blocks":12,"source_sound_bytes":12345}',
                encoding="utf-8",
            )
            catalog = CaptureAuditionCatalog(package, root, (), design_slots=("S01 KICK",))
            attachments, errors = discover_codec_attachments(catalog)
            self.assertEqual(errors, ())
            self.assertEqual(attachments["S01 KICK"].preview.sound_name, "TEST_001")
            self.assertEqual(attachments["S01 KICK"].encoded_bytes, 12345)
            self.assertEqual(attachments["S01 KICK"].variation_parameter_bytes, 20)


if __name__ == "__main__":
    unittest.main()
