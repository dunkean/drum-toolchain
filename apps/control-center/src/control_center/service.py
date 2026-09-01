"""Process orchestration with no MIDI or hardware dependencies."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
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


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_campaign_session_contract(campaign: dict[str, object], session_path: Path) -> None:
    """Reject a session whose exact note/controller grid differs from the campaign."""
    expected = campaign.get("capture_session_sha256")
    if not isinstance(expected, str) or not session_path.is_file() or _sha256_file(session_path) != expected:
        raise ValueError("capture-session differs from the immutable campaign contract")


def _validate_passing_capture_quality(report_path: Path, library_path: Path,
                                      expected_takes: int,
                                      session_path: Path | None = None) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("a passing full-capture quality report is required") from error
    summary = report.get("summary")
    if (not library_path.is_file() or report.get("kind") != "capture-quality-report"
            or report.get("library_sha256") != _sha256_file(library_path)
            or (session_path is not None
                and report.get("session_sha256") != _sha256_file(session_path))
            or not isinstance(summary, dict)
            or summary.get("accepted") != expected_takes
            or summary.get("rejected") != 0 or summary.get("missing") != 0
            or summary.get("round_robin_duplicate_cells") != 0):
        raise ValueError("the full-capture quality report failed, is incomplete, or is stale")
    if summary.get("round_robin_duplicate_cells") != 0:
        raise ValueError("the full-capture quality report found duplicate round-robin audio")


def _validate_passing_composite_quality(report_path: Path, *, session_path: Path,
                                        plan_path: Path, composite_root: Path,
                                        expected_filenames: tuple[str, ...]) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("a passing simultaneous-layer quality report is required") from error
    summary = report.get("summary")
    if (report.get("kind") != "drumgizmo-composite-quality-report"
            or not isinstance(summary, dict)
            or report.get("session_sha256") != _sha256_file(session_path)
            or report.get("megakit_plan_sha256") != _sha256_file(plan_path)
            or summary.get("accepted") != len(expected_filenames)
            or summary.get("rejected") != 0 or summary.get("missing") != 0
            or summary.get("round_robin_duplicate_cells") != 0):
        raise ValueError("the simultaneous-layer quality report failed or is incomplete")
    records = report.get("takes")
    if not isinstance(records, list):
        raise ValueError("the simultaneous-layer quality report has no take grid")
    indexed: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("the simultaneous-layer quality report has an invalid take")
        name = Path(record["path"]).name
        if name in indexed:
            raise ValueError(f"the simultaneous-layer quality report duplicates {name}")
        indexed[name] = record
    if set(indexed) != set(expected_filenames):
        raise ValueError("the simultaneous-layer quality report does not cover the exact take grid")
    for name in expected_filenames:
        path = composite_root / name
        facts = indexed[name].get("facts")
        if (indexed[name].get("automatic_status") != "accepted"
                or not isinstance(facts, dict) or not path.is_file()
                or facts.get("sha256") != _sha256_file(path)):
            raise ValueError(f"simultaneous-layer WAV changed after quality review: {name}")


def _resolve_sd3_preset(campaign: dict[str, object]) -> tuple[Path, str]:
    """Resolve one unambiguous preset file and enforce its recorded fingerprint."""
    candidates: list[Path] = []
    declared_file = campaign.get("sd3_preset_file")
    if isinstance(declared_file, str) and declared_file.strip():
        candidates.append(Path(declared_file))
    preset_name = campaign.get("sd3_preset")
    if isinstance(preset_name, str) and preset_name.strip():
        filename = preset_name if preset_name.lower().endswith(".sd3p") else f"{preset_name}.sd3p"
        candidates.extend((
            Path("captures") / "sd3" / filename,
            Path.home() / "Documents" / "Toontrack" / "Superior Drummer 3" / filename,
            Path.home() / "Documents" / "Toontrack" / "Superior Drummer 3" / filename.replace("_", " "),
        ))
    existing: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen and resolved.is_file():
            seen.add(resolved)
            existing.append((resolved, _sha256_file(resolved)))
    if not existing:
        raise ValueError("campaign SD3 preset file cannot be found; select the generated .sd3p")
    hashes = {digest for _, digest in existing}
    if len(hashes) != 1:
        details = ", ".join(f"{path}={digest[:12]}" for path, digest in existing)
        raise ValueError(f"multiple SD3 preset candidates have different fingerprints: {details}")
    path, digest = existing[0]
    declared_sha = campaign.get("sd3_preset_sha256")
    if isinstance(declared_sha, str) and declared_sha.lower() != digest:
        raise ValueError(
            f"campaign SD3 preset fingerprint changed: expected {declared_sha.lower()}, got {digest}"
        )
    return path, digest


def _normalized_sd3_name(value: str) -> str:
    """Normalize a preset/window label without relying on shell encoding."""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def active_sd3_window_titles() -> tuple[str, ...]:
    """Read visible SD3 window titles directly through Win32, without a shell."""
    if os.name != "nt":
        return ()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    titles: list[str] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(window: int, _parameter: int) -> bool:
        if not user32.IsWindowVisible(window):
            return True
        length = user32.GetWindowTextLengthW(window)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window, buffer, length + 1)
        title = buffer.value.strip()
        if "Superior Drummer 3" in title:
            titles.append(title)
        return True

    user32.EnumWindows(collect, 0)
    return tuple(dict.fromkeys(titles))


def verify_active_sd3_preset(campaign: dict[str, object], window_title: str | None) -> None:
    """Require direct evidence that the campaign preset is active in SD3."""
    preset_name = campaign.get("sd3_preset")
    if not isinstance(preset_name, str) or not preset_name.strip():
        raise ValueError("campaign does not declare an SD3 preset name")
    expected = _normalized_sd3_name(Path(preset_name).stem)
    active = _normalized_sd3_name(window_title or "")
    if not expected or expected not in active or "superiordrummer3" not in active:
        shown = window_title.strip() if isinstance(window_title, str) and window_title.strip() else "no SD3 window"
        raise ValueError(f"wrong SD3 preset is active: expected {preset_name!r}; active: {shown!r}")


def _validate_passing_calibration(calibration: object, *, session_sha256: str,
                                  preset_sha256: str) -> None:
    """Validate a complete v2 calibration, not merely its headline status."""
    if not isinstance(calibration, dict) or calibration.get("format") != "sd3-calibration-report/v2":
        raise ValueError("full capture requires an SD3 calibration report v2")
    summary = calibration.get("summary")
    preset = calibration.get("preset")
    policy = calibration.get("policy")
    rows = calibration.get("rows")
    if (not isinstance(summary, dict) or not isinstance(preset, dict)
            or not isinstance(policy, dict) or not isinstance(rows, list)):
        raise ValueError("full capture requires a complete SD3 calibration report v2")
    level_groups = summary.get("level_groups")
    if not isinstance(level_groups, dict) or not level_groups:
        raise ValueError("full capture requires calibration level groups")
    for name, group in level_groups.items():
        if (not isinstance(name, str) or not isinstance(group, dict)
                or not isinstance(group.get("articulations"), int)
                or group["articulations"] < 1
                or not isinstance(group.get("peak_span_db"), (int, float))
                or not isinstance(group.get("quietest_peak_dbfs"), (int, float))
                or not isinstance(group.get("loudest_peak_dbfs"), (int, float))
                or not isinstance(group.get("outliers"), list)):
            raise ValueError(f"invalid calibration level group: {name!r}")
    relative_outliers = summary.get("relative_level_outliers")
    if not isinstance(relative_outliers, list):
        raise ValueError("full capture requires calibration relative-level results")
    if (summary.get("status") != "technical-pass-user-mix-review-required"
            or summary.get("technical_failures") != 0
            or relative_outliers
            or any(group["outliers"] for group in level_groups.values())):
        raise ValueError("full capture requires a technically passing, level-balanced calibration")
    if policy.get("only") != []:
        raise ValueError("full capture requires a complete calibration, not targeted probes")
    if summary.get("articulations") != len(rows) or not rows:
        raise ValueError("full capture requires every calibration articulation row")
    if (calibration.get("session_sha256") != session_sha256
            or preset.get("sha256") != preset_sha256
            or preset.get("loaded_confirmed") is not True):
        raise ValueError("full capture requires the exact current session and loaded SD3 preset")


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
                        confirm_capture: bool = False,
                        active_sd3_title: str | None = None,
                        confirm_midi_map: bool = False) -> tuple[str, ...]:
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
        campaign_document: dict[str, object] | None = None
        if campaign_path.is_file():
            try:
                loaded_campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
                campaign_document = loaded_campaign if isinstance(loaded_campaign, dict) else None
                declared_id = campaign_document.get("id") if campaign_document is not None else None
                if isinstance(declared_id, str) and declared_id:
                    identifier = declared_id
            except (OSError, json.JSONDecodeError):
                pass
        if campaign_document is not None:
            _validate_campaign_session_contract(campaign_document, session)
        command = (sys.executable, "-m", "drum_sampler.cli")
        if action in {"capture", "capture-composites"}:
            if not confirm_capture:
                raise ValueError(f"{action} requires explicit confirmation")
            if campaign_document is not None:
                preset_path, preset_sha256 = _resolve_sd3_preset(campaign_document)
                verify_active_sd3_preset(campaign_document, active_sd3_title)
                if not confirm_midi_map:
                    raise ValueError("capture requires explicit confirmation of the declared SD3 MIDI map")
                calibration_path = reports / "calibration.json"
                try:
                    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raise ValueError(
                        "full capture requires a passing calibration for the exact current session and loaded SD3 preset"
                    )
                _validate_passing_calibration(
                    calibration,
                    session_sha256=_sha256_file(session),
                    preset_sha256=preset_sha256,
                )
            if action == "capture-composites":
                if megakit_plan is None and campaign_document is not None:
                    declared_plan = campaign_document.get("megakit_plan_file")
                    if isinstance(declared_plan, str) and declared_plan:
                        megakit_plan = Path(declared_plan)
                if megakit_plan is None:
                    raise ValueError("simultaneous layered-center capture requires the reviewed MegaKit plan")
                if campaign_document is not None:
                    expected_takes = campaign_document.get("expected_take_count")
                    if not isinstance(expected_takes, int):
                        raise ValueError("campaign expected_take_count is invalid")
                    _validate_passing_capture_quality(reports / "quality.json", library, expected_takes, session)
                return (*command, "capture-composites", "--session", str(session),
                        "--megakit-plan", str(megakit_plan),
                        "--output-directory", str(run_directory / "drumgizmo-composite-wav"),
                        "--quality-report", str(reports / "composite-quality.json"),
                        "--confirm-capture")
            return (*command, "capture", "--session", str(session), "--raw-directory", str(raw),
                    "--library-output", str(library), "--id", identifier, "--source", "sd3",
                    "--license", "SD3 capture for personal kit development", "--confirm-capture")
        if action == "calibrate":
            if not confirm_capture:
                raise ValueError("calibration requires explicit confirmation")
            if campaign_document is None:
                raise ValueError("calibration requires a valid campaign.json with an SD3 preset identity")
            preset_path, preset_sha256 = _resolve_sd3_preset(campaign_document)
            verify_active_sd3_preset(campaign_document, active_sd3_title)
            if not confirm_midi_map:
                raise ValueError("calibration requires explicit confirmation of the declared SD3 MIDI map")
            return (*command, "calibrate", "--session", str(session),
                    "--preset-file", str(preset_path),
                    "--expected-preset-sha256", preset_sha256,
                    "--output-directory", str(run_directory / "calibration-wav"),
                    "--report", str(reports / "calibration.json"),
                    "--preferred-velocity", "110", "--duration-seconds", "1.5",
                    "--confirm-capture", "--confirm-preset-loaded")
        if action == "audit-quality":
            quality_command = (*command, "audit-quality", "--library", str(library), "--audio-root", str(raw),
                               "--output", str(reports / "quality.json"), "--session", str(session))
            if campaign_document is not None:
                sample_rate = campaign_document.get("sample_rate")
                channels = campaign_document.get("channels")
                if isinstance(sample_rate, int):
                    quality_command += ("--expected-sample-rate", str(sample_rate))
                if isinstance(channels, list) and channels:
                    quality_command += ("--expected-channels", str(len(channels)))
            return quality_command
        if action == "export-drumgizmo":
            if note_map is None:
                raise ValueError("DrumGizmo export requires a compiled note map")
            if megakit_plan is None:
                raise ValueError("MegaKit DrumGizmo export requires its reviewed MegaKit plan")
            if campaign_document is not None:
                expected_takes = campaign_document.get("expected_take_count")
                if not isinstance(expected_takes, int):
                    raise ValueError("campaign expected_take_count is invalid")
                _validate_passing_capture_quality(reports / "quality.json", library, expected_takes, session)
                from .campaign import drumgizmo_composite_filenames
                composite_filenames = drumgizmo_composite_filenames(megakit_plan)
                if composite_filenames:
                    _validate_passing_composite_quality(
                        reports / "composite-quality.json", session_path=session,
                        plan_path=megakit_plan,
                        composite_root=run_directory / "drumgizmo-composite-wav",
                        expected_filenames=composite_filenames,
                    )
            export_command = (*command, "export-drumgizmo", "--library", str(library), "--audio-root", str(raw),
                              "--output-directory", str(run_directory / "drumgizmo-kit"), "--note-map", str(note_map),
                              "--megakit-plan", str(megakit_plan))
            return (*export_command, "--report", str(reports / "drumgizmo-export.json"))
        if action == "verify-drumgizmo":
            return (*command, "verify-drumgizmo", "--kit-directory", str(run_directory / "drumgizmo-kit"),
                    "--report", str(reports / "drumgizmo-verify.json"))
        if action == "validate-drumgizmo":
            return (*command, "validate-drumgizmo", "--kit-directory", str(run_directory / "drumgizmo-kit"),
                    "--report", str(reports / "drumgizmo-validation.json"))
        raise ValueError(f"unsupported sampler action: {action}")

    def run_sampler(self, action: str, run_directory: Path, *, note_map: Path | None = None,
                    megakit_plan: Path | None = None,
                    confirm_capture: bool = False, active_sd3_title: str | None = None,
                    confirm_midi_map: bool = False, dry_run: bool = False) -> CommandResult:
        command = self.sampler_command(action, run_directory, note_map=note_map, megakit_plan=megakit_plan,
                                       confirm_capture=confirm_capture, active_sd3_title=active_sd3_title,
                                       confirm_midi_map=confirm_midi_map)
        if dry_run:
            return CommandResult(command, None, dry_run=True)
        completed = self._runner(command, **_offline_run_options())
        return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)

    @staticmethod
    def ddti_command(action: str, dump: Path, *, preset: Path | None = None,
                     layout: Path | None = None, output: Path | None = None,
                     name: str | None = None) -> tuple[str, ...]:
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
        if action == "apply-role-preset":
            if preset is None or layout is None or output is None:
                raise ValueError("DDTi apply-role-preset requires a generated role template, input layout, and staged output")
            return (sys.executable, "-m", "ddti.cli", action, str(dump), str(preset), str(layout), str(output))
        if action == "diff":
            if preset is None:
                raise ValueError("DDTi diff requires a second dump")
            return (sys.executable, "-m", "ddti.cli", action, str(dump), str(preset))
        raise ValueError(f"unsupported offline DDTi action: {action}")

    def run_ddti(self, action: str, dump: Path, *, preset: Path | None = None,
                 layout: Path | None = None, output: Path | None = None, name: str | None = None,
                 dry_run: bool = False) -> CommandResult:
        command = self.ddti_command(action, dump, preset=preset, layout=layout, output=output, name=name)
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
