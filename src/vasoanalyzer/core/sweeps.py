"""Triggered sweep extraction utilities."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vasoanalyzer.core.trace_model import TraceModel


@dataclass
class TriggerConfig:
    """Configuration for detecting waveform triggers."""

    component: str  # "inner" or "outer"
    threshold: float
    direction: str  # "rising" or "falling"
    pre_window: float
    post_window: float
    min_interval: float = 0.0


@dataclass
class SweepResult:
    """Container with captured sweeps and their averages."""

    relative_time: np.ndarray
    triggers: np.ndarray
    inner_sweeps: np.ndarray
    outer_sweeps: np.ndarray | None
    average_inner: np.ndarray | None
    average_outer: np.ndarray | None

    @property
    def count(self) -> int:
        return int(self.inner_sweeps.shape[0])

    def has_outer(self) -> bool:
        return self.outer_sweeps is not None and self.outer_sweeps.size > 0


def compute_sweeps(model: TraceModel, config: TriggerConfig) -> SweepResult:
    """Capture triggered sweeps from ``model`` according to ``config``."""

    if config.pre_window < 0 or config.post_window < 0:
        raise ValueError("pre_window and post_window must be non-negative")

    component = config.component.lower()
    if component not in {"inner", "outer"}:
        raise ValueError("component must be 'inner' or 'outer'")

    time = model.time_full
    if time.size < 2:
        raise ValueError("TraceModel must contain at least two samples")

    if component == "outer":
        signal = model.outer_full
        if signal is None:
            raise ValueError("Outer diameter data is not available in this model")
    else:
        signal = model.inner_full

    signal = np.asarray(signal, dtype=float)
    mask_valid = np.isfinite(signal)
    if not mask_valid.all():
        signal = signal.copy()
        signal[~mask_valid] = np.nan

    triggers = _detect_triggers(time, signal, config.threshold, config.direction)
    if config.min_interval > 0:
        triggers = _enforce_min_interval(triggers, config.min_interval)

    dt = float(np.nanmedian(np.diff(time)))
    total_window = float(config.pre_window + config.post_window)
    samples = 1 if total_window <= 0 else int(max(round(total_window / dt), 1)) + 1
    relative = np.linspace(-config.pre_window, config.post_window, samples)

    kept_triggers = []
    inner_sweeps = []
    outer_sweeps = []
    inner_full = model.inner_full.astype(float, copy=False)
    outer_full = None if model.outer_full is None else model.outer_full.astype(float, copy=False)

    for center in triggers:
        target_times = center + relative
        inner_vals = np.interp(target_times, time, inner_full, left=np.nan, right=np.nan)
        if np.isnan(inner_vals).any():
            continue
        outer_vals = None
        if outer_full is not None:
            outer_vals = np.interp(target_times, time, outer_full, left=np.nan, right=np.nan)
            if np.isnan(outer_vals).any():
                outer_vals = None
        inner_sweeps.append(inner_vals)
        if outer_vals is not None:
            outer_sweeps.append(outer_vals)
        kept_triggers.append(center)

    if not inner_sweeps:
        inner_array = np.empty((0, samples))
        outer_array = None
        avg_inner = None
        avg_outer = None
        triggers_arr = np.empty((0,), dtype=float)
    else:
        inner_array = np.vstack(inner_sweeps)
        triggers_arr = np.asarray(kept_triggers, dtype=float)
        avg_inner = np.mean(inner_array, axis=0)
        if outer_sweeps:
            outer_array = np.vstack(outer_sweeps)
            avg_outer = np.mean(outer_array, axis=0)
        elif outer_full is not None:
            outer_array = np.empty((0, samples))
            avg_outer = None
        else:
            outer_array = None
            avg_outer = None

    return SweepResult(
        relative_time=relative,
        triggers=triggers_arr,
        inner_sweeps=inner_array,
        outer_sweeps=outer_array,
        average_inner=avg_inner,
        average_outer=avg_outer,
    )


def _detect_triggers(
    time: np.ndarray, signal: np.ndarray, threshold: float, direction: str
) -> np.ndarray:
    if signal.size != time.size:
        raise ValueError("signal and time arrays must be the same length")

    direction = direction.lower()
    valid = np.isfinite(signal)
    sig = signal.astype(float, copy=False)
    sig[~valid] = np.nan

    lead = sig[:-1]
    trail = sig[1:]
    t0 = time[:-1]
    t1 = time[1:]

    if direction == "rising":
        crossings = (lead < threshold) & (trail >= threshold)
    elif direction == "falling":
        crossings = (lead > threshold) & (trail <= threshold)
    else:
        raise ValueError("direction must be 'rising' or 'falling'")

    indices = np.nonzero(crossings & np.isfinite(lead) & np.isfinite(trail))[0]
    if indices.size == 0:
        return np.empty((0,), dtype=float)

    trigger_times = []
    for idx in indices:
        y0 = lead[idx]
        y1 = trail[idx]
        x0 = t0[idx]
        x1 = t1[idx]
        if y1 == y0:
            trigger_times.append(x1)
        else:
            frac = (threshold - y0) / (y1 - y0)
            frac = np.clip(frac, 0.0, 1.0)
            trigger_times.append(x0 + frac * (x1 - x0))
    return np.asarray(trigger_times, dtype=float)


def _enforce_min_interval(triggers: np.ndarray, min_interval: float) -> np.ndarray:
    if triggers.size == 0 or min_interval <= 0:
        return triggers
    accepted = [triggers[0]]
    last = triggers[0]
    for time in triggers[1:]:
        if time - last >= min_interval:
            accepted.append(time)
            last = time
    return np.asarray(accepted, dtype=float)
