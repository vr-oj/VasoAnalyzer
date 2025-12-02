"""Minimal Figure Composer window for quick matplotlib preview."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
)
from matplotlib.backends.backend_qt5agg import (
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from PyQt5 import QtCore
from PyQt5.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QGuiApplication
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.plot_host import LayoutState

__all__ = ["FigureComposerWindow"]

log = logging.getLogger(__name__)

# Keep side event labels close to their dashed lines
EVENT_LABEL_X_OFFSET_FRACTION = 0.005


class MinimalNavigationToolbar(NavigationToolbar):
    """
    Navigation toolbar variant that exposes only the core navigation tools.
    """

    toolitems = [
        item
        for item in NavigationToolbar.toolitems
        if item is not None and item[0] in ("Home", "Back", "Forward", "Pan", "Zoom")
    ]


class FigureComposerWindow(QMainWindow):
    """Lightweight composer that previews the current trace in matplotlib."""

    preset_saved = pyqtSignal(dict)
    studio_closed = pyqtSignal()
    annotations_changed = pyqtSignal(list)
    figure_state_saved = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Figure Composer")

        self.trace_model: TraceModel | None = None
        self.event_colors: list[str] = []
        self.event_times: list[float] = []
        self.event_labels: list[str] = []
        self.event_label_meta: list[dict[str, Any]] = []
        self.channel_specs: list[ChannelTrackSpec] = []
        self.layout_state: Any = None
        self.style_dict: dict[str, Any] | None = None
        self.annotations: Any = None
        self.figure_state: Any = None
        self._current_window: tuple[float, float] | None = None
        self._grid_enabled: bool = True
        self._graph_width_in: float = 0.0
        self._graph_height_in: float = 0.0
        self._graph_aspect_ratio: float | None = None
        self._graph_units: str = "mm"
        self._is_updating_graph_size: bool = False

        self.x_label_edit: QLineEdit | None = None
        self.y_label_edit: QLineEdit | None = None
        self.grid_checkbox: QCheckBox | None = None
        self.xmin_spin: QDoubleSpinBox | None = None
        self.xmax_spin: QDoubleSpinBox | None = None
        self.ymin_spin: QDoubleSpinBox | None = None
        self.ymax_spin: QDoubleSpinBox | None = None
        self.axis_label_fontsize_spin: QSpinBox | None = None
        self.trace_linewidth_spin: QDoubleSpinBox | None = None
        self._trace_lines: list = []
        self.tick_fontsize_spin: QSpinBox | None = None
        self.x_tick_rotation_combo: QComboBox | None = None
        self.max_xticks_spin: QSpinBox | None = None
        self.label_bold_checkbox: QCheckBox | None = None
        self.label_italic_checkbox: QCheckBox | None = None
        self.tick_bold_checkbox: QCheckBox | None = None
        self.tick_italic_checkbox: QCheckBox | None = None
        self.trace_selector: QComboBox | None = None
        self._selected_track_id: str | None = None
        self.style_copy_button: QPushButton | None = None
        self.style_apply_button: QPushButton | None = None
        self._style_clipboard: dict[str, Any] | None = None
        self.trace_color_button: QPushButton | None = None
        self._trace_color_overrides: dict[str, str] = {}
        self.show_events_checkbox: QCheckBox | None = None
        self.event_fontsize_spin: QSpinBox | None = None
        self.event_y_spin: QDoubleSpinBox | None = None
        self._show_events: bool = True
        self.event_label_style_combo: QComboBox | None = None
        self._event_label_style: str = "side_v"
        self._event_y_position: float | None = None
        self._is_rendering: bool = False

        self.figure, self.canvas, self.ax = self._build_canvas()
        self.canvas_scroll = QScrollArea(self)
        self.canvas_scroll.setWidgetResizable(False)
        self.canvas_scroll.setFrameShape(QFrame.NoFrame)
        self.canvas_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.canvas_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.canvas_scroll.setWidget(self.canvas)
        self._xlim_cid = self.ax.callbacks.connect(
            "xlim_changed", self._on_axes_limits_changed_from_matplotlib
        )
        self._ylim_cid = self.ax.callbacks.connect(
            "ylim_changed", self._on_axes_limits_changed_from_matplotlib
        )
        self._controls_widget = QWidget(self)
        self._build_controls_panel()
        controls_scroll = QScrollArea(self)
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QScrollArea.NoFrame)
        controls_scroll.setWidget(self._controls_widget)

        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Horizontal)

        canvas_container = QWidget(splitter)
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        self.toolbar = MinimalNavigationToolbar(self.canvas, canvas_container)
        canvas_layout.addWidget(self.toolbar)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        canvas_layout.addWidget(self.canvas_scroll)

        splitter.addWidget(controls_scroll)
        splitter.addWidget(canvas_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        central = QWidget(self)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(splitter)
        self.setCentralWidget(central)
        splitter.setSizes([300, 900])

        self._init_graph_size_state()
        self._update_canvas_size_from_figure()

        # Give the composer a comfortable default size and keep it resizable
        self.resize(1500, 900)
        # Used to only center on the first show
        self._first_show = True
        log.info("[FIGURE_COMPOSER] window created")

    # ------------------------------------------------------------------ public API
    def load_from_main_window(
        self,
        trace_model: TraceModel | None,
        event_times,
        event_colors,
        event_labels,
        event_label_meta,
        channel_specs,
        layout_state,
        style_dict,
        annotations,
        figure_state,
        *,
        current_window: tuple[float, float] | None = None,
    ) -> None:
        """Clone state from the main window and render a simple preview."""
        log.info(
            "[FIGURE_COMPOSER] load_from_main_window: trace_model=%s n_events=%d "
            "n_channel_specs=%d layout_visibility=%s",
            type(trace_model).__name__ if trace_model is not None else None,
            len(event_times) if event_times is not None else 0,
            len(channel_specs) if channel_specs is not None else 0,
            (
                getattr(layout_state, "visibility", None)
                if isinstance(layout_state, LayoutState)
                else (
                    getattr(layout_state, "get", lambda *_: None)("visibility")
                    if isinstance(layout_state, dict)
                    else None
                )
            ),
        )

        self.trace_model = trace_model
        self.event_colors = list(event_colors or [])
        self.event_times = list(event_times or [])
        self.event_labels = list(event_labels or [])
        self.event_label_meta = list(event_label_meta or [])
        self.channel_specs = list(channel_specs or [])
        self.layout_state = layout_state
        self.style_dict = style_dict if isinstance(style_dict, dict) else None
        self.annotations = annotations
        self.figure_state = figure_state
        self._current_window = current_window
        if getattr(self, "_event_label_style", "side_v") == "top":
            self._event_label_style = "side_v"
        # Populate trace selector from main-window visibility
        visible_specs = list(self._iter_visible_channel_specs())
        if not visible_specs:
            visible_specs = list(self.channel_specs or [])
        valid_ids = {
            getattr(spec, "track_id", None)
            for spec in visible_specs
            if getattr(spec, "track_id", None) is not None
        }
        if self.trace_selector is not None:
            self.trace_selector.blockSignals(True)
            self.trace_selector.clear()
            for spec in visible_specs:
                track_id = getattr(spec, "track_id", None)
                if track_id is None:
                    continue
                label = getattr(spec, "label", str(track_id))
                self.trace_selector.addItem(label, track_id)

            if not valid_ids:
                self._selected_track_id = None
            else:
                if self._selected_track_id not in valid_ids:
                    preferred = None
                    for spec in visible_specs:
                        if getattr(spec, "component", None) == "inner":
                            preferred = getattr(spec, "track_id", None)
                            break
                    self._selected_track_id = preferred or next(iter(valid_ids))

                for idx in range(self.trace_selector.count()):
                    if self.trace_selector.itemData(idx) == self._selected_track_id:
                        self.trace_selector.setCurrentIndex(idx)
                        break
            self.trace_selector.blockSignals(False)

        self._render_trace()
        self._sync_widgets_from_axes()

    def maximize_figure_to_canvas(self, forward: bool = True) -> None:
        """Placeholder to preserve compatibility with legacy calls."""
        del forward  # unused
        self.canvas.draw_idle()

    # ------------------------------------------------------------------ internals
    def _build_canvas(self) -> tuple[Figure, FigureCanvasQTAgg, Any]:
        figure = Figure(facecolor="white")
        canvas = FigureCanvasQTAgg(figure)
        ax = figure.add_subplot(111)
        figure.subplots_adjust(left=0.12, right=0.98, top=0.95, bottom=0.12)
        return figure, canvas, ax

    def _wrap_canvas(self, canvas: FigureCanvasQTAgg) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(canvas)
        # Legacy method retained; controls are now built in __init__ directly.
        return container

    def _update_canvas_size_from_figure(self) -> None:
        fig = getattr(self, "figure", None)
        canvas = getattr(self, "canvas", None)
        if fig is None or canvas is None:
            return

        width_in, height_in = fig.get_size_inches()
        dpi = fig.get_dpi()
        try:
            width_px = int(round(width_in * dpi))
            height_px = int(round(height_in * dpi))
        except Exception:
            return

        width_px = max(1, width_px)
        height_px = max(1, height_px)

        canvas.setFixedSize(width_px, height_px)
        canvas.updateGeometry()

        scroll = getattr(self, "canvas_scroll", None)
        if scroll is not None:
            widget = scroll.widget()
            if widget is not None:
                widget.adjustSize()

    def _init_graph_size_state(self) -> None:
        if self.figure is None:
            return
        width_in, height_in = self.figure.get_size_inches()
        self._graph_width_in = float(width_in)
        self._graph_height_in = float(height_in)
        if width_in > 0:
            self._graph_aspect_ratio = float(height_in / width_in)
        else:
            self._graph_aspect_ratio = None

        self._graph_units = "mm"
        if getattr(self, "graph_units_combo", None) is not None:
            with QtCore.QSignalBlocker(self.graph_units_combo):
                self.graph_units_combo.setCurrentText("mm")

        self._sync_graph_size_widgets_from_figure()

    def _sync_graph_size_widgets_from_figure(self) -> None:
        if self._is_updating_graph_size:
            return
        if self.figure is None:
            return
        if (
            getattr(self, "graph_width_spin", None) is None
            or getattr(self, "graph_height_spin", None) is None
        ):
            return

        self._is_updating_graph_size = True
        try:
            width_in, height_in = self.figure.get_size_inches()
            self._graph_width_in = float(width_in)
            self._graph_height_in = float(height_in)

            if (
                getattr(self, "graph_aspect_lock_checkbox", None) is not None
                and self.graph_aspect_lock_checkbox.isChecked()
            ):
                if width_in > 0:
                    self._graph_aspect_ratio = float(height_in / width_in)
                else:
                    self._graph_aspect_ratio = None

            if self._graph_units == "mm":
                width_val = width_in * 25.4
                height_val = height_in * 25.4
            else:
                width_val = width_in
                height_val = height_in

            with QtCore.QSignalBlocker(self.graph_width_spin):
                self.graph_width_spin.setValue(width_val)
            with QtCore.QSignalBlocker(self.graph_height_spin):
                self.graph_height_spin.setValue(height_val)
        finally:
            self._is_updating_graph_size = False

    def _on_graph_units_changed(self) -> None:
        if (
            getattr(self, "graph_units_combo", None) is None
            or getattr(self, "graph_width_spin", None) is None
            or getattr(self, "graph_height_spin", None) is None
        ):
            return
        if self._is_updating_graph_size:
            return

        self._is_updating_graph_size = True
        try:
            text = self.graph_units_combo.currentText().lower().strip()
            new_units = "mm" if text.startswith("mm") else "in"

            width_in = self._graph_width_in
            height_in = self._graph_height_in

            if new_units == "mm":
                width_val = width_in * 25.4
                height_val = height_in * 25.4
            else:
                width_val = width_in
                height_val = height_in

            with QtCore.QSignalBlocker(self.graph_width_spin):
                self.graph_width_spin.setValue(width_val)
            with QtCore.QSignalBlocker(self.graph_height_spin):
                self.graph_height_spin.setValue(height_val)

            self._graph_units = new_units
        finally:
            self._is_updating_graph_size = False

    def _on_graph_size_spin_changed(self) -> None:
        if (
            getattr(self, "graph_width_spin", None) is None
            or getattr(self, "graph_height_spin", None) is None
            or self.figure is None
        ):
            return
        if self._is_updating_graph_size:
            return

        sender = self.sender()
        if sender not in (self.graph_width_spin, self.graph_height_spin):
            return

        self._is_updating_graph_size = True
        try:
            units = self._graph_units
            width_val = self.graph_width_spin.value()
            height_val = self.graph_height_spin.value()

            if units == "mm":
                width_in = width_val / 25.4
                height_in = height_val / 25.4
            else:
                width_in = width_val
                height_in = height_val

            ratio = self._graph_aspect_ratio
            if (
                getattr(self, "graph_aspect_lock_checkbox", None) is not None
                and self.graph_aspect_lock_checkbox.isChecked()
                and ratio is not None
                and ratio != 0.0
            ):
                if sender is self.graph_width_spin and width_in > 0:
                    height_in = width_in * ratio
                    height_val = height_in * 25.4 if units == "mm" else height_in
                    with QtCore.QSignalBlocker(self.graph_height_spin):
                        self.graph_height_spin.setValue(height_val)
                elif sender is self.graph_height_spin:
                    width_in = height_in / ratio
                    width_val = width_in * 25.4 if units == "mm" else width_in
                    with QtCore.QSignalBlocker(self.graph_width_spin):
                        self.graph_width_spin.setValue(width_val)

            self._graph_width_in = float(width_in)
            self._graph_height_in = float(height_in)

            if (
                getattr(self, "graph_aspect_lock_checkbox", None) is not None
                and self.graph_aspect_lock_checkbox.isChecked()
            ):
                if width_in > 0:
                    self._graph_aspect_ratio = float(height_in / width_in)
                else:
                    self._graph_aspect_ratio = None

            self.figure.set_size_inches(width_in, height_in, forward=True)
            self._update_canvas_size_from_figure()
            self.canvas.draw_idle()
        finally:
            self._is_updating_graph_size = False

    def _on_graph_aspect_lock_toggled(self, checked: bool) -> None:
        if not checked:
            return
        if self._graph_width_in > 0:
            self._graph_aspect_ratio = float(self._graph_height_in / self._graph_width_in)
        else:
            self._graph_aspect_ratio = None

    def _render_trace(self) -> None:
        if getattr(self, "_is_rendering", False):
            log.debug("[FIGURE_COMPOSER][RENDER] _render_trace skipped (re-entrant guard)")
            return
        log.debug("[FIGURE_COMPOSER][RENDER] _render_trace start")
        self._is_rendering = True
        try:
            preserve_limits = False
            prev_xlim = None
            prev_ylim = None
            if self.ax is not None and self.ax.lines and self._current_window is None:
                try:
                    prev_xlim = self.ax.get_xlim()
                    prev_ylim = self.ax.get_ylim()
                    preserve_limits = True
                except Exception:
                    preserve_limits = False

            self.ax.clear()
            self._trace_lines = []
            model = self.trace_model

            if model is None:
                log.info("[FIGURE_COMPOSER][RENDER] no trace model available")
                self.ax.text(
                    0.5,
                    0.5,
                    "No trace loaded",
                    ha="center",
                    va="center",
                    color="#666666",
                    transform=self.ax.transAxes,
                )
                self.ax.set_axis_off()
                self.canvas.draw_idle()
                return

            time = getattr(model, "time_full", None)
            inner = getattr(model, "inner_full", None)
            outer = getattr(model, "outer_full", None)
            avg_pressure = getattr(model, "avg_pressure_full", None)
            set_pressure = getattr(model, "set_pressure_full", None)

            plotted = 0
            active_spec = self._get_active_spec()
            if active_spec is None:
                log.info("[FIGURE_COMPOSER][RENDER] no active channel spec to plot")
                self.ax.set_facecolor("white")
                self.ax.grid(self._grid_enabled, alpha=0.25)
                self.ax.set_xlim(0.0, 1.0)
                self.ax.set_ylim(0.0, 1.0)
                self.figure.tight_layout()
                if self.canvas is not None:
                    self.canvas.draw_idle()
                return

            component = getattr(active_spec, "component", "inner")
            label = getattr(active_spec, "label", None)
            track_id = getattr(active_spec, "track_id", None)
            color = None
            if track_id is not None:
                color = self._trace_color_overrides.get(track_id)
            if color is None:
                color = "#000000"
            if track_id is not None and track_id not in self._trace_color_overrides:
                self._trace_color_overrides[track_id] = color
            lw_value = 1.0
            if self.trace_linewidth_spin is not None:
                try:
                    lw_value = float(self.trace_linewidth_spin.value() or 1.0)
                except Exception:
                    lw_value = 1.0
            log.info(
                "[FIGURE_COMPOSER][RENDER] plotting: track_id=%s component=%s color=%s "
                "line_width=%.3f show_events=%s event_style=%s",
                track_id,
                component,
                color,
                lw_value,
                getattr(self, "_show_events", True),
                getattr(self, "_event_label_style", None),
            )

            if component in {"inner", "dual"} and inner is not None:
                (line_inner,) = self.ax.plot(
                    time,
                    inner,
                    color=color,
                    linewidth=lw_value,
                    label=label or "Inner Diameter",
                )
                self._trace_lines.append(line_inner)
                plotted += 1

            if component in {"outer", "dual"} and outer is not None:
                (line_outer,) = self.ax.plot(
                    time,
                    outer,
                    color=color,
                    linewidth=lw_value,
                    label=label or "Outer Diameter",
                )
                self._trace_lines.append(line_outer)
                plotted += 1

            if component == "avg_pressure" and avg_pressure is not None:
                (line_avg,) = self.ax.plot(
                    time,
                    avg_pressure,
                    color=color,
                    linewidth=lw_value,
                    label=label or "Avg Pressure",
                )
                self._trace_lines.append(line_avg)
                plotted += 1

            if component == "set_pressure" and set_pressure is not None:
                (line_set,) = self.ax.plot(
                    time,
                    set_pressure,
                    color=color,
                    linewidth=lw_value,
                    label=label or "Set Pressure",
                )
                self._trace_lines.append(line_set)
                plotted += 1

            self.ax.set_facecolor("white")
            self.ax.grid(self._grid_enabled, alpha=0.25)

            full_xmin = None
            full_xmax = None
            if time is not None:
                try:
                    if len(time) >= 2:
                        full_xmin = float(time[0])
                        full_xmax = float(time[-1])
                except Exception:
                    full_xmin = None
                    full_xmax = None

            if plotted == 0:
                self.ax.set_xlim(0.0, 1.0)
                self.ax.set_ylim(0.0, 1.0)
                self.figure.tight_layout()
                if self.canvas is not None:
                    self.canvas.draw_idle()
                return

            applied_window = False
            if full_xmin is not None and full_xmax is not None and self._current_window is not None:
                x0, x1 = self._current_window
                if x0 > x1:
                    x0, x1 = x1, x0
                x0 = max(full_xmin, min(x0, full_xmax))
                x1 = max(full_xmin, min(x1, full_xmax))
                if x1 > x0:
                    try:
                        self.ax.set_xlim(x0, x1)
                        applied_window = True
                    except Exception:
                        pass
                self._current_window = None

            if applied_window:
                log.debug(
                    "[FIGURE_COMPOSER][RENDER] applied_window: x0=%.3f x1=%.3f",
                    x0,
                    x1,
                )

            if (
                getattr(self, "_show_events", True)
                and self.event_times
                and self.event_labels
                and self.ax is not None
            ):
                with contextlib.suppress(Exception):
                    self._draw_events_on_axes()

            default_y_label = getattr(active_spec, "label", None) or "Value"

            if not self.ax.get_xlabel():
                self.ax.set_xlabel("Time (s)")

            if not self.ax.get_ylabel():
                self.ax.set_ylabel(default_y_label)

            if plotted > 1:
                self.ax.legend(loc="best")

            if (
                preserve_limits
                and not applied_window
                and prev_xlim is not None
                and prev_ylim is not None
            ):
                try:
                    self.ax.set_xlim(prev_xlim)
                    self.ax.set_ylim(prev_ylim)
                except Exception:
                    pass

            self.figure.tight_layout()

            self._sync_widgets_from_axes()
            self.canvas.draw_idle()
        finally:
            self._is_rendering = False
            log.debug("[FIGURE_COMPOSER][RENDER] _render_trace done")

    def _on_axes_limits_changed_from_matplotlib(self, axes) -> None:
        """Keep X/Y spin boxes in sync with the actual axes limits."""
        if axes is not self.ax:
            return
        if not (self.xmin_spin and self.xmax_spin and self.ymin_spin and self.ymax_spin):
            return
        try:
            xmin, xmax = self.ax.get_xlim()
            ymin, ymax = self.ax.get_ylim()
        except Exception:
            return
        self._sync_limits_from_axes(xmin, xmax, ymin, ymax)

    def _draw_events_on_axes(self) -> None:
        """Draw vertical event lines and stacked labels above the trace."""
        if self.ax is None:
            return
        if not (self.event_times and self.event_labels):
            return

        events = [
            (float(t), str(lbl))
            for t, lbl in zip(self.event_times, self.event_labels, strict=False)
            if t is not None and str(lbl).strip() != ""
        ]
        if not events:
            return
        events.sort(key=lambda e: e[0])

        style = getattr(self, "_event_label_style", "side_v") or "side_v"
        if style == "top":
            style = "side_v"
        log.info(
            "[FIGURE_COMPOSER][EVENTS] draw_events: style=%s n_events=%d y_pos=%s",
            style,
            len(events),
            self._event_y_position,
        )

        for t, _ in events:
            try:
                self.ax.axvline(
                    t,
                    linestyle="--",
                    linewidth=1.0,
                    color="0.5",
                    alpha=0.8,
                )
            except Exception:
                continue

        fontsize = 10
        if self.event_fontsize_spin is not None:
            fontsize = int(self.event_fontsize_spin.value() or 10)

        if style == "side_h":
            try:
                x_min, x_max = self.ax.get_xlim()
                y_min, y_max = self.ax.get_ylim()
                span_x = abs(x_max - x_min)
                span_y = abs(y_max - y_min)
                dx = max(span_x * EVENT_LABEL_X_OFFSET_FRACTION, 1e-6)
            except Exception:
                dx = 1.0
                span_y = 0.0
                y_min = 0.0

            y = self._event_y_position
            if y is None:
                y = y_min + 0.9 * span_y if span_y > 0 else y_min
                self._event_y_position = y
                if self.event_y_spin is not None:
                    self.event_y_spin.blockSignals(True)
                    self.event_y_spin.setValue(y)
                    self.event_y_spin.blockSignals(False)
            # Keep labels within current Y limits
            with contextlib.suppress(Exception):
                y = min(max(y, y_min), y_max)

            for t, label in events:
                try:
                    self.ax.text(
                        t + dx,
                        y,
                        label,
                        ha="left",
                        va="center",
                        fontsize=fontsize,
                        rotation=0,
                        clip_on=True,
                    )
                except Exception:
                    continue

        elif style == "side_v":
            try:
                x_min, x_max = self.ax.get_xlim()
                y_min, y_max = self.ax.get_ylim()
                span_x = abs(x_max - x_min)
                span_y = abs(y_max - y_min)
                dx = max(span_x * EVENT_LABEL_X_OFFSET_FRACTION, 1e-6)
            except Exception:
                dx = 1.0
                span_y = 0.0
                y_min = 0.0

            y = self._event_y_position
            if y is None:
                y = y_min + 0.5 * span_y if span_y > 0 else y_min
                self._event_y_position = y
                if self.event_y_spin is not None:
                    self.event_y_spin.blockSignals(True)
                    self.event_y_spin.setValue(y)
                    self.event_y_spin.blockSignals(False)
            # Keep labels within current Y limits
            with contextlib.suppress(Exception):
                y = min(max(y, y_min), y_max)

            for t, label in events:
                try:
                    self.ax.text(
                        t + dx,
                        y,
                        label,
                        ha="left",
                        va="center",
                        fontsize=fontsize,
                        rotation=90,
                        clip_on=True,
                    )
                except Exception:
                    continue

    def _get_active_spec(self) -> ChannelTrackSpec | None:
        visible_specs = list(self._iter_visible_channel_specs())
        if not visible_specs:
            return None
        if self._selected_track_id is not None:
            for spec in visible_specs:
                if getattr(spec, "track_id", None) == self._selected_track_id:
                    return spec
        return visible_specs[0]

    def _iter_visible_channel_specs(self):
        """Yield channel specs that were visible in the main plot."""

        visibility_map = {}
        order = []
        layout = self.layout_state
        if isinstance(layout, LayoutState):
            visibility_map = layout.visibility or {}
            order = list(layout.order or [])
        else:
            # Best-effort map if layout_state is a plain dict-like
            if isinstance(layout, dict):
                visibility_map = layout.get("visibility", {}) or {}
                order = list(layout.get("order", []) or [])

        ordered_specs = []
        if order:
            spec_lookup = {spec.track_id: spec for spec in self.channel_specs}
            ordered_specs = [spec_lookup[track_id] for track_id in order if track_id in spec_lookup]
        else:
            ordered_specs = list(self.channel_specs)

        for spec in ordered_specs:
            track_id = getattr(spec, "track_id", None)
            visible = visibility_map.get(track_id, True)
            if visible:
                yield spec

    def _build_controls_panel(self) -> None:
        """Build the grouped controls on the left panel."""
        controls_layout = QVBoxLayout(self._controls_widget)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(8)

        # Axes group
        axes_group = QGroupBox("Axes", self._controls_widget)
        axes_form = QFormLayout(axes_group)
        axes_form.setContentsMargins(8, 8, 8, 8)
        axes_form.setSpacing(6)

        self.x_label_edit = QLineEdit(self._controls_widget)
        self.y_label_edit = QLineEdit(self._controls_widget)
        self.grid_checkbox = QCheckBox("Show grid", self._controls_widget)
        self.grid_checkbox.setChecked(self._grid_enabled)
        self.xmin_spin = QDoubleSpinBox(self._controls_widget)
        self.xmax_spin = QDoubleSpinBox(self._controls_widget)
        self.ymin_spin = QDoubleSpinBox(self._controls_widget)
        self.ymax_spin = QDoubleSpinBox(self._controls_widget)
        for spin in (self.xmin_spin, self.xmax_spin, self.ymin_spin, self.ymax_spin):
            spin.setDecimals(3)
            spin.setRange(-1e9, 1e9)
            spin.setSingleStep(1.0)
        self.axis_label_fontsize_spin = QSpinBox(self._controls_widget)
        self.axis_label_fontsize_spin.setRange(6, 48)
        self.axis_label_fontsize_spin.setSingleStep(1)

        axes_form.addRow("X axis label", self.x_label_edit)
        axes_form.addRow("Y axis label", self.y_label_edit)
        axes_form.addRow(self.grid_checkbox)
        axes_form.addRow("X min", self.xmin_spin)
        axes_form.addRow("X max", self.xmax_spin)
        axes_form.addRow("Y min", self.ymin_spin)
        axes_form.addRow("Y max", self.ymax_spin)
        axes_form.addRow("Axis label font size", self.axis_label_fontsize_spin)
        self.label_bold_checkbox = QCheckBox("Bold labels", axes_group)
        self.label_italic_checkbox = QCheckBox("Italic labels", axes_group)
        axes_form.addRow(self.label_bold_checkbox)
        axes_form.addRow(self.label_italic_checkbox)

        # Traces group
        traces_group = QGroupBox("Traces", self._controls_widget)
        traces_layout = QVBoxLayout(traces_group)
        traces_layout.setContentsMargins(8, 8, 8, 8)
        traces_layout.setSpacing(6)

        self.trace_selector = QComboBox(self._controls_widget)
        self.trace_linewidth_spin = QDoubleSpinBox(self._controls_widget)
        self.trace_linewidth_spin.setDecimals(1)
        self.trace_linewidth_spin.setRange(0.1, 10.0)
        self.trace_linewidth_spin.setSingleStep(0.1)
        self.trace_linewidth_spin.setValue(1.0)
        self.trace_color_button = QPushButton("Select…", self._controls_widget)
        self.trace_color_button.setStyleSheet("background-color: #000000")

        trace_form = QFormLayout()
        trace_form.setContentsMargins(0, 0, 0, 0)
        trace_form.setSpacing(6)
        trace_form.addRow("Trace to display", self.trace_selector)
        trace_form.addRow("Trace line width", self.trace_linewidth_spin)
        trace_form.addRow("Trace color", self.trace_color_button)
        traces_layout.addLayout(trace_form)

        traces_layout.addStretch(1)

        # Ticks group
        ticks_group = QGroupBox("Ticks", self._controls_widget)
        ticks_form = QFormLayout(ticks_group)
        ticks_form.setContentsMargins(8, 8, 8, 8)
        ticks_form.setSpacing(6)

        self.tick_fontsize_spin = QSpinBox(self._controls_widget)
        self.tick_fontsize_spin.setRange(6, 48)
        self.tick_fontsize_spin.setSingleStep(1)
        self.x_tick_rotation_combo = QComboBox(self._controls_widget)
        self.x_tick_rotation_combo.addItem("Horizontal (0°)", 0)
        self.x_tick_rotation_combo.addItem("Slanted (45°)", 45)
        self.x_tick_rotation_combo.addItem("Vertical (90°)", 90)
        self.max_xticks_spin = QSpinBox(self._controls_widget)
        self.max_xticks_spin.setRange(3, 20)
        self.max_xticks_spin.setSingleStep(1)
        self.max_xticks_spin.setValue(10)

        ticks_form.addRow("Tick label font size", self.tick_fontsize_spin)
        ticks_form.addRow("X tick rotation", self.x_tick_rotation_combo)
        ticks_form.addRow("Max X ticks", self.max_xticks_spin)
        self.tick_bold_checkbox = QCheckBox("Tick labels bold", ticks_group)
        self.tick_italic_checkbox = QCheckBox("Tick labels italic", ticks_group)
        ticks_form.addRow(self.tick_bold_checkbox)
        ticks_form.addRow(self.tick_italic_checkbox)

        # Events group
        events_group = QGroupBox("Events", self._controls_widget)
        events_form = QFormLayout(events_group)
        events_form.setContentsMargins(8, 8, 8, 8)
        events_form.setSpacing(6)

        self.show_events_checkbox = QCheckBox("Show events", self._controls_widget)
        self.show_events_checkbox.setChecked(True)
        self.event_fontsize_spin = QSpinBox(self._controls_widget)
        self.event_fontsize_spin.setRange(6, 36)
        self.event_fontsize_spin.setSingleStep(1)
        self.event_fontsize_spin.setValue(10)
        self.event_label_style_combo = QComboBox(self._controls_widget)
        self.event_label_style_combo.addItem("Side (horizontal)", "side_h")
        self.event_label_style_combo.addItem("Side (vertical)", "side_v")
        self.event_label_style_combo.setCurrentIndex(1)
        self.event_y_spin = QDoubleSpinBox(self._controls_widget)
        self.event_y_spin.setDecimals(3)
        self.event_y_spin.setRange(-1e9, 1e9)
        self.event_y_spin.setSingleStep(1.0)
        self.event_y_spin.setEnabled(False)

        events_form.addRow(self.show_events_checkbox)
        events_form.addRow("Label font size", self.event_fontsize_spin)
        events_form.addRow("Label style", self.event_label_style_combo)
        events_form.addRow("Label Y (data units)", self.event_y_spin)

        # Style presets group
        style_group = QGroupBox("Style", self._controls_widget)
        style_layout = QVBoxLayout(style_group)
        style_layout.setContentsMargins(8, 8, 8, 8)
        style_layout.setSpacing(6)
        self.style_copy_button = QPushButton("Copy style", self._controls_widget)
        self.style_apply_button = QPushButton("Apply style", self._controls_widget)
        self.style_apply_button.setEnabled(False)
        style_buttons_layout = QHBoxLayout()
        style_buttons_layout.setContentsMargins(0, 0, 0, 0)
        style_buttons_layout.setSpacing(6)
        style_buttons_layout.addWidget(self.style_copy_button)
        style_buttons_layout.addWidget(self.style_apply_button)
        style_layout.addLayout(style_buttons_layout)

        # Graph size group
        graph_group = QGroupBox("Graph size", self._controls_widget)
        graph_layout = QGridLayout(graph_group)
        graph_layout.setContentsMargins(8, 8, 8, 8)
        graph_layout.setHorizontalSpacing(6)
        graph_layout.setVerticalSpacing(4)

        graph_units_label = QLabel("Units:", graph_group)
        self.graph_units_combo = QComboBox(graph_group)
        self.graph_units_combo.addItems(["mm", "in"])
        self.graph_units_combo.setCurrentText("mm")

        graph_width_label = QLabel("Width:", graph_group)
        self.graph_width_spin = QDoubleSpinBox(graph_group)
        self.graph_width_spin.setDecimals(1)
        self.graph_width_spin.setSingleStep(1.0)
        self.graph_width_spin.setRange(20.0, 400.0)

        graph_height_label = QLabel("Height:", graph_group)
        self.graph_height_spin = QDoubleSpinBox(graph_group)
        self.graph_height_spin.setDecimals(1)
        self.graph_height_spin.setSingleStep(1.0)
        self.graph_height_spin.setRange(20.0, 400.0)

        self.graph_aspect_lock_checkbox = QCheckBox("Lock aspect", graph_group)
        self.graph_aspect_lock_checkbox.setChecked(True)

        graph_layout.addWidget(graph_units_label, 0, 0)
        graph_layout.addWidget(self.graph_units_combo, 0, 1)
        graph_layout.addWidget(graph_width_label, 1, 0)
        graph_layout.addWidget(self.graph_width_spin, 1, 1)
        graph_layout.addWidget(graph_height_label, 2, 0)
        graph_layout.addWidget(self.graph_height_spin, 2, 1)
        graph_layout.addWidget(self.graph_aspect_lock_checkbox, 3, 0, 1, 2)

        # Wire signals
        self.x_label_edit.editingFinished.connect(self._on_axes_labels_changed)
        self.y_label_edit.editingFinished.connect(self._on_axes_labels_changed)
        self.grid_checkbox.toggled.connect(self._on_grid_toggled)
        self.xmin_spin.valueChanged.connect(self._on_axis_limits_changed)
        self.xmax_spin.valueChanged.connect(self._on_axis_limits_changed)
        self.ymin_spin.valueChanged.connect(self._on_axis_limits_changed)
        self.ymax_spin.valueChanged.connect(self._on_axis_limits_changed)
        self.axis_label_fontsize_spin.valueChanged.connect(self._on_axis_label_fontsize_changed)
        self.trace_linewidth_spin.valueChanged.connect(self._on_trace_linewidth_changed)
        self.tick_fontsize_spin.valueChanged.connect(self._on_tick_fontsize_changed)
        self.x_tick_rotation_combo.currentIndexChanged.connect(self._on_x_tick_rotation_changed)
        self.max_xticks_spin.valueChanged.connect(self._on_max_xticks_changed)
        self.label_bold_checkbox.toggled.connect(self._on_label_bold_toggled)
        self.label_italic_checkbox.toggled.connect(self._on_label_italic_toggled)
        self.tick_bold_checkbox.toggled.connect(self._on_tick_bold_toggled)
        self.tick_italic_checkbox.toggled.connect(self._on_tick_italic_toggled)
        self.trace_selector.currentIndexChanged.connect(self._on_trace_selection_changed)
        self.style_copy_button.clicked.connect(self._on_copy_style_clicked)
        self.style_apply_button.clicked.connect(self._on_apply_style_clicked)
        self.trace_color_button.clicked.connect(self._on_trace_color_clicked)
        self.show_events_checkbox.toggled.connect(self._on_show_events_toggled)
        self.event_fontsize_spin.valueChanged.connect(self._on_event_fontsize_changed)
        self.event_label_style_combo.currentIndexChanged.connect(self._on_event_label_style_changed)
        self.event_y_spin.valueChanged.connect(self._on_event_y_position_changed)
        self.graph_units_combo.currentIndexChanged.connect(self._on_graph_units_changed)
        self.graph_width_spin.valueChanged.connect(self._on_graph_size_spin_changed)
        self.graph_height_spin.valueChanged.connect(self._on_graph_size_spin_changed)
        self.graph_aspect_lock_checkbox.toggled.connect(self._on_graph_aspect_lock_toggled)

        controls_layout.addWidget(axes_group)
        controls_layout.addWidget(traces_group)
        controls_layout.addWidget(ticks_group)
        controls_layout.addWidget(events_group)
        controls_layout.addWidget(style_group)
        controls_layout.addWidget(graph_group)
        controls_layout.addStretch(1)

    def _on_axes_labels_changed(self) -> None:
        if self.ax is None:
            return
        if self.x_label_edit is not None:
            self.ax.set_xlabel(self.x_label_edit.text())
        if self.y_label_edit is not None:
            self.ax.set_ylabel(self.y_label_edit.text())
        log.info(
            "[FIGURE_COMPOSER][AXES] labels_changed: xlabel=%r ylabel=%r",
            self.x_label_edit.text() if self.x_label_edit is not None else None,
            self.y_label_edit.text() if self.y_label_edit is not None else None,
        )
        self.canvas.draw_idle()

    def _on_grid_toggled(self, checked: bool) -> None:
        self._grid_enabled = bool(checked)
        if self.ax is None:
            return
        self.ax.grid(self._grid_enabled)
        log.info("[FIGURE_COMPOSER][AXES] grid_toggled: checked=%s", checked)
        self.canvas.draw_idle()

    def _on_axis_limits_changed(self) -> None:
        if self.ax is None:
            return
        if not (self.xmin_spin and self.xmax_spin and self.ymin_spin and self.ymax_spin):
            return

        xmin = self.xmin_spin.value()
        xmax = self.xmax_spin.value()
        ymin = self.ymin_spin.value()
        ymax = self.ymax_spin.value()

        if xmin > xmax:
            xmin, xmax = xmax, xmin
        if ymin > ymax:
            ymin, ymax = ymax, ymin
        if xmin == xmax:
            delta = abs(xmin) * 0.01 or 1.0
            xmin -= delta
            xmax += delta
            self.xmin_spin.blockSignals(True)
            self.xmax_spin.blockSignals(True)
            self.xmin_spin.setValue(xmin)
            self.xmax_spin.setValue(xmax)
            self.xmin_spin.blockSignals(False)
            self.xmax_spin.blockSignals(False)
        if ymin == ymax:
            delta = abs(ymin) * 0.01 or 1.0
            ymin -= delta
            ymax += delta
            self.ymin_spin.blockSignals(True)
            self.ymax_spin.blockSignals(True)
            self.ymin_spin.setValue(ymin)
            self.ymax_spin.setValue(ymax)
            self.ymin_spin.blockSignals(False)
            self.ymax_spin.blockSignals(False)
        self.ax.set_xlim(xmin, xmax)
        self.ax.set_ylim(ymin, ymax)
        log.info(
            "[FIGURE_COMPOSER][AXES] limits_changed: x_min=%.3f x_max=%.3f y_min=%.3f y_max=%.3f",
            xmin,
            xmax,
            ymin,
            ymax,
        )
        self.canvas.draw_idle()

    def _on_axis_label_fontsize_changed(self, size: int) -> None:
        if self.ax is None:
            return
        try:
            self.ax.xaxis.label.set_fontsize(size)
            self.ax.yaxis.label.set_fontsize(size)
        except Exception:
            return
        log.info("[FIGURE_COMPOSER][AXES] label_fontsize_changed: size=%d", size)
        self.canvas.draw_idle()

    def _on_trace_linewidth_changed(self, value: float) -> None:
        lines = getattr(self, "_trace_lines", None)
        if not lines:
            return
        for line in lines:
            try:
                line.set_linewidth(value)
            except Exception:
                continue
        log.info("[FIGURE_COMPOSER][TRACE] linewidth_changed: value=%.3f", value)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_tick_fontsize_changed(self, size: int) -> None:
        if self.ax is None:
            return
        try:
            for tick in self.ax.get_xticklabels():
                tick.set_fontsize(size)
            for tick in self.ax.get_yticklabels():
                tick.set_fontsize(size)
        except Exception:
            return
        log.info("[FIGURE_COMPOSER][TICKS] fontsize_changed: size=%d", size)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_x_tick_rotation_changed(self, index: int) -> None:
        if self.ax is None or self.x_tick_rotation_combo is None:
            return
        angle = self.x_tick_rotation_combo.itemData(index)
        if angle is None:
            angle = 0
        try:
            for label in self.ax.get_xticklabels():
                label.set_rotation(angle)
                if angle == 0:
                    label.set_ha("center")
                    label.set_va("top")
                elif angle == 45:
                    label.set_ha("right")
                    label.set_va("top")
                elif angle == 90:
                    label.set_ha("right")
                    label.set_va("center")
        except Exception:
            return
        log.info("[FIGURE_COMPOSER][TICKS] x_tick_rotation_changed: angle=%s", angle)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_max_xticks_changed(self, value: int) -> None:
        if self.ax is None:
            return
        try:
            self.ax.locator_params(axis="x", nbins=value)
        except Exception:
            return
        log.info("[FIGURE_COMPOSER][TICKS] max_xticks_changed: nbins=%d", value)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_label_bold_toggled(self, checked: bool) -> None:
        if self.ax is None:
            return
        weight = "bold" if checked else "normal"
        try:
            self.ax.xaxis.label.set_fontweight(weight)
            self.ax.yaxis.label.set_fontweight(weight)
        except Exception:
            return
        log.info("[FIGURE_COMPOSER][AXES] label_bold_toggled: checked=%s", checked)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_label_italic_toggled(self, checked: bool) -> None:
        if self.ax is None:
            return
        style = "italic" if checked else "normal"
        try:
            self.ax.xaxis.label.set_fontstyle(style)
            self.ax.yaxis.label.set_fontstyle(style)
        except Exception:
            return
        log.info("[FIGURE_COMPOSER][AXES] label_italic_toggled: checked=%s", checked)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_tick_bold_toggled(self, checked: bool) -> None:
        if self.ax is None:
            return
        weight = "bold" if checked else "normal"
        try:
            for tick in self.ax.get_xticklabels():
                tick.set_fontweight(weight)
            for tick in self.ax.get_yticklabels():
                tick.set_fontweight(weight)
        except Exception:
            return
        log.info("[FIGURE_COMPOSER][TICKS] bold_toggled: checked=%s", checked)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_tick_italic_toggled(self, checked: bool) -> None:
        if self.ax is None:
            return
        style = "italic" if checked else "normal"
        try:
            for tick in self.ax.get_xticklabels():
                tick.set_fontstyle(style)
            for tick in self.ax.get_yticklabels():
                tick.set_fontstyle(style)
        except Exception:
            return
        log.info("[FIGURE_COMPOSER][TICKS] italic_toggled: checked=%s", checked)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_trace_color_clicked(self) -> None:
        """Let the user pick a color for the currently selected trace."""
        if self.trace_selector is None:
            return
        track_id = getattr(self, "_selected_track_id", None)
        if track_id is None:
            return

        current_hex = self._trace_color_overrides.get(track_id)
        if current_hex is None and self._trace_lines:
            try:
                current_hex = to_hex(self._trace_lines[0].get_color())
            except Exception:
                current_hex = None
        if current_hex is None:
            current_hex = "#1f77b4"

        initial_color = QColor(current_hex)
        color = QColorDialog.getColor(initial_color, self, "Select trace color")
        if not color.isValid():
            return

        hex_color = color.name()
        log.info(
            "[FIGURE_COMPOSER][TRACE] color_changed: track_id=%s color=%s",
            track_id,
            hex_color,
        )
        self._trace_color_overrides[track_id] = hex_color

        for line in self._trace_lines:
            with contextlib.suppress(Exception):
                line.set_color(hex_color)

        if self.trace_color_button is not None:
            self.trace_color_button.setStyleSheet(f"background-color: {hex_color}")

        if self.canvas is not None:
            self.canvas.draw_idle()

    def _on_trace_selection_changed(self, index: int) -> None:
        if self.trace_selector is None:
            return
        track_id = self.trace_selector.itemData(index)
        self._selected_track_id = str(track_id) if track_id is not None else None
        log.info(
            "[FIGURE_COMPOSER][TRACE] trace_selected: index=%d text=%s track_id=%s",
            index,
            self.trace_selector.itemText(index) if index >= 0 else None,
            self._selected_track_id,
        )
        if self._selected_track_id is not None:
            color = self._trace_color_overrides.get(self._selected_track_id)
            if color and self.trace_color_button is not None:
                self.trace_color_button.setStyleSheet(f"background-color: {color}")
        self._render_trace()

    def _on_show_events_toggled(self, checked: bool) -> None:
        """Toggle visibility of event lines/labels."""
        self._show_events = bool(checked)
        log.info("[FIGURE_COMPOSER][EVENTS] show_events_toggled: checked=%s", checked)
        self._render_trace()

    def _on_event_fontsize_changed(self, size: int) -> None:
        """Update event label font size."""
        del size  # unused; redraw uses current spin value
        current_size = None
        if self.event_fontsize_spin is not None:
            try:
                current_size = int(self.event_fontsize_spin.value())
            except Exception:
                current_size = None
        log.info("[FIGURE_COMPOSER][EVENTS] fontsize_changed: size=%s", current_size)
        self._render_trace()

    def _on_event_label_style_changed(self, index: int) -> None:
        """Update the event label style and re-render."""
        if self.event_label_style_combo is None:
            return
        style = self.event_label_style_combo.itemData(index)
        if style not in ("side_h", "side_v"):
            style = "side_v"
        self._event_label_style = style
        if self.event_y_spin is not None:
            self.event_y_spin.setEnabled(style in ("side_h", "side_v"))
        log.info("[FIGURE_COMPOSER][EVENTS] label_style_changed: style=%s", style)
        self._render_trace()

    def _on_event_y_position_changed(self, value: float) -> None:
        """User-set Y position for side event label styles."""
        if getattr(self, "_event_label_style", "side_v") not in ("side_h", "side_v"):
            return
        try:
            self._event_y_position = float(value)
        except Exception:
            self._event_y_position = None
            return
        log.info("[FIGURE_COMPOSER][EVENTS] y_position_changed: value=%.3f", value)
        self._render_trace()

    def _on_copy_style_clicked(self) -> None:
        style: dict[str, Any] = {}

        style["grid_enabled"] = bool(self._grid_enabled)

        if self.x_label_edit is not None:
            style["x_label_text"] = self.x_label_edit.text()
        if self.y_label_edit is not None:
            style["y_label_text"] = self.y_label_edit.text()
        if self.xmin_spin is not None:
            style["x_min"] = self.xmin_spin.value()
        if self.xmax_spin is not None:
            style["x_max"] = self.xmax_spin.value()
        if self.ymin_spin is not None:
            style["y_min"] = self.ymin_spin.value()
        if self.ymax_spin is not None:
            style["y_max"] = self.ymax_spin.value()

        if self.axis_label_fontsize_spin is not None:
            style["axis_label_fontsize"] = self.axis_label_fontsize_spin.value()
        if self.label_bold_checkbox is not None:
            style["label_bold"] = self.label_bold_checkbox.isChecked()
        if self.label_italic_checkbox is not None:
            style["label_italic"] = self.label_italic_checkbox.isChecked()

        if self.tick_fontsize_spin is not None:
            style["tick_fontsize"] = self.tick_fontsize_spin.value()
        if self.x_tick_rotation_combo is not None:
            style["x_tick_rotation"] = self.x_tick_rotation_combo.currentData()
        if self.tick_bold_checkbox is not None:
            style["tick_bold"] = self.tick_bold_checkbox.isChecked()
        if self.tick_italic_checkbox is not None:
            style["tick_italic"] = self.tick_italic_checkbox.isChecked()
        if self.max_xticks_spin is not None:
            style["max_xticks"] = self.max_xticks_spin.value()

        if self.trace_linewidth_spin is not None:
            style["trace_linewidth"] = self.trace_linewidth_spin.value()
        trace_color = None
        if self._trace_lines:
            try:
                trace_color = to_hex(self._trace_lines[0].get_color())
            except Exception:
                trace_color = None
        if trace_color:
            style["trace_color"] = trace_color

        if self.show_events_checkbox is not None:
            style["show_events"] = self.show_events_checkbox.isChecked()
        if self.event_fontsize_spin is not None:
            style["event_fontsize"] = self.event_fontsize_spin.value()
        if self.event_label_style_combo is not None:
            style["event_label_style"] = self.event_label_style_combo.currentData()
        if self.event_y_spin is not None:
            style["event_y"] = self.event_y_spin.value()

        self._style_clipboard = style
        if self.style_apply_button is not None:
            self.style_apply_button.setEnabled(True)
        log.info(
            "[FIGURE_COMPOSER][STYLE] copy_style: keys=%s",
            sorted(self._style_clipboard.keys()) if self._style_clipboard else [],
        )

    def _on_apply_style_clicked(self) -> None:
        style = self._style_clipboard
        if not style:
            return
        log.info(
            "[FIGURE_COMPOSER][STYLE] apply_style: keys=%s",
            sorted(style.keys()),
        )

        # Grid and labels
        if self.grid_checkbox is not None and "grid_enabled" in style:
            blocker = QSignalBlocker(self.grid_checkbox)
            self.grid_checkbox.setChecked(bool(style["grid_enabled"]))
            del blocker

        if self.x_label_edit is not None and "x_label_text" in style:
            blocker = QSignalBlocker(self.x_label_edit)
            self.x_label_edit.setText(style["x_label_text"])
            del blocker
        if self.y_label_edit is not None and "y_label_text" in style:
            blocker = QSignalBlocker(self.y_label_edit)
            self.y_label_edit.setText(style["y_label_text"])
            del blocker

        if self.xmin_spin is not None and "x_min" in style:
            self.xmin_spin.blockSignals(True)
            self.xmin_spin.setValue(float(style["x_min"]))
            self.xmin_spin.blockSignals(False)
        if self.xmax_spin is not None and "x_max" in style:
            self.xmax_spin.blockSignals(True)
            self.xmax_spin.setValue(float(style["x_max"]))
            self.xmax_spin.blockSignals(False)
        if self.ymin_spin is not None and "y_min" in style:
            self.ymin_spin.blockSignals(True)
            self.ymin_spin.setValue(float(style["y_min"]))
            self.ymin_spin.blockSignals(False)
        if self.ymax_spin is not None and "y_max" in style:
            self.ymax_spin.blockSignals(True)
            self.ymax_spin.setValue(float(style["y_max"]))
            self.ymax_spin.blockSignals(False)

        if self.axis_label_fontsize_spin is not None and "axis_label_fontsize" in style:
            blocker = QSignalBlocker(self.axis_label_fontsize_spin)
            self.axis_label_fontsize_spin.setValue(int(style["axis_label_fontsize"]))
            del blocker
        if self.label_bold_checkbox is not None and "label_bold" in style:
            blocker = QSignalBlocker(self.label_bold_checkbox)
            self.label_bold_checkbox.setChecked(bool(style["label_bold"]))
            del blocker
        if self.label_italic_checkbox is not None and "label_italic" in style:
            blocker = QSignalBlocker(self.label_italic_checkbox)
            self.label_italic_checkbox.setChecked(bool(style["label_italic"]))
            del blocker

        if self.tick_fontsize_spin is not None and "tick_fontsize" in style:
            blocker = QSignalBlocker(self.tick_fontsize_spin)
            self.tick_fontsize_spin.setValue(int(style["tick_fontsize"]))
            del blocker
        if self.x_tick_rotation_combo is not None and "x_tick_rotation" in style:
            target_angle = style["x_tick_rotation"]
            for idx in range(self.x_tick_rotation_combo.count()):
                if self.x_tick_rotation_combo.itemData(idx) == target_angle:
                    blocker = QSignalBlocker(self.x_tick_rotation_combo)
                    self.x_tick_rotation_combo.setCurrentIndex(idx)
                    del blocker
                    break
        if self.tick_bold_checkbox is not None and "tick_bold" in style:
            blocker = QSignalBlocker(self.tick_bold_checkbox)
            self.tick_bold_checkbox.setChecked(bool(style["tick_bold"]))
            del blocker
        if self.tick_italic_checkbox is not None and "tick_italic" in style:
            blocker = QSignalBlocker(self.tick_italic_checkbox)
            self.tick_italic_checkbox.setChecked(bool(style["tick_italic"]))
            del blocker
        if self.max_xticks_spin is not None and "max_xticks" in style:
            blocker = QSignalBlocker(self.max_xticks_spin)
            self.max_xticks_spin.setValue(int(style["max_xticks"]))
            del blocker

        if self.trace_linewidth_spin is not None and "trace_linewidth" in style:
            blocker = QSignalBlocker(self.trace_linewidth_spin)
            self.trace_linewidth_spin.setValue(float(style["trace_linewidth"]))
            del blocker

        color = style.get("trace_color")
        if color:
            track_id = getattr(self, "_selected_track_id", None)
            if track_id is not None:
                self._trace_color_overrides[track_id] = color
            if self.trace_color_button is not None:
                self.trace_color_button.setStyleSheet(f"background-color: {color}")
            for line in self._trace_lines:
                with contextlib.suppress(Exception):
                    line.set_color(color)
        if self.show_events_checkbox is not None and "show_events" in style:
            blocker = QSignalBlocker(self.show_events_checkbox)
            self.show_events_checkbox.setChecked(bool(style["show_events"]))
            del blocker
        if self.event_fontsize_spin is not None and "event_fontsize" in style:
            blocker = QSignalBlocker(self.event_fontsize_spin)
            self.event_fontsize_spin.setValue(int(style["event_fontsize"]))
            del blocker
        if self.event_label_style_combo is not None and "event_label_style" in style:
            target = style["event_label_style"]
            for idx in range(self.event_label_style_combo.count()):
                if self.event_label_style_combo.itemData(idx) == target:
                    blocker = QSignalBlocker(self.event_label_style_combo)
                    self.event_label_style_combo.setCurrentIndex(idx)
                    del blocker
                    break
            self._event_label_style = (
                target if target in ("side_h", "side_v") else self._event_label_style
            )
        if self.event_y_spin is not None and "event_y" in style:
            blocker = QSignalBlocker(self.event_y_spin)
            self.event_y_spin.setValue(float(style["event_y"]))
            del blocker
            with contextlib.suppress(Exception):
                self._event_y_position = float(style["event_y"])

        # Apply axis limits now that spins are set
        self._on_axis_limits_changed()

        # Re-render to apply style changes, then re-apply limits to ensure they stick
        self._render_trace()
        self._on_axis_limits_changed()

    def _sync_limits_from_axes(self, xmin: float, xmax: float, ymin: float, ymax: float) -> None:
        if not (self.xmin_spin and self.xmax_spin and self.ymin_spin and self.ymax_spin):
            return
        for spin, value in (
            (self.xmin_spin, xmin),
            (self.xmax_spin, xmax),
            (self.ymin_spin, ymin),
            (self.ymax_spin, ymax),
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _sync_widgets_from_axes(self) -> None:
        """Sync widget state from the current axes/figure without triggering handlers."""
        if self.ax is None:
            return

        if self.x_label_edit is not None:
            self.x_label_edit.blockSignals(True)
            self.x_label_edit.setText(self.ax.get_xlabel() or "")
            self.x_label_edit.blockSignals(False)
        if self.y_label_edit is not None:
            self.y_label_edit.blockSignals(True)
            self.y_label_edit.setText(self.ax.get_ylabel() or "")
            self.y_label_edit.blockSignals(False)

        if self.grid_checkbox is not None:
            self.grid_checkbox.blockSignals(True)
            self.grid_checkbox.setChecked(self._grid_enabled)
            self.grid_checkbox.blockSignals(False)

        if self.xmin_spin and self.xmax_spin and self.ymin_spin and self.ymax_spin:
            try:
                xmin, xmax = self.ax.get_xlim()
                ymin, ymax = self.ax.get_ylim()
                self._sync_limits_from_axes(xmin, xmax, ymin, ymax)
            except Exception:
                pass

        if self.axis_label_fontsize_spin is not None:
            try:
                size = self.ax.xaxis.label.get_fontsize()
                if size:
                    self.axis_label_fontsize_spin.blockSignals(True)
                    self.axis_label_fontsize_spin.setValue(int(size))
                    self.axis_label_fontsize_spin.blockSignals(False)
            except Exception:
                pass
        if self.label_bold_checkbox is not None or self.label_italic_checkbox is not None:
            x_label = self.ax.xaxis.label
            weight = x_label.get_fontweight() if x_label is not None else None
            style = x_label.get_fontstyle() if x_label is not None else None
            if self.label_bold_checkbox is not None:
                is_bold = False
                if isinstance(weight, str):
                    is_bold = weight.lower() == "bold"
                elif isinstance(weight, int | float):
                    is_bold = weight >= 600
                self.label_bold_checkbox.blockSignals(True)
                self.label_bold_checkbox.setChecked(is_bold)
                self.label_bold_checkbox.blockSignals(False)
            if self.label_italic_checkbox is not None:
                is_italic = False
                if isinstance(style, str):
                    is_italic = style.lower() in ("italic", "oblique")
                self.label_italic_checkbox.blockSignals(True)
                self.label_italic_checkbox.setChecked(is_italic)
                self.label_italic_checkbox.blockSignals(False)

        if self.trace_linewidth_spin is not None:
            lw = 1.5
            if self._trace_lines:
                try:
                    lw = self._trace_lines[0].get_linewidth()
                except Exception:
                    lw = 1.5
            self.trace_linewidth_spin.blockSignals(True)
            self.trace_linewidth_spin.setValue(lw)
            self.trace_linewidth_spin.blockSignals(False)

        active_spec = self._get_active_spec()
        if active_spec is not None and self._trace_lines:
            track_id = getattr(active_spec, "track_id", None)
            current_color = None
            try:
                current_color = to_hex(self._trace_lines[0].get_color())
            except Exception:
                current_color = None
            if track_id is not None and current_color:
                if track_id not in self._trace_color_overrides:
                    self._trace_color_overrides[track_id] = current_color
                if self.trace_color_button is not None:
                    self.trace_color_button.setStyleSheet(f"background-color: {current_color}")

        if self.tick_fontsize_spin is not None:
            xticks = self.ax.get_xticklabels()
            yticks = self.ax.get_yticklabels()
            size = None
            if xticks:
                try:
                    size = xticks[0].get_fontsize()
                except Exception:
                    size = None
            if size is None and yticks:
                try:
                    size = yticks[0].get_fontsize()
                except Exception:
                    size = None
            if size is not None:
                self.tick_fontsize_spin.blockSignals(True)
                self.tick_fontsize_spin.setValue(int(size))
                self.tick_fontsize_spin.blockSignals(False)

        if self.x_tick_rotation_combo is not None:
            angle = 0.0
            xticks = self.ax.get_xticklabels()
            if xticks:
                try:
                    angle = float(xticks[0].get_rotation() or 0.0)
                except Exception:
                    angle = 0.0
            candidates = [0, 45, 90]
            nearest = min(candidates, key=lambda a: abs(a - angle))
            for idx in range(self.x_tick_rotation_combo.count()):
                if self.x_tick_rotation_combo.itemData(idx) == nearest:
                    self.x_tick_rotation_combo.blockSignals(True)
                    self.x_tick_rotation_combo.setCurrentIndex(idx)
                    self.x_tick_rotation_combo.blockSignals(False)
                    break

        if self.max_xticks_spin is not None and self.max_xticks_spin.value() <= 0:
            self.max_xticks_spin.blockSignals(True)
            self.max_xticks_spin.setValue(10)
            self.max_xticks_spin.blockSignals(False)

        xticks = self.ax.get_xticklabels()
        tick_weight = None
        tick_style = None
        if xticks:
            try:
                tick_weight = xticks[0].get_fontweight()
                tick_style = xticks[0].get_fontstyle()
            except Exception:
                tick_weight = None
                tick_style = None
        if self.tick_bold_checkbox is not None:
            tick_is_bold = False
            if isinstance(tick_weight, str):
                tick_is_bold = tick_weight.lower() == "bold"
            elif isinstance(tick_weight, int | float):
                tick_is_bold = tick_weight >= 600
            self.tick_bold_checkbox.blockSignals(True)
            self.tick_bold_checkbox.setChecked(tick_is_bold)
            self.tick_bold_checkbox.blockSignals(False)
        if self.tick_italic_checkbox is not None:
            tick_is_italic = False
            if isinstance(tick_style, str):
                tick_is_italic = tick_style.lower() in ("italic", "oblique")
            self.tick_italic_checkbox.blockSignals(True)
            self.tick_italic_checkbox.setChecked(tick_is_italic)
            self.tick_italic_checkbox.blockSignals(False)

        if self.show_events_checkbox is not None:
            self.show_events_checkbox.blockSignals(True)
            self.show_events_checkbox.setChecked(self._show_events)
            self.show_events_checkbox.blockSignals(False)
        if self.event_fontsize_spin is not None:
            self.event_fontsize_spin.blockSignals(True)
            self.event_fontsize_spin.setValue(int(self.event_fontsize_spin.value() or 10))
            self.event_fontsize_spin.blockSignals(False)
        if self.event_label_style_combo is not None:
            current_style = getattr(self, "_event_label_style", "side_v") or "side_v"
            if current_style == "top":
                current_style = "side_v"
            for idx in range(self.event_label_style_combo.count()):
                if self.event_label_style_combo.itemData(idx) == current_style:
                    self.event_label_style_combo.blockSignals(True)
                    self.event_label_style_combo.setCurrentIndex(idx)
                    self.event_label_style_combo.blockSignals(False)
                    break
        if self.event_y_spin is not None:
            self.event_y_spin.blockSignals(True)
            if self._event_y_position is not None:
                self.event_y_spin.setValue(self._event_y_position)
            self.event_y_spin.setEnabled(
                getattr(self, "_event_label_style", "side_h") in ("side_h", "side_v")
            )
            self.event_y_spin.blockSignals(False)

    # ------------------------------------------------------------------ Qt lifecycle
    def closeEvent(self, event) -> None:
        try:
            self.studio_closed.emit()
        finally:
            super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_first_show", False):
            self._first_show = False
            self._center_on_parent_or_screen()

    def _center_on_parent_or_screen(self) -> None:
        """
        Center this window over its parent if possible; otherwise center on the active screen.
        Intended to run only on first show.
        """
        parent = self.parent()
        try:
            if parent is not None and hasattr(parent, "frameGeometry"):
                parent_geom = parent.frameGeometry()
                self_geom = self.frameGeometry()
                self_geom.moveCenter(parent_geom.center())
                self.move(self_geom.topLeft())
                return

            screen = self.screen()
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is not None:
                screen_geom = screen.availableGeometry()
                self_geom = self.frameGeometry()
                self_geom.moveCenter(screen_geom.center())
                self.move(self_geom.topLeft())
        except Exception:
            return
