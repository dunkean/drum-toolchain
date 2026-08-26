from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from control_center import ControlCenter
from control_center.ddrum4_matrix import UNKNOWN, audition_command, load_kit_matrix
from control_center.simulator import RigSimulator
from control_center.campaign import (CaptureRow, Sd3CaptureCampaign,
                                     METALCORE_ELECTRONIC_V1_ADDITIONS)


class ControlCenterTests(unittest.TestCase):
    def test_sd3_campaign_writes_resumable_sampler_session_and_reports_file_progress(self) -> None:
        campaign = Sd3CaptureCampaign(
            identifier="sd3_test_kit", sd3_preset="Test MegaKit", midi_output="SD3 input",
            audio_input="UMC404HD input 1-2", channels=("left", "right"),
            rows=(CaptureRow("snare_main", "rimshot", 40, (40, 80), 2),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / campaign.identifier
            campaign.write_new(run)
            session = json.loads((run / "capture-session.json").read_text(encoding="utf-8"))
            self.assertEqual(session["kind"], "capture-session")
            self.assertEqual(session["requests"][0]["note"], 40)
            self.assertEqual(session["requests"][0]["velocities"], [40, 80])
            self.assertEqual(campaign.progress(run).captured_takes, 0)
            raw = run / "raw-wav"; raw.mkdir()
            (raw / "snare_main__rimshot__v040__rr01_raw.wav").write_bytes(b"raw")
            progress = Sd3CaptureCampaign.read(run).progress(run)
            self.assertEqual((progress.captured_takes, progress.total_takes, progress.missing_takes), (1, 4, 3))
            with self.assertRaisesRegex(FileExistsError, "campaign directory"):
                campaign.write_new(run)

    def test_campaign_commands_are_ordered_and_capture_is_explicit(self) -> None:
        run = Path("D:/Studio/drum-runs/sd3_test_kit")
        center = ControlCenter()
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            center.sampler_command("capture", run)
        capture = center.sampler_command("capture", run, confirm_capture=True)
        self.assertIn("--confirm-capture", capture)
        self.assertEqual(capture[1:4], ("-m", "drum_sampler.cli", "capture"))
        quality = center.sampler_command("audit-quality", run)
        self.assertEqual(quality[1:4], ("-m", "drum_sampler.cli", "audit-quality"))
        with self.assertRaisesRegex(ValueError, "note map"):
            center.sampler_command("export-drumgizmo", run)

    def test_v1_electronic_additions_have_unique_raw_capture_cells(self) -> None:
        filenames = [filename for row in METALCORE_ELECTRONIC_V1_ADDITIONS for filename in row.raw_filenames()]
        self.assertEqual(len(filenames), len(set(filenames)))
        self.assertEqual({row.note for row in METALCORE_ELECTRONIC_V1_ADDITIONS} & {26, 47, 68, 85, 93},
                         {26, 47, 68, 85, 93})

    def test_complete_chain_simulator_traces_ddrum4_return_and_both_software_renderers(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        simulator = RigSimulator.from_path(project)
        simulator.set_state(scene="dnb")

        result = simulator.simulate_pad("ddrum4", 85, 106)

        self.assertEqual(result.physical, "stack.hit")
        self.assertEqual(result.logical_target, "perc.glitch")
        messages = {step.stage: step.message for step in result.steps}
        self.assertEqual(messages["Arduino DDrum4 renderer"]["note"], 86)
        self.assertEqual(messages["SD3 renderer"]["note"], 89)
        self.assertEqual(messages["DrumGizmo renderer"]["instrument"], "percussion")
        self.assertIn("hardware_io", result.to_document())

    def test_complete_chain_simulator_accepts_each_declared_module(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        simulator = RigSimulator.from_path(project)
        raw_notes = {"edrumin": 38, "ddti": 38, "ddrum4": 40}

        results = {source: simulator.simulate_pad(source, note) for source, note in raw_notes.items()}

        self.assertEqual({result.physical for result in results.values()}, {"snare.head"})
        self.assertEqual({result.logical_target for result in results.values()}, {"snare.metalcore"})

    def test_complete_chain_simulator_traces_logical_scene_to_declared_ddrum_program(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        simulator = RigSimulator.from_path(project)

        result = simulator.simulate_logical_control("pc", 15, "program_change", 1)

        self.assertEqual(result.state["scene"], "dnb")
        action = next(step for step in result.steps if step.stage == "Arduino DDrum4 state")
        self.assertEqual(action.message, {"type": "program_change", "channel": 12, "program": 1,
                                          "status": "user-confirmed"})
        self.assertTrue(result.to_document()["hardware_io"] == "disabled")

    def test_complete_chain_simulator_rejects_undeclared_logical_control(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        with self.assertRaisesRegex(ValueError, "not a declared"):
            RigSimulator.from_path(project).simulate_logical_control("pc", 15, "cc", 99, 1)

    def test_r15_simulator_covers_ten_sounds_from_each_of_three_modules(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "metalcore-r15-chain-simulator.yaml"
        simulator = RigSimulator.from_path(project)
        notes = (0, 8, 16, 24, 32, 40, 48, 56, 64, 72)
        expected_ddrum = (0, 8, 18, 24, 32, 40, 48, 56, 64, 72)

        for source in ("ddrum4", "ddti", "edrumin"):
            results = [simulator.simulate_pad(source, note, 100) for note in notes]
            rendered = tuple(next(step.message["note"] for step in result.steps
                                  if step.stage == "Arduino DDrum4 renderer") for result in results)
            channels = {next(step.message["channel"] for step in result.steps
                             if step.stage == "Arduino DDrum4 renderer") for result in results}
            self.assertEqual(rendered, expected_ddrum)
            self.assertEqual(channels, {12})

    def test_installed_r15_matrix_exposes_shared_crash_variations_without_extra_samples(self) -> None:
        manifest = Path(__file__).resolve().parents[3] / "profiles" / "banks" / "metalcore-r15-installed.yaml"
        matrix = load_kit_matrix(manifest)
        crash = next(sound for sound in matrix.sounds if sound.sound_id == "CYMB_982")
        self.assertEqual(crash.encoded_blocks, 1038)
        self.assertEqual(crash.layers[2].variation, (2,))
        self.assertEqual((crash.layers[2].pitch, crash.layers[2].source, crash.layers[2].velocity),
                         (3, "crash high shared", 68))

    def test_kit_matrix_keeps_unmeasured_memory_unknown_and_marks_missing_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "kit.yaml"
            manifest.write_text("""sounds:
  - sound_id: SNRE_998
    source: snare-main
    status: prepared
    provenance: capture-2026-08-10
    layers:
      - wav: absent.wav
""", encoding="utf-8")
            matrix = load_kit_matrix(manifest)
            sound = matrix.sound(1)
            self.assertEqual(sound.sound_id, "SNRE_998")
            self.assertIsNone(sound.mem_left_delta_blocks)
            self.assertEqual(sound.layers[0].resource_status, "missing")
            self.assertEqual(matrix.sound(2).status, "missing")

    def test_kit_matrix_merges_builder_report_without_inventing_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kit.json").write_text(json.dumps({"sounds": [{"sound_id": "KICK_997"}]}), encoding="utf-8")
            (root / "build.json").write_text(json.dumps({
                "kind": "ddrum4-flagship-cymbal-build", "sound_id": "KICK_997",
                "instrument": "kick", "encoded_blocks": 124,
                "layers": [{"prepared_file": "KICK_997_s01.wav"}],
            }), encoding="utf-8")
            sound = load_kit_matrix(root / "kit.json", [root / "build.json"]).sound(1)
            self.assertEqual(sound.encoded_blocks, 124)
            self.assertIsNone(sound.mem_left_delta_blocks)
            self.assertEqual(sound.layers[0].resource_status, "missing")

    def test_default_player_command_is_platform_specific_and_wav_only(self) -> None:
        self.assertEqual(audition_command(Path("take.wav"), "win32"),
                         ("cmd", "/c", "start", "", "take.wav"))
        self.assertEqual(audition_command(Path("take.wav"), "darwin"), ("open", "take.wav"))
        self.assertEqual(audition_command(Path("take.wav"), "linux"), ("xdg-open", "take.wav"))
        with self.assertRaisesRegex(ValueError, "WAV"):
            audition_command(Path("take.mid"), "linux")

    def test_offline_command_construction(self) -> None:
        center = ControlCenter("drum-toolchain")
        command = center.rig_command("compile", Path("profiles/projects/kit.yaml"), output=Path("build/kit"),
                                     replace=True, base_dump=Path("captures/base.syx"))
        self.assertEqual(command, ("drum-toolchain", "compile", str(Path("profiles/projects/kit.yaml")), "--output",
                                   str(Path("build/kit")), "--replace", "--base-dump", str(Path("captures/base.syx"))))

    def test_ddti_commands_are_offline_export_diff_or_stage_only(self) -> None:
        center = ControlCenter()
        self.assertEqual(center.ddti_command("export-config", Path("base.syx"), output=Path("preset.yaml")),
                         ("ddti", "export-config", "base.syx", "preset.yaml"))
        self.assertEqual(center.ddti_command("apply-config", Path("base.syx"), preset=Path("preset.yaml"), output=Path("staged.syx")),
                         ("ddti", "apply-config", "base.syx", "preset.yaml", "staged.syx"))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            center.ddti_command("write-config", Path("base.syx"))

    def test_dry_run_never_invokes_runner_or_launcher(self) -> None:
        def forbidden(*args: object, **kwargs: object) -> object:
            raise AssertionError("a dry run must not start a process")
        center = ControlCenter(runner=forbidden, launcher=forbidden)
        result = center.run_rig("validate", Path("project.yaml"), dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertIsNone(result.returncode)
        launch = center.launch("converter", converter=Path("converter.exe"), runtime_profile=Path("runtime-profile.yaml"), dry_run=True)
        self.assertEqual(launch.command, ("converter.exe",))

    def test_run_collects_logs_without_hardware(self) -> None:
        def runner(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(tuple(command), ("drum-toolchain", "report", "project.yaml"))
            self.assertTrue(kwargs["capture_output"])
            return subprocess.CompletedProcess(command, 0, "report\n", "")
        result = ControlCenter(runner=runner).run_rig("report", Path("project.yaml"))
        self.assertEqual(result.text, "report\n")

    def test_offline_runners_hide_windows_console_without_using_shell(self) -> None:
        calls: list[dict[str, object]] = []
        project = Path("project.yaml")
        base_dump = Path("base.syx")
        preset = Path("next.syx")

        def runner(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(dict(kwargs))
            return subprocess.CompletedProcess(command, 0, "ok\n", "")

        with patch("control_center.service.os.name", "nt"):
            control_center = ControlCenter(runner=runner)
            control_center.run_rig("report", project)
            control_center.run_ddti("diff", base_dump, preset=preset)

        self.assertEqual(len(calls), 2)
        expected_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        for kwargs in calls:
            self.assertIs(kwargs["capture_output"], True)
            self.assertIs(kwargs["text"], True)
            self.assertIs(kwargs["check"], False)
            self.assertIs(kwargs["shell"], False)
            self.assertEqual(kwargs["creationflags"], expected_flag)

    def test_launchers_are_explicit(self) -> None:
        center = ControlCenter()
        with self.assertRaisesRegex(ValueError, "explicit executable"):
            center.launch_command("ddrum4ui")
        self.assertEqual(center.launch_command("ddti"), ("ddti-editor",))

    def test_control_center_lists_and_stops_only_processes_it_started(self) -> None:
        class Process:
            def __init__(self) -> None:
                self.running = True
                self.terminated = False
            def poll(self) -> None:
                return None if self.running else 0
            def terminate(self) -> None:
                self.terminated = True
                self.running = False
        process = Process()
        center = ControlCenter(launcher=lambda *args, **kwargs: process)
        center.launch("external", external=Path("sd3-host.exe"))
        self.assertEqual(center.launched_processes(), (("external:sd3-host.exe:None", True),))
        self.assertEqual(center.stop_launched_processes(), ("external:sd3-host.exe:None",))
        self.assertTrue(process.terminated)

    def test_converter_launch_sets_profile_environment_and_blocks_duplicate(self) -> None:
        class Process:
            def poll(self) -> None:
                return None
        calls: list[tuple[object, object]] = []
        def launcher(command: object, **kwargs: object) -> Process:
            calls.append((command, kwargs.get("env")))
            return Process()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        center = ControlCenter(launcher=launcher, lock_directory=Path(temporary.name))
        center.launch("converter", converter=Path("converter.exe"), runtime_profile=Path("build/runtime-profile.yaml"))
        self.assertEqual(calls[0][1]["DDRUM4_RUNTIME_PROFILE"], str(Path("build/runtime-profile.yaml")))
        self.assertEqual(calls[0][1]["DDRUM4_RENDERER_TARGET"], "sd3")
        with self.assertRaisesRegex(RuntimeError, "already running"):
            center.launch("converter", converter=Path("converter.exe"), runtime_profile=Path("build/runtime-profile.yaml"))

    def test_stale_cross_process_lock_is_cleaned_before_launch(self) -> None:
        class Process:
            pid = 424242
            def poll(self) -> None:
                return None
        with tempfile.TemporaryDirectory() as temporary:
            center = ControlCenter(launcher=lambda *args, **kwargs: Process(), lock_directory=Path(temporary))
            converter, profile = Path("converter.exe"), Path("build/runtime-profile.yaml")
            lock = center.converter_lock_path(converter, profile)
            lock.parent.mkdir(parents=True)
            lock.write_text('{"pid": -1}', encoding="utf-8")
            center.launch("converter", converter=converter, runtime_profile=profile)
            self.assertEqual(lock.read_text(encoding="utf-8"), '{"pid": 424242}')

    def test_live_cross_process_lock_blocks_a_second_controller(self) -> None:
        class Process:
            def poll(self) -> None:
                return None
        with tempfile.TemporaryDirectory() as temporary:
            converter, profile = Path("converter.exe"), Path("build/runtime-profile.yaml")
            first = ControlCenter(launcher=lambda *args, **kwargs: Process(), lock_directory=Path(temporary))
            first.launch("converter", converter=converter, runtime_profile=profile)
            second = ControlCenter(launcher=lambda *args, **kwargs: Process(), lock_directory=Path(temporary))
            with self.assertRaisesRegex(RuntimeError, "another Control Center"):
                second.launch("converter", converter=converter, runtime_profile=profile)

    def test_converter_requires_runtime_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "runtime profile"):
            ControlCenter().launch_command("converter", converter=Path("converter.exe"))

    def test_converter_rejects_unknown_renderer_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "renderer target"):
            ControlCenter().launch_command("converter", converter=Path("converter.exe"),
                                           runtime_profile=Path("runtime-profile.yaml"), renderer_target="unknown")
