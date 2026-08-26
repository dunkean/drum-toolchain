from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ddrum4_bank.capture_package import CAPTURE_ROUTES, create_capture_package, resolve_capture_package
from ddrum4_bank.auditioner import CaptureAuditionCatalog
from drum_sampler.library import SampleLibrary, SampleTake


class CapturePackageTests(unittest.TestCase):
    def test_complete_capture_produces_offline_package_and_resolves_round_robin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "raw-wav"; audio.mkdir()
            takes: list[SampleTake] = []
            for route in CAPTURE_ROUTES:
                for repetition in (1, 2, 3):
                    filename = f"{route.instrument}__{route.articulation}__v104__rr{repetition:02d}_raw.wav"
                    (audio / filename).write_bytes(b"RIFF")
                    takes.append(SampleTake(
                        route.instrument, route.articulation, route.return_note, 10, 104, repetition,
                        filename, source="test capture", license_statement="test licence", status="captured",
                        sha256=f"{repetition:064x}", peak_dbfs=-12.0,
                    ))
            library_path = root / "library.json"
            SampleLibrary("fixture-capture", ("left", "right"), tuple(takes)).write(library_path)
            package = root / "package"
            result = create_capture_package(library_path=library_path, audio_root=audio, output_directory=package)
            self.assertEqual(result["captured_entries"], len(takes))
            self.assertEqual(result["matrix_sounds"], 10)
            self.assertTrue((package / "audition" / "all-captures.m3u8").is_file())
            self.assertTrue((package / "ddrum4-kit-matrix.yaml").is_file())
            design = json.loads((package / "kit-design.json").read_text(encoding="utf-8"))
            self.assertEqual(len(design["sounds"]), 10)
            audition_catalog = CaptureAuditionCatalog.load(package)
            self.assertEqual(len(audition_catalog.keys), len(CAPTURE_ROUTES))
            self.assertEqual(audition_catalog.resolve(("stack", "hit"), 100, 2).round_robin, 2)
            resolved = resolve_capture_package(
                package, instrument="stack", articulation="hit", velocity=100, round_robin=2,
            )
            self.assertEqual(resolved["ddrum4"]["return_note"], 76)
            self.assertEqual(resolved["resolved_capture"]["round_robin"], 2)
            self.assertTrue(str(resolved["resolved_capture"]["audio_path"]).endswith("rr02_raw.wav"))
            matrix = (package / "ddrum4-kit-matrix.yaml").read_text(encoding="utf-8")
            self.assertEqual(matrix.count("sound_id: UNRESERVED-"), 10)
            simulation = json.loads((package / "ddrum4-routing-simulation.json").read_text(encoding="utf-8"))
            self.assertEqual(simulation["hardware_io"], "disabled")

    def test_c1_excludes_ride_edge_and_the_known_bad_snare_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio = root / "raw-wav"; audio.mkdir()
            takes: list[SampleTake] = []
            for route in CAPTURE_ROUTES:
                if not route.required_in_capture:
                    continue
                filename = f"{route.instrument}__{route.articulation}__v104__rr01_raw.wav"
                (audio / filename).write_bytes(b"RIFF")
                takes.append(SampleTake(
                    route.instrument, route.articulation, route.return_note, 10, 104, 1,
                    filename, source="test capture", license_statement="test licence", status="captured",
                    sha256="1" * 64, peak_dbfs=-12.0,
                ))
            for instrument, articulation, note in (("snare_metalcore", "edge", 12), ("ride", "punch", 119)):
                filename = f"{instrument}__{articulation}__v104__rr01_raw.wav"
                (audio / filename).write_bytes(b"RIFF")
                takes.append(SampleTake(
                    instrument, articulation, note, 10, 104, 1,
                    filename, source="test capture", license_statement="test licence", status="captured",
                    sha256="1" * 64, peak_dbfs=-12.0,
                ))
            library_path = root / "library.json"
            SampleLibrary("kit-metalcore-4-hd-c1", ("left", "right"), tuple(takes)).write(library_path)
            package = root / "package"
            create_capture_package(library_path=library_path, audio_root=audio, output_directory=package)
            catalog = json.loads((package / "audition" / "catalog.json").read_text(encoding="utf-8"))
            keys = {(row["instrument"], row["articulation"]) for row in catalog}
            self.assertNotIn(("ride", "punch"), keys)
            self.assertNotIn(("snare_metalcore", "edge"), keys)
            simulation = json.loads((package / "ddrum4-routing-simulation.json").read_text(encoding="utf-8"))
            self.assertEqual(len(simulation["unavailable_routes"]), 3)
            design = json.loads((package / "kit-design.json").read_text(encoding="utf-8"))
            s09 = next(sound for sound in design["sounds"] if sound["slot"] == "S09 CYMBAL2")
            sources = [source for position in s09["positions"] for source in position["sources"]]
            self.assertNotIn(("ride", "punch"), {(source["instrument"], source["articulation"]) for source in sources})

    def test_resolution_rejects_unknown_round_robin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"; (package / "audition").mkdir(parents=True)
            (package / "audition" / "catalog.json").write_text(json.dumps([{
                "instrument": "stack", "articulation": "hit", "velocity": 104, "round_robin": 1,
                "raw_file": "stack.wav", "sound_slot": "S10 PERC", "return_note": 48,
                "note_p": 1, "variation": "P1", "ddrum4_status": "candidate",
            }]), encoding="utf-8")
            (package / "ddrum4-routing-simulation.json").write_text(json.dumps({"source_audio_root": str(root)}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "round robins: 1"):
                resolve_capture_package(package, instrument="stack", articulation="hit", velocity=104, round_robin=2)


if __name__ == "__main__":
    unittest.main()
