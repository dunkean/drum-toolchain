from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from drum_sampler.audio import QualityProfile
from drum_sampler.library import SampleLibrary, SampleTake
from drum_sampler.offline import (apply_captured_drumgizmo_composites, audit_drumgizmo_composites, capture_drumgizmo_composites, compose_drumgizmo_layers, drumgizmo_capture_note_overrides, drumgizmo_instrument_groups, drumgizmo_note_overrides, expand_shared_variations, merge_library_files,
                                  prepare_selected_takes, run_offline_recipe, validate_drumgizmo_kit,
                                  verify_drumgizmo_kit, resolved_drumgizmo_note_overrides)
from drum_sampler.offline import validate_drumgizmo_composite_report, write_drumgizmo_validation_report
from drum_sampler.session import CaptureRequest, CaptureSessionPlan
from drum_sampler.cli import _validate_megakit_export_inputs
from drum_sampler.cli import main as sampler_main
from drum_sampler.drumgizmo_probe import analyze_probe, prepare_probe


class OfflineSamplerTests(unittest.TestCase):
    def test_drumgizmo_aftertouch_probe_is_addressed_and_audio_proven(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "midimap.xml").write_text(
                '<midimap><map note="72" instr="crash1__bow" /></midimap>', encoding="utf-8",
            )
            prepared = prepare_probe(root / "midimap.xml", root, instrument="crash1__bow")
            self.assertEqual(prepared["note"], 72)
            sample_rate = 48000
            time_axis = np.arange(int(0.8 * sample_rate)) / sample_rate
            base = (0.2 * np.exp(-3.0 * time_axis) * np.sin(2 * np.pi * 800 * time_axis)).astype(np.float32)
            choked = base.copy()
            choke_start = int(0.25 * sample_rate)
            choked[choke_start:] *= np.linspace(1.0, 0.001, len(choked) - choke_start, dtype=np.float32)
            wavfile.write(root / "controlleft-0.wav", sample_rate, base)
            wavfile.write(root / "chokeleft-0.wav", sample_rate, choked)
            report = analyze_probe(root, root / "proof.json")
            self.assertEqual(report["status"], "pass")
            self.assertLess(report["measurements"]["tail_ratio_db"], -12.0)

    def test_direct_megakit_export_rejects_a_partial_library_before_xml_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); reports = root / "reports"; reports.mkdir()
            plan = root / "plan.yaml"; plan.write_text("kind: sd3-megakit-plan\n", encoding="utf-8")
            preset = root / "preset.sd3p"; preset.write_bytes(b"preset")
            session = root / "capture-session.json"; session.write_text("{}", encoding="utf-8")
            take = SampleTake("kick", "head", 36, 10, 100, 1, "kick.wav", status="planned")
            library = SampleLibrary("partial", ("left",), (take,))
            library_path = root / "library.json"; library.write(library_path)
            (root / "campaign.json").write_text(json.dumps({
                "expected_take_count": 1,
                "capture_session_sha256": hashlib.sha256(session.read_bytes()).hexdigest(),
                "megakit_plan_file": str(plan),
                "sd3_preset_file": str(preset),
                "sd3_preset_sha256": hashlib.sha256(preset.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            (reports / "quality.json").write_text(json.dumps({
                "kind": "capture-quality-report",
                "library_sha256": hashlib.sha256(library_path.read_bytes()).hexdigest(),
                "session_sha256": hashlib.sha256(session.read_bytes()).hexdigest(),
                "summary": {"accepted": 1, "rejected": 0, "missing": 0,
                            "round_robin_duplicate_cells": 0},
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "complete"):
                _validate_megakit_export_inputs(
                    library, library_path=library_path, audio_root=root,
                    plan_path=plan, output_directory=root / "drumgizmo-kit",
                )
            with self.assertRaisesRegex(ValueError, "--megakit-plan"):
                sampler_main([
                    "export-drumgizmo", "--library", str(library_path),
                    "--audio-root", str(root), "--output-directory", str(root / "kit"),
                ])

    def test_simultaneous_drumgizmo_composite_capture_is_resumable_and_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "plan.yaml"
            plan.write_text(
                "kind: sd3-megakit-plan\n"
                "drumgizmo_composites:\n"
                "  - target: snare1.deftones\n"
                "    sources: [snare1.deftones, snare_layer.sd02, snare_layer.sd30]\n",
                encoding="utf-8",
            )
            requests = (
                CaptureRequest("snare1", "deftones", 37, (40, 80), 2, channel=10),
                CaptureRequest("snare_layer", "sd02", 100, (40, 80), 2, channel=10),
                CaptureRequest("snare_layer", "sd30", 101, (40, 80), 2, channel=10),
            )
            session = CaptureSessionPlan(
                "virtual", "loopback:output", ("left", "right"), requests,
                sample_rate=48000, tail_ms=100,
            )
            calls = []

            def fake_capture(**kwargs: object) -> Path:
                calls.append((kwargs["notes"], kwargs["velocity"]))
                output = kwargs["output"]
                assert isinstance(output, Path)
                wavfile.write(output, 48000, np.full((9600, 2), 0.25, dtype=np.float32))
                return output

            output = root / "composite"
            with patch("drum_sampler.offline.time.sleep", create=True):
                first = capture_drumgizmo_composites(
                    session, plan_path=plan, output_root=output, capture=fake_capture,
                )
                second = capture_drumgizmo_composites(
                    session, plan_path=plan, output_root=output, capture=fake_capture,
                )
            self.assertEqual(len(first), 4)
            self.assertEqual(second, ())
            self.assertEqual(calls, [((37, 100, 101), 40), ((37, 100, 101), 40),
                                     ((37, 100, 101), 80), ((37, 100, 101), 80)])
            audit = audit_drumgizmo_composites(session, plan_path=plan, composite_root=output)
            self.assertEqual(audit["summary"], {
                "accepted": 4, "rejected": 0, "missing": 0,
                "round_robin_duplicate_cells": 2,
            })
            session_path = root / "session.json"; session.write(session_path)
            audit["session_sha256"] = hashlib.sha256(session_path.read_bytes()).hexdigest()
            report_path = root / "composite-quality.json"
            report_path.write_text(json.dumps(audit), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "failed"):
                validate_drumgizmo_composite_report(
                    report_path, session_path=session_path, composite_root=output, plan_path=plan,
                )
            # Make each fake RR transient distinct, then a fresh report is
            # accepted and any later WAV mutation invalidates it.
            for index, path in enumerate(sorted(output.glob("*.wav")), start=1):
                waveform = (0.2 * np.sin(np.linspace(0, np.pi * index * 8, 9600))).astype(np.float32)
                wavfile.write(path, 48000, np.column_stack((waveform, waveform)))
            audit = audit_drumgizmo_composites(session, plan_path=plan, composite_root=output)
            audit["session_sha256"] = hashlib.sha256(session_path.read_bytes()).hexdigest()
            report_path.write_text(json.dumps(audit), encoding="utf-8")
            validate_drumgizmo_composite_report(
                report_path, session_path=session_path, composite_root=output, plan_path=plan,
            )
            changed = sorted(output.glob("*.wav"))[0]
            wavfile.write(changed, 48000, np.full((9600, 2), 0.333, dtype=np.float32))
            with self.assertRaisesRegex(ValueError, "no longer matches|changed"):
                validate_drumgizmo_composite_report(
                    report_path, session_path=session_path, composite_root=output, plan_path=plan,
                )
            raw = root / "raw"; raw.mkdir()
            takes = []
            for request in requests:
                for velocity in request.velocities:
                    for repetition in range(1, request.repetitions + 1):
                        filename = f"{request.instrument}__{request.articulation}__v{velocity:03d}__rr{repetition:02d}_raw.wav"
                        wavfile.write(raw / filename, 48000, np.full((9600, 2), 0.1, dtype=np.float32))
                        takes.append(SampleTake(
                            request.instrument, request.articulation, request.note, 10,
                            velocity, repetition, filename, sample_rate=48000,
                            channels=("left", "right"), frames=9600, status="captured",
                        ))
            applied = apply_captured_drumgizmo_composites(
                SampleLibrary("kit", ("left", "right"), tuple(takes)),
                composite_root=output, plan_path=plan,
            )
            target = next(take for take in applied.takes if take.instrument == "snare1")
            self.assertIn("simultaneous-layer-capture:snare1.deftones+snare_layer.sd02+snare_layer.sd30",
                          target.processing_history)
            self.assertTrue(Path(target.prepared_file or "").is_file())

    def test_audit_composites_cli_rechecks_existing_audio_without_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "plan.yaml"
            plan.write_text(
                "kind: sd3-megakit-plan\n"
                "drumgizmo_composites:\n"
                "  - target: snare1.deftones\n"
                "    sources: [snare1.deftones, snare_layer.sd02]\n",
                encoding="utf-8",
            )
            session = CaptureSessionPlan(
                "virtual", "loopback:output", ("left", "right"),
                (
                    CaptureRequest("snare1", "deftones", 37, (80,), 1, channel=10),
                    CaptureRequest("snare_layer", "sd02", 100, (80,), 1, channel=10),
                ),
                sample_rate=48000,
                tail_ms=100,
            )
            session_path = root / "session.json"
            session.write(session_path)
            audio = root / "composites"
            audio.mkdir()
            waveform = np.linspace(-0.25, 0.25, 9600, dtype=np.float32)
            wavfile.write(
                audio / "snare1__deftones__v080__rr01_composite.wav",
                48000,
                np.column_stack((waveform, waveform)),
            )
            report_path = root / "composite-quality.json"

            with patch("drum_sampler.offline.capture_chord") as capture:
                result = sampler_main([
                    "audit-composites", "--session", str(session_path),
                    "--megakit-plan", str(plan), "--input-directory", str(audio),
                    "--quality-report", str(report_path),
                ])

            self.assertEqual(result, 0)
            capture.assert_not_called()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["accepted"], 1)
            self.assertEqual(
                report["megakit_plan_sha256"],
                hashlib.sha256(plan.read_bytes()).hexdigest(),
            )

    def test_drumgizmo_layer_composite_matches_velocity_and_round_robin_without_touching_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"; raw.mkdir()
            cells = (
                ("snare1", "deftones", "base.wav", 0.20),
                ("snare_layer", "sd02", "sd02.wav", 0.10),
                ("snare_layer", "sd30", "sd30.wav", -0.02),
            )
            takes = []
            originals = {}
            for instrument, articulation, filename, value in cells:
                path = raw / filename
                wavfile.write(path, 48000, np.full((32, 2), value, dtype=np.float32))
                originals[filename] = path.read_bytes()
                takes.append(SampleTake(
                    instrument, articulation, 37, 10, 104, 1, filename,
                    sample_rate=48000, channels=("left", "right"), frames=32,
                    status="captured",
                ))
            plan = root / "plan.yaml"
            plan.write_text(
                "kind: sd3-megakit-plan\n"
                "drumgizmo_composites:\n"
                "  - target: snare1.deftones\n"
                "    sources: [snare1.deftones, snare_layer.sd02, snare_layer.sd30]\n",
                encoding="utf-8",
            )

            composed = compose_drumgizmo_layers(
                SampleLibrary("kit", ("left", "right"), tuple(takes)),
                audio_root=raw, output_root=root / "composite", plan_path=plan,
            )

            target = composed.takes[0]
            self.assertIsNotNone(target.prepared_file)
            rate, samples = wavfile.read(Path(target.prepared_file or ""))
            self.assertEqual(rate, 48000)
            np.testing.assert_allclose(samples, 0.28, atol=1e-6)
            self.assertIn("layer-composite:snare1.deftones+snare_layer.sd02+snare_layer.sd30",
                          target.processing_history)
            self.assertEqual({name: (raw / name).read_bytes() for name in originals}, originals)

    def test_megakit_capture_variants_replace_base_hihat_with_discrete_drumgizmo_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = Path(temporary) / "plan.yaml"
            plan.write_text(
                "kind: sd3-megakit-plan\narticulations:\n"
                "  - logical: hh.bow\n"
                "    capture_variants:\n"
                "      - {articulation: bow_closed, controllers: [[4, 127]], drumgizmo_note: 112}\n"
                "      - {articulation: bow_open, controllers: [[4, 0]], drumgizmo_note: 113}\n",
                encoding="utf-8",
            )
            overrides, replaced = drumgizmo_capture_note_overrides(plan)
            self.assertEqual(overrides, {("hh", "bow_closed"): 112, ("hh", "bow_open"): 113})
            self.assertEqual(replaced, {("hh", "bow")})

    def test_megakit_plan_declares_explicit_drumgizmo_choke_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = Path(temporary) / "plan.yaml"
            plan.write_text(
                "kind: sd3-megakit-plan\n"
                "drumgizmo_instrument_groups:\n"
                "  hihat: [hh.bow_closed, hh.edge_open, hh.pedal_close]\n",
                encoding="utf-8",
            )
            self.assertEqual(drumgizmo_instrument_groups(plan), {
                ("hh", "bow_closed"): "hihat",
                ("hh", "edge_open"): "hihat",
                ("hh", "pedal_close"): "hihat",
            })

    def test_resolved_drumgizmo_map_removes_continuous_hihat_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            note_map = root / "map.json"
            note_map.write_text(json.dumps({
                "format": "drum-note-map/v1", "target": "drumgizmo",
                "mappings": [
                    {"logical_target": "hh.bow", "note": 64},
                    {"logical_target": "kick.acoustic", "note": 24},
                ],
            }), encoding="utf-8")
            plan = root / "plan.yaml"
            plan.write_text(
                "kind: sd3-megakit-plan\narticulations:\n"
                "  - logical: hh.bow\n"
                "    capture_variants:\n"
                "      - {articulation: bow_closed, controllers: [[4, 127]], drumgizmo_note: 112}\n"
                "      - {articulation: bow_open, controllers: [[4, 0]], drumgizmo_note: 113}\n",
                encoding="utf-8",
            )
            self.assertEqual(resolved_drumgizmo_note_overrides(note_map, plan), {
                ("kick", "acoustic"): 24,
                ("hh", "bow_closed"): 112,
                ("hh", "bow_open"): 113,
            })

    def test_compiler_note_map_parses_instrument_articulation_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "drumgizmo-midimap.json"
            path.write_text(json.dumps({"format": "drum-note-map/v1", "target": "drumgizmo",
                                        "mappings": [{"logical_target": "hi_hat.closed", "note": 42}]}), encoding="utf-8")
            self.assertEqual(drumgizmo_note_overrides(path), {("hi_hat", "closed"): 42})

    def test_compiler_note_map_prefers_explicit_drumgizmo_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "drumgizmo-midimap.json"
            path.write_text(json.dumps({"format": "drum-note-map/v1", "target": "drumgizmo",
                                        "mappings": [{"logical_target": "scene.variant", "note": 42,
                                                      "instrument": "hi_hat", "articulation": "closed"}]}), encoding="utf-8")
            self.assertEqual(drumgizmo_note_overrides(path), {("hi_hat", "closed"): 42})

    def test_compiler_note_map_prefers_capture_identity_for_generated_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "drumgizmo-midimap.json"
            path.write_text(json.dumps({"format": "drum-note-map/v1", "target": "drumgizmo",
                                        "mappings": [{"logical_target": "hh.electronic_open", "note": 69,
                                                      "instrument": "hihat", "articulation": "open",
                                                      "capture_instrument": "hh", "capture_articulation": "electronic_open"}]}), encoding="utf-8")
            self.assertEqual(drumgizmo_note_overrides(path), {("hh", "electronic_open"): 69})

    def test_preparation_writes_new_file_and_preserves_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); raw = root / "raw.wav"
            wavfile.write(raw, 44100, np.array([0, 12000, -12000, 0], dtype=np.int16))
            original = raw.read_bytes()
            take = SampleTake("snare", "head", 38, 10, 100, 1, "raw.wav", sample_rate=44100,
                              channels=("left",), frames=4, status="captured")
            library = SampleLibrary("fixture", ("left",), (take,))
            prepared = prepare_selected_takes(library, audio_root=root, output_root=root / "prepared",
                                              profile=QualityProfile(target_sample_rate=44100))
            self.assertEqual(raw.read_bytes(), original)
            self.assertTrue((root / prepared.takes[0].prepared_file).is_file())
            self.assertEqual(prepared.takes[0].processing_history, ("offline-quality-profile",))

    def test_shared_variation_reuses_captured_file_without_new_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "plan.yaml"
            plan.write_text(
                "kind: sd3-megakit-plan\narticulations:\n"
                "  - {logical: perc.clap, note: 50, capture: true}\n"
                "  - {logical: stack.clap, note: 99, capture: false, shared_with: perc.clap}\n",
                encoding="utf-8",
            )
            take = SampleTake("perc", "clap", 50, 10, 100, 1, "clap.wav", sample_rate=44100,
                              channels=("left",), frames=32, status="captured")
            expanded = expand_shared_variations(SampleLibrary("kit", ("left",), (take,)), plan)
            self.assertEqual(len(expanded.takes), 2)
            alias = expanded.takes[1]
            self.assertEqual((alias.instrument, alias.articulation, alias.note), ("stack", "clap", 99))
            self.assertEqual(alias.raw_file, take.raw_file)

    def test_merge_files_prefixes_audio_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            take = SampleTake("kick", "head", 36, 10, 90, 1, "raw.wav", channels=("left",))
            source = root / "one.json"; SampleLibrary("one", ("left",), (take,)).write(source)
            merged = merge_library_files("merged", ((source, "source-one"),))
            self.assertEqual(merged.takes[0].raw_file, "source-one/raw.wav")

    def test_recipe_writes_resumable_offline_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = root / "library.json"
            SampleLibrary("fixture", ("left", "right"), ()).write(library)
            note_map = root / "drumgizmo-midimap.json"
            note_map.write_text(json.dumps({"format": "drum-note-map/v1", "target": "drumgizmo", "mappings": []}), encoding="utf-8")
            recipe = root / "recipe.json"
            recipe.write_text(json.dumps({"kind": "drum-sampler-offline-recipe", "schema_version": 1,
                                          "library": "library.json", "drumgizmo_note_map": "drumgizmo-midimap.json",
                                          "output_directory": "kit"}), encoding="utf-8")
            report = root / "report.json"
            result = run_offline_recipe(recipe, report)
            self.assertEqual(result["channel_layout"], ["left", "right"])
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["hardware_io"], "disabled")

    def test_drumgizmo_verification_records_version_backend_and_valid_xml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "instruments").mkdir(); (root / "samples").mkdir()
            wavfile.write(root / "samples" / "kick.wav", 44100, np.zeros(16, dtype=np.int16))
            (root / "instruments" / "kick.xml").write_text(
                '<instrument version="2.0" name="kick"><samples><sample name="hit" power="1.0">'
                '<audiofile channel="left" file="../samples/kick.wav" filechannel="1"/>'
                '</sample></samples></instrument>', encoding="utf-8")
            (root / "drumkit.xml").write_text(
                '<drumkit version="2.0" samplerate="44100"><metadata><author>test</author>'
                '<email>test@example.invalid</email><version>1.0.0</version></metadata><channels><channel name="left"/>'
                '</channels><instruments><instrument name="kick" file="instruments/kick.xml"/>'
                '</instruments></drumkit>', encoding="utf-8")
            (root / "midimap.xml").write_text('<midimap><map note="36" instr="kick"/></midimap>', encoding="utf-8")
            report_path = root / "report.json"
            with patch("drum_sampler.offline.subprocess.run") as run:
                run.return_value = __import__("subprocess").CompletedProcess(("drumgizmo", "--version"), 0, "DrumGizmo 0.9\n", "")
                report = verify_drumgizmo_kit(root, report_path, backend="jackmidi")
            self.assertEqual(report["drumgizmo"]["version"], "DrumGizmo 0.9")
            self.assertEqual(report["backend"], "jackmidi")
            self.assertEqual(report["audio_load"], "not_executed")
            self.assertEqual(report["kit"], {"channels": 1, "instruments": 1, "samples": 1, "mappings": 1})
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["kind"], "drumgizmo-smoke-report")

            validation_path = root / "validation.json"
            validation = write_drumgizmo_validation_report(root, validation_path)
            self.assertEqual(validation["status"], "pass")
            self.assertGreaterEqual(len(validation["files"]), 4)
            self.assertTrue(all(len(item["sha256"]) == 64 for item in validation["files"]))

            from drum_sampler.offline import verify_drumgizmo_validation_report
            self.assertEqual(
                verify_drumgizmo_validation_report(root, validation_path)["status"], "pass"
            )
            midimap_path = root / "midimap.xml"
            midimap_path.write_text(
                '<midimap><map note="37" instr="kick"/></midimap>', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "midimap.xml"):
                verify_drumgizmo_validation_report(root, validation_path)
            midimap_path.write_text('<midimap><map note="36" instr="kick"/></midimap>', encoding="utf-8")

            drumkit_path = root / "drumkit.xml"
            drumkit_path.write_text(
                drumkit_path.read_text(encoding="utf-8").replace("<author>test</author>", ""),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "metadata needs non-empty author"):
                validate_drumgizmo_kit(root)

    def test_drumgizmo_validation_rejects_unknown_midi_instrument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "drumkit.xml").write_text(
                '<drumkit version="2.0" samplerate="44100"><metadata><author>test</author>'
                '<email>test@example.invalid</email><version>1.0.0</version></metadata><channels><channel name="left"/>'
                '</channels><instruments><instrument name="kick" file="kick.xml"/>'
                '</instruments></drumkit>', encoding="utf-8")
            (root / "kick.xml").write_text(
                '<instrument version="2.0" name="kick"><samples><sample name="hit" power="1">'
                '<audiofile channel="left" file="kick.wav" filechannel="1"/>'
                '</sample></samples></instrument>', encoding="utf-8")
            wavfile.write(root / "kick.wav", 44100, np.zeros(16, dtype=np.int16))
            (root / "midimap.xml").write_text('<midimap><map note="36" instr="missing"/></midimap>', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown instrument"):
                validate_drumgizmo_kit(root)

    def test_drumgizmo_validation_rejects_invalid_wav_channel_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wavfile.write(root / "kick.wav", 44100, np.zeros(16, dtype=np.int16))
            (root / "kick.xml").write_text(
                '<instrument version="2.0" name="kick"><samples><sample name="hit" power="1">'
                '<audiofile channel="left" file="kick.wav" filechannel="2"/>'
                '</sample></samples></instrument>', encoding="utf-8")
            (root / "drumkit.xml").write_text(
                '<drumkit version="2.0" samplerate="44100"><metadata><author>test</author>'
                '<email>test@example.invalid</email><version>1.0.0</version></metadata><channels><channel name="left"/>'
                '</channels><instruments><instrument name="kick" file="kick.xml"/>'
                '</instruments></drumkit>', encoding="utf-8")
            (root / "midimap.xml").write_text('<midimap><map note="36" instr="kick"/></midimap>', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "exceeds WAV channels"):
                validate_drumgizmo_kit(root)


if __name__ == "__main__":
    unittest.main()
