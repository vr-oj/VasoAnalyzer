"""Deterministic sample data helpers shared across tests."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import List, Sequence, Tuple

import numpy as np
import pandas as pd

_RNG = np.random.default_rng(20250204)


@lru_cache(maxsize=1)
def synthetic_time_series() -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return canonical time, inner, and outer diameter arrays."""

    times = np.linspace(0.0, 60.0, 600, dtype=float)
    base = 40.0 + 6.5 * np.sin(times / 7.5) + 2.1 * np.cos(times / 2.8)
    inner = base + 0.6 * np.sin(times / 0.9) + 0.35 * np.cos(times / 3.7)
    noise = _RNG.normal(scale=0.15, size=times.shape)
    inner = inner + noise
    outer = base + 4.0 + 0.5 * np.sin(times / 5.2)
    return times, inner.astype(float), outer.astype(float)


@dataclass(frozen=True)
class EventRecord:
    time: float
    label: str
    frame: int


def canonical_events() -> List[EventRecord]:
    """Return a curated list of events used throughout the tests."""

    labels = [
        "Baseline",
        "Stimulus",
        "Valve open",
        "Valve verify",
        "Pressure spike",
        "Sensor trip",
        "Intervention",
        "Stabilise",
    ]
    times = [2.5, 5.0, 5.1, 8.4, 12.0, 15.0, 22.5, 30.0]
    frames = [int(t * 4) for t in times]
    return [EventRecord(time=t, label=lbl, frame=frm) for t, lbl, frm in zip(times, labels, frames)]


def trace_dataframe() -> pd.DataFrame:
    """Return a pandas DataFrame formatted like an imported trace."""

    times, inner, outer = synthetic_time_series()
    return pd.DataFrame(
        {
            "Time (s)": times,
            "Inner Diameter": inner,
            "Outer Diameter": outer,
        }
    )


def events_dataframe() -> pd.DataFrame:
    """Return a pandas DataFrame containing deterministic events."""

    records = canonical_events()
    return pd.DataFrame(
        {
            "Time": [rec.time for rec in records],
            "EventLabel": [rec.label for rec in records],
            "Frame": [rec.frame for rec in records],
        }
    )


def event_tuples() -> List[Tuple[float, str]]:
    """Return event tuples for direct plotting helpers."""

    return [(rec.time, rec.label) for rec in canonical_events()]


def snapshot_array(width: int = 192, height: int = 128) -> np.ndarray:
    """Return a pseudo-snapshot image used for overlay tests."""

    y, x = np.mgrid[0:height, 0:width]
    baseline = np.sin(x / 9.5) + np.cos(y / 13.3)
    ripple = np.sin(0.25 * np.hypot(x - width / 2.2, y - height / 3.7))
    gradient = (x / width) * 0.8 + (y / height) * 0.2
    data = baseline + 0.7 * ripple + gradient
    data = (data - data.min()) / (data.max() - data.min())
    return data.astype(np.float32)
