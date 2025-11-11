"""PyQtGraph-based trace view with GPU-accelerated rendering."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from vasoanalyzer.core.trace_model import TraceModel, TraceWindow
from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.plots.abstract_renderer import AbstractTraceRenderer
from vasoanalyzer.ui.plots.pyqtgraph_event_labels import PyQtGraphEventLabeler
from vasoanalyzer.ui.theme import CURRENT_THEME


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
            mode: Rendering mode - "inner", "outer", or "dual" (both channels)
            y_label: Custom Y-axis label
            enable_opengl: Enable GPU acceleration (default: True)
        """
        if mode not in {"inner", "outer", "dual"}:
            raise ValueError(f"Unsupported trace view mode: {mode}")

        self._mode = mode
        self._explicit_ylabel = y_label
        self._enable_opengl = enable_opengl

        # Create plot widget with optimizations
        self._plot_widget = pg.PlotWidget()
        self._plot_item = self._plot_widget.getPlotItem()

        # Enable OpenGL acceleration for better performance
        if self._enable_opengl:
            try:
                self._plot_widget.useOpenGL(True)
            except Exception:
                # OpenGL not available, fall back to software rendering
                pass

        # Configure plot appearance
        self._plot_item.showGrid(x=True, y=True, alpha=0.3)
        self._plot_item.setMenuEnabled(False)  # Disable right-click menu

        # Data model and state
        self.model: TraceModel | None = None
        self._current_window: TraceWindow | None = None
        self._autoscale_y = True

        # Plot items
        self.inner_curve: pg.PlotDataItem | None = None
        self.outer_curve: pg.PlotDataItem | None = None
        self.inner_band: pg.FillBetweenItem | None = None
        self.outer_band: pg.FillBetweenItem | None = None
        self.event_lines: list[pg.InfiniteLine] = []

        # Band visibility
        self._show_uncertainty_bands: bool = False

        # Event labeling
        self._event_labeler: PyQtGraphEventLabeler | None = None
        self._event_entries: list[EventEntryV3] = []
        self._event_labels_visible: bool = False

        # Create initial plot items
        self._create_plot_items()

        # Apply theme
        self._apply_theme()

    def _create_plot_items(self) -> None:
        """Create PyQtGraph plot items for traces and events."""
        # Inner diameter trace (primary)
        theme_color = CURRENT_THEME.get("trace_color", "#000000")
        self.inner_curve = self._plot_item.plot(
            pen=pg.mkPen(color=theme_color, width=1.5),
            antialias=True,
            name="Inner Diameter",
        )

        # Outer diameter trace (secondary, if dual mode)
        if self._mode == "dual":
            outer_color = CURRENT_THEME.get("trace_color_secondary", "#FF8C00")
            self.outer_curve = self._plot_item.plot(
                pen=pg.mkPen(color=outer_color, width=1.2),
                antialias=True,
                name="Outer Diameter",
            )

    def _apply_theme(self) -> None:
        """Apply color theme from CURRENT_THEME."""
        # Background colors
        bg_color = CURRENT_THEME.get("window_bg", "#FFFFFF")
        self._plot_widget.setBackground(bg_color)

        # Axis colors
        text_color = CURRENT_THEME.get("text", "#000000")
        for axis in ["bottom", "left", "right"]:
            ax = self._plot_item.getAxis(axis)
            ax.setPen(text_color)
            ax.setTextPen(text_color)

        # Grid color
        grid_color = CURRENT_THEME.get("grid_color", "#E0E0E0")
        self._plot_item.showGrid(x=True, y=True, alpha=0.3)

    def get_widget(self) -> pg.PlotWidget:
        """Return the PyQtGraph PlotWidget for embedding."""
        return self._plot_widget

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
            self._plot_item.setXRange(x0, x1, padding=0.02)

            # Render the initial data window
            pixel_width = max(int(self._plot_widget.width()), 400)
            self.update_window(x0, x1, pixel_width=pixel_width)

    def _default_ylabel(self) -> str:
        """Get default Y-axis label based on mode."""
        if self._mode == "outer":
            return "Outer Diameter (µm)"
        return "Inner Diameter (µm)"

    def set_events(
        self,
        times: Sequence[float],
        colors: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
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
            if colors is not None and i < len(colors):
                color = colors[i]
            else:
                color = default_color

            # Determine label text
            label_text = ""
            if labels is not None and i < len(labels):
                label_text = labels[i]

            # Create dashed vertical line
            line = pg.InfiniteLine(
                pos=time,
                angle=90,
                pen=pg.mkPen(color=color, width=1.2, style=Qt.DashLine),
                movable=False,
            )
            line.setZValue(5)  # Draw above traces

            # Store label for event labeler
            if label_text:
                line.label = label_text
                # Create EventEntryV3 for label rendering
                event_entry = EventEntryV3(
                    t=time,
                    text=label_text,
                    meta={"color": color},
                )
                self._event_entries.append(event_entry)

            self._plot_item.addItem(line)
            self.event_lines.append(line)

        # Update event labels if labeler exists and is visible
        if self._event_labeler and self._event_labels_visible and self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 400)
            self._event_labeler.render(self._event_entries, xlim, pixel_width)

    def update_window(
        self, x0: float, x1: float, *, pixel_width: int | None = None
    ) -> None:
        """Update the visible time window with LOD selection."""
        if self.model is None:
            return

        # Calculate pixel width if not provided
        if pixel_width is None:
            view_rect = self._plot_item.viewRect()
            pixel_width = max(int(view_rect.width()), 1)

        # Get appropriate LOD level
        level_idx = self.model.best_level_for_window(x0, x1, pixel_width)
        window = self.model.window(level_idx, x0, x1)
        self._current_window = window

        # Update trace data
        self._apply_window(window)

        # Update visible event markers (hide events outside window)
        self._update_event_visibility(x0, x1)

    def _apply_window(self, window: TraceWindow) -> None:
        """Apply windowed data to plot curves."""
        time = window.time
        if time.size == 0:
            if self.inner_curve is not None:
                self.inner_curve.setData([], [])
            if self.inner_band is not None and self.inner_band.scene() is not None:
                self._plot_item.removeItem(self.inner_band)
                self.inner_band = None
            if self.outer_curve is not None:
                self.outer_curve.setData([], [])
            if self.outer_band is not None and self.outer_band.scene() is not None:
                self._plot_item.removeItem(self.outer_band)
                self.outer_band = None
            return

        # Update primary trace (inner or outer depending on mode)
        primary = self._primary_series(window)
        if primary is not None and self.inner_curve is not None:
            mean, ymin, ymax = primary
            # Plot the mean line
            self.inner_curve.setData(time, mean)

            # Add uncertainty bands if enabled
            if self._show_uncertainty_bands and time.size > 1:
                # Create min/max band
                if self.inner_band is None:
                    # Create placeholder curves for FillBetweenItem
                    min_curve = pg.PlotDataItem(time, ymin)
                    max_curve = pg.PlotDataItem(time, ymax)

                    # Create fill between
                    theme_color = CURRENT_THEME.get("accent_fill", "#BBD7FF")
                    qcolor = QColor(theme_color)
                    qcolor.setAlpha(77)  # ~30% opacity

                    self.inner_band = pg.FillBetweenItem(
                        min_curve,
                        max_curve,
                        brush=qcolor,
                    )
                    self.inner_band.setZValue(-1)  # Behind the main trace
                    self._plot_item.addItem(self.inner_band)
                else:
                    # Update existing band
                    # Note: FillBetweenItem doesn't have a direct setData method
                    # We need to recreate it
                    self._plot_item.removeItem(self.inner_band)

                    min_curve = pg.PlotDataItem(time, ymin)
                    max_curve = pg.PlotDataItem(time, ymax)

                    theme_color = CURRENT_THEME.get("accent_fill", "#BBD7FF")
                    qcolor = QColor(theme_color)
                    qcolor.setAlpha(77)

                    self.inner_band = pg.FillBetweenItem(
                        min_curve,
                        max_curve,
                        brush=qcolor,
                    )
                    self.inner_band.setZValue(-1)
                    self._plot_item.addItem(self.inner_band)
            elif self.inner_band is not None:
                # Remove band if disabled
                if self.inner_band.scene() is not None:
                    self._plot_item.removeItem(self.inner_band)
                self.inner_band = None

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
                    if self.outer_band is None:
                        min_curve = pg.PlotDataItem(time, ymin2)
                        max_curve = pg.PlotDataItem(time, ymax2)

                        theme_color = CURRENT_THEME.get("accent_fill_secondary", "#FFD1A9")
                        qcolor = QColor(theme_color)
                        qcolor.setAlpha(51)  # ~20% opacity

                        self.outer_band = pg.FillBetweenItem(
                            min_curve,
                            max_curve,
                            brush=qcolor,
                        )
                        self.outer_band.setZValue(-1)
                        self._plot_item.addItem(self.outer_band)
                    else:
                        # Update existing band
                        self._plot_item.removeItem(self.outer_band)

                        min_curve = pg.PlotDataItem(time, ymin2)
                        max_curve = pg.PlotDataItem(time, ymax2)

                        theme_color = CURRENT_THEME.get("accent_fill_secondary", "#FFD1A9")
                        qcolor = QColor(theme_color)
                        qcolor.setAlpha(51)

                        self.outer_band = pg.FillBetweenItem(
                            min_curve,
                            max_curve,
                            brush=qcolor,
                        )
                        self.outer_band.setZValue(-1)
                        self._plot_item.addItem(self.outer_band)
                elif self.outer_band is not None:
                    if self.outer_band.scene() is not None:
                        self._plot_item.removeItem(self.outer_band)
                    self.outer_band = None
            else:
                self.outer_curve.setData([], [])
                if self.outer_band is not None and self.outer_band.scene() is not None:
                    self._plot_item.removeItem(self.outer_band)
                    self.outer_band = None

    def _primary_series(
        self, window: TraceWindow
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Get primary data series based on mode."""
        if self._mode == "outer":
            if (
                window.outer_mean is None
                or window.outer_min is None
                or window.outer_max is None
            ):
                return None
            return window.outer_mean, window.outer_min, window.outer_max
        return window.inner_mean, window.inner_min, window.inner_max

    def _secondary_series(
        self, window: TraceWindow
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Get secondary data series (outer in dual mode)."""
        if self._mode == "dual":
            if (
                window.outer_mean is None
                or window.outer_min is None
                or window.outer_max is None
            ):
                return None
            return window.outer_mean, window.outer_min, window.outer_max
        return None

    def _update_event_visibility(self, x0: float, x1: float) -> None:
        """Show/hide event markers based on visible window."""
        # PyQtGraph handles clipping automatically, but we could
        # optimize by hiding lines far outside the viewport
        pass

    def set_xlim(self, x0: float, x1: float) -> None:
        """Set X-axis limits."""
        self._plot_item.setXRange(x0, x1, padding=0)

    def set_ylim(self, y0: float, y1: float) -> None:
        """Set Y-axis limits."""
        self._plot_item.setYRange(y0, y1, padding=0)
        self._autoscale_y = False  # Disable autoscale when manually set

    def get_xlim(self) -> tuple[float, float]:
        """Get current X-axis limits."""
        x_range = self._plot_item.viewRange()[0]
        return float(x_range[0]), float(x_range[1])

    def get_ylim(self) -> tuple[float, float]:
        """Get current Y-axis limits."""
        y_range = self._plot_item.viewRange()[1]
        return float(y_range[0]), float(y_range[1])

    def autoscale_y(self) -> None:
        """Autoscale Y-axis to fit visible data."""
        if self._current_window is None:
            return

        # Recalculate Y limits from current window
        self._autoscale_y = True
        self._apply_window(self._current_window)

    def set_autoscale_y(self, enabled: bool) -> None:
        """Enable/disable Y-axis autoscaling."""
        self._autoscale_y = enabled
        if enabled:
            self.autoscale_y()

    def refresh(self) -> None:
        """Force a complete redraw."""
        if self._current_window is not None:
            self._apply_window(self._current_window)

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
        elif self._mode == "dual":
            parts = []
            if (
                window.inner_min is not None
                and window.inner_max is not None
            ):
                parts.append(
                    (
                        np.nanmin(window.inner_min),
                        np.nanmax(window.inner_max),
                    )
                )
            if (
                window.outer_min is not None
                and window.outer_max is not None
            ):
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

    def set_xlabel(self, label: str) -> None:
        """Set X-axis label."""
        self._plot_item.setLabel("bottom", label)

    def set_ylabel(self, label: str) -> None:
        """Set Y-axis label."""
        self._plot_item.setLabel("left", label)

    def set_title(self, title: str) -> None:
        """Set plot title."""
        self._plot_item.setTitle(title)

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

        if (
            "trace_color_secondary" in style
            and self.outer_curve is not None
        ):
            pen = pg.mkPen(color=style["trace_color_secondary"], width=1.2)
            self.outer_curve.setPen(pen)

        # Update background
        if "background_color" in style:
            self._plot_widget.setBackground(style["background_color"])

        # Update grid
        if "grid_color" in style:
            # PyQtGraph grid styling is limited
            pass

        # Update event line colors
        if "event_line_color" in style:
            event_color = style["event_line_color"]
            for line in self.event_lines:
                pen = pg.mkPen(color=event_color, width=1.2, style=Qt.DashLine)
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
                pixel_width = max(int(self._plot_widget.width()), 400)
                self._event_labeler.render(self._event_entries, xlim, pixel_width)
        else:
            # Hide labels
            if self._event_labeler:
                self._event_labeler.set_visible(False)

    def update_event_labels(self) -> None:
        """Update event label positions after view change."""
        if (
            self._event_labeler
            and self._event_labels_visible
            and self._event_entries
        ):
            xlim = self.get_xlim()
            self._event_labeler.update_positions(xlim)

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
        # This is a placeholder for hover tooltip functionality
        # Full implementation would involve:
        # 1. Creating a pg.TextItem for the tooltip
        # 2. Connecting to plot's sigMouseMoved signal
        # 3. Finding nearest data point to cursor
        # 4. Displaying formatted value in tooltip
        # 5. Positioning tooltip near cursor
        #
        # For now, we'll store the settings for future implementation
        self._hover_tooltip_enabled = enabled
        self._hover_tooltip_precision = precision

        # TODO: Implement actual hover tooltip rendering
        # This would require:
        # - Mouse tracking
        # - Data point lookup (efficient nearest-neighbor search)
        # - Tooltip positioning and styling
        pass
