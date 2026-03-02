"""Pure math helpers for PyQtGraph navigation and styling policies."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TickStyle:
    """Discrete tick density + label spacing policy."""

    density: float
    text_offset: int
    text_width: int
    text_height: int


ZOOM_STEP_IN = 0.9
ZOOM_STEP_OUT = 1.1


def pan_step(window_span: float, fraction: float) -> float:
    """Return pan delta for a given window span and fraction."""
    if not math.isfinite(window_span) or window_span <= 0:
        return 0.0
    return float(window_span) * float(fraction)


def zoomed_range(
    x_min: float,
    x_max: float,
    anchor: float | None,
    factor: float,
    *,
    min_span: float | None = None,
    max_span: float | None = None,
) -> tuple[float, float]:
    """Return a zoomed range anchored at a specific data coordinate."""
    span = float(x_max) - float(x_min)
    if not math.isfinite(span) or span <= 0:
        return float(x_min), float(x_max)
    if not math.isfinite(factor) or factor <= 0:
        return float(x_min), float(x_max)

    new_span = span * float(factor)
    if min_span is not None:
        new_span = max(new_span, float(min_span))
    if max_span is not None:
        new_span = min(new_span, float(max_span))

    if anchor is None or not math.isfinite(anchor):
        anchor = 0.5 * (float(x_min) + float(x_max))

    ratio = (float(anchor) - float(x_min)) / span
    ratio = max(0.0, min(1.0, ratio))

    new_x_min = float(anchor) - new_span * ratio
    new_x_max = new_x_min + new_span
    return float(new_x_min), float(new_x_max)


def font_size_for_trace_count(base_size: float, trace_count: int) -> float:
    """Return a stable font size regardless of trace count."""
    _ = max(int(trace_count), 0)
    return float(base_size)


def tick_style_for_trace_count(trace_count: int) -> TickStyle:
    """Return discrete tick density and padding values for a trace count."""
    count = max(int(trace_count), 0)
    if count <= 2:
        density = 1.0
    elif count <= 4:
        density = 0.7
    else:
        density = 0.55
    return TickStyle(density=density, text_offset=6, text_width=34, text_height=18)
    if count <= 4:
        return TickStyle(density=0.85, text_offset=5, text_width=30, text_height=16)
    return TickStyle(density=0.7, text_offset=4, text_width=28, text_height=14)
