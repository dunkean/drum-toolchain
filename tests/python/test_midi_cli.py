from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from midi_lab.cli import main
from midi_lab.live_session import LiveSessionError, preview_drumgizmo_session, start_drumgizmo_session


class MidiCliTests(unittest.TestCase):
    @staticmethod
    def _fixture_executable() -> Path:
        """Return an executable usable by mocked live-session process tests."""
        return Path(sys.executable).resolve()

    @staticmethod
    def _write_valid_drumgizmo_kit(kit: Path) -> None:
        (kit / "instruments").mkdir(); (kit / "samples").mkdir()
        (kit / "samples" / "kick.wav").write_bytes(b"fixture")
        (kit / "instruments" / "kick.xml").write_text(
            '<instrument version="2.0" name="kick"><samples><sample name="hit" power="1">'
            '<audiofile channel="left" file="../samples/kick.wav" filechannel="1"/>'
            '</sample></samples></instrument>', encoding="utf-8")
        (kit / "drumkit.xml").write_text(
            '<drumkit version="2.0" samplerate="44100"><channels><channel name="left"/>'
            '</channels><instruments><instrument name="kick" file="instruments/kick.xml"/>'
            '</instruments></drumkit>', encoding="utf-8")
        (kit / "midimap.xml").write_text('<midimap><map note="36" instr="kick"/></midimap>', encoding="utf-8")

    def test_list_reports_an_unavailable_backend_without_a_traceback(self) -> None:
        with patch("midi_lab.cli._port_names", side_effect=RuntimeError("ALSA unavailable")):
            self.assertEqual(main(["list"]), 2)

    def test_drumgizmo_session_requires_confirmation_and_connects_explicit_ports(self) -> None:
        class Process:
            next_pid = 4000

            def __init__(self) -> None:
                self.pid = Process.next_pid
                Process.next_pid += 1
                self.terminated = False

            def poll(self) -> None:
                return None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout: float | None = None) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = self._fixture_executable()
            runtime = root / "runtime-profile.yaml"; runtime.write_text("format: rig-runtime-profile/v1\n", encoding="utf-8")
            kit = root / "kit"; kit.mkdir()
            self._write_valid_drumgizmo_kit(kit)
            config = root / "session.json"
            config.write_text(json.dumps({
                "schema_version": 1, "renderer": "drumgizmo",
                "converter": {"path": str(executable), "arguments": ["--headless"]},
                "runtime_profile": {"path": str(runtime)},
                "midi_bridge": {"path": str(executable)},
                "drumgizmo": {"path": str(executable), "kit_directory": str(kit)},
                "jack_connections": [{"source": "converter:midi_out", "destination": "drumgizmo:midi_in"}],
            }), encoding="utf-8")
            state_path = root / "state.json"
            with self.assertRaisesRegex(LiveSessionError, "confirm-start"):
                start_drumgizmo_session(config, state_path, confirm_start=False)
            commands: list[tuple[str, ...]] = []

            def runner(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                return subprocess.CompletedProcess(command, 0, "DrumGizmo 0.9\n", "")

            calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

            def popen(command: tuple[str, ...], **kwargs: object) -> Process:
                calls.append((command, dict(kwargs)))
                return Process()

            state = start_drumgizmo_session(config, state_path, confirm_start=True, runner=runner, popen=popen)
            self.assertEqual(commands[0], (str(executable), "--version"))
            self.assertEqual(commands[1], ("jack_connect", "converter:midi_out", "drumgizmo:midi_in"))
            self.assertEqual(calls[0][0], (str(executable), "-e"))
            self.assertIn("-I", calls[1][0])
            self.assertIn(f"midimap={(kit / 'midimap.xml').resolve()}", calls[1][0])
            self.assertEqual(calls[2][1]["env"]["DDRUM4_RENDERER_TARGET"], "drumgizmo")
            self.assertEqual(calls[2][1]["env"]["DDRUM4_RUNTIME_PROFILE"], str(runtime.resolve()))
            self.assertEqual(state["renderer"], "drumgizmo")
            self.assertTrue(state_path.is_file())

    def test_drumgizmo_session_rolls_back_when_jack_connection_fails(self) -> None:
        class Process:
            def __init__(self, pid: int) -> None:
                self.pid = pid
                self.terminated = False

            def poll(self) -> None:
                return None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout: float | None = None) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); executable = self._fixture_executable(); runtime = root / "runtime.yaml"; runtime.write_text("ready\n", encoding="utf-8")
            kit = root / "kit"; kit.mkdir(); self._write_valid_drumgizmo_kit(kit)
            config = root / "session.json"
            config.write_text(json.dumps({"schema_version": 1, "renderer": "drumgizmo", "converter": {"path": str(executable)}, "runtime_profile": {"path": str(runtime)}, "midi_bridge": {"path": str(executable)}, "drumgizmo": {"path": str(executable), "kit_directory": str(kit)}, "jack_connections": [{"source": "a", "destination": "b"}]}), encoding="utf-8")
            processes = [Process(1), Process(2), Process(3)]
            created: list[Process] = []

            def runner(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
                if command[-1] == "--version":
                    return subprocess.CompletedProcess(command, 0, "DrumGizmo\n", "")
                return subprocess.CompletedProcess(command, 1, "", "not found")

            with self.assertRaisesRegex(LiveSessionError, "JACK connection"):
                start_drumgizmo_session(config, root / "state.json", confirm_start=True, runner=runner,
                                        popen=lambda *args, **kwargs: created.append(processes.pop(0)) or created[-1],
                                        sleep=lambda _: None)
            self.assertTrue(all(process.terminated for process in created))

    def test_drumgizmo_session_dry_run_has_no_process_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); executable = self._fixture_executable(); runtime = root / "runtime.yaml"; runtime.write_text("ready\n", encoding="utf-8")
            kit = root / "kit"; kit.mkdir(); self._write_valid_drumgizmo_kit(kit)
            config = root / "session.json"
            config.write_text(json.dumps({
                "schema_version": 1, "renderer": "drumgizmo", "converter": {"path": str(executable)},
                "runtime_profile": {"path": str(runtime)}, "midi_bridge": {"path": str(executable)},
                "drumgizmo": {"path": str(executable), "kit_directory": str(kit)},
                "jack_connections": [{"source": "a", "destination": "b"}],
            }), encoding="utf-8")
            state_path = root / "state.json"

            preview = preview_drumgizmo_session(config, state_path)

            self.assertEqual(preview["hardware_io"], "disabled")
            self.assertEqual(preview["commands"]["a2jmidid"], [str(executable), "-e"])
            self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
