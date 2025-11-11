from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["TraceWindow", "ensure_float_array"]


@dataclass(frozen=True)
class TraceWindow:
    """Lightweight container for a window of trace data."""

    time: np.ndarray
    inner_mean: np.ndarray
    inner_min: np.ndarray
    inner_max: np.ndarray
    outer_mean: np.ndarray | None = None
    outer_min: np.ndarray | None = None
    outer_max: np.ndarray | None = None
    avg_pressure_mean: np.ndarray | None = None
    avg_pressure_min: np.ndarray | None = None
    avg_pressure_max: np.ndarray | None = None
    set_pressure_mean: np.ndarray | None = None
    set_pressure_min: np.ndarray | None = None
    set_pressure_max: np.ndarray | None = None


def ensure_float_array(data: np.ndarray) -> np.ndarray:
    """Return a contiguous 1-D float array for downstream computations."""

    arr = np.asarray(data, dtype=float)
    if arr.ndim != 1:
        raise ValueError("Trace arrays must be 1-D")
    return np.ascontiguousarray(arr)
