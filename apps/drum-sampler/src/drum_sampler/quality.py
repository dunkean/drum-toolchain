"""Offline, reproducible capture quality gates.

These checks intentionally classify a take; they never delete or replace raw
audio.  Musical suitability (tail character, bleed and articulation) remains
an explicit audition decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import wavfile

from .audio import _to_float, analyze_wav
from .library import SampleLibrary


@dataclass(frozen=True)
class CaptureQualityPolicy:
    minimum_duration_ms: int = 80
    silence_rms_dbfs: float = -75.0
    reject_clipped: bool = True

    def __post_init__(self) -> None:
        if self.minimum_duration_ms < 1:
            raise ValueError("minimum_duration_ms must be positive")


def assess_wav(path: Path, policy: CaptureQualityPolicy = CaptureQualityPolicy()) -> dict[str, Any]:
    """Return facts and deterministic automatic gate findings for one WAV."""
    facts = analyze_wav(path)
    duration_ms = round(1000 * int(facts["frames"]) / int(facts["sample_rate"]))
    findings: list[str] = []
    if duration_ms < policy.minimum_duration_ms:
        findings.append("too_short")
    # A retained long recording window deliberately makes the full-file RMS
    # very low for short one-shots. Test whether any audio is present above
    # the configured floor instead of rejecting a real hit because its tail
    # is mostly digital silence.
    _, raw = wavfile.read(path)
    samples = _to_float(raw)
    if samples.ndim == 1:
        samples = samples[:, None]
    activity_floor = 10 ** (policy.silence_rms_dbfs / 20.0)
    active = np.max(np.abs(samples), axis=1) >= activity_floor
    if not np.any(active):
        findings.append("silent")
    if policy.reject_clipped and bool(facts["clipped"]):
        findings.append("clipped")
    return {
        "path": str(path),
        "duration_ms": duration_ms,
        "facts": facts,
        "automatic_status": "accepted" if not findings else "rejected",
        "findings": findings,
        "audition_status": "pending",
    }


def audit_library(library: SampleLibrary, audio_root: Path,
                  policy: CaptureQualityPolicy = CaptureQualityPolicy()) -> dict[str, Any]:
    """Audit every present raw take without changing the library or WAVs."""
    records: list[dict[str, Any]] = []
    for take in library.takes:
        path = audio_root / take.raw_file
        record: dict[str, Any] = {
            "instrument": take.instrument,
            "articulation": take.articulation,
            "velocity": take.velocity,
            "repetition": take.repetition,
        }
        if path.is_file():
            record.update(assess_wav(path, policy))
        else:
            record.update({"path": str(path), "automatic_status": "missing", "findings": ["missing_raw"], "audition_status": "pending"})
        records.append(record)
    counts = {status: sum(record["automatic_status"] == status for record in records)
              for status in ("accepted", "rejected", "missing")}
    return {"kind": "capture-quality-report", "schema_version": 1,
            "policy": {"minimum_duration_ms": policy.minimum_duration_ms,
                       "silence_rms_dbfs": policy.silence_rms_dbfs,
                       "reject_clipped": policy.reject_clipped},
            "summary": counts, "takes": records}
