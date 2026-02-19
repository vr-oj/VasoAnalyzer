"""Synchronize left-axis widths across stacked PyQtGraph tracks."""

from __future__ import annotations

import contextlib
import math
import time
import weakref
from collections.abc import Iterable

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtGui import QFontMetricsF
from PyQt5.QtWidgets import QApplication

__all__ = ["AxisWidthSync"]


class AxisWidthSync(QObject):
    """Keep all registered axes at the same width with shrink hysteresis."""

    def __init__(
        self,
        *,
        shrink_delay_s: float = 0.5,
        axis_padding_px: float = 8.0,
        min_axis_width_px: int = 48,
        left_gutter_px: int = 0,
    ) -> None:
        super().__init__()
        self._axis_refs: list[weakref.ReferenceType] = []
        self._shrink_delay_s = max(float(shrink_delay_s), 0.0)
        self._axis_padding_px = max(float(axis_padding_px), 0.0)
        self._min_axis_width_px = max(int(min_axis_width_px), 0)
        self._left_gutter_px = max(int(left_gutter_px), 0)
        self._current_axis_width_px = 0
        self._shrink_candidate_width: int | None = None
        self._shrink_candidate_since: float | None = None
        self._shrink_timer = QTimer(self)
        self._shrink_timer.setSingleShot(True)
        self._shrink_timer.timeout.connect(self.request_sync)

    def set_axes(self, axes: Iterable[object]) -> None:
        """Replace the tracked axes set."""
        self._axis_refs.clear()
        for axis in axes:
            if axis is None:
                continue
            self._axis_refs.append(weakref.ref(axis))
        self.request_sync()

    def add_axis(self, axis: object) -> None:
        if axis is None:
            return
        self._axis_refs.append(weakref.ref(axis))
        self.request_sync()

    def clear(self) -> None:
        self._axis_refs.clear()
        self._current_axis_width_px = 0
        self._shrink_candidate_width = None
        self._shrink_candidate_since = None
        with contextlib.suppress(Exception):
            self._shrink_timer.stop()

    def set_left_gutter_px(self, width_px: int) -> None:
        self._left_gutter_px = max(int(width_px), 0)

    def left_gutter_px(self) -> int:
        return int(self._left_gutter_px)

    def axis_width_px(self) -> int:
        return int(self._current_axis_width_px)

    def left_column_width_px(self) -> int:
        return int(self._current_axis_width_px + self._left_gutter_px)

    def request_sync(self) -> None:
        axes = self._alive_axes()
        if not axes:
            return

        measured = max((self._measure_axis_width(axis) for axis in axes), default=0)
        required = max(int(measured), int(self._min_axis_width_px))
        now = time.monotonic()

        if required > self._current_axis_width_px:
            self._apply_axis_width(required, axes)
            self._clear_shrink_candidate()
            return

        if required == self._current_axis_width_px:
            self._clear_shrink_candidate()
            return

        if (
            self._shrink_candidate_width is None
            or required != int(self._shrink_candidate_width)
            or self._shrink_candidate_since is None
        ):
            self._shrink_candidate_width = int(required)
            self._shrink_candidate_since = now

        elapsed = now - float(self._shrink_candidate_since)
        if elapsed >= self._shrink_delay_s:
            self._apply_axis_width(int(self._shrink_candidate_width), axes)
            self._clear_shrink_candidate()
            return

        remaining_s = max(self._shrink_delay_s - elapsed, 0.0)
        with contextlib.suppress(Exception):
            self._shrink_timer.start(int(max(1, math.ceil(remaining_s * 1000.0))))

    def _clear_shrink_candidate(self) -> None:
        self._shrink_candidate_width = None
        self._shrink_candidate_since = None
        with contextlib.suppress(Exception):
            self._shrink_timer.stop()

    def _alive_axes(self) -> list[object]:
        alive: list[object] = []
        next_refs: list[weakref.ReferenceType] = []
        for ref in self._axis_refs:
            axis = ref()
            if axis is None:
                continue
            alive.append(axis)
            next_refs.append(ref)
        self._axis_refs = next_refs
        return alive

    def _apply_axis_width(self, width_px: int, axes: Iterable[object]) -> None:
        target = max(int(width_px), 0)
        self._current_axis_width_px = target
        for axis in axes:
            with contextlib.suppress(Exception):
                axis.setWidth(target)

    def _measure_axis_width(self, axis: object) -> int:
        try:
            if hasattr(axis, "isVisible") and not axis.isVisible():
                return 0
        except Exception:
            pass

        geometry_widths: list[float] = []
        tick_text_widths: list[float] = []
        label_width = 0.0

        with contextlib.suppress(Exception):
            geometry_widths.append(float(axis.boundingRect().width()))
        with contextlib.suppress(Exception):
            geometry_widths.append(float(axis.size().width()))
        with contextlib.suppress(Exception):
            geometry_widths.append(float(axis.width()))

        tick_font = None
        with contextlib.suppress(Exception):
            tick_font = axis.style.get("tickFont")
        if tick_font is None:
            tick_font = QApplication.font()
        metrics = QFontMetricsF(tick_font)

        with contextlib.suppress(Exception):
            linked_view = axis.linkedView()
            if linked_view is not None:
                orientation = str(getattr(axis, "orientation", "")).lower()
                view_range = linked_view.viewRange()
                if orientation in {"left", "right"}:
                    axis_min, axis_max = view_range[1]
                    pixel_extent = max(int(linked_view.height()), 1)
                else:
                    axis_min, axis_max = view_range[0]
                    pixel_extent = max(int(linked_view.width()), 1)
                tick_levels = axis.tickValues(float(axis_min), float(axis_max), pixel_extent)
                scale = float(getattr(axis, "scale", 1.0) or 1.0)
                for spacing, values in tick_levels:
                    tick_strings = axis.tickStrings(values, scale, spacing)
                    for text in tick_strings:
                        width_px = 0.0
                        with contextlib.suppress(AttributeError):
                            width_px = float(metrics.horizontalAdvance(str(text)))
                        if width_px <= 0.0:
                            with contextlib.suppress(Exception):
                                width_px = float(metrics.width(str(text)))
                        tick_text_widths.append(width_px)

        with contextlib.suppress(Exception):
            label = getattr(axis, "label", None)
            if label is not None:
                label_rect = label.boundingRect()
                label_width = max(label_width, float(label_rect.height()))

        tick_text_offset = 0.0
        with contextlib.suppress(Exception):
            tick_text_offset = float(axis.style.get("tickTextOffset", 0) or 0.0)

        if tick_text_widths:
            measured = max(
                (value for value in tick_text_widths if math.isfinite(value)),
                default=0.0,
            )
        else:
            measured = max(
                (value for value in geometry_widths if math.isfinite(value)),
                default=0.0,
            )
        measured = max(measured, label_width)
        measured += tick_text_offset + self._axis_padding_px
        return max(int(math.ceil(measured)), 0)
