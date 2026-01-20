from __future__ import annotations

import math

TIME_SCROLLBAR_SCALE = 1_000_000


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_scrollbar_state(
    t0: float,
    t1: float,
    win_start: float,
    win_end: float,
    *,
    scale: int = TIME_SCROLLBAR_SCALE,
) -> tuple[int, int]:
    """Return scrollbar value and page step for the current time window."""
    scale = int(scale) if int(scale) > 0 else TIME_SCROLLBAR_SCALE
    if not all(math.isfinite(val) for val in (t0, t1, win_start, win_end)):
        return 0, scale

    total = t1 - t0
    if total <= 0:
        return 0, scale

    win_width = max(0.0, win_end - win_start)
    page_step = int(round((win_width / total) * scale)) if win_width > 0 else 1
    page_step = int(_clamp(page_step, 1, scale))

    max_start = t1 - win_width
    if max_start < t0:
        max_start = t0
    win_start = float(_clamp(win_start, t0, max_start))

    value = int(round(((win_start - t0) / total) * scale))
    value = int(_clamp(value, 0, max(0, scale - page_step)))
    return value, page_step


def window_from_scroll_value(
    value: int,
    *,
    t0: float,
    t1: float,
    current_width: float,
    max_value: int,
) -> tuple[float, float]:
    """Return a time window from the scrollbar value, preserving width."""
    if not all(math.isfinite(val) for val in (t0, t1, current_width)):
        start = float(t0) if math.isfinite(t0) else 0.0
        width = float(current_width) if math.isfinite(current_width) else 0.0
        return start, start + max(0.0, width)

    total = max(0.0, float(t1) - float(t0))
    width = max(0.0, min(float(current_width), total))
    travel = max(0.0, total - width)
    if max_value <= 0 or travel <= 0.0:
        start = float(t0)
        return start, start + width

    frac = float(value) / float(max_value)
    start = float(t0) + frac * travel
    start = _clamp(start, float(t0), float(t0) + travel)
    return float(start), float(start + width)


def compute_window_start(
    t0: float,
    t1: float,
    win_width: float,
    value: int,
    *,
    scale: int = TIME_SCROLLBAR_SCALE,
) -> float:
    """Map scrollbar value to window start, clamped to the trace range."""
    start, _end = window_from_scroll_value(
        value,
        t0=t0,
        t1=t1,
        current_width=win_width,
        max_value=int(scale),
    )
    return start
