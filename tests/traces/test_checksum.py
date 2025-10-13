"""Deterministic hash checks for TraceModel.window outputs."""

from __future__ import annotations

import hashlib

import numpy as np

from vasoanalyzer.core.trace_model import TraceModel

from tests._sample_data import synthetic_time_series


def _window_digest(window) -> str:
    digest = hashlib.sha256()

    def _update(arr: np.ndarray | None) -> None:
        if arr is None:
            return
        digest.update(np.asarray(arr, dtype="<f8").tobytes())

    _update(window.time)
    _update(window.inner_mean)
    _update(window.inner_min)
    _update(window.inner_max)
    _update(window.outer_mean)
    _update(window.outer_min)
    _update(window.outer_max)
    return digest.hexdigest()


def test_trace_window_hash_is_stable():
    time, inner, outer = synthetic_time_series()
    model = TraceModel(time=time, inner=inner, outer=outer)
    level = model.best_level_for_window(5.0, 30.0, pixel_width=720)
    window = model.window(level, 5.0, 30.0)
    # Expected digest generated via the helper above (documented for reproducibility).
    expected = "91cbd0cc39368affab27dd26c6f46e4e230cbb203e744a4480c1a337c0bed49b"
    assert _window_digest(window) == expected
