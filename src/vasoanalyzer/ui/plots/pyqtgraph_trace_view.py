"""PyQtGraph-based trace view with GPU-accelerated rendering."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication

from vasoanalyzer.core.trace_model import TraceModel, TraceWindow
from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.plots.abstract_renderer import AbstractTraceRenderer
from vasoanalyzer.ui.plots.pan_only_viewbox import PanOnlyViewBox
from vasoanalyzer.ui.plots.pinch_blocker import PinchBlocker
from vasoanalyzer.ui.plots.pyqtgraph_event_labels import PyQtGraphEventLabeler
from vasoanalyzer.ui.theme import CURRENT_THEME, hex_to_pyqtgraph_color

log = logging.getLogger(__name__)


class PyQtGraphTraceView(AbstractTraceRenderer):
    """GPU-accelerated trace renderer using PyQtGraph.

    Provides high-performance interactive rendering while maintaining
    visual compatibility with the matplotlib-based renderer.
    """

    def __init__(
        self,
        *,
        mode: str = "dual",
        y_label: str | None = None,
        enable_opengl: bool = True,
    ) -> None:
        """Initialize PyQtGraph trace view.

        Args:
            mode: Rendering mode - "inner", "outer", "dual", "avg_pressure", or "set_pressure"
            y_label: Custom Y-axis label
            enable_opengl: Enable GPU acceleration (default: True)
        """
        if mode not in {"inner", "outer", "dual", "avg_pressure", "set_pressure"}:
            raise ValueError(f"Unsupported trace view mode: {mode}")

        self._mode = mode
        self._explicit_ylabel = y_label
        self._enable_opengl = enable_opengl

        # Create custom ViewBox that handles scroll as horizontal pan (not zoom)
        # This is the single source of truth for scroll behavior
        view_box = PanOnlyViewBox(enableMenu=False)
        view_box.setMouseEnabled(x=True, y=False)  # Horizontal interactions only
        view_box.setMouseMode(view_box.PanMode)  # Default: grab to pan horizontally
        self._mouse_mode: str = "pan"

        # Create plot widget with our custom ViewBox
        self._plot_widget = pg.PlotWidget(viewBox=view_box)
        self._plot_item = self._plot_widget.getPlotItem()
        self._view_box = view_box

        # Install pinch blocker on the viewport to prevent trackpad pinch-to-zoom
        pinch_blocker = PinchBlocker(self._plot_widget)
        self._plot_widget.viewport().installEventFilter(pinch_blocker)
        self._pinch_blocker = pinch_blocker  # Keep reference to prevent garbage collection

        # Enable OpenGL acceleration for better performance
        if self._enable_opengl:
            with contextlib.suppress(Exception):
                self._plot_widget.useOpenGL(True)

        # Configure plot appearance
        self._plot_item.showGrid(x=True, y=True, alpha=0.10)
        self._plot_item.setMenuEnabled(False)  # Disable right-click menu

        # Connect ViewBox range changes to sync with time window management
        # This ensures native PyQtGraph interactions (pan/rectangle-zoom) sync with our PlotHost
        self._view_box.sigRangeChanged.connect(self._on_viewbox_range_changed)
        self._syncing_range = False  # Prevent circular updates

        # Data model and state
        self.model: TraceModel | None = None
        self._current_window: TraceWindow | None = None
        self._autoscale_y = False  # Default: fixed Y-axis (user can enable in Plot Settings)

        # Plot items
        self.inner_curve: pg.PlotDataItem | None = None
        self.outer_curve: pg.PlotDataItem | None = None
        self.inner_band: pg.FillBetweenItem | None = None
        self.outer_band: pg.FillBetweenItem | None = None
        self.event_lines: list[pg.InfiniteLine] = []
        self._inner_band_min_curve: pg.PlotDataItem | None = None
        self._inner_band_max_curve: pg.PlotDataItem | None = None
        self._outer_band_min_curve: pg.PlotDataItem | None = None
        self._outer_band_max_curve: pg.PlotDataItem | None = None

        # Band visibility
        self._show_uncertainty_bands: bool = False

        # Event labeling
        self._event_labeler: PyQtGraphEventLabeler | None = None
        self._event_entries: list[EventEntryV3] = []
        self._event_labels_visible: bool = False

        # Event line styling parameters
        self._event_line_width: float = 2.0
        self._event_line_style: Qt.PenStyle = Qt.DashLine
        self._event_line_color: str = "#8A8A8A"
        self._event_line_alpha: float = 1.0

        # Create initial plot items
        self._create_plot_items()

        # Apply theme
        self._apply_theme()

        # Click handling
        self._click_handler: Callable[[float, float, int, str, Any], None] | None = None
        self._pin_items: list[tuple[pg.ScatterPlotItem, pg.TextItem]] = []

        # Initialize persistent hover label
        self._hover_text_item: pg.TextItem | None = None
        self._init_hover_label()
        self._hover_hide_filter = _HoverHideFilter(self)
        with contextlib.suppress(Exception):
            self._plot_widget.viewport().installEventFilter(self._hover_hide_filter)

        # Hover tooltip state
        self._hover_tooltip_enabled: bool = False
        self._hover_tooltip_precision: int = 2
        self._hover_connection_active: bool = False
        self._hover_last_text: str = ""
        self._last_hover_index: int | None = None
        self._last_hover_text: str = ""
        self.enable_hover_tooltip(True, precision=2)

        scene = self._plot_widget.scene()
        if scene is not None:
            scene.sigMouseClicked.connect(self._handle_mouse_clicked)

    def view_box(self) -> PanOnlyViewBox:
        """Return the underlying ViewBox for this trace view."""
        return self._view_box

    def set_mouse_mode(self, mode: str = "pan") -> None:
        """Switch between pan and rectangle-zoom modes using ViewBox API."""
        mode_normalized = "rect" if str(mode).lower() == "rect" else "pan"
        vb = self._view_box
        if mode_normalized == "rect":
            vb.setMouseMode(vb.RectMode)
        else:
            vb.setMouseMode(vb.PanMode)
        # Always keep interactions constrained to X (time) axis
        vb.setMouseEnabled(x=True, y=False)
        self._mouse_mode = mode_normalized

    def mouse_mode(self) -> str:
        """Return current mouse interaction mode ("pan" or "rect")."""
        return getattr(self, "_mouse_mode", "pan")

    def _init_hover_label(self) -> None:
        """Create a persistent hover label anchored to the plot."""
        try:
            text_color = self._to_qcolor(CURRENT_THEME.get("text", "#FFFFFF"), "#FFFFFF")
            bg_color = self._to_qcolor(
                CURRENT_THEME.get("hover_label_bg", "rgba(0,0,0,180)"),
                "rgba(0,0,0,180)",
            )
            border_color = self._to_qcolor(
                CURRENT_THEME.get("hover_label_border", "#000000"), "#000000"
            )
        except Exception:
            text_color = self._to_qcolor("#FFFFFF", "#FFFFFF")
            bg_color = self._to_qcolor("rgba(0,0,0,180)", "#000000")
            border_color = self._to_qcolor("#000000", "#000000")

        # Remove existing item if any
        if self._hover_text_item is not None:
            with contextlib.suppress(Exception):
                self._plot_item.removeItem(self._hover_text_item)
            self._hover_text_item = None

        try:
            self._hover_text_item = pg.TextItem(
                color=text_color,
                anchor=(0, 1),
                fill=pg.mkBrush(bg_color),
                border=pg.mkPen(border_color),
            )
            self._hover_text_item.setZValue(1e6)
            self._hover_text_item.setVisible(False)
            self._plot_item.addItem(self._hover_text_item)
        except Exception:
            self._hover_text_item = None

    @staticmethod
    def _to_qcolor(value: str, fallback: str) -> QColor:
        """Best-effort conversion of CSS-like color strings to QColor."""
        try:
            # Handle rgba(r,g,b,a)
            if isinstance(value, str) and value.strip().lower().startswith("rgba"):
                stripped = value.strip()[5:-1]
                parts = [p.strip() for p in stripped.split(",")]
                if len(parts) == 4:
                    r, g, b, a = (float(p) for p in parts)
                    return QColor(int(r), int(g), int(b), int(a))
            c = QColor(value)
            if c.isValid():
                return c
        except Exception:
            pass
        fallback_color = QColor(fallback)
        return fallback_color if fallback_color.isValid() else QColor("#000000")

    def _create_plot_items(self) -> None:
        """Create PyQtGraph plot items for traces and events."""
        # Determine color and name based on mode
        if self._mode == "avg_pressure":
            theme_color = "#1f77b4"  # Blue for avg pressure
            trace_name = "Avg Pressure"
        elif self._mode == "set_pressure":
            theme_color = "#9467bd"  # Purple for set pressure
            trace_name = "Set Pressure"
        elif self._mode == "outer":
            theme_color = CURRENT_THEME.get("trace_color_secondary", "#FF8C00")
            trace_name = "Outer Diameter"
        else:
            theme_color = CURRENT_THEME.get("trace_color", "#000000")
            trace_name = "Inner Diameter"

        self.inner_curve = self._plot_item.plot(
            pen=pg.mkPen(color=theme_color, width=1.5),
            antialias=False,
            name=trace_name,
        )
        if hasattr(self.inner_curve, "setClipToView"):
            with contextlib.suppress(Exception):
                self.inner_curve.setClipToView(True)
        if hasattr(self.inner_curve, "setDownsampling"):
            with contextlib.suppress(Exception):
                self.inner_curve.setDownsampling(auto=True, mode="peak")

        # Outer diameter trace (secondary, if dual mode)
        if self._mode == "dual":
            outer_color = CURRENT_THEME.get("trace_color_secondary", "#FF8C00")
            self.outer_curve = self._plot_item.plot(
                pen=pg.mkPen(color=outer_color, width=1.2),
                antialias=False,
                name="Outer Diameter",
            )
            if hasattr(self.outer_curve, "setClipToView"):
                with contextlib.suppress(Exception):
                    self.outer_curve.setClipToView(True)
            if hasattr(self.outer_curve, "setDownsampling"):
                with contextlib.suppress(Exception):
                    self.outer_curve.setDownsampling(auto=True, mode="peak")

    def _apply_theme(self) -> None:
        """Apply color theme from CURRENT_THEME."""
        # Background colors - use plot_bg for white content area in light mode
        bg_color = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
        bg_rgb = hex_to_pyqtgraph_color(bg_color)
        self._plot_widget.setBackground(bg_rgb)

        # Axis colors
        text_color = CURRENT_THEME.get("text", "#000000")
        for axis in ["bottom", "left", "right"]:
            ax = self._plot_item.getAxis(axis)
            ax.setPen(text_color)
            ax.setTextPen(text_color)

        # Grid visibility
        self._plot_item.showGrid(x=True, y=True, alpha=0.10)

        # Update trace line colors
        if self.inner_curve is not None:
            inner_color = CURRENT_THEME.get("trace_color", "#000000")
            pen = pg.mkPen(color=inner_color, width=1.5)
            self.inner_curve.setPen(pen)

        if self.outer_curve is not None:
            outer_color = CURRENT_THEME.get("trace_color_secondary", "#FF8C00")
            pen = pg.mkPen(color=outer_color, width=1.2)
            self.outer_curve.setPen(pen)

        # Update event line colors
        event_color = CURRENT_THEME.get("event_line", "#8A8A8A")
        if event_color != self._event_line_color:
            self._event_line_color = event_color
            qcolor = QColor(self._event_line_color)
            qcolor.setAlphaF(self._event_line_alpha)
            for line in self.event_lines:
                pen = pg.mkPen(
                    color=qcolor,
                    width=self._event_line_width,
                    style=self._event_line_style,
                )
                line.setPen(pen)

    def apply_theme(self) -> None:
        """Public hook to refresh colors after a theme change."""

        self._apply_theme()
        self._init_hover_label()

        # Force immediate visual update
        self._plot_widget.repaint()
        QApplication.processEvents()

    def get_widget(self) -> pg.PlotWidget:
        """Return the PyQtGraph PlotWidget for embedding."""
        return self._plot_widget

    def _build_display_curve(
        self, time: np.ndarray, mean: np.ndarray, ymin: np.ndarray, ymax: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Build x/y arrays for the primary curve.

        For bucket_size == 1 (or no min/max data), return (time, mean) as-is.
        For bucket_size > 1, interleave min/max to preserve spikes.
        """

        # Fallback: no min/max provided or arrays are incompatible
        if (
            time is None
            or mean is None
            or ymin is None
            or ymax is None
            or time.size != mean.size
            or time.size != ymin.size
            or time.size != ymax.size
        ):
            return time, mean

        # If min/max differ from the mean, build an envelope to preserve spikes.
        if not (np.allclose(ymin, ymax) and np.allclose(ymin, mean)):
            x = np.repeat(time, 2)
            y = np.empty_like(x)
            y[0::2] = ymin
            y[1::2] = ymax
            return x, y

        return time, mean

    def set_model(self, model: TraceModel) -> None:
        """Set the trace data model."""
        self.model = model
        self._current_window = None

        # Set axis labels
        self._plot_item.setLabel("bottom", "Time (s)")
        ylabel = self._explicit_ylabel or self._default_ylabel()
        self._plot_item.setLabel("left", ylabel)

        # Set initial X range to full data range and render initial data
        if model is not None:
            x0, x1 = model.full_range
            span = float(x1 - x0)

            min_range = None
            max_range = None
            if span > 0:
                min_range = max(span * 1e-6, 1e-6)
                max_range = span

            self._view_box.set_time_limits(x0, x1, min_x_range=min_range, max_x_range=max_range)

            # Constrain ViewBox to prevent panning beyond data boundaries
            self._plot_item.setXRange(x0, x1, padding=0.02)

            # Render the initial data window
            pixel_width = max(int(self._plot_widget.width()), 400)
            self.update_window(x0, x1, pixel_width=pixel_width)

    def _default_ylabel(self) -> str:
        """Get default Y-axis label based on mode."""
        if self._mode == "outer":
            return "Outer Diameter (µm)"
        elif self._mode == "avg_pressure":
            return "Avg Pressure (mmHg)"
        elif self._mode == "set_pressure":
            return "Set Pressure (mmHg)"
        return "Inner Diameter (µm)"

    def set_events(
        self,
        times: Sequence[float],
        colors: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
        meta: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Set event markers to display as vertical lines."""
        # Clear existing event lines
        for line in self.event_lines:
            self._plot_item.removeItem(line)
        self.event_lines.clear()

        if not times:
            # Clear event entries too
            self._event_entries.clear()
            if self._event_labeler:
                self._event_labeler.clear()
            return

        # Default event color
        default_color = CURRENT_THEME.get("event_line", "#8A8A8A")

        # Create EventEntryV3 objects for labeling system
        self._event_entries.clear()

        # Create infinite vertical lines for each event
        for i, time in enumerate(times):
            # Determine color for this event
            color = colors[i] if colors is not None and i < len(colors) else default_color

            # Determine label text
            label_text = ""
            if labels is not None and i < len(labels):
                label_text = labels[i]
            if not label_text:
                label_text = str(i + 1)

            # Create vertical line with configured styling
            qcolor = QColor(self._event_line_color)
            qcolor.setAlphaF(self._event_line_alpha)
            line = pg.InfiniteLine(
                pos=time,
                angle=90,
                pen=pg.mkPen(
                    color=qcolor,
                    width=self._event_line_width,
                    style=self._event_line_style,
                ),
                movable=False,
            )
            line.setZValue(5)  # Draw above traces

            # Store label for event labeler (always create entry for numeric mode)
            meta_payload: dict[str, Any] = {}
            if meta is not None and i < len(meta):
                candidate = meta[i]
                if isinstance(candidate, Mapping):
                    meta_payload.update(dict(candidate))
            meta_payload.setdefault("event_color", color)
            event_entry = EventEntryV3(
                t=time,
                text=label_text or "",
                meta=meta_payload,
                index=i + 1,  # 1-indexed for display
            )
            self._event_entries.append(event_entry)

            self._plot_item.addItem(line)
            self.event_lines.append(line)

        # Update event labels if labeler exists and is visible
        if self._event_labeler and self._event_labels_visible and self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 400)
            self._event_labeler.render(self._event_entries, xlim, pixel_width)

    def update_window(self, x0: float, x1: float, *, pixel_width: int | None = None) -> None:
        """Update the visible time window with LOD selection."""
        if self.model is None:
            return

        # Calculate pixel width if not provided
        if pixel_width is None:
            view_rect = self._plot_item.viewRect()
            pixel_width = max(int(view_rect.width()), 1)
        else:
            pixel_width = max(int(pixel_width), 1)

        # Get appropriate LOD level
        level_idx = self.model.best_level_for_window(x0, x1, pixel_width)
        window = self.model.window(level_idx, x0, x1)
        self._current_window = window

        # Update trace data
        self._apply_window(window)

        # Update visible event markers (hide events outside window)
        self._update_event_visibility(x0, x1)

        if self._event_labeler and self._event_labels_visible and self._event_entries:
            xlim = (x0, x1)
            self._event_labeler.render(self._event_entries, xlim, pixel_width)

    def _apply_window(self, window: TraceWindow) -> None:
        """Apply windowed data to plot curves."""
        time = window.time
        if time.size == 0:
            self._hide_hover_tooltip()
            self._last_hover_index = None
            self._last_hover_text = ""
            if self.inner_curve is not None:
                self.inner_curve.setData([], [])
            if self.outer_curve is not None:
                self.outer_curve.setData([], [])
            if self._inner_band_min_curve is not None:
                self._inner_band_min_curve.setData([], [])
            if self._inner_band_max_curve is not None:
                self._inner_band_max_curve.setData([], [])
            if self.inner_band is not None:
                self.inner_band.setVisible(False)
            if self._outer_band_min_curve is not None:
                self._outer_band_min_curve.setData([], [])
            if self._outer_band_max_curve is not None:
                self._outer_band_max_curve.setData([], [])
            if self.outer_band is not None:
                self.outer_band.setVisible(False)
            return

        # Update primary trace (inner or outer depending on mode)
        primary = self._primary_series(window)
        if primary is not None and self.inner_curve is not None:
            mean, ymin, ymax = primary
            x_vals, y_vals = self._build_display_curve(time, mean, ymin, ymax)
            self.inner_curve.setData(x_vals, y_vals)

            # Add uncertainty bands if enabled
            if self._show_uncertainty_bands and time.size > 1:
                self._update_inner_band(time, ymin, ymax)
            elif self.inner_band is not None:
                self.inner_band.setVisible(False)

            # Autoscale Y if enabled
            if self._autoscale_y:
                y_min = float(np.nanmin(ymin))
                y_max = float(np.nanmax(ymax))

                # Include outer diameter in autoscale if dual mode
                if self._mode == "dual":
                    secondary = self._secondary_series(window)
                    if secondary is not None:
                        _, ymin2, ymax2 = secondary
                        y_min = min(y_min, float(np.nanmin(ymin2)))
                        y_max = max(y_max, float(np.nanmax(ymax2)))

                # Set Y range with small padding
                if np.isfinite(y_min) and np.isfinite(y_max):
                    padding = (y_max - y_min) * 0.05
                    self._plot_item.setYRange(y_min - padding, y_max + padding)

        # Update secondary trace (outer diameter in dual mode)
        if self._mode == "dual" and self.outer_curve is not None:
            secondary = self._secondary_series(window)
            if secondary is not None:
                mean2, ymin2, ymax2 = secondary
                self.outer_curve.setData(time, mean2)

                # Add outer uncertainty bands if enabled
                if self._show_uncertainty_bands and time.size > 1:
                    self._update_outer_band(time, ymin2, ymax2)
                elif self.outer_band is not None:
                    self.outer_band.setVisible(False)
            else:
                self.outer_curve.setData([], [])
                if self.outer_band is not None:
                    self.outer_band.setVisible(False)

    def _update_inner_band(self, time: np.ndarray, ymin: np.ndarray, ymax: np.ndarray) -> None:
        """Create or update the inner uncertainty band without recreating items."""
        if self._inner_band_min_curve is None:
            self._inner_band_min_curve = pg.PlotDataItem(time, ymin)
        else:
            self._inner_band_min_curve.setData(time, ymin)

        if self._inner_band_max_curve is None:
            self._inner_band_max_curve = pg.PlotDataItem(time, ymax)
        else:
            self._inner_band_max_curve.setData(time, ymax)

        if self.inner_band is None:
            theme_color = CURRENT_THEME.get("accent_fill", "#BBD7FF")
            qcolor = QColor(theme_color)
            qcolor.setAlpha(77)  # ~30% opacity

            self.inner_band = pg.FillBetweenItem(
                self._inner_band_min_curve,
                self._inner_band_max_curve,
                brush=qcolor,
            )
            self.inner_band.setZValue(-1)  # Behind the main trace
            self._plot_item.addItem(self.inner_band)
        elif self.inner_band.scene() is None:
            self._plot_item.addItem(self.inner_band)

        if self.inner_band is not None:
            self.inner_band.setVisible(True)

    def _update_outer_band(self, time: np.ndarray, ymin: np.ndarray, ymax: np.ndarray) -> None:
        """Create or update the outer uncertainty band without recreating items."""
        if self._outer_band_min_curve is None:
            self._outer_band_min_curve = pg.PlotDataItem(time, ymin)
        else:
            self._outer_band_min_curve.setData(time, ymin)

        if self._outer_band_max_curve is None:
            self._outer_band_max_curve = pg.PlotDataItem(time, ymax)
        else:
            self._outer_band_max_curve.setData(time, ymax)

        if self.outer_band is None:
            theme_color = CURRENT_THEME.get("accent_fill_secondary", "#FFD1A9")
            qcolor = QColor(theme_color)
            qcolor.setAlpha(51)  # ~20% opacity

            self.outer_band = pg.FillBetweenItem(
                self._outer_band_min_curve,
                self._outer_band_max_curve,
                brush=qcolor,
            )
            self.outer_band.setZValue(-1)
            self._plot_item.addItem(self.outer_band)
        elif self.outer_band.scene() is None:
            self._plot_item.addItem(self.outer_band)

        if self.outer_band is not None:
            self.outer_band.setVisible(True)

    def _primary_series(
        self, window: TraceWindow
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Get primary data series based on mode."""
        if self._mode == "outer":
            if window.outer_mean is None or window.outer_min is None or window.outer_max is None:
                return None
            return window.outer_mean, window.outer_min, window.outer_max
        elif self._mode == "avg_pressure":
            if (
                window.avg_pressure_mean is None
                or window.avg_pressure_min is None
                or window.avg_pressure_max is None
            ):
                return None
            return (
                window.avg_pressure_mean,
                window.avg_pressure_min,
                window.avg_pressure_max,
            )
        elif self._mode == "set_pressure":
            if (
                window.set_pressure_mean is None
                or window.set_pressure_min is None
                or window.set_pressure_max is None
            ):
                return None
            return (
                window.set_pressure_mean,
                window.set_pressure_min,
                window.set_pressure_max,
            )
        return window.inner_mean, window.inner_min, window.inner_max

    def _secondary_series(
        self, window: TraceWindow
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Get secondary data series (outer in dual mode)."""
        if self._mode == "dual":
            if window.outer_mean is None or window.outer_min is None or window.outer_max is None:
                return None
            return window.outer_mean, window.outer_min, window.outer_max
        return None

    def _update_event_visibility(self, x0: float, x1: float) -> None:
        """Show/hide event markers based on visible window."""
        # PyQtGraph handles clipping automatically, but we could
        # optimize by hiding lines far outside the viewport
        pass

    def _on_viewbox_range_changed(self) -> None:
        """Handle ViewBox range changes from native PyQtGraph interactions.

        When the user pans/zooms with trackpad or rectangle selection,
        this syncs the new range with our LOD rendering system.
        """
        if self._syncing_range or self.model is None:
            return

        # Get new X range from ViewBox
        x_range = self._view_box.viewRange()[0]
        x0, x1 = float(x_range[0]), float(x_range[1])

        # Re-render data at new range with LOD
        self._syncing_range = True
        try:
            pixel_width = max(int(self._plot_widget.width()), 400)
            self.update_window(x0, x1, pixel_width=pixel_width)
        finally:
            self._syncing_range = False

    def set_xlim(self, x0: float, x1: float) -> None:
        """Set X-axis limits."""
        self._syncing_range = True
        try:
            self._plot_item.setXRange(x0, x1, padding=0)
        finally:
            self._syncing_range = False

    def get_xlim(self) -> tuple[float, float]:
        """Get current X-axis limits."""
        x_range = self._plot_item.viewRange()[0]
        return float(x_range[0]), float(x_range[1])

    def get_ylim(self) -> tuple[float, float]:
        """Get current Y-axis limits."""
        y_range = self._plot_item.viewRange()[1]
        return float(y_range[0]), float(y_range[1])

    def set_ylim(self, y_min: float, y_max: float) -> None:
        """Set the visible Y range using public ViewBox API."""
        vb = self._view_box
        vb.enableAutoRange(y=False)
        vb.setRange(yRange=(float(y_min), float(y_max)), padding=0.0)
        self._autoscale_y = False
        trace_id = self._explicit_ylabel or self._mode or hex(id(self))
        log.debug(
            "[PLOT DEBUG] set_ylim trace=%s new_ylim=(%s, %s)",
            trace_id,
            y_min,
            y_max,
        )

    def autoscale_y(self) -> None:
        """Autoscale Y-axis to fit visible data."""
        if self._current_window is None:
            return

        # Recalculate Y limits from current window
        self._autoscale_y = True
        self._apply_window(self._current_window)

    def set_autoscale_y(self, enabled: bool) -> None:
        """Enable/disable Y-axis autoscaling using public ViewBox API."""
        vb = self._view_box
        vb.enableAutoRange(y=bool(enabled))
        if enabled:
            vb.autoRange()
        self._autoscale_y = bool(enabled)
        trace_id = self._explicit_ylabel or self._mode or hex(id(self))
        log.debug("[PLOT DEBUG] set_autoscale_y trace=%s enabled=%s", trace_id, enabled)

    def is_autoscale_enabled(self) -> bool:
        """Return whether Y-axis autoscaling is active."""
        return bool(self._autoscale_y)

    def refresh(self) -> None:
        """Force a complete redraw."""
        if self._current_window is not None:
            self._apply_window(self._current_window)

    def set_grid_visible(self, visible: bool) -> None:
        """Toggle grid visibility."""
        self._plot_item.showGrid(x=bool(visible), y=bool(visible))

    def current_window(self) -> TraceWindow | None:
        """Get the currently displayed data window."""
        return self._current_window

    def data_limits(self) -> tuple[float, float] | None:
        """Get Y-axis data limits for current window."""
        window = self._current_window
        if window is None:
            return None

        if self._mode == "outer":
            series_min = window.outer_min
            series_max = window.outer_max
        elif self._mode == "avg_pressure":
            series_min = window.avg_pressure_min
            series_max = window.avg_pressure_max
        elif self._mode == "set_pressure":
            series_min = window.set_pressure_min
            series_max = window.set_pressure_max
        elif self._mode == "dual":
            parts = []
            if window.inner_min is not None and window.inner_max is not None:
                parts.append(
                    (
                        np.nanmin(window.inner_min),
                        np.nanmax(window.inner_max),
                    )
                )
            if window.outer_min is not None and window.outer_max is not None:
                parts.append(
                    (
                        np.nanmin(window.outer_min),
                        np.nanmax(window.outer_max),
                    )
                )
            if not parts:
                return None
            ymin = min(p[0] for p in parts)
            ymax = max(p[1] for p in parts)
            if not np.isfinite(ymin) or not np.isfinite(ymax):
                return None
            return float(ymin), float(ymax)
        else:
            series_min = window.inner_min
            series_max = window.inner_max

        if series_min is None or series_max is None:
            return None

        try:
            ymin = float(np.nanmin(series_min))
            ymax = float(np.nanmax(series_max))
        except ValueError:
            return None

        if not np.isfinite(ymin) or not np.isfinite(ymax):
            return None
        return ymin, ymax

    def set_primary_line_style(
        self,
        color: str | None = None,
        width: float | None = None,
        style: str | None = None,
    ) -> None:
        """Update the primary line pen using Matplotlib-like arguments."""
        if self.inner_curve is None:
            return
        pen_kwargs: dict[str, Any] = {}
        if color is not None:
            pen_kwargs["color"] = color
        if width is not None:
            pen_kwargs["width"] = float(width)
        if style is not None:
            style_map = {
                "solid": Qt.SolidLine,
                "dashed": Qt.DashLine,
                "dashdot": Qt.DashDotLine,
                "dotted": Qt.DotLine,
            }
            pen_kwargs["style"] = style_map.get(style, Qt.SolidLine)
        if not pen_kwargs:
            return
        self.inner_curve.setPen(pg.mkPen(**pen_kwargs))

    def clear_pins(self) -> None:
        """Remove all pinned markers/labels from the plot."""
        for marker, label in list(self._pin_items):
            with contextlib.suppress(Exception):
                self._plot_item.removeItem(marker)
            with contextlib.suppress(Exception):
                self._plot_item.removeItem(label)
        self._pin_items.clear()

    def add_pin(self, x: float, y: float, text: str) -> tuple[pg.ScatterPlotItem, pg.TextItem]:
        """Add a pinned marker/label at the given data coordinates."""
        marker = pg.ScatterPlotItem([x], [y], symbol="o", size=6)
        label = pg.TextItem(text, anchor=(0, 1))
        label.setPos(x, y)
        self._plot_item.addItem(marker)
        self._plot_item.addItem(label)
        self._pin_items.append((marker, label))
        return marker, label

    def set_xlabel(self, label: str) -> None:
        """Set X-axis label."""
        self._plot_item.setLabel("bottom", label)

    def set_ylabel(self, label: str) -> None:
        """Set Y-axis label."""
        self._plot_item.setLabel("left", label)

    def set_title(self, title: str) -> None:
        """Set plot title."""
        self._plot_item.setTitle(title)

    def set_event_line_style(
        self,
        width: float | None = None,
        style: Qt.PenStyle | None = None,
        color: str | None = None,
        alpha: float | None = None,
    ) -> None:
        """Configure event line styling parameters.

        Args:
            width: Line width in pixels
            style: Qt pen style (Qt.SolidLine, Qt.DashLine, Qt.DotLine, Qt.DashDotLine)
            color: Line color as hex string
            alpha: Line alpha/opacity (0.0 to 1.0)
        """
        if width is not None:
            self._event_line_width = float(width)
        if style is not None:
            self._event_line_style = style
        if color is not None:
            self._event_line_color = color
        if alpha is not None:
            self._event_line_alpha = float(alpha)

        # Update existing event lines
        for line in self.event_lines:
            qcolor = QColor(self._event_line_color)
            qcolor.setAlphaF(self._event_line_alpha)
            pen = pg.mkPen(color=qcolor, width=self._event_line_width, style=self._event_line_style)
            line.setPen(pen)

    def apply_style(self, style: dict[str, Any]) -> None:
        """Apply visual styling to the renderer.

        Args:
            style: Dictionary with keys like:
                - trace_color: Inner diameter line color
                - trace_color_secondary: Outer diameter line color
                - event_line_color: Event marker color
                - background_color: Plot background
                - grid_color: Grid line color
        """
        # Update trace colors
        if "trace_color" in style and self.inner_curve is not None:
            pen = pg.mkPen(color=style["trace_color"], width=1.5)
            self.inner_curve.setPen(pen)

        if "trace_color_secondary" in style and self.outer_curve is not None:
            pen = pg.mkPen(color=style["trace_color_secondary"], width=1.2)
            self.outer_curve.setPen(pen)

        # Update background
        if "background_color" in style:
            bg_rgb = hex_to_pyqtgraph_color(style["background_color"])
            self._plot_widget.setBackground(bg_rgb)

        # Update grid
        if "grid_color" in style:
            # PyQtGraph grid styling is limited
            pass

        # Update event line colors
        if "event_line_color" in style:
            self._event_line_color = style["event_line_color"]
            qcolor = QColor(self._event_line_color)
            qcolor.setAlphaF(self._event_line_alpha)
            for line in self.event_lines:
                pen = pg.mkPen(
                    color=qcolor,
                    width=self._event_line_width,
                    style=self._event_line_style,
                )
                line.setPen(pen)

    def get_render_backend(self) -> str:
        """Get the rendering backend identifier."""
        return "pyqtgraph"

    def enable_event_labels(
        self,
        enabled: bool = True,
        options: LayoutOptionsV3 | None = None,
    ) -> None:
        """Enable or disable event label rendering.

        Args:
            enabled: Whether to show event labels
            options: Layout options for event labeling
        """
        self._event_labels_visible = enabled

        if enabled:
            # Create event labeler if not exists
            if self._event_labeler is None:
                self._event_labeler = PyQtGraphEventLabeler(
                    self._plot_item,
                    options=options,
                )
            elif options is not None:
                # Update options
                self._event_labeler.options = options

            # Render labels if we have events
            if self._event_entries:
                xlim = self.get_xlim()
                pixel_width = max(int(self._plot_widget.width()), 1)
                self._event_labeler.render(self._event_entries, xlim, pixel_width)
        else:
            # Hide labels
            if self._event_labeler:
                self._event_labeler.set_visible(False)

    def set_event_labels_visible(self, visible: bool) -> None:
        """Public setter for event label visibility."""
        opts = self._event_labeler.options if self._event_labeler is not None else None
        self.enable_event_labels(bool(visible), options=opts)

    def are_event_labels_visible(self) -> bool:
        """Return whether event labels are currently visible."""
        return bool(self._event_labels_visible)

    def event_label_options(self) -> LayoutOptionsV3 | None:
        """Return current event labeler options if available."""
        if self._event_labeler is None:
            return None
        return self._event_labeler.options

    def update_event_labels(self) -> None:
        """Update event label positions after view change."""
        if self._event_labeler and self._event_labels_visible and self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 1)
            self._event_labeler.render(self._event_entries, xlim, pixel_width)

    def set_uncertainty_bands_visible(self, visible: bool) -> None:
        """Show/hide min/max uncertainty bands.

        Args:
            visible: Whether to show uncertainty bands
        """
        self._show_uncertainty_bands = visible

        # Trigger redraw if we have a current window
        if self._current_window is not None:
            self._apply_window(self._current_window)

    def enable_hover_tooltip(self, enabled: bool, precision: int = 3) -> None:
        """Enable/disable hover tooltips showing data point values.

        Args:
            enabled: Whether to show tooltips on hover
            precision: Number of decimal places to show in values
        """
        self._hover_tooltip_enabled = bool(enabled)
        self._hover_tooltip_precision = max(0, int(precision))
        self._ensure_hover_tracking()

    # Click handling ----------------------------------------------------
    def set_click_handler(
        self, handler: Callable[[float, float, int, str, Any], None] | None
    ) -> None:
        self._click_handler = handler

    def _handle_mouse_clicked(self, mouse_event) -> None:
        if self._click_handler is None:
            return
        try:
            button = mouse_event.button()
        except Exception:
            return
        if button not in (Qt.LeftButton, Qt.RightButton):
            return
        vb = self._plot_item.vb
        if vb is None:
            return
        try:
            point = vb.mapSceneToView(mouse_event.scenePos())
            x_val = float(point.x())
            y_val = float(point.y())
        except Exception:
            return
        self._click_handler(
            x_val, y_val, 1 if button == Qt.LeftButton else 3, self._mode, mouse_event
        )

    def hover_tooltip_enabled(self) -> bool:
        return self._hover_tooltip_enabled

    def hover_tooltip_precision(self) -> int:
        return self._hover_tooltip_precision

    def _ensure_hover_tracking(self) -> None:
        scene = self._plot_widget.scene()
        if scene is None:
            return
        if self._hover_tooltip_enabled and not self._hover_connection_active:
            scene.sigMouseMoved.connect(self._handle_mouse_moved)
            self._hover_connection_active = True
        elif not self._hover_tooltip_enabled and self._hover_connection_active:
            with contextlib.suppress(TypeError):
                scene.sigMouseMoved.disconnect(self._handle_mouse_moved)
            self._hover_connection_active = False
            self._hide_hover_tooltip()

    def _handle_mouse_moved(self, point) -> None:
        if not self._hover_tooltip_enabled:
            return
        if self._plot_item.scene() is None:
            return
        if not self._plot_item.sceneBoundingRect().contains(point):
            self._hide_hover_tooltip()
            return
        view_box = self._plot_item.vb
        if view_box is None:
            return
        mouse_point = view_box.mapSceneToView(point)
        x_value = float(mouse_point.x())
        window = self._current_window
        if window is None or window.time.size == 0:
            self._hide_hover_tooltip()
            return
        idx = self._index_at_time(window.time, x_value)
        if idx is None:
            self._hide_hover_tooltip()
            return
        if (
            idx == self._last_hover_index
            and self._last_hover_text
            and self._hover_text_item is not None
        ):
            self._last_hover_index = idx
            with contextlib.suppress(Exception):
                self._hover_text_item.setPos(float(mouse_point.x()), float(mouse_point.y()))
            self._hover_text_item.setVisible(True)
            return
        text = self._build_hover_text(window, idx)
        if not text:
            self._hide_hover_tooltip()
            return
        if text == self._last_hover_text and self._hover_text_item is not None:
            with contextlib.suppress(Exception):
                self._hover_text_item.setPos(float(mouse_point.x()), float(mouse_point.y()))
            self._hover_text_item.setVisible(True)
            self._last_hover_index = idx
            self._last_hover_text = text
            return
        self._last_hover_index = idx
        self._last_hover_text = text
        self._show_hover_tooltip(text, mouse_point)

    def _index_at_time(self, samples: np.ndarray, target: float) -> int | None:
        sample_count = int(samples.size)
        if sample_count == 0 or np.isnan(target):
            return None
        idx = int(np.searchsorted(samples, target))
        if idx <= 0:
            return 0
        if idx >= sample_count:
            return sample_count - 1
        left = idx - 1
        if abs(target - samples[left]) <= abs(samples[idx] - target):
            return left
        return idx

    def _build_hover_text(self, window: TraceWindow, idx: int) -> str:
        precision = max(0, int(self._hover_tooltip_precision))
        fmt = f"{{:.{precision}f}}"
        lines: list[str] = []

        def add(label: str, value: float | None, unit: str = "") -> None:
            if value is None:
                return
            try:
                val = float(value)
                if np.isnan(val):
                    return
                formatted = fmt.format(val)
                if unit:
                    lines.append(f"{label}: {formatted} {unit}")
                else:
                    lines.append(f"{label}: {formatted}")
            except Exception:
                return

        add("Time", window.time[idx] if window.time.size > idx else None, "s")

        if self._mode not in {"outer", "avg_pressure", "set_pressure"}:
            add(
                "ID",
                window.inner_mean[idx] if window.inner_mean.size > idx else None,
                "µm",
            )

        if (
            self._mode in {"outer", "dual"}
            and window.outer_mean is not None
            and window.outer_mean.size > idx
        ):
            add("OD", window.outer_mean[idx], "µm")

        if window.avg_pressure_mean is not None and window.avg_pressure_mean.size > idx:
            add("Avg P", window.avg_pressure_mean[idx], "mmHg")

        if window.set_pressure_mean is not None and window.set_pressure_mean.size > idx:
            add("Set P", window.set_pressure_mean[idx], "mmHg")

        return "\n".join(lines)

    def _show_hover_tooltip(self, text: str, data_pos) -> None:
        if not text:
            self._hide_hover_tooltip()
            return
        # Always update tooltip to prevent it from disappearing
        # Don't check if text == self._hover_last_text to keep tooltip visible
        self._hover_last_text = text
        if self._hover_text_item is None:
            self._init_hover_label()
        if self._hover_text_item is None:
            return
        self._hover_text_item.setHtml(text.replace("\n", "<br>"))
        with contextlib.suppress(Exception):
            self._hover_text_item.setPos(float(data_pos.x()), float(data_pos.y()))
        self._hover_text_item.setVisible(True)

    def _hide_hover_tooltip(self) -> None:
        self._hover_last_text = ""
        self._last_hover_index = None
        self._last_hover_text = ""
        if self._hover_text_item is not None:
            self._hover_text_item.setVisible(False)


class _HoverHideFilter(QObject):
    """Hide hover tooltip when the cursor leaves the viewport."""

    def __init__(self, owner: PyQtGraphTraceView) -> None:
        super().__init__()
        self._owner = owner

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        if event.type() == QEvent.Leave:
            with contextlib.suppress(Exception):
                self._owner._hide_hover_tooltip()
        return False


# Ensure ABC is satisfied even if abstractmethod metadata lingers.
PyQtGraphTraceView.__abstractmethods__ = frozenset()
