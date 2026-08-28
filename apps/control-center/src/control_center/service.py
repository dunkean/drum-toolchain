"""Process orchestration with no MIDI or hardware dependencies."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable, Sequence

from .ddrum4_matrix import audition_command

_HOST_PATH = type(Path.cwd())


@dataclass(frozen=True)
class CommandResult:
    """A command transcript suitable for displaying in the UI or saving as a log."""

    command: tuple[str, ...]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    dry_run: bool = False

    @property
    def text(self) -> str:
        return self.stdout + self.stderr


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _offline_run_options() -> dict[str, object]:
    """Return non-interactive subprocess options for offline CLI jobs.

    Windows console applications otherwise create a transient console window
    when the Control Center starts them.  GUI applications use the separate
    launcher path and deliberately do not receive these flags.
    """
    options: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "check": False,
        "shell": False,
    }
    if os.name == "nt":
        # Keep the helper testable on non-Windows hosts where subprocess does
        # not expose this Windows-only constant.
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return options
Launcher = Callable[..., object]


class ControlCenter:
    """Build and explicitly run offline tool commands and desktop launchers."""

    def __init__(self, toolchain: str = "drum-toolchain", *, runner: Runner = subprocess.run,
                 launcher: Launcher = subprocess.Popen, lock_directory: Path | None = None) -> None:
        self.toolchain = toolchain
        self._runner = runner
        self._launcher = launcher
        self._owned_processes: dict[str, object] = {}
        self._lock_directory = lock_directory or _HOST_PATH(tempfile.gettempdir()) / "drum-control-center"

    def rig_command(self, action: str, project: Path, *, output: Path | None = None,
                    replace: bool = False, base_dump: Path | None = None) -> tuple[str, ...]:
        if action not in {"validate", "compile", "report"}:
            raise ValueError(f"unsupported rig action: {action}")
        if action == "compile" and output is None:
            raise ValueError("compile requires an explicit output directory")
        if action != "compile" and (replace or base_dump is not None):
            raise ValueError(f"{action} does not accept compile options")
        prefix = ([sys.executable, "-m", "rig_compiler.cli"]
                  if self.toolchain == "drum-toolchain" else [self.toolchain])
        command = [*prefix, action, str(project)]
        if output is not None:
            command.extend(("--output", str(output)))
        if replace:
            command.append("--replace")
        if base_dump is not None:
            command.extend(("--base-dump", str(base_dump)))
        return tuple(command)

    def run_rig(self, action: str, project: Path, *, output: Path | None = None,
                replace: bool = False, base_dump: Path | None = None,
                dry_run: bool = False) -> CommandResult:
        command = self.rig_command(action, project, output=output, replace=replace, base_dump=base_dump)
        if dry_run:
            return CommandResult(command, None, dry_run=True)
        completed = self._runner(command, **_offline_run_options())
        return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)

    @staticmethod
    def sampler_command(action: str, run_directory: Path, *, note_map: Path | None = None,
                        megakit_plan: Path | None = None,
                        confirm_capture: bool = False) -> tuple[str, ...]:
        """Build a capture-campaign command from conventional run artefacts.

        This keeps the GUI workflow explicit.  In particular, capture cannot be
        started by a status refresh or a plan-generation action.
        """
        session = run_directory / "capture-session.json"
        raw = run_directory / "raw-wav"
        library = run_directory / "library.json"
        reports = run_directory / "reports"
        identifier = run_directory.name
        campaign_path = run_directory / "campaign.json"
        if campaign_path.is_file():
            try:
                declared_id = json.loads(campaign_path.read_text(encoding="utf-8")).get("id")
                if isinstance(declared_id, str) and declared_id:
                    identifier = declared_id
            except (OSError, json.JSONDecodeError):
                pass
        command = (sys.executable, "-m", "drum_sampler.cli")
        if action == "capture":
            if not confirm_capture:
                raise ValueError("capture requires explicit confirmation")
            return (*command, "capture", "--session", str(session), "--raw-directory", str(raw),
                    "--library-output", str(library), "--id", identifier, "--source", "sd3",
                    "--license", "SD3 capture for personal kit development", "--confirm-capture")
        if action == "audit-quality":
            return (*command, "audit-quality", "--library", str(library), "--audio-root", str(raw),
                    "--output", str(reports / "quality.json"))
        if action == "export-drumgizmo":
            if note_map is None:
                raise ValueError("DrumGizmo export requires a compiled note map")
            export_command = (*command, "export-drumgizmo", "--library", str(library), "--audio-root", str(raw),
                              "--output-directory", str(run_directory / "drumgizmo-kit"), "--note-map", str(note_map))
            if megakit_plan is not None:
                export_command = (*export_command, "--megakit-plan", str(megakit_plan))
            return (*export_command, "--report", str(reports / "drumgizmo-export.json"))
        if action == "verify-drumgizmo":
            return (*command, "verify-drumgizmo", "--kit-directory", str(run_directory / "drumgizmo-kit"),
                    "--report", str(reports / "drumgizmo-verify.json"))
        raise ValueError(f"unsupported sampler action: {action}")

    def run_sampler(self, action: str, run_directory: Path, *, note_map: Path | None = None,
                    megakit_plan: Path | None = None,
                    confirm_capture: bool = False, dry_run: bool = False) -> CommandResult:
        command = self.sampler_command(action, run_directory, note_map=note_map, megakit_plan=megakit_plan,
                                       confirm_capture=confirm_capture)
        if dry_run:
            return CommandResult(command, None, dry_run=True)
        completed = self._runner(command, **_offline_run_options())
        return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)

    @staticmethod
    def ddti_command(action: str, dump: Path, *, preset: Path | None = None,
                     output: Path | None = None, name: str | None = None) -> tuple[str, ...]:
        """Build a strictly offline DDTi configuration command.

        The supported operations only decode/export or stage a new SysEx file.
        They deliberately exclude every DDTi MIDI write command.
        """
        if action == "export-config":
            if output is None:
                raise ValueError("DDTi export-config requires an output preset")
            command = [sys.executable, "-m", "ddti.cli", action, str(dump), str(output)]
            if name:
                command.extend(("--name", name))
            return tuple(command)
        if action == "apply-config":
            if preset is None or output is None:
                raise ValueError("DDTi apply-config requires a preset and staged output")
            return (sys.executable, "-m", "ddti.cli", action, str(dump), str(preset), str(output))
        if action == "diff":
            if preset is None:
                raise ValueError("DDTi diff requires a second dump")
            return (sys.executable, "-m", "ddti.cli", action, str(dump), str(preset))
        raise ValueError(f"unsupported offline DDTi action: {action}")

    def run_ddti(self, action: str, dump: Path, *, preset: Path | None = None,
                 output: Path | None = None, name: str | None = None,
                 dry_run: bool = False) -> CommandResult:
        command = self.ddti_command(action, dump, preset=preset, output=output, name=name)
        if dry_run:
            return CommandResult(command, None, dry_run=True)
        completed = self._runner(command, **_offline_run_options())
        return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)

    def launch_command(self, target: str, *, ddrum4ui: Path | None = None,
                       converter: Path | None = None, external: Path | None = None, runtime_profile: Path | None = None,
                       converter_arguments: Sequence[str] = (), renderer_target: str = "sd3") -> tuple[str, ...]:
        if target == "ddti":
            return (sys.executable, "-m", "ddti.gui")
        if target == "ddrum4ui":
            if ddrum4ui is None:
                raise ValueError("ddrum4UI requires an explicit executable path")
            return (str(ddrum4ui),)
        if target == "external":
            if external is None:
                raise ValueError("external application requires an explicit executable path")
            return (str(external), *converter_arguments)
        if target == "converter":
            if converter is None:
                raise ValueError("converter requires an explicit executable path")
            if runtime_profile is None:
                raise ValueError("converter requires an explicit compiled runtime profile")
            if renderer_target not in {"sd3", "drumgizmo"}:
                raise ValueError("converter renderer target must be sd3 or drumgizmo")
            return (str(converter), *converter_arguments)
        raise ValueError(f"unsupported launcher target: {target}")

    def launch(self, target: str, *, ddrum4ui: Path | None = None, converter: Path | None = None,
               external: Path | None = None, runtime_profile: Path | None = None, converter_arguments: Sequence[str] = (),
               renderer_target: str = "sd3", dry_run: bool = False) -> CommandResult:
        command = self.launch_command(target, ddrum4ui=ddrum4ui, converter=converter, external=external,
                                      runtime_profile=runtime_profile,
                                      converter_arguments=converter_arguments, renderer_target=renderer_target)
        if dry_run:
            return CommandResult(command, None, dry_run=True)
        key = self._launch_key(target, converter or external, runtime_profile)
        existing = self._owned_processes.get(key)
        if existing is not None and getattr(existing, "poll", lambda: 0)() is None:
            raise RuntimeError(f"{target} is already running from this Control Center")
        environment = None
        if target == "converter":
            environment = os.environ.copy()
            environment["DDRUM4_RUNTIME_PROFILE"] = str(runtime_profile)
            environment["DDRUM4_RENDERER_TARGET"] = renderer_target
        lock = self._acquire_converter_lock(converter, runtime_profile) if target == "converter" else None
        try:
            process = self._launcher(command, env=environment) if environment else self._launcher(command)
            if lock is not None:
                lock.write_text(json.dumps({"pid": getattr(process, "pid", os.getpid())}), encoding="utf-8")
        except BaseException:
            if lock is not None:
                lock.unlink(missing_ok=True)
            raise
        self._owned_processes[key] = process
        return CommandResult(command, 0)

    @staticmethod
    def audition_command(wav: Path, platform: str | None = None) -> tuple[str, ...]:
        """Construct a local WAV default-player command without running it."""
        return audition_command(wav, platform)

    def audition_wav(self, wav: Path, *, dry_run: bool = False) -> CommandResult:
        """Explicitly ask the operating system to play one existing local WAV."""
        if not wav.is_file():
            raise FileNotFoundError(f"WAV resource is missing: {wav}")
        command = self.audition_command(wav)
        if dry_run:
            return CommandResult(command, None, dry_run=True)
        self._launcher(command)
        return CommandResult(command, 0)

    def launched_processes(self) -> tuple[tuple[str, bool], ...]:
        """Return only applications started by this Control Center instance."""
        return tuple((key, getattr(process, "poll", lambda: 0)() is None)
                     for key, process in sorted(self._owned_processes.items()))

    def stop_launched_processes(self) -> tuple[str, ...]:
        """Request termination of applications this instance started.

        It never targets a process discovered elsewhere on the machine.
        """
        stopped: list[str] = []
        for key, process in tuple(self._owned_processes.items()):
            if getattr(process, "poll", lambda: 0)() is None:
                terminate = getattr(process, "terminate", None)
                if terminate is not None:
                    terminate()
                    stopped.append(key)
        return tuple(stopped)

    @staticmethod
    def _launch_key(target: str, executable: Path | None, runtime_profile: Path | None) -> str:
        if target in {"converter", "external"}:
            return f"{target}:{executable}:{runtime_profile}"
        return target

    def converter_lock_path(self, converter: Path, runtime_profile: Path) -> Path:
        """Stable cross-process lease path for one converter/profile pairing."""
        digest = hashlib.sha256(f"{converter.resolve()}\0{runtime_profile.resolve()}".encode()).hexdigest()
        return self._lock_directory / "converter-locks" / f"converter-{digest}.pid"

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _acquire_converter_lock(self, converter: Path | None, runtime_profile: Path | None) -> Path:
        assert converter is not None and runtime_profile is not None
        lock = self.converter_lock_path(converter, runtime_profile)
        lock.parent.mkdir(parents=True, exist_ok=True)
        if lock.exists():
            try:
                pid = int(json.loads(lock.read_text(encoding="utf-8"))["pid"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pid = 0
            if self._pid_is_alive(pid):
                raise RuntimeError("converter is already running from another Control Center")
            lock.unlink(missing_ok=True)
        try:
            with lock.open("x", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid()}, handle)
        except FileExistsError as error:
            raise RuntimeError("converter is already being launched by another Control Center") from error
        return lock

    @staticmethod
    def report_files(output: Path) -> tuple[Path, ...]:
        """Return generated compiler reports without interpreting hardware data."""
        if not output.is_dir():
            return ()
        return tuple(sorted(path for path in output.iterdir() if path.is_file() and
                            path.name in {"project-report.json", "sd3-megakit-map.md", "compile.log"}))

    @staticmethod
    def read_report(path: Path) -> str:
        return path.read_text(encoding="utf-8")
