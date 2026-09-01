"""Offline, reproducible capture quality gates.

These checks intentionally classify a take; they never delete or replace raw
audio.  Musical suitability (tail character, bleed and articulation) remains
an explicit audition decision.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any
from collections import defaultdict

import numpy as np
from scipy.io import wavfile

from .audio import _to_float, analyze_wav
from .library import SampleLibrary


@dataclass(frozen=True)
class CaptureQualityPolicy:
    minimum_duration_ms: int = 80
    silence_rms_dbfs: float = -75.0
    reject_clipped: bool = True
    expected_sample_rate: int | None = None
    expected_channels: int | None = None

    def __post_init__(self) -> None:
        if (self.minimum_duration_ms < 1 or
                (self.expected_sample_rate is not None and self.expected_sample_rate < 8000) or
                (self.expected_channels is not None and not 1 <= self.expected_channels <= 4)):
            raise ValueError("capture quality duration, sample rate, or channel count is invalid")


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
    if policy.expected_sample_rate is not None and int(facts["sample_rate"]) != policy.expected_sample_rate:
        findings.append("wrong_sample_rate")
    if policy.expected_channels is not None and int(facts["channels"]) != policy.expected_channels:
        findings.append("wrong_channel_count")
    variation_fingerprint: str | None = None
    if np.any(active):
        frame_peak = np.max(np.abs(samples), axis=1)
        peak = float(np.max(frame_peak))
        onset_candidates = np.flatnonzero(frame_peak >= max(activity_floor, peak * 0.02))
        if onset_candidates.size:
            onset = int(onset_candidates[0])
            stop = min(samples.shape[0], onset + round(int(facts["sample_rate"]) * 0.25))
            transient = samples[onset:stop]
            transient_peak = float(np.max(np.abs(transient))) if transient.size else 0.0
            if transient_peak > 0:
                # Onset alignment and amplitude normalization make this hash
                # detect a repeated source waveform even when capture preroll
                # or gain differs slightly. Twelve-bit quantisation ignores
                # irrelevant float noise while retaining transient character.
                quantized = np.round(np.clip(transient / transient_peak, -1.0, 1.0) * 2047).astype("<i2")
                variation_fingerprint = hashlib.sha256(quantized.tobytes()).hexdigest()
    return {
        "path": str(path),
        "duration_ms": duration_ms,
        "facts": facts,
        "automatic_status": "accepted" if not findings else "rejected",
        "findings": findings,
        "variation_fingerprint_sha256": variation_fingerprint,
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
    rr_groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        rr_groups[(record["instrument"], record["articulation"], record["velocity"])].append(record)
    duplicate_round_robins: list[dict[str, Any]] = []
    for (instrument, articulation, velocity), group in sorted(rr_groups.items()):
        hashes = [record.get("variation_fingerprint_sha256") for record in group
                  if record.get("automatic_status") == "accepted"]
        hashes = [value for value in hashes if isinstance(value, str)]
        if len(group) > 1 and len(hashes) == len(group) and len(set(hashes)) < len(hashes):
            duplicate_round_robins.append({
                "instrument": instrument, "articulation": articulation,
                "velocity": velocity, "repetitions": len(group),
                "unique_audio_fingerprints": len(set(hashes)),
            })
    counts["round_robin_duplicate_cells"] = len(duplicate_round_robins)
    return {"kind": "capture-quality-report", "schema_version": 1,
            "policy": {"minimum_duration_ms": policy.minimum_duration_ms,
                       "silence_rms_dbfs": policy.silence_rms_dbfs,
                       "reject_clipped": policy.reject_clipped,
                       "expected_sample_rate": policy.expected_sample_rate,
                       "expected_channels": policy.expected_channels},
            "summary": counts, "round_robin_duplicates": duplicate_round_robins,
            "takes": records}
