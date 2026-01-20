"""Helpers for deterministic event selection synchronization."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

EventRow = Sequence[Any]


def event_time_for_row(row: EventRow | None) -> float | None:
    """Return the event time in seconds for a row, or None when unavailable."""
    if row is None or len(row) < 2:
        return None
    try:
        value = float(row[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def pick_event_row(rows: Iterable[int], event_table_data: Sequence[EventRow]) -> int | None:
    """Pick a deterministic row from a multi-selection (earliest time, then lowest index)."""
    candidates: set[int] = set()
    for row in rows:
        try:
            candidates.add(int(row))
        except (TypeError, ValueError):
            continue
    candidates = sorted(candidates)
    if not candidates:
        return None
    valid = [row for row in candidates if 0 <= row < len(event_table_data)]
    if not valid:
        return None
    timed = []
    for row in valid:
        event_time = event_time_for_row(event_table_data[row])
        if event_time is not None:
            timed.append((event_time, row))
    if timed:
        timed.sort(key=lambda item: (item[0], item[1]))
        return timed[0][1]
    return valid[0]
