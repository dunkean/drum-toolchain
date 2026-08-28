"""Bounded SD3 signal calibration before a long capture campaign."""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from pathlib import Path
import time
from typing import Callable

from .audio import analyze_wav, capture_note
from .session import CaptureSessionPlan


CaptureFunction = Callable[..., Path]
ProgressFunction = Callable[[int, int, dict[str, object]], None]


def _selected_velocity(velocities: tuple[int, ...], preferred: int) -> int:
    return min(velocities, key=lambda value: (abs(value - preferred), -value))


def _safe_level(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if isfinite(converted) else None


def calibrate_session(
    session: CaptureSessionPlan,
    output_directory: Path,
    *,
    session_sha256: str,
    preset_path: Path,
    preset_sha256: str,
    preset_loaded_confirmed: bool,
    preferred_velocity: int = 110,
    duration_seconds: float = 1.5,
    silence_peak_dbfs: float = -60.0,
    minimum_headroom_db: float = 0.5,
    relative_outlier_db: float = 18.0,
    only: tuple[str, ...] = (),
    capture: CaptureFunction = capture_note,
    progress: ProgressFunction | None = None,
) -> dict[str, object]:
    """Capture/reuse one representative hit per articulation and report levels.

    This is deliberately not the sample library: tails and every round robin
    are left to the complete resumable campaign after the signal path passes.
    """
    if not 1 <= preferred_velocity <= 127 or duration_seconds <= 0:
        raise ValueError("preferred velocity and calibration duration are invalid")
    if not preset_loaded_confirmed:
        raise ValueError("the exact SD3 preset must be explicitly confirmed as loaded")
    if len(session_sha256) != 64 or len(preset_sha256) != 64:
        raise ValueError("session and preset SHA-256 values are required")
    if minimum_headroom_db < 0 or relative_outlier_db <= 0:
        raise ValueError("calibration level thresholds are invalid")
    requested_ids = tuple(dict.fromkeys(only))
    available_ids = {
        f"{request.instrument}.{request.articulation}"
        for request in session.requests
    }
    missing_ids = sorted(set(requested_ids) - available_ids)
    if missing_ids:
        raise ValueError(f"unknown calibration articulation selectors: {missing_ids}")
    selected_requests = tuple(
        request for request in session.requests
        if not requested_ids or f"{request.instrument}.{request.articulation}" in requested_ids
    )
    if not selected_requests:
        raise ValueError("calibration selection is empty")
    probe_identity = hashlib.sha256(json.dumps({
        "session_sha256": session_sha256,
        "preset_sha256": preset_sha256,
        "preferred_velocity": preferred_velocity,
        "duration_seconds": duration_seconds,
    }, sort_keys=True).encode("utf-8")).hexdigest()
    probe_directory = output_directory / probe_identity[:16]
    probe_directory.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    captured_count = 0
    for index, request in enumerate(selected_requests, start=1):
        velocity = _selected_velocity(request.velocities, preferred_velocity)
        controller_label = "".join(f"__cc{control:03d}-{value:03d}" for control, value in request.controllers)
        filename = (
            f"{request.instrument}__{request.articulation}__n{request.note:03d}"
            f"__v{velocity:03d}{controller_label}_calibration.wav"
        )
        output = probe_directory / filename
        reused = output.is_file()
        if not reused:
            capture(
                midi_port=session.midi_output,
                audio_input=session.audio_input,
                note=request.note,
                velocity=velocity,
                output=output,
                channel=request.channel,
                controllers=request.controllers,
                duration=duration_seconds,
                gate=session.gate_ms / 1000,
                preroll=session.preroll_ms / 1000,
                sample_rate=session.sample_rate,
                channels=len(session.channels),
            )
            captured_count += 1
            if session.cooldown_ms:
                time.sleep(session.cooldown_ms / 1000)
        facts = analyze_wav(output)
        peak = _safe_level(facts.get("peak_dbfs"))
        rms = _safe_level(facts.get("rms_dbfs"))
        findings: list[str] = []
        if peak is None or peak < silence_peak_dbfs:
            findings.append("silent")
        if bool(facts.get("clipped")):
            findings.append("clipped")
        if peak is not None and peak > -minimum_headroom_db:
            findings.append("insufficient-headroom")
        row: dict[str, object] = {
            "instrument": request.instrument,
            "articulation": request.articulation,
            "note": request.note,
            "channel": request.channel,
            "controllers": [list(pair) for pair in request.controllers],
            "velocity": velocity,
            "file": str(output.relative_to(output_directory)),
            "reused": reused,
            "peak_dbfs": peak,
            "rms_dbfs": rms,
            "clipped": bool(facts.get("clipped")),
            "sha256": facts["sha256"],
            "findings": findings,
        }
        rows.append(row)
        if progress is not None:
            progress(index, len(selected_requests), row)

    valid_peaks = [float(row["peak_dbfs"]) for row in rows if row["peak_dbfs"] is not None]
    loudest = max(valid_peaks) if valid_peaks else None
    relative_outliers: list[str] = []
    if loudest is not None:
        for row in rows:
            peak = row["peak_dbfs"]
            if isinstance(peak, float) and peak < loudest - relative_outlier_db:
                relative_outliers.append(f"{row['instrument']}.{row['articulation']}")
                row["findings"].append("relative-level-outlier")  # type: ignore[union-attr]
    technical_failures = sum(
        any(finding in {"silent", "clipped", "insufficient-headroom"} for finding in row["findings"])
        for row in rows
    )
    return {
        "format": "sd3-calibration-report/v1",
        "session_sha256": session_sha256,
        "preset": {
            "path": str(preset_path),
            "sha256": preset_sha256,
            "loaded_confirmed": preset_loaded_confirmed,
        },
        "probe_set_id": probe_identity,
        "midi_output": session.midi_output,
        "audio_input": session.audio_input,
        "sample_rate": session.sample_rate,
        "channels": list(session.channels),
        "policy": {
            "preferred_velocity": preferred_velocity,
            "duration_seconds": duration_seconds,
            "silence_peak_dbfs": silence_peak_dbfs,
            "minimum_headroom_db": minimum_headroom_db,
            "relative_outlier_db": relative_outlier_db,
            "only": list(requested_ids),
        },
        "rows": rows,
        "summary": {
            "articulations": len(rows),
            "captured_now": captured_count,
            "reused": len(rows) - captured_count,
            "technical_failures": technical_failures,
            "relative_level_outliers": relative_outliers,
            "loudest_peak_dbfs": loudest,
            "quietest_peak_dbfs": min(valid_peaks) if valid_peaks else None,
            "peak_span_db": (loudest - min(valid_peaks)) if loudest is not None else None,
            "status": "technical-fail" if technical_failures else "technical-pass-user-mix-review-required",
        },
    }


def calibrate_session_file(
    session_path: Path,
    preset_path: Path,
    output_directory: Path,
    report_path: Path,
    *,
    expected_preset_sha256: str | None = None,
    preset_loaded_confirmed: bool = False,
    **kwargs: object,
) -> dict[str, object]:
    payload = session_path.read_bytes()
    preset_payload = preset_path.read_bytes()
    preset_sha256 = hashlib.sha256(preset_payload).hexdigest()
    if expected_preset_sha256 is not None and preset_sha256 != expected_preset_sha256.lower():
        raise ValueError(
            f"SD3 preset SHA-256 mismatch: expected {expected_preset_sha256.lower()}, got {preset_sha256}"
        )
    report = calibrate_session(
        CaptureSessionPlan.read(session_path),
        output_directory,
        session_sha256=hashlib.sha256(payload).hexdigest(),
        preset_path=preset_path.resolve(),
        preset_sha256=preset_sha256,
        preset_loaded_confirmed=preset_loaded_confirmed,
        **kwargs,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    return report
