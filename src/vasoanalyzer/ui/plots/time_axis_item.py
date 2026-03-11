"""PyQtGraph AxisItem that formats x-ticks with the shared time formatter."""

from __future__ import annotations

from typing import Iterable

import pyqtgraph as pg

from vasoanalyzer.ui.formatting.time_format import TimeFormatter, TimeMode, coerce_time_mode

__all__ = ["TimeAxisItem"]


class TimeAxisItem(pg.AxisItem):
    def __init__(
        self,
        *args,
        formatter: TimeFormatter | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._formatter = formatter or TimeFormatter(TimeMode.AUTO)

    def set_time_mode(self, mode: TimeMode | str) -> None:
        self._formatter.set_mode(coerce_time_mode(mode))
        # Reset accumulated textHeight so stale values don't poison
        # the textFillLimits density check in generateDrawSpecs.
        self.textHeight = self.style.get("tickTextHeight", 18)
        self.picture = None
        self.update()

    def time_mode(self) -> TimeMode:
        return self._formatter.mode

    def tickStrings(self, values: Iterable[float], scale: float, spacing: float):
        return [self._formatter.format(float(value)) for value in values]
