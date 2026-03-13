# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""NavigationManager -- trace navigation (zoom, pan, scroll, fit, jump) logic
extracted from VasoAnalyzerApp."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QKeySequence, QAction

if TYPE_CHECKING:
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

logger = logging.getLogger(__name__)


class NavigationManager(QObject):
    """Manages trace navigation: zoom, pan, scroll, fit, jump-to operations."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

    # ------------------------------------------------------------------
    # Full-view reset
    # ------------------------------------------------------------------

    def reset_to_full_view(self) -> None:
        """Restore the plot to the stored full-view limits."""
        h = self._host
        if h.xlim_full is None:
            h.xlim_full = h.ax.get_xlim()
        if h.ylim_full is None:
            h.ylim_full = h.ax.get_ylim()

        if h.xlim_full is not None:
            h._apply_time_window(h.xlim_full)
        h.ax.set_ylim(h.ylim_full)
        h.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Shortcut registration
    # ------------------------------------------------------------------

    def _register_trace_nav_shortcuts(self) -> None:
        h = self._host
        if getattr(h, "_trace_nav_shortcuts", None):
            return
        h._trace_nav_shortcuts: list[QAction] = []

        def _add_action(label: str, shortcut: str, handler) -> None:
            action = QAction(label, h)
            action.setShortcut(shortcut)
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(handler)
            h.addAction(action)
            h._trace_nav_shortcuts.append(action)

        zoom_all = QAction("Zoom to All (X)", h)
        zoom_all.setShortcuts([QKeySequence("0"), QKeySequence("Ctrl+0")])
        zoom_all.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        zoom_all.triggered.connect(self._zoom_all_x)
        h.addAction(zoom_all)
        h._trace_nav_shortcuts.append(zoom_all)
        h.actZoomAllX = zoom_all

        _add_action("Pan Left (10%)", "Left", lambda: self._pan_window_fraction(0.10, -1))
        _add_action("Pan Right (10%)", "Right", lambda: self._pan_window_fraction(0.10, 1))
        _add_action(
            "Pan Left (50%)", "Shift+Left", lambda: self._pan_window_fraction(0.50, -1)
        )
        _add_action(
            "Pan Right (50%)", "Shift+Right", lambda: self._pan_window_fraction(0.50, 1)
        )
        _add_action("Jump to Start", "Home", self._jump_to_start)
        _add_action("Jump to End", "End", self._jump_to_end)

        _add_action("Previous Event", "[", lambda: self._jump_to_event(-1))
        _add_action("Next Event", "]", lambda: self._jump_to_event(1))

    # ------------------------------------------------------------------
    # Go-to time dialog
    # ------------------------------------------------------------------

    def show_goto_time_dialog(self) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None:
            return
        full_range = plot_host.full_range() if hasattr(plot_host, "full_range") else None
        current_window = (
            plot_host.current_window() if hasattr(plot_host, "current_window") else None
        )
        if full_range is None and current_window is None:
            return
        cursor_available = h._time_cursor_time is not None

        from vasoanalyzer.ui.dialogs.goto_time_dialog import GotoTimeDialog

        dialog = GotoTimeDialog(
            h,
            full_range=full_range,
            current_window=current_window,
            cursor_available=cursor_available,
        )
        if not dialog.exec():
            return
        time_value = dialog.time_value()
        if time_value is None:
            return
        mode = dialog.mode()
        if mode == "cursor":
            h.jump_to_time(float(time_value), source="cursor")
        else:
            h.jump_to_time(float(time_value), source="manual")

    # ------------------------------------------------------------------
    # Jump helpers
    # ------------------------------------------------------------------

    def _jump_to_start(self) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "full_range"):
            return
        full_range = plot_host.full_range()
        if full_range is None:
            return
        start, end = full_range
        span = None
        window = plot_host.current_window() if hasattr(plot_host, "current_window") else None
        if window is not None:
            span = window[1] - window[0]
        if span is None or span <= 0 or span >= (end - start):
            h._apply_time_window(full_range)
            return
        h._apply_time_window((start, start + span))

    def _jump_to_end(self) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "full_range"):
            return
        full_range = plot_host.full_range()
        if full_range is None:
            return
        start, end = full_range
        span = None
        window = plot_host.current_window() if hasattr(plot_host, "current_window") else None
        if window is not None:
            span = window[1] - window[0]
        if span is None or span <= 0 or span >= (end - start):
            h._apply_time_window(full_range)
            return
        h._apply_time_window((end - span, end))

    # ------------------------------------------------------------------
    # Pan / scroll
    # ------------------------------------------------------------------

    def _pan_window_fraction(self, fraction: float, direction: int) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "current_window"):
            return
        window = plot_host.current_window()
        if window is None:
            return
        span = float(window[1] - window[0])
        if span <= 0:
            return
        from vasoanalyzer.ui.plots.pyqtgraph_nav_math import pan_step

        delta = pan_step(span, fraction) * (1 if direction >= 0 else -1)
        plot_host.scroll_by(delta)

    # ------------------------------------------------------------------
    # Event navigation
    # ------------------------------------------------------------------

    def _jump_to_event(self, direction: int) -> None:
        h = self._host
        times = sorted(h._overview_event_times())
        if not times:
            return
        plot_host = getattr(h, "plot_host", None)
        current = h._time_cursor_time
        if current is None:
            window = plot_host.current_window() if plot_host is not None else None
            if window is not None:
                current = 0.5 * (window[0] + window[1])
            else:
                current = times[0]
        idx = 0
        if direction > 0:
            for i, t in enumerate(times):
                if t > current:
                    idx = i
                    break
            else:
                return
        else:
            for i in range(len(times) - 1, -1, -1):
                if times[i] < current:
                    idx = i
                    break
            else:
                return
        h.jump_to_time(float(times[idx]), from_event=True, source="event")

    # ------------------------------------------------------------------
    # Zoom operations
    # ------------------------------------------------------------------

    def _zoom_all_x(self) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "full_range"):
            if (
                hasattr(plot_host, "get_render_backend")
                and plot_host.get_render_backend() == "pyqtgraph"
                and hasattr(plot_host, "zoom_to_full_range")
            ):
                full = plot_host.full_range()
                if full is not None:
                    h._set_xrange_source("zoom.all", (float(full[0]), float(full[1])))
                else:
                    h._set_xrange_source("zoom.all", None)
                plot_host.zoom_to_full_range()
                return
            full = plot_host.full_range()
            if full is not None:
                h._set_xrange_source("zoom.all", (float(full[0]), float(full[1])))
                h._apply_time_window(full)
                return
        if h.xlim_full is not None:
            h._set_xrange_source(
                "zoom.all",
                (float(h.xlim_full[0]), float(h.xlim_full[1])),
            )
            h._apply_time_window(h.xlim_full)

    def reset_view(self, checked: bool = False) -> None:
        """Reset view to full extent.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self.reset_to_full_view()

    def fit_to_data(self, checked: bool = False) -> None:
        """Fit view to full data bounds (delegates to _zoom_all_x for PyQtGraph).

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self._zoom_all_x()

    def zoom_to_selection(self, checked: bool = False) -> None:
        """Zoom to current selection, or to full data range if no selection is active.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        h = self._host
        range_sel = getattr(h, "_range_selection", None)
        if range_sel is not None:
            t0, t1 = range_sel
            h._apply_time_window((t0, t1))
        else:
            self._zoom_all_x()

    def zoom_out(self, factor: float = 1.5, x_only: bool = True) -> None:
        """Zoom out by ``factor`` around the current view's center.

        ``factor`` is relative to the current axis span. Limits are clamped to
        the full data range so repeated zooming never drifts beyond the
        available data. This ensures zooming always begins from the current
        view rather than an arbitrary level.
        """
        h = self._host

        if h.xlim_full is None:
            h.xlim_full = h.ax.get_xlim()
        if h.ylim_full is None:
            h.ylim_full = h.ax.get_ylim()

        xmin, xmax = h.ax.get_xlim()
        ymin, ymax = h.ax.get_ylim()

        x_center = (xmin + xmax) / 2
        y_center = (ymin + ymax) / 2

        x_half = (xmax - xmin) * factor / 2
        y_half = (ymax - ymin) * factor / 2

        new_xmin, new_xmax = x_center - x_half, x_center + x_half
        new_ymin, new_ymax = y_center - y_half, y_center + y_half

        if h.xlim_full is not None:
            new_xmin = max(new_xmin, h.xlim_full[0])
            new_xmax = min(new_xmax, h.xlim_full[1])
        if h.ylim_full is not None:
            new_ymin = max(new_ymin, h.ylim_full[0])
            new_ymax = min(new_ymax, h.ylim_full[1])

        h._apply_time_window((new_xmin, new_xmax))
        if not x_only:
            h.ax.set_ylim(new_ymin, new_ymax)
        h.canvas.draw_idle()
        h.update_scroll_slider()

    # ------------------------------------------------------------------
    # Fit helpers
    # ------------------------------------------------------------------

    def fit_x_full(self) -> None:
        h = self._host
        if h.trace_data is None or h.ax is None:
            return
        if (
            h.trace_model is not None
            and getattr(h.trace_model, "time_full", None) is not None
        ):
            times = h.trace_model.time_full
            if getattr(times, "size", 0):
                span = (float(times[0]), float(times[-1]))
            else:
                span = h.ax.get_xlim()
        else:
            series = h.trace_data.get("Time (s)")
            if series is None or series.empty:
                return
            values = series.to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            if values.size == 0:
                return
            span = (float(values.min()), float(values.max()))
        h._apply_time_window(span)
        h.update_scroll_slider()
        h.canvas.draw_idle()

    def fit_y_in_current_x(self) -> None:
        h = self._host
        if h.trace_data is None or h.ax is None:
            return
        x0, x1 = h.ax.get_xlim()
        if not np.isfinite(x0) or not np.isfinite(x1) or x0 == x1:
            return
        times = h.trace_data["Time (s)"].to_numpy(dtype=float)
        mask = (times >= x0) & (times <= x1)
        inner = h.trace_data["Inner Diameter"].to_numpy(dtype=float)
        y_min, y_max = self._value_range(inner, mask)
        if not np.isfinite(y_min) or not np.isfinite(y_max):
            return
        pad = max((y_max - y_min) * 0.05, 0.5)
        h.ax.set_ylim(y_min - pad, y_max + pad)

        if h.ax2 is not None and "Outer Diameter" in h.trace_data.columns:
            outer = h.trace_data["Outer Diameter"].to_numpy(dtype=float)
            o_min, o_max = self._value_range(outer, mask)
            if np.isfinite(o_min) and np.isfinite(o_max):
                opad = max((o_max - o_min) * 0.05, 0.5)
                h.ax2.set_ylim(o_min - opad, o_max + opad)
        h.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _value_range(values: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
        if values.size == 0:
            return float("nan"), float("nan")
        subset = values
        if (
            isinstance(mask, np.ndarray)
            and mask.dtype == bool
            and mask.size == values.size
        ) and mask.any():
            subset = values[mask]
        subset = subset[np.isfinite(subset)]
        if subset.size == 0:
            subset = values[np.isfinite(values)]
        if subset.size == 0:
            return float("nan"), float("nan")
        return float(np.min(subset)), float(np.max(subset))
