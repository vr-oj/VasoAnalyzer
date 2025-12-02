"""Interpolation helpers for manual point editing."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

__all__ = [
    "linear_bridge",
    "cubic_hermite_bridge",
]


def _find_neighbor(
    values: np.ndarray,
    forbidden: set[int],
    start_idx: int,
    step: int,
) -> int | None:
    idx = start_idx
    n = len(values)
    while 0 <= idx < n:
        if idx not in forbidden and np.isfinite(values[idx]):
            return idx
        idx += step
    return None


def _estimate_slope(
    time: np.ndarray,
    values: np.ndarray,
    anchor_idx: int,
    direction: int,
    forbidden: set[int],
) -> float | None:
    neighbor = _find_neighbor(values, forbidden, anchor_idx + direction, direction)
    if neighbor is None:
        return None
    dt = float(time[anchor_idx] - time[neighbor])
    if dt == 0:
        return None
    return float(values[anchor_idx] - values[neighbor]) / dt


def linear_bridge(
    time: np.ndarray,
    values: np.ndarray,
    indices: Sequence[int],
    *,
    left_idx: int,
    right_idx: int,
) -> np.ndarray:
    """Linear interpolation between ``left_idx`` and ``right_idx`` covering indices."""

    span = float(time[right_idx] - time[left_idx])
    if span == 0.0:
        return np.full(len(indices), values[left_idx], dtype=float)

    left_val = float(values[left_idx])
    right_val = float(values[right_idx])
    out = np.empty(len(indices), dtype=float)
    for pos, idx in enumerate(indices):
        u = (float(time[idx]) - float(time[left_idx])) / span
        out[pos] = (1.0 - u) * left_val + u * right_val
    return out


def cubic_hermite_bridge(
    time: np.ndarray,
    clean_values: np.ndarray,
    raw_values: np.ndarray,
    indices: Sequence[int],
    *,
    left_idx: int,
    right_idx: int,
    forbidden: Iterable[int],
) -> np.ndarray:
    """Slope-preserving cubic Hermite bridge over the selected indices."""

    forbidden_set = {int(i) for i in forbidden}
    span = float(time[right_idx] - time[left_idx])
    if span <= 0.0:
        return linear_bridge(time, clean_values, indices, left_idx=left_idx, right_idx=right_idx)

    left_val = float(clean_values[left_idx])
    right_val = float(clean_values[right_idx])
    if not (np.isfinite(left_val) and np.isfinite(right_val)):
        return np.full(len(indices), np.nan, dtype=float)

    secant = (right_val - left_val) / span

    slope_left = _estimate_slope(time, raw_values, left_idx, -1, forbidden_set)
    slope_right = _estimate_slope(time, raw_values, right_idx, +1, forbidden_set)
    if slope_left is None:
        slope_left = secant
    if slope_right is None:
        slope_right = secant

    if np.isclose(right_val, left_val):
        slope_left = 0.0
        slope_right = 0.0
    else:
        sign = np.sign(right_val - left_val)
        if slope_left * sign < 0:
            slope_left = 0.0
        if slope_right * sign < 0:
            slope_right = 0.0

    out = np.empty(len(indices), dtype=float)
    for pos, idx in enumerate(indices):
        u = (float(time[idx]) - float(time[left_idx])) / span
        u = min(max(u, 0.0), 1.0)
        h00 = (2 * u**3) - (3 * u**2) + 1
        h10 = (u**3) - (2 * u**2) + u
        h01 = (-2 * u**3) + (3 * u**2)
        h11 = (u**3) - (u**2)
        out[pos] = (
            h00 * left_val + h10 * span * slope_left + h01 * right_val + h11 * span * slope_right
        )
    return out
