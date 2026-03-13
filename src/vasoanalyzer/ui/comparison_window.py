# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Floating comparison window for side-by-side channel comparison across datasets."""

from __future__ import annotations

import contextlib
import logging
import math
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.drag_drop import DATASET_MIME_TYPE, decode_dataset_mime
from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)

# Mapping from SQLite canonical column names to UI-facing labels
_DB_TO_UI_COLUMNS = {
    "t_seconds": "Time (s)",
    "inner_diam": "Inner Diameter",
    "outer_diam": "Outer Diameter",
    "p_avg": "Avg Pressure (mmHg)",
    "p1": "Pressure 1 (mmHg)",
    "p2": "Set Pressure (mmHg)",
    "frame_number": "FrameNumber",
    "tiff_page": "TiffPage",
}

# Channel key → combo label  (keys match PyQtGraphTraceView mode parameter)
_CHANNELS: list[tuple[str, str]] = [
    ("inner",        "Inner Diameter"),
    ("outer",        "Outer Diameter"),
    ("avg_pressure", "Avg Pressure"),
    ("set_pressure", "Set Pressure"),
]

_MAX_PANELS = 4


def _load_icon(filename: str) -> QIcon:
    """Load an icon from the app's resources/icons directory, dark-aware."""
    try:
        from utils import resource_path
        is_dark = bool(CURRENT_THEME.get("is_dark", False))
        if is_dark:
            name, ext = os.path.splitext(filename)
            candidate = resource_path("resources", "icons", f"{name}_Dark{ext}")
            if os.path.exists(candidate):
                return QIcon(candidate)
        return QIcon(resource_path("resources", "icons", filename))
    except Exception:
        return QIcon()


def _apply_toolbar_style(toolbar: QToolBar) -> None:
    """Apply the same stylesheet the main window's PlotToolbar uses."""
    border = CURRENT_THEME.get("panel_border", CURRENT_THEME.get("grid_color", "#d0d0d0"))
    sep = CURRENT_THEME.get("grid_color", border)
    bg = CURRENT_THEME.get("toolbar_bg", CURRENT_THEME.get("window_bg", "#FFFFFF"))
    button_bg = CURRENT_THEME.get("button_bg", bg)
    hover_bg = CURRENT_THEME.get("button_hover_bg", CURRENT_THEME.get("selection_bg", bg))
    checked_bg = CURRENT_THEME.get("selection_bg", hover_bg)
    pressed_bg = CURRENT_THEME.get("button_active_bg", checked_bg)
    checked_border = CURRENT_THEME.get("accent", border)
    text = CURRENT_THEME.get("text", "#000000")
    disabled_text = CURRENT_THEME.get("text_disabled", text)
    radius = int(CURRENT_THEME.get("panel_radius", 4))
    toolbar.setStyleSheet(f"""
        QToolBar#PlotToolbar {{
            background: {bg};
            border: 1px solid {border};
            border-radius: {radius}px;
            padding: 3px 4px;
            spacing: 3px;
        }}
        QToolBar#PlotToolbar::separator {{
            background: {sep};
            width: 1px;
            margin: 3px 6px;
        }}
        QToolBar#PlotToolbar QToolButton {{
            background: {button_bg};
            border: 1px solid {border};
            border-radius: {radius}px;
            margin: 1px 2px;
            padding: 4px 7px;
            min-width: 44px;
            color: {text};
        }}
        QToolBar#PlotToolbar QToolButton:disabled {{
            background: {bg};
            border: 1px solid {border};
            color: {disabled_text};
        }}
        QToolBar#PlotToolbar QToolButton:hover {{
            background: {hover_bg};
        }}
        QToolBar#PlotToolbar QToolButton:checked {{
            background: {checked_bg};
            border: 1px solid {checked_border};
            color: {text};
        }}
        QToolBar#PlotToolbar QToolButton:checked:hover {{
            background: {checked_bg};
            border: 1px solid {checked_border};
            color: {text};
        }}
        QToolBar#PlotToolbar QToolButton:pressed {{
            background: {pressed_bg};
        }}
    """)


# ======================================================================

class TraceViewNavProxy:
    """Duck-type plot_host adapter so TraceNavBar can drive a PyQtGraphTraceView.

    Implements the full interface PyQtGraphPlotHost exposes to TraceNavBar,
    including request_zoom_x and set_time_compression_target so presets and
    zoom buttons behave identically to the main window.
    """

    def __init__(self, trace_model) -> None:
        self._trace_model = trace_model
        self._trace_view = None
        self._connected_vb = None
        self._listeners: list = []
        self._time_mode: str = "auto"

    # ------------------------------------------------------------------
    # Wire to a live trace_view (called after channel rebuilds)
    # ------------------------------------------------------------------
    def attach(self, trace_view) -> None:
        if self._connected_vb is not None:
            with contextlib.suppress(Exception):
                self._connected_vb.sigRangeChanged.disconnect(self._on_range_changed)
        self._trace_view = trace_view
        self._connected_vb = trace_view.view_box()
        self._connected_vb.sigRangeChanged.connect(self._on_range_changed)

    def _on_range_changed(self, *_) -> None:
        for cb in list(self._listeners):
            with contextlib.suppress(Exception):
                cb()

    # ------------------------------------------------------------------
    # TraceNavBar duck-type interface  (mirrors PyQtGraphPlotHost)
    # ------------------------------------------------------------------
    def get_time_window(self) -> tuple[float, float] | None:
        if self._trace_view is None:
            return None
        with contextlib.suppress(Exception):
            r = self._trace_view.get_widget().getPlotItem().viewRange()[0]
            return float(r[0]), float(r[1])
        return None

    def get_total_span(self) -> tuple[float, float] | None:
        if self._trace_model is None:
            return None
        with contextlib.suppress(Exception):
            x0, x1 = self._trace_model.full_range
            return float(x0), float(x1)
        return None

    def set_time_window(self, x0: float, x1: float) -> None:
        """Pan/zoom — direct setXRange so sigRangeChanged auto-triggers LOD update."""
        if self._trace_view is None:
            return
        with contextlib.suppress(Exception):
            self._trace_view.get_widget().getPlotItem().setXRange(
                float(x0), float(x1), padding=0
            )

    def add_time_window_listener(self, callback) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_time_window_listener(self, callback) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(callback)

    def request_zoom_x(
        self, factor: float, anchor_x: float | None, reason: str = "zoom"
    ) -> None:
        """Multiplicative zoom around anchor_x — matches PyQtGraphPlotHost behaviour."""
        window = self.get_time_window()
        total = self.get_total_span()
        if window is None or total is None:
            return
        x0, x1 = window
        dur = max(float(x1 - x0), 1e-6)
        anchor = float(anchor_x) if anchor_x is not None else (x0 + x1) * 0.5
        t_min, t_max = total
        anchor = max(min(anchor, float(t_max)), float(t_min))
        factor = float(factor)
        if not (factor > 0.0):
            return
        new_dur = max(dur * factor, 1e-6)
        left_ratio = max(0.0, min((anchor - x0) / dur if dur > 0 else 0.5, 1.0))
        new_x0 = max(anchor - new_dur * left_ratio, float(t_min))
        new_x1 = min(new_x0 + new_dur, float(t_max))
        self.set_time_window(new_x0, new_x1)

    def set_time_compression_target(self, seconds: float | None) -> None:
        """Set a fixed visible duration centered on current view — matches PyQtGraphPlotHost."""
        if seconds is None:
            self.zoom_to_full_range()
            return
        target_span = float(seconds)
        if not (math.isfinite(target_span) and target_span > 0.0):
            return
        window = self.get_time_window()
        total = self.get_total_span()
        if window is None or total is None:
            return
        center = 0.5 * (float(window[0]) + float(window[1]))
        half = target_span * 0.5
        t_min, t_max = total
        new_x0 = max(center - half, float(t_min))
        new_x1 = min(center + half, float(t_max))
        self.set_time_window(new_x0, new_x1)

    def zoom_to_full_range(self) -> None:
        total = self.get_total_span()
        if total is not None:
            self.set_time_window(total[0], total[1])

    def autoscale_all_y_once(self) -> None:
        if self._trace_view is None:
            return
        with contextlib.suppress(Exception):
            self._trace_view.set_autoscale_y(True)
            self._trace_view.set_autoscale_y(False)

    def visible_track_count(self) -> int:
        return 1  # one channel per comparison panel

    def time_mode(self) -> str:
        return self._time_mode

    def set_time_mode(self, mode: str) -> None:
        self._time_mode = str(mode)
        if self._trace_view is None:
            return
        with contextlib.suppress(Exception):
            from vasoanalyzer.ui.formatting.time_format import coerce_time_mode
            axis = getattr(self._trace_view, "_time_axis", None)
            if axis is not None and hasattr(axis, "set_mode"):
                axis.set_mode(coerce_time_mode(mode))


# ======================================================================

class ComparisonPanel(QWidget):
    """One panel — a PyQtGraphChannelTrack with its own TraceNavBar.

    Uses PyQtGraphChannelTrack (same as the main window per-channel track)
    so the Y-axis gutter controls, drag-to-pan-Y, and context menu are
    identical to what users see in the main view.
    """

    close_requested = pyqtSignal(object)  # emits self

    # Emitted when this panel's X-range changes (x0, x1)
    time_range_changed = pyqtSignal(object, float, float)  # (self, x0, x1)

    def __init__(
        self,
        dataset_id: int,
        name: str,
        trace,
        channel: str,
        mouse_mode: str = "pan",
        autoscale_y: bool = True,
        show_nav_bar: bool = True,
        events: dict | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.dataset_id = dataset_id
        self._trace = trace
        self._channel = channel
        self._mouse_mode = mouse_mode
        self._autoscale_y = autoscale_y
        self._show_nav_bar = show_nav_bar
        self._events = events  # {"times": [...], "labels": [...]}

        self._track = None           # PyQtGraphChannelTrack
        self._trace_view = None      # track.view  (PyQtGraphTraceView)
        self._nav_bar = None
        self._proxy = TraceViewNavProxy(trace)
        self._syncing = False        # guard against recursive sync

        self._plot_container_layout: QVBoxLayout | None = None
        self._nav_bar_container_layout: QVBoxLayout | None = None

        self._setup_ui(name)
        self._build_track()

    # ------------------------------------------------------------------
    def _setup_ui(self, name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header: dataset name + close button
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(name)
        font = name_label.font()
        font.setBold(True)
        name_label.setFont(font)
        header.addWidget(name_label, 1)

        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setToolTip("Remove from comparison")
        close_btn.clicked.connect(lambda: self.close_requested.emit(self))
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Plot container — swapped on channel change
        plot_container = QWidget()
        self._plot_container_layout = QVBoxLayout(plot_container)
        self._plot_container_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(plot_container, 1)

        # Nav bar container (only if nav bar is shown)
        if self._show_nav_bar:
            nav_container = QWidget()
            self._nav_bar_container_layout = QVBoxLayout(nav_container)
            self._nav_bar_container_layout.setContentsMargins(0, 2, 0, 0)
            layout.addWidget(nav_container, 0)

    def _build_track(self) -> None:
        from PyQt6.QtCore import QTimer
        from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
        from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
        from vasoanalyzer.ui.plots.pyqtgraph_style import PLOT_AXIS_LABELS

        # Remove stale nav bar
        if self._nav_bar is not None and self._nav_bar_container_layout is not None:
            self._nav_bar_container_layout.removeWidget(self._nav_bar)
            self._nav_bar.setParent(None)
            self._nav_bar.deleteLater()
            self._nav_bar = None

        # PyQtGraphChannelTrack provides gutter + Y-axis controls + TrackFrame,
        # matching the main window's per-channel rendering exactly.
        spec = ChannelTrackSpec(
            track_id=f"comp_{self._channel}",
            component=self._channel,
            label=PLOT_AXIS_LABELS.get(self._channel),
        )
        self._track = PyQtGraphChannelTrack(spec=spec)
        self._trace_view = self._track.view
        self._trace_view.set_mouse_mode(self._mouse_mode)

        # Add the track's outer widget (TrackFrame) to the plot container
        self._plot_container_layout.addWidget(self._track.widget)

        # Wire proxy to the new trace view
        self._proxy.attach(self._trace_view)

        # Wire the SmoothPanViewBox host-driven callbacks so panning/zooming
        # feels identical to the main window (smooth inertia, proper clamping).
        view_box = self._trace_view.view_box()
        if hasattr(view_box, "set_time_window_requesters"):
            import contextlib
            with contextlib.suppress(Exception):
                view_box.set_time_window_requesters(
                    pan_x=self._host_pan_x,
                    zoom_x=self._host_zoom_x,
                    set_window=lambda x0, x1, _reason: self._proxy.set_time_window(x0, x1),
                    get_window=lambda: self._proxy.get_time_window() or (0.0, 1.0),
                )

        # Emit time_range_changed when the user pans/zooms this panel
        self._proxy.add_time_window_listener(self._emit_range_changed)

        # TraceNavBar (only if requested)
        if self._show_nav_bar and self._nav_bar_container_layout is not None:
            from vasoanalyzer.ui.navigation.trace_nav_bar import TraceNavBar
            self._nav_bar = TraceNavBar(plot_host=self._proxy, parent=self)
            self._nav_bar_container_layout.addWidget(self._nav_bar)

        # Defer set_model until the widget has real pixel dimensions
        QTimer.singleShot(0, self._apply_model)

    def _host_pan_x(self, dt: float, reason: str = "pan") -> None:
        """Pan the view by dt seconds (called by SmoothPanViewBox)."""
        window = self._proxy.get_time_window()
        if window is None:
            return
        x0, x1 = window
        self._proxy.set_time_window(x0 + float(dt), x1 + float(dt))

    def _host_zoom_x(
        self, factor: float, anchor_x: float | None, reason: str = "zoom"
    ) -> None:
        """Zoom by factor around anchor (called by SmoothPanViewBox)."""
        self._proxy.request_zoom_x(factor, anchor_x, reason)

    def _emit_range_changed(self) -> None:
        """Forward viewbox range change as a signal for cross-panel sync."""
        if self._syncing:
            return
        window = self._proxy.get_time_window()
        if window is not None:
            self.time_range_changed.emit(self, float(window[0]), float(window[1]))

    def set_time_window(self, x0: float, x1: float) -> None:
        """Set X range from external sync (guards against recursion)."""
        self._syncing = True
        try:
            self._proxy.set_time_window(x0, x1)
        finally:
            self._syncing = False

    def _apply_model(self) -> None:
        if self._track is None or self._trace is None:
            return
        # PyQtGraphChannelTrack.set_model calls view.set_model internally
        self._track.set_model(self._trace)
        # Explicitly force the full X range (set_time_limits only sets constraints)
        x0, x1 = self._trace.full_range
        pw = max(int(self._trace_view.get_widget().width()), 400)
        self._trace_view.update_window(x0, x1, pixel_width=pw)
        self._trace_view.get_widget().getPlotItem().setXRange(float(x0), float(x1), padding=0)
        # One-time autoscale so the trace is visible, then leave Y manual
        self._track.autoscale_y_once()
        self._trace_view.set_autoscale_y(False)
        # Push event markers to the track and enable labels
        if self._events and self._events.get("times"):
            self._track.set_events(
                self._events["times"],
                labels=self._events.get("labels"),
            )
            # Use a larger font for readability in comparison panels
            self._trace_view._event_layer.set_label_font_size(11.0)
            self._trace_view.set_channel_event_labels_visible(True)
            # Force label positioning now that view geometry is known
            self._trace_view._event_layer.refresh_for_view(x0, x1, pw)
        if self._nav_bar is not None:
            self._nav_bar.refresh_from_host()

    # ------------------------------------------------------------------
    def set_channel(self, channel: str) -> None:
        if channel == self._channel:
            return
        self._channel = channel

        if self._track is not None:
            widget = self._track.widget
            self._plot_container_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
            self._track = None
            self._trace_view = None

        self._build_track()

    def set_mouse_mode(self, mode: str) -> None:
        self._mouse_mode = mode
        if self._trace_view is not None:
            self._trace_view.set_mouse_mode(mode)

    def set_autoscale_y(self, enabled: bool) -> None:
        self._autoscale_y = enabled
        if self._trace_view is not None:
            self._trace_view.set_autoscale_y(enabled)

    def autoscale_y_once(self) -> None:
        """Fit Y once using channel track's smart autoscale (same as main window)."""
        if self._track is not None:
            self._track.autoscale_y_once()
            self._autoscale_y = False
        elif self._trace_view is not None:
            self._trace_view.set_autoscale_y(True)
            self._trace_view.set_autoscale_y(False)
            self._autoscale_y = False

    def zoom_all_x(self) -> None:
        if self._trace is not None:
            x0, x1 = self._trace.full_range
            self._proxy.set_time_window(float(x0), float(x1))

    def zoom_x(self, factor: float) -> None:
        """Zoom X by factor around view center (factor > 1 = zoom out)."""
        window = self._proxy.get_time_window()
        if window is not None:
            center = (window[0] + window[1]) * 0.5
            self._proxy.request_zoom_x(factor, center)


# ======================================================================

class ComparisonWindow(QWidget):
    """Floating window for side-by-side single-channel comparison of up to 4 datasets."""

    def __init__(self, host: "VasoAnalyzerApp"):
        # Qt.WindowType.Tool keeps the window above its parent without being system-wide always-on-top.
        super().__init__(host, Qt.WindowType.Tool)
        self._host = host
        self._panels: list[ComparisonPanel] = []
        self._channel = "inner"
        self._mouse_mode = "pan"

        from utils.config import APP_VERSION
        self.setWindowTitle(f"VasoAnalyzer {APP_VERSION} — Dataset Comparison")
        self.resize(1100, 600)
        self.setAcceptDrops(True)

        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)

        # ── Toolbar + channel selector ────────────────────────────────
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        self._toolbar = self._build_toolbar()
        top.addWidget(self._toolbar)

        top.addWidget(QLabel("Channel:"))
        self._combo = QComboBox()
        for key, label in _CHANNELS:
            self._combo.addItem(label, key)
        self._combo.currentIndexChanged.connect(self._on_channel_changed)
        top.addWidget(self._combo)

        top.addStretch()

        self._hint_label = QLabel()
        top.addWidget(self._hint_label)
        layout.addLayout(top)

        # ── Panel splitter ────────────────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self._splitter, 1)

        # ── Empty state ───────────────────────────────────────────────
        self._empty_label = QLabel(
            "Drop datasets from the project tree to compare them\n"
            f"(up to {_MAX_PANELS} datasets — drag the same dataset twice for dual-viewport)"
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)

        self._refresh_state()

    def _build_toolbar(self) -> QToolBar:
        """Build a toolbar that looks identical to the main window's PlotToolbar."""
        tb = QToolBar()
        tb.setObjectName("PlotToolbar")
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setMovable(False)
        tb.setFloatable(False)
        _apply_toolbar_style(tb)

        # ── Mouse-mode toggle (mutually exclusive) ────────────────────
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        self._act_pan = QAction(_load_icon("Pan.svg"), "Pan", self)
        self._act_pan.setCheckable(True)
        self._act_pan.setChecked(True)
        self._act_pan.setToolTip("Pan — drag to scroll the trace horizontally")
        self._act_pan.toggled.connect(
            lambda checked: self._set_mouse_mode("pan") if checked else None
        )
        mode_group.addAction(self._act_pan)
        tb.addAction(self._act_pan)

        self._act_zoom_box = QAction(_load_icon("Zoom.svg"), "Select", self)
        self._act_zoom_box.setCheckable(True)
        self._act_zoom_box.setToolTip("Select — drag a rectangle to zoom into that time range")
        self._act_zoom_box.toggled.connect(
            lambda checked: self._set_mouse_mode("rect") if checked else None
        )
        mode_group.addAction(self._act_zoom_box)
        tb.addAction(self._act_zoom_box)

        tb.addSeparator()

        # ── X-range controls ──────────────────────────────────────────
        act_zoom_all = QAction(_load_icon("Home.svg"), "Zoom All (X)", self)
        act_zoom_all.setToolTip("Zoom All — reset all panels to full trace range")
        act_zoom_all.triggered.connect(self._on_zoom_all_x)
        tb.addAction(act_zoom_all)

        act_zoom_in = QAction(_load_icon("Zoom.svg"), "Zoom In", self)
        act_zoom_in.setToolTip("Zoom In — show less time (all panels)")
        act_zoom_in.triggered.connect(lambda: self._on_zoom_x(0.8))
        tb.addAction(act_zoom_in)

        act_zoom_out = QAction(_load_icon("ZoomOut.svg"), "Zoom Out", self)
        act_zoom_out.setToolTip("Zoom Out — show more time (all panels)")
        act_zoom_out.triggered.connect(lambda: self._on_zoom_x(1.25))
        tb.addAction(act_zoom_out)

        tb.addSeparator()

        # ── Y controls ────────────────────────────────────────────────
        act_autoscale_once = QAction(_load_icon("autoscale.svg"), "Autoscale Y", self)
        act_autoscale_once.setToolTip("Autoscale Y — fit Y axis to visible data (all panels)")
        act_autoscale_once.triggered.connect(self._on_autoscale_y_once)
        tb.addAction(act_autoscale_once)

        return tb

    # ------------------------------------------------------------------
    # Toolbar handlers
    # ------------------------------------------------------------------
    def _set_mouse_mode(self, mode: str) -> None:
        self._mouse_mode = mode
        for panel in self._panels:
            panel.set_mouse_mode(mode)

    def _on_zoom_all_x(self) -> None:
        for panel in self._panels:
            panel.zoom_all_x()

    def _on_zoom_x(self, factor: float) -> None:
        for panel in self._panels:
            panel.zoom_x(factor)

    def _on_autoscale_y_once(self) -> None:
        for panel in self._panels:
            panel.autoscale_y_once()

    # ------------------------------------------------------------------
    # Drag-and-drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(DATASET_MIME_TYPE) and len(self._panels) < _MAX_PANELS:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(DATASET_MIME_TYPE) and len(self._panels) < _MAX_PANELS:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        data = decode_dataset_mime(event.mimeData())
        if data:
            self._add_dataset(data["dataset_id"], data.get("name", ""))
            event.acceptProposedAction()

    # ------------------------------------------------------------------
    def _add_dataset(self, dataset_id: int, name: str) -> None:
        if len(self._panels) >= _MAX_PANELS:
            return

        existing = sum(1 for p in self._panels if p.dataset_id == dataset_id)
        display_name = f"{name} ({existing + 1})" if existing > 0 else name

        trace = self._load_trace(dataset_id)
        if trace is None:
            QMessageBox.information(
                self,
                "Dataset Not Loaded",
                f"Open \"{name}\" in the main view first so its trace data is available.",
            )
            return

        # Load events for this dataset
        events_info = self._load_events(dataset_id)

        panel = ComparisonPanel(
            dataset_id,
            display_name,
            trace,
            self._channel,
            mouse_mode=self._mouse_mode,
            autoscale_y=False,
            events=events_info,
            parent=self,
        )
        panel.close_requested.connect(self._remove_panel)
        self._panels.append(panel)
        self._splitter.addWidget(panel)
        self._refresh_state()

    def _load_trace(self, dataset_id: int):
        """Return a TraceModel for dataset_id.

        First checks in-memory cache on the sample, then falls back to
        loading from the project's SQLite database.
        """
        from vasoanalyzer.core.trace_model import TraceModel

        project = self._host.current_project
        if project is None:
            return None

        # 1) Try in-memory cache
        for exp in project.experiments:
            for s in exp.samples:
                if getattr(s, "dataset_id", None) == dataset_id:
                    if s.trace_data is not None:
                        try:
                            return TraceModel.from_dataframe(s.trace_data)
                        except Exception:
                            log.warning(
                                "Could not build TraceModel from cached data for dataset_id=%s",
                                dataset_id,
                            )

        # 2) Fall back to project database
        ctx = getattr(self._host, "project_ctx", None)
        if ctx is not None:
            try:
                df = ctx.repo.get_trace(dataset_id)
                if df is not None and not df.empty:
                    df = df.rename(columns=_DB_TO_UI_COLUMNS)
                    return TraceModel.from_dataframe(df)
            except Exception:
                log.warning(
                    "Could not load trace from database for dataset_id=%s",
                    dataset_id,
                    exc_info=True,
                )

        return None

    def _load_events(self, dataset_id: int) -> dict | None:
        """Return event times and labels for a dataset, or None."""
        import pandas as pd

        project = self._host.current_project
        if project is None:
            return None

        events_df: pd.DataFrame | None = None

        # 1) Try in-memory cache on the sample
        for exp in project.experiments:
            for s in exp.samples:
                if getattr(s, "dataset_id", None) == dataset_id:
                    if s.events_data is not None and not s.events_data.empty:
                        events_df = s.events_data
                    break
            if events_df is not None:
                break

        # 2) Fall back to project database
        if events_df is None:
            ctx = getattr(self._host, "project_ctx", None)
            if ctx is not None:
                with contextlib.suppress(Exception):
                    events_df = ctx.repo.get_events(dataset_id)

        if events_df is None or events_df.empty:
            return None

        # Extract times and labels
        time_col = None
        for candidate in ("Time (s)", "t_seconds", "time"):
            if candidate in events_df.columns:
                time_col = candidate
                break
        label_col = None
        for candidate in ("Event", "event", "label"):
            if candidate in events_df.columns:
                label_col = candidate
                break

        if time_col is None:
            return None

        times = events_df[time_col].tolist()
        labels = events_df[label_col].tolist() if label_col else [str(i + 1) for i in range(len(times))]
        return {"times": times, "labels": labels}

    def _remove_panel(self, panel: ComparisonPanel) -> None:
        if panel in self._panels:
            self._panels.remove(panel)
        panel.setParent(None)
        panel.deleteLater()
        self._refresh_state()

    def _on_channel_changed(self, index: int) -> None:
        self._channel = self._combo.itemData(index)
        for panel in self._panels:
            panel.set_channel(self._channel)

    def _refresh_state(self) -> None:
        has_panels = bool(self._panels)
        self._empty_label.setVisible(not has_panels)
        self._splitter.setVisible(has_panels)

        remaining = _MAX_PANELS - len(self._panels)
        if remaining == 0:
            self._hint_label.setText("Maximum 4 datasets reached")
        else:
            slot_word = "slot" if remaining == 1 else "slots"
            self._hint_label.setText(
                f"← Drop datasets from the project tree  ({remaining} {slot_word} remaining)"
            )
