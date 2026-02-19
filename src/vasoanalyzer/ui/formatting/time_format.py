"""Shared time formatter for axis ticks, tables, and readouts."""

from __future__ import annotations

import math
from enum import Enum

__all__ = ["TimeMode", "TimeFormatter", "coerce_time_mode"]


class TimeMode(str, Enum):
    AUTO = "auto"
    SECONDS = "seconds"
    MMSS = "mm:ss"
    HHMMSS = "hh:mm:ss"


def coerce_time_mode(value: object) -> TimeMode:
    if isinstance(value, TimeMode):
        return value
    raw = str(value or "").strip().lower()
    aliases = {
        "auto": TimeMode.AUTO,
        "seconds": TimeMode.SECONDS,
        "second": TimeMode.SECONDS,
        "s": TimeMode.SECONDS,
        "mm:ss": TimeMode.MMSS,
        "mmss": TimeMode.MMSS,
        "min:sec": TimeMode.MMSS,
        "hh:mm:ss": TimeMode.HHMMSS,
        "hhmmss": TimeMode.HHMMSS,
        "hms": TimeMode.HHMMSS,
    }
    return aliases.get(raw, TimeMode.AUTO)


def _format_seconds(value: float, decimals: int) -> str:
    return f"{float(value):.{max(0, int(decimals))}f}"


def _format_mmss(value: float) -> str:
    sign = "-" if float(value) < 0 else ""
    total = abs(float(value))
    minutes = int(total // 60.0)
    seconds = total - (minutes * 60.0)

    rounded = int(round(seconds))
    if abs(seconds - rounded) < 0.005:
        if rounded >= 60:
            minutes += 1
            rounded = 0
        sec_text = f"{rounded:02d}"
    else:
        sec_text = f"{seconds:05.2f}"
    return f"{sign}{minutes:02d}:{sec_text}"


def _format_hhmmss(value: float) -> str:
    sign = "-" if float(value) < 0 else ""
    total = abs(float(value))
    hours = int(total // 3600.0)
    rem = total - (hours * 3600.0)
    minutes = int(rem // 60.0)
    seconds = rem - (minutes * 60.0)

    rounded = int(round(seconds))
    if abs(seconds - rounded) < 0.005:
        if rounded >= 60:
            minutes += 1
            rounded = 0
        if minutes >= 60:
            hours += 1
            minutes = 0
        sec_text = f"{rounded:02d}"
    else:
        sec_text = f"{seconds:05.2f}"
    return f"{sign}{hours:02d}:{minutes:02d}:{sec_text}"


class TimeFormatter:
    """Format seconds using a unified display mode."""

    def __init__(self, mode: TimeMode = TimeMode.AUTO, *, seconds_decimals: int = 2) -> None:
        self._mode = coerce_time_mode(mode)
        self._seconds_decimals = max(0, int(seconds_decimals))

    @property
    def mode(self) -> TimeMode:
        return self._mode

    def set_mode(self, mode: TimeMode | str) -> None:
        self._mode = coerce_time_mode(mode)

    def _effective_mode(self, seconds: float) -> TimeMode:
        if self._mode != TimeMode.AUTO:
            return self._mode
        abs_seconds = abs(float(seconds))
        if abs_seconds < 120.0:
            return TimeMode.SECONDS
        if abs_seconds < 3600.0:
            return TimeMode.MMSS
        return TimeMode.HHMMSS

    def format(self, seconds: float) -> str:
        if not math.isfinite(float(seconds)):
            return "--"
        mode = self._effective_mode(float(seconds))
        if mode == TimeMode.SECONDS:
            return _format_seconds(float(seconds), self._seconds_decimals)
        if mode == TimeMode.MMSS:
            return _format_mmss(float(seconds))
        return _format_hhmmss(float(seconds))

    def format_range(self, t0: float, t1: float) -> str:
        return f"{self.format(float(t0))} - {self.format(float(t1))}"
