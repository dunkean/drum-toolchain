from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ddrum4_bank.sound_config import materialize_sound_config


def _template() -> str:
    rows = "\n".join(
        f"V{kind}{index:X} " + "00 00 00 00 00 00 00 00 00 00"
        for index in range(1, 11) for kind in ("L", "S")
    )
    return "\n".join((
        "-Begin-Layers-", "L01 " + "00 " * 50, "-End-Layers-",
        "-Begin-Variations-", rows, "-End-Variations-",
        "-Begin-Sample-Files-", "S01 old.wav", "-End-Sample-Files-",
        "-Begin-Sample-Name-", "OLD_001", "-End-Sample-Name-",
        "-Begin-Sound-File-Out-", "old.mid", "-End-Sound-File-Out-",
    )) + "\n"


class SoundConfigVariationTests(unittest.TestCase):
    def test_materializes_layer_and_sequence_masks_for_each_variation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template.cfg"; template.write_text(_template(), encoding="utf-8")
            output = root / "preview.cfg"
            row = "00 00 00 00 FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
            materialize_sound_config(
                template, output, sound_name="TEST_001", output_sound=root / "TEST_001.mid",
                sample_files=("one.wav", "two.wav"), layer_rows=(row, row),
                variation_layers=((True, False), (False, True)),
                variation_sequences=((False, True), (False, False)),
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn("VL1 01 00 00 00 00 00 00 00 00 00", text)
            self.assertIn("VS1 00 01 00 00 00 00 00 00 00 00", text)
            self.assertIn("VL2 00 01 00 00 00 00 00 00 00 00", text)
            self.assertIn("VS2 00 00 00 00 00 00 00 00 00 00", text)


if __name__ == "__main__":
    unittest.main()
