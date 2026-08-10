"""Objective, non-destructive comparison of source and DDrum4 render WAVs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly


def _float_mono(path: Path) -> tuple[int, np.ndarray]:
    if not path.is_file():
        raise ValueError(f"render WAV is missing: {path}")
    rate, values = wavfile.read(path)
    if values.size == 0:
        raise ValueError(f"render WAV is empty: {path}")
    if np.issubdtype(values.dtype, np.integer):
        values = values.astype(np.float64) / max(abs(np.iinfo(values.dtype).min), np.iinfo(values.dtype).max)
    else:
        values = values.astype(np.float64)
    if values.ndim > 1:
        values = np.mean(values, axis=1)
    return int(rate), values


def _dbfs(value: float) -> float:
    return -float("inf") if value <= 0 else float(20 * np.log10(value))


def _onset(values: np.ndarray) -> int:
    peak = float(np.max(np.abs(values)))
    if not peak:
        raise ValueError("render WAV is silent")
    # A relative threshold is robust to intentionally different module gain.
    active = np.flatnonzero(np.abs(values) >= peak * 0.01)
    return int(active[0]) if active.size else 0


def _tail_seconds(values: np.ndarray, rate: int) -> float:
    peak = float(np.max(np.abs(values)))
    active = np.flatnonzero(np.abs(values) >= peak * (10 ** (-48 / 20)))
    return 0.0 if not active.size else float(active[-1] / rate)


def _centroid_hz(values: np.ndarray, rate: int) -> float:
    window = values[:min(len(values), max(256, round(rate * 0.12)))]
    if len(window) < 8:
        return 0.0
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    total = float(np.sum(spectrum))
    if not total:
        return 0.0
    return float(np.sum(np.fft.rfftfreq(len(window), 1 / rate) * spectrum) / total)


@dataclass(frozen=True)
class RenderComparison:
    source_path: str
    source_sha256: str
    module_path: str
    module_sha256: str
    sample_rate: int
    source_peak_dbfs: float
    module_peak_dbfs: float
    module_minus_source_peak_db: float
    source_tail_seconds: float
    module_tail_seconds: float
    module_minus_source_tail_seconds: float
    source_centroid_hz: float
    module_centroid_hz: float
    module_minus_source_centroid_hz: float
    onset_delta_ms: float
    module_pre_onset_rms_dbfs: float

    def to_document(self) -> dict[str, object]:
        return {"schema_version": 1, "kind": "ddrum4-render-comparison", **asdict(self)}


def compare_renders(source: Path, module: Path) -> RenderComparison:
    """Measure differences without judging their musical acceptability."""
    source_rate, source_values = _float_mono(source)
    module_rate, module_values = _float_mono(module)
    if source_rate != module_rate:
        module_values = resample_poly(module_values, source_rate, module_rate)
        module_rate = source_rate
    source_onset = _onset(source_values)
    module_onset = _onset(module_values)
    pre_onset = module_values[:module_onset]
    module_noise = float(np.sqrt(np.mean(np.square(pre_onset)))) if pre_onset.size else 0.0
    source_peak = float(np.max(np.abs(source_values)))
    module_peak = float(np.max(np.abs(module_values)))
    source_tail = _tail_seconds(source_values[source_onset:], source_rate)
    module_tail = _tail_seconds(module_values[module_onset:], module_rate)
    source_centroid = _centroid_hz(source_values[source_onset:], source_rate)
    module_centroid = _centroid_hz(module_values[module_onset:], module_rate)
    return RenderComparison(
        str(source), sha256(source.read_bytes()).hexdigest(), str(module), sha256(module.read_bytes()).hexdigest(), source_rate,
        _dbfs(source_peak), _dbfs(module_peak), _dbfs(module_peak) - _dbfs(source_peak),
        source_tail, module_tail, module_tail - source_tail,
        source_centroid, module_centroid, module_centroid - source_centroid,
        1000 * (module_onset / module_rate - source_onset / source_rate), _dbfs(module_noise),
    )
