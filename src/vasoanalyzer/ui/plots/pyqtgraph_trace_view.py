"""PyQtGraph-based trace view with GPU-accelerated rendering."""

from __future__ import annotations

import contextlib
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtWidgets import QApplication, QWidget

from vasoanalyzer.core.trace_model import TraceModel, TraceWindow
from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.formatting.time_format import TimeMode, coerce_time_mode
from vasoanalyzer.ui.plots.abstract_renderer import AbstractTraceRenderer
from vasoanalyzer.ui.plots.event_display_mode import (
    EventDisplayMode,
    coerce_event_display_mode,
)
from vasoanalyzer.ui.plots.pinch_blocker import PinchBlocker
from vasoanalyzer.ui.plots.pyqtgraph_event_marker_layer import (
    PyQtGraphEventMarkerLayer,
)
from vasoanalyzer.ui.plots.pyqtgraph_style import (
    PLOT_AXIS_LABELS,
    apply_selection_box_style,
    get_pyqtgraph_style,
)
from vasoanalyzer.ui.plots.smooth_pan_viewbox import SmoothPanViewBox
from vasoanalyzer.ui.plots.time_axis_item import TimeAxisItem
from vasoanalyzer.ui.plots.y_axis_controls import required_outer_gutter_px
from vasoanalyzer.ui.parity_flags import chart_view_parity_v1_enabled
from vasoanalyzer.ui.theme import CURRENT_THEME, hex_to_pyqtgraph_color

log = logging.getLogger(__name__)

TOP_PAD = 3
BOTTOM_PAD = 3
INTER_TRACK_GAP_MIN = 6


def y_axis_scale_factor_for_drag_delta(dy_px: float, *, gain: float = 0.006) -> float:
    """Convert axis drag delta (pixels) into multiplicative Y span factor."""
    return float(math.exp(float(dy_px) * float(gain)))


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
        self._chart_parity_v1 = chart_view_parity_v1_enabled()

        # Create custom ViewBox that handles smooth horizontal pan (not zoom)
        # This is the single source of truth for scroll behavior
        view_box = SmoothPanViewBox(enableMenu=False)
        view_box.setMouseEnabled(x=True, y=False)  # Horizontal interactions only
        view_box.setMouseMode(view_box.PanMode)  # Default: grab to pan horizontally
        self._mouse_mode: str = "pan"
        self._time_axis = TimeAxisItem(orientation="bottom")
        self._left_outer_gutter_px = int(required_outer_gutter_px())
        self._bottom_axis_visible = True

        # Create plot widget with our custom ViewBox
        self._plot_widget = pg.PlotWidget(viewBox=view_box, axisItems={"bottom": self._time_axis})
        self._plot_item = self._plot_widget.getPlotItem()
        self._apply_plot_item_layout()
        self._view_box = view_box
        self._y_axis_controls_host: QWidget = self._plot_widget
        with contextlib.suppress(Exception):
            self._view_box.setDefaultPadding(0.0)
        self._disable_plot_title()
        self._collapse_top_axis()
        self._y_axis_controls_clamped_left_logged = False
        self.set_bottom_axis_visible(True)

        # Suppress pyqtgraph's built-in hover buttons and context menu.
        with contextlib.suppress(Exception):
            self._plot_item.hideButtons()
        with contextlib.suppress(Exception):
            self._plot_item.setMenuEnabled(False)
        with contextlib.suppress(Exception):
            self._plot_item.getViewBox().setMenuEnabled(False)

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

        # Connect ViewBox range changes to sync with time window management
        # This ensures native PyQtGraph interactions (pan/rectangle-zoom) sync with our PlotHost
        self._view_box.sigRangeChanged.connect(self._on_viewbox_range_changed)
        self._syncing_range = False  # Prevent circular updates

        # Data model and state
        self.model: TraceModel | None = None
        self._current_window: TraceWindow | None = None
        self._autoscale_y = False  # Default: fixed Y-axis (user can enable in Plot Settings)
        self._host_driven_xrange = False

        # Plot items
        self.inner_curve: pg.PlotDataItem | None = None
        self.outer_curve: pg.PlotDataItem | None = None
        self.inner_band: pg.FillBetweenItem | None = None
        self.outer_band: pg.FillBetweenItem | None = None
        self._inner_band_min_curve: pg.PlotDataItem | None = None
        self._inner_band_max_curve: pg.PlotDataItem | None = None
        self._outer_band_min_curve: pg.PlotDataItem | None = None
        self._outer_band_max_curve: pg.PlotDataItem | None = None

        # Band visibility
        self._show_uncertainty_bands: bool = False

        # Event markers/labels
        self._event_layer = PyQtGraphEventMarkerLayer(self._plot_item)
        self._event_entries: list[EventEntryV3] = []
        self._event_times_np = np.empty(0, dtype=float)
        self._event_labels_visible: bool = False
        self._event_layer.set_labels_visible(False)
        self._event_display_mode = EventDisplayMode.NAMES_ON_HOVER
        self._event_layer.set_display_mode(self._event_display_mode)
        self._event_hover_handler: Callable[[int | None], None] | None = None
        self._hovered_event_index: int | None = None

        # Event line styling parameters
        style = get_pyqtgraph_style()
        self._event_line_width = float(style.event_marker.width)
        self._event_line_style = style.event_marker.style
        self._event_line_color = str(style.event_marker.color)
        self._event_line_alpha = float(style.event_marker.alpha)

        # Create initial plot items
        self._create_plot_items()

        # Apply theme
        self._apply_theme()

        # Click handling
        self._click_handler: Callable[[float, float, int, str, Any], None] | None = None
        self._pin_items: list[tuple[pg.ScatterPlotItem, pg.TextItem]] = []
        self._y_axis_controls: QWidget | None = None
        self._y_axis_menu_control_widget: QWidget | None = None
        self._y_axis_scale_control_widget: QWidget | None = None
        self._y_axis_autoscale_once_handler: Callable[[], None] | None = None
        self._y_axis_menu_handler: Callable[[QPoint], None] | None = None
        self._y_axis_scale_about_handler: Callable[[float | None, float], None] | None = None
        self._y_axis_drag_started_handler: Callable[[], None] | None = None
        self._y_axis_drag_finished_handler: Callable[[], None] | None = None
        self._y_axis_drag_active = False
        self._y_axis_drag_last_pos: QPoint | None = None
        self._y_axis_cursor_forced = False
        self._y_axis_saved_cursor_explicit = False
        self._y_axis_saved_cursor = QCursor()
        self._y_axis_controls_filter = _YAxisControlsFilter(self, parent=self._plot_widget)
        self._plot_widget.installEventFilter(self._y_axis_controls_filter)
        with contextlib.suppress(Exception):
            self._plot_widget.viewport().installEventFilter(self._y_axis_controls_filter)

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

    def _disable_plot_title(self) -> None:
        """Remove PlotItem title text and reclaim the title row height."""
        with contextlib.suppress(Exception):
            # In pyqtgraph, an empty-string title still reserves title-row height.
            # `None` is the only value that truly disables the title row.
            self._plot_item.setTitle(None)

        label = getattr(self._plot_item, "titleLabel", None)
        if label is not None:
            with contextlib.suppress(Exception):
                label.setText("")
            with contextlib.suppress(Exception):
                label.setVisible(False)
            with contextlib.suppress(Exception):
                label.hide()
            for setter in ("setMaximumHeight", "setMinimumHeight", "setPreferredHeight"):
                fn = getattr(label, setter, None)
                if callable(fn):
                    with contextlib.suppress(Exception):
                        fn(0)

        layout = getattr(self._plot_item, "layout", None)
        if layout is not None:
            # Fully collapse the title row. `setRowFixedHeight` alone is not
            # sufficient because the LabelItem can still contribute min/preferred
            # size and leave a top gutter.
            for setter in (
                "setRowFixedHeight",
                "setRowPreferredHeight",
                "setRowMinimumHeight",
                "setRowMaximumHeight",
            ):
                fn = getattr(layout, setter, None)
                if callable(fn):
                    with contextlib.suppress(Exception):
                        fn(0, 0)

    def _collapse_top_axis(self) -> None:
        """Remove reserved top-axis row height so Y-axis spans full track height."""
        with contextlib.suppress(Exception):
            self._plot_item.hideAxis("top")
        axis = self._plot_item.getAxis("top")
        if axis is None:
            return
        with contextlib.suppress(Exception):
            axis.setVisible(False)
        with contextlib.suppress(Exception):
            axis.setStyle(showValues=False, tickLength=0)
        with contextlib.suppress(Exception):
            axis.setLabel("")
        with contextlib.suppress(Exception):
            axis.setHeight(0)
        with contextlib.suppress(AttributeError):
            axis.label.hide()
            axis.showLabel(False)

    def _apply_plot_item_layout(self) -> None:
        """Tighten PlotItem layout while reserving a fixed left gutter for controls."""
        layout = getattr(self._plot_item, "layout", None)
        if layout is None:
            return
        with contextlib.suppress(Exception):
            layout.setContentsMargins(int(self._left_outer_gutter_px), 0, 0, 0)
        with contextlib.suppress(Exception):
            layout.setHorizontalSpacing(0)
        with contextlib.suppress(Exception):
            layout.setVerticalSpacing(0)

    def set_left_outer_gutter_px(self, width_px: int) -> None:
        """Set reserved left-side gutter in pixels for Y-axis controls."""
        value = max(int(width_px), 0)
        if value == int(self._left_outer_gutter_px):
            return
        self._left_outer_gutter_px = value
        self._apply_plot_item_layout()
        self._reposition_y_axis_controls()

    def set_bottom_axis_visible(self, visible: bool) -> None:
        """Show/hide bottom axis and collapse hidden-axis height."""
        self._bottom_axis_visible = bool(visible)
        axis = self._plot_item.getAxis("bottom")
        if axis is None:
            return
        if self._bottom_axis_visible:
            self._plot_item.showAxis("bottom")
            with contextlib.suppress(AttributeError):
                axis.enableAutoSIPrefix(False)
            axis.setVisible(True)
            axis.setStyle(showValues=True)
            axis.setLabel(self._time_axis_label())
            with contextlib.suppress(AttributeError):
                axis.setTickLength(5, 0)
            with contextlib.suppress(Exception):
                axis.setHeight(None)
            with contextlib.suppress(AttributeError):
                axis.label.show()
                axis.showLabel(True)
            return

        with contextlib.suppress(Exception):
            self._plot_item.hideAxis("bottom")
        axis.setVisible(False)
        with contextlib.suppress(Exception):
            axis.setStyle(showValues=False, tickLength=0)
        with contextlib.suppress(Exception):
            axis.setLabel("")
        with contextlib.suppress(Exception):
            axis.setHeight(0)
        with contextlib.suppress(AttributeError):
            axis.label.hide()
            axis.showLabel(False)

    def bottom_axis_visible(self) -> bool:
        """Return whether the bottom axis is currently visible."""
        return bool(self._bottom_axis_visible)

    def view_box(self) -> SmoothPanViewBox:
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

    def _time_axis_label(self) -> str:
        mode = self.time_mode()
        if mode == TimeMode.SECONDS:
            return "Time (s)"
        return "Time"

    def set_time_mode(self, mode: TimeMode | str) -> None:
        resolved = coerce_time_mode(mode)
        self._time_axis.set_time_mode(resolved)
        self.set_bottom_axis_visible(self._bottom_axis_visible)

    def time_mode(self) -> TimeMode:
        return self._time_axis.time_mode()

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
            theme_color = "#1f77b4"  # Blue for avg pressure (fixed)
            trace_name = "Avg Pressure"
        elif self._mode == "set_pressure":
            theme_color = "#9467bd"  # Purple for set pressure (fixed)
            trace_name = "Set Pressure"
        elif self._mode == "outer":
            theme_color = "#FF8C00"  # Orange for outer diameter (fixed)
            trace_name = "Outer Diameter"
        else:
            theme_color = CURRENT_THEME.get("trace_color", "#000000")  # Changes with theme
            trace_name = "Inner Diameter"

        self.inner_curve = self._plot_item.plot(
            pen=pg.mkPen(color=theme_color, width=1.2),
            antialias=False,
            name=None,
        )
        if hasattr(self.inner_curve, "setClipToView"):
            with contextlib.suppress(Exception):
                self.inner_curve.setClipToView(True)
        if hasattr(self.inner_curve, "setDownsampling"):
            with contextlib.suppress(Exception):
                self.inner_curve.setDownsampling(auto=True, mode="peak")

        # Outer diameter trace (secondary, if dual mode)
        if self._mode == "dual":
            outer_color = "#FF8C00"  # Orange for outer diameter (fixed, doesn't change with theme)
            self.outer_curve = self._plot_item.plot(
                pen=pg.mkPen(color=outer_color, width=1.1),
                antialias=False,
                name=None,
            )
            if hasattr(self.outer_curve, "setClipToView"):
                with contextlib.suppress(Exception):
                    self.outer_curve.setClipToView(True)
            if hasattr(self.outer_curve, "setDownsampling"):
                with contextlib.suppress(Exception):
                    self.outer_curve.setDownsampling(auto=True, mode="peak")

    def _apply_theme(self) -> None:
        """Apply color theme from CURRENT_THEME."""
        style = get_pyqtgraph_style()
        # Background colors - use plot_bg for white content area in light mode
        bg_rgb = hex_to_pyqtgraph_color(style.background_color)
        self._plot_widget.setBackground(bg_rgb)

        # Axis colors
        axis_color = style.axis_pen_color
        tick_color = style.tick_label_color
        for axis in ["bottom", "left", "right"]:
            ax = self._plot_item.getAxis(axis)
            ax.setPen(pg.mkPen(axis_color))
            ax.setTextPen(pg.mkPen(tick_color))
        self._collapse_top_axis()

        # Grid visibility
        self._plot_item.showGrid(x=True, y=True, alpha=style.grid_alpha)

        # Update trace line colors
        # Only update inner diameter trace color (changes with theme: black in light, white in dark)
        # Other traces (outer, pressure, set_pressure) keep their fixed colors
        if self.inner_curve is not None and self._mode in ("inner", "dual"):
            inner_color = CURRENT_THEME.get("trace_color", "#000000")
            pen = pg.mkPen(color=inner_color, width=1.2)
            self.inner_curve.setPen(pen)

        # Outer diameter trace always stays orange (doesn't change with theme)
        # No need to update outer_curve color on theme change

        # Update event line colors
        event_style = style.event_marker
        if (
            event_style.color != self._event_line_color
            or event_style.width != self._event_line_width
            or event_style.style != self._event_line_style
            or event_style.alpha != self._event_line_alpha
        ):
            self._event_line_color = str(event_style.color)
            self._event_line_width = float(event_style.width)
            self._event_line_style = event_style.style
            self._event_line_alpha = float(event_style.alpha)
            self._event_layer.apply_theme()
            self._event_layer.set_line_style(
                width=self._event_line_width,
                style=self._event_line_style,
                color=self._event_line_color,
                alpha=self._event_line_alpha,
            )

    def apply_theme(self) -> None:
        """Public hook to refresh colors after a theme change."""

        self._apply_theme()
        self._event_layer.apply_theme()
        with contextlib.suppress(Exception):
            apply_selection_box_style(self._view_box, get_pyqtgraph_style().selection_box)
        self._init_hover_label()
        self._reposition_y_axis_controls()

        # Force immediate visual update
        self._plot_widget.repaint()
        QApplication.processEvents()

    def get_widget(self) -> pg.PlotWidget:
        """Return the PyQtGraph PlotWidget for embedding."""
        return self._plot_widget

    def install_y_axis_controls(self, controls: QWidget) -> None:
        """Attach compact Y-axis controls as a PlotWidget overlay."""
        if self._y_axis_controls is not None and self._y_axis_controls is not controls:
            with contextlib.suppress(Exception):
                self._y_axis_controls.hide()
                self._y_axis_controls.setParent(None)
            self._detach_y_axis_control_widgets()

        host_widget = self._y_axis_controls_host or self._plot_widget
        if self._chart_parity_v1 and host_widget is self._plot_widget:
            raise RuntimeError("Y-axis controls host must be the dedicated gutter widget")
        controls.setParent(host_widget)
        controls.hide()
        self._y_axis_controls = controls

        menu_widget = getattr(controls, "menu_button_widget", None)
        scale_widget = getattr(controls, "scale_buttons_widget", None)

        self._y_axis_menu_control_widget = menu_widget if isinstance(menu_widget, QWidget) else None
        self._y_axis_scale_control_widget = (
            scale_widget if isinstance(scale_widget, QWidget) else None
        )

        if self._y_axis_menu_control_widget is not None:
            self._y_axis_menu_control_widget.setParent(host_widget)
            self._y_axis_menu_control_widget.show()
            self._y_axis_menu_control_widget.raise_()

        if self._y_axis_scale_control_widget is not None:
            self._y_axis_scale_control_widget.setParent(host_widget)
            self._y_axis_scale_control_widget.show()
            self._y_axis_scale_control_widget.raise_()

        if self._y_axis_menu_control_widget is None and self._y_axis_scale_control_widget is None:
            controls.show()
            controls.raise_()
        attach_controls = getattr(host_widget, "attach_control_widgets", None)
        if callable(attach_controls):
            with contextlib.suppress(Exception):
                attach_controls(
                    menu_widget=self._y_axis_menu_control_widget,
                    scale_widget=self._y_axis_scale_control_widget,
                    controls_widget=controls,
                )
        assert controls.parent() is host_widget
        if self._y_axis_menu_control_widget is not None:
            assert self._y_axis_menu_control_widget.parent() is host_widget
        if self._y_axis_scale_control_widget is not None:
            assert self._y_axis_scale_control_widget.parent() is host_widget
        self.refresh_y_axis_controls()
        self._reposition_y_axis_controls()

    def set_y_axis_controls_host(self, host: QWidget | None) -> None:
        """Set the widget that owns and positions Y-axis controls."""
        target = host if isinstance(host, QWidget) else self._plot_widget
        if target is self._y_axis_controls_host:
            return
        self._y_axis_controls_host = target
        controls = self._y_axis_controls
        if controls is not None:
            self.install_y_axis_controls(controls)

    def set_y_axis_interaction_handlers(
        self,
        *,
        autoscale_once: Callable[[], None] | None = None,
        open_menu: Callable[[QPoint], None] | None = None,
        scale_about: Callable[[float | None, float], None] | None = None,
        drag_started: Callable[[], None] | None = None,
        drag_finished: Callable[[], None] | None = None,
    ) -> None:
        """Set callbacks used by left-axis gestures."""
        self._y_axis_autoscale_once_handler = autoscale_once
        self._y_axis_menu_handler = open_menu
        self._y_axis_scale_about_handler = scale_about
        self._y_axis_drag_started_handler = drag_started
        self._y_axis_drag_finished_handler = drag_finished

    def refresh_y_axis_controls(self) -> None:
        """Refresh the axis controls state from current autoscale settings."""
        controls = self._y_axis_controls
        if controls is None:
            return

        menu_widget = self._y_axis_menu_control_widget
        scale_widget = self._y_axis_scale_control_widget
        host_widget = self._y_axis_controls_host or self.get_widget()
        track_height = int(self.get_widget().height())
        viewbox_rect = self._viewbox_rect_in_widget()
        if viewbox_rect is not None and viewbox_rect.height() > 0:
            track_height = int(viewbox_rect.height())
        elif int(host_widget.height()) > 0:
            track_height = int(host_widget.height())
        show_controls = track_height >= 48
        show_menu_button = track_height >= 48
        show_scale_buttons = track_height >= 64

        if menu_widget is not None:
            menu_widget.setVisible(show_controls and show_menu_button)
        if scale_widget is not None:
            scale_widget.setVisible(show_controls and show_scale_buttons)
        if menu_widget is None and scale_widget is None:
            controls.setVisible(show_controls)
        else:
            controls.setVisible(False)

        refresh_state = getattr(controls, "refresh_state", None)
        if callable(refresh_state):
            with contextlib.suppress(Exception):
                refresh_state()
        self._reposition_y_axis_controls()

    def _detach_y_axis_control_widgets(self) -> None:
        for widget in (self._y_axis_menu_control_widget, self._y_axis_scale_control_widget):
            if widget is None:
                continue
            with contextlib.suppress(Exception):
                widget.hide()
                widget.setParent(None)
        self._y_axis_menu_control_widget = None
        self._y_axis_scale_control_widget = None

    def _left_axis_rect_in_widget(self) -> QRect | None:
        axis = self._plot_item.getAxis("left")
        if axis is None:
            return None
        with contextlib.suppress(Exception):
            rect = axis.sceneBoundingRect()
            if rect is None or not rect.isValid() or rect.isEmpty():
                return None
            top_left = self._plot_widget.mapFromScene(rect.topLeft())
            bottom_right = self._plot_widget.mapFromScene(rect.bottomRight())
            mapped = QRect(top_left, bottom_right).normalized()
            if mapped.isEmpty():
                return None
            return mapped
        return None

    def _viewbox_rect_in_widget(self) -> QRect | None:
        view_box = self._plot_item.getViewBox()
        if view_box is None:
            return None
        with contextlib.suppress(Exception):
            rect = view_box.sceneBoundingRect()
            if rect is None or not rect.isValid() or rect.isEmpty():
                return None
            top_left = self._plot_widget.mapFromScene(rect.topLeft())
            bottom_right = self._plot_widget.mapFromScene(rect.bottomRight())
            mapped = QRect(top_left, bottom_right).normalized()
            if mapped.isEmpty():
                return None
            return mapped
        return None

    def _point_in_left_axis(self, pos: QPoint) -> bool:
        axis_rect = self._left_axis_rect_in_widget()
        if axis_rect is None:
            return False
        return axis_rect.adjusted(-2, -2, 2, 2).contains(pos)

    def _event_pos_in_plot_widget(self, obj, event) -> QPoint | None:
        if not hasattr(event, "pos"):
            return None
        try:
            pos = event.pos()
        except Exception:
            return None
        viewport = self._plot_widget.viewport()
        if obj is self._plot_widget or obj is viewport:
            return QPoint(pos)
        return None

    def _event_global_pos(self, obj, event) -> QPoint:
        if hasattr(event, "globalPos"):
            with contextlib.suppress(Exception):
                return event.globalPos()
        local_pos = self._event_pos_in_plot_widget(obj, event)
        if local_pos is None:
            return QCursor.pos()
        return self._plot_widget.mapToGlobal(local_pos)

    def _data_y_for_widget_pos(self, pos: QPoint) -> float | None:
        view_box = self._plot_item.getViewBox()
        if view_box is None:
            return None
        with contextlib.suppress(Exception):
            scene_pos = self._plot_widget.mapToScene(pos)
            view_pos = view_box.mapSceneToView(scene_pos)
            y_value = float(view_pos.y())
            if np.isfinite(y_value):
                return y_value
        return None

    def _set_y_axis_cursor_feedback(self, enabled: bool) -> None:
        enabled_flag = bool(enabled)
        if enabled_flag:
            if not self._y_axis_cursor_forced:
                self._y_axis_saved_cursor_explicit = bool(
                    self._plot_widget.testAttribute(Qt.WA_SetCursor)
                )
                self._y_axis_saved_cursor = QCursor(self._plot_widget.cursor())
            cursor = QCursor(Qt.SizeVerCursor)
            self._plot_widget.setCursor(cursor)
            with contextlib.suppress(Exception):
                self._plot_widget.viewport().setCursor(cursor)
            self._y_axis_cursor_forced = True
            return

        if not self._y_axis_cursor_forced:
            return
        if self._y_axis_saved_cursor_explicit:
            self._plot_widget.setCursor(self._y_axis_saved_cursor)
            with contextlib.suppress(Exception):
                self._plot_widget.viewport().setCursor(self._y_axis_saved_cursor)
        else:
            self._plot_widget.unsetCursor()
            with contextlib.suppress(Exception):
                self._plot_widget.viewport().unsetCursor()
        self._y_axis_cursor_forced = False
        self._y_axis_saved_cursor_explicit = False

    def _update_cursor_for_position(self, scene_pos: QPointF | None) -> None:
        if scene_pos is None:
            self._set_y_axis_cursor_feedback(False)
            return
        y_axis = self._plot_item.getAxis("left")
        if y_axis is None:
            self._set_y_axis_cursor_feedback(False)
            return
        axis_rect = y_axis.sceneBoundingRect()
        if axis_rect is None or not axis_rect.isValid() or axis_rect.isEmpty():
            self._set_y_axis_cursor_feedback(False)
            return
        self._set_y_axis_cursor_feedback(axis_rect.contains(scene_pos))

    def _reposition_y_axis_controls(self) -> None:
        controls = self._y_axis_controls
        if controls is None:
            return
        host_widget = self._y_axis_controls_host or self._plot_widget

        menu_widget = self._y_axis_menu_control_widget
        scale_widget = self._y_axis_scale_control_widget

        if host_widget is not self._plot_widget:
            attach_controls = getattr(host_widget, "attach_control_widgets", None)
            if callable(attach_controls):
                with contextlib.suppress(Exception):
                    attach_controls(
                        menu_widget=menu_widget,
                        scale_widget=scale_widget,
                        controls_widget=controls,
                    )
            layout_channel_label = getattr(host_widget, "layout_channel_label", None)
            if callable(layout_channel_label):
                with contextlib.suppress(Exception):
                    layout_channel_label()
            return

    def _trigger_y_axis_autoscale_once(self) -> bool:
        handler = self._y_axis_autoscale_once_handler
        if not callable(handler):
            return False
        with contextlib.suppress(Exception):
            handler()
            self.refresh_y_axis_controls()
            return True
        return False

    def _show_y_axis_menu(self, global_pos: QPoint) -> bool:
        handler = self._y_axis_menu_handler
        if callable(handler):
            with contextlib.suppress(Exception):
                handler(global_pos)
                self.refresh_y_axis_controls()
                return True
        controls = self._y_axis_controls
        if controls is not None:
            popup_menu = getattr(controls, "popup_menu", None)
            if callable(popup_menu):
                with contextlib.suppress(Exception):
                    popup_menu(global_pos)
                    return True
        return False

    def _end_y_axis_drag(self) -> None:
        if self._y_axis_drag_active:
            handler = self._y_axis_drag_finished_handler
            if callable(handler):
                with contextlib.suppress(Exception):
                    handler()
        self._y_axis_drag_active = False
        self._y_axis_drag_last_pos = None
        self._set_y_axis_cursor_feedback(False)

    def _apply_y_axis_drag_scale(self, dy_px: float, center_y: float | None) -> bool:
        if not self._chart_parity_v1:
            return False
        handler = self._y_axis_scale_about_handler
        if not callable(handler):
            return False
        factor = y_axis_scale_factor_for_drag_delta(float(dy_px))
        if not np.isfinite(factor) or factor <= 0:
            return False
        with contextlib.suppress(Exception):
            handler(center_y, float(factor))
            self.refresh_y_axis_controls()
            return True
        return False

    def _process_axis_mouse_event(self, obj, event) -> bool:
        if obj is None or event is None:
            return False
        viewport = self._plot_widget.viewport()
        if obj is not self._plot_widget and obj is not viewport:
            return False

        event_type = event.type()
        if event_type in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            self._reposition_y_axis_controls()
            return False

        if event_type == QEvent.Leave:
            if self._y_axis_drag_active:
                self._end_y_axis_drag()
            else:
                self._set_y_axis_cursor_feedback(False)
            return False

        if event_type == QEvent.MouseMove and self._y_axis_drag_active:
            pos = self._event_pos_in_plot_widget(obj, event)
            if pos is None:
                return False
            self._set_y_axis_cursor_feedback(True)
            last_pos = self._y_axis_drag_last_pos
            self._y_axis_drag_last_pos = QPoint(pos)
            if last_pos is None:
                event.accept()
                return True
            dy_px = float(pos.y() - last_pos.y())
            if dy_px == 0.0:
                event.accept()
                return True
            center_y = self._data_y_for_widget_pos(pos)
            if self._apply_y_axis_drag_scale(dy_px, center_y):
                event.accept()
                return True
            return False

        if event_type == QEvent.MouseMove:
            pos = self._event_pos_in_plot_widget(obj, event)
            scene_pos = self._plot_widget.mapToScene(pos) if pos is not None else None
            self._update_cursor_for_position(scene_pos)
            return False

        if event_type == QEvent.MouseButtonRelease and self._y_axis_drag_active:
            with contextlib.suppress(Exception):
                if event.button() == Qt.LeftButton:
                    self._end_y_axis_drag()
                    pos = self._event_pos_in_plot_widget(obj, event)
                    self._set_y_axis_cursor_feedback(
                        pos is not None and self._point_in_left_axis(pos)
                    )
                    event.accept()
                    return True

        if event_type not in (
            QEvent.MouseButtonDblClick,
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
        ):
            return False

        pos = self._event_pos_in_plot_widget(obj, event)
        if pos is None or not self._point_in_left_axis(pos):
            return False

        with contextlib.suppress(Exception):
            button = event.button()
            if event_type == QEvent.MouseButtonDblClick and button == Qt.LeftButton:
                self._end_y_axis_drag()
                if self._trigger_y_axis_autoscale_once():
                    event.accept()
                    return True
                return False
            if (
                self._chart_parity_v1
                and event_type == QEvent.MouseButtonPress
                and button == Qt.LeftButton
            ):
                self._y_axis_drag_active = True
                self._y_axis_drag_last_pos = QPoint(pos)
                self._set_y_axis_cursor_feedback(True)
                handler = self._y_axis_drag_started_handler
                if callable(handler):
                    with contextlib.suppress(Exception):
                        handler()
                event.accept()
                return True
            if event_type == QEvent.MouseButtonPress and button == Qt.RightButton:
                global_pos = self._event_global_pos(obj, event)
                if self._show_y_axis_menu(global_pos):
                    event.accept()
                    return True
        return False

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
        self.set_bottom_axis_visible(self._bottom_axis_visible)
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

            # Render the initial data window
            pixel_width = max(int(self._plot_widget.width()), 400)
            self.update_window(x0, x1, pixel_width=pixel_width)
        self._reposition_y_axis_controls()

    def _default_ylabel(self) -> str:
        """Get default Y-axis label based on mode."""
        mapped = PLOT_AXIS_LABELS.get(self._mode)
        if mapped:
            return mapped
        return PLOT_AXIS_LABELS.get("inner", "ID (µm)")

    def set_events(
        self,
        times: Sequence[float],
        colors: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
        meta: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Set event markers to display as vertical lines."""
        # Clear existing event markers/labels
        self._event_layer.clear()

        if not times:
            # Clear event entries too
            self._event_entries.clear()
            self._event_times_np = np.empty(0, dtype=float)
            self._hovered_event_index = None
            self._event_layer.set_hovered_event(None)
            return

        # Default event color
        default_color = get_pyqtgraph_style().event_marker.color

        # Create EventEntryV3 objects for labeling system
        self._event_entries.clear()

        # Create event entries for the marker layer
        for i, time in enumerate(times):
            # Determine color for this event
            color = colors[i] if colors is not None and i < len(colors) else default_color

            # Determine label text
            label_text = ""
            if labels is not None and i < len(labels):
                label_text = labels[i]

            # Store label metadata for the marker layer
            meta_payload: dict[str, Any] = {}
            if meta is not None and i < len(meta):
                candidate = meta[i]
                if isinstance(candidate, Mapping):
                    meta_payload.update(dict(candidate))
            meta_payload.setdefault("event_color", color)
            event_entry = EventEntryV3(
                t=time,
                text=str(label_text or ""),
                meta=meta_payload,
                index=i + 1,  # 1-indexed for display
            )
            self._event_entries.append(event_entry)

        self._event_layer.set_events(self._event_entries)
        self._event_times_np = np.asarray([float(entry.t) for entry in self._event_entries], dtype=float)
        self._hovered_event_index = None
        self._event_layer.set_hovered_event(None)

        if self._event_labels_visible and self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 400)
            self._event_layer.refresh_for_view(xlim[0], xlim[1], pixel_width)

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

        if self._event_labels_visible and self._event_entries:
            self._event_layer.refresh_for_view(x0, x1, pixel_width)

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
        """Manual API: sets X-axis limits directly on this view."""
        if getattr(self, "_host_driven_xrange", False):
            log.warning(
                "TraceView.set_xlim ignored (host-driven xrange active): (%s, %s)",
                x0,
                x1,
            )
            return
        self._syncing_range = True
        try:
            self._plot_item.setXRange(x0, x1, padding=0)
        finally:
            self._syncing_range = False

    def set_host_driven_xrange(self, enabled: bool) -> None:
        """Enable/disable host-driven X ownership guard."""
        self._host_driven_xrange = bool(enabled)

    def get_xlim(self) -> tuple[float, float]:
        """Get current X-axis limits."""
        x_range = self._plot_item.viewRange()[0]
        return float(x_range[0]), float(x_range[1])

    def get_ylim(self) -> tuple[float, float]:
        """Get current Y-axis limits."""
        y_range = self._plot_item.viewRange()[1]
        return float(y_range[0]), float(y_range[1])

    def set_ylim(self, y_min: float, y_max: float, *, preserve_autoscale: bool = False) -> None:
        """Set the visible Y range using public ViewBox API."""
        self._set_ylim_internal(
            float(y_min),
            float(y_max),
            preserve_autoscale=bool(preserve_autoscale),
        )
        trace_id = self._explicit_ylabel or self._mode or hex(id(self))
        log.debug(
            "[PLOT DEBUG] set_ylim trace=%s new_ylim=(%s, %s)",
            trace_id,
            y_min,
            y_max,
        )

    def _set_ylim_internal(self, y_min: float, y_max: float, *, preserve_autoscale: bool) -> None:
        vb = self._view_box
        if preserve_autoscale:
            vb.setRange(
                yRange=(float(y_min), float(y_max)),
                padding=0.0,
                update=True,
                disableAutoRange=not self._autoscale_y,
            )
            return
        vb.enableAutoRange(y=False)
        vb.setRange(
            yRange=(float(y_min), float(y_max)),
            padding=0.0,
            update=True,
            disableAutoRange=True,
        )
        self._autoscale_y = False

    def autoscale_y(self) -> None:
        """Autoscale Y-axis to fit visible data."""
        if self._current_window is None:
            return
        limits = self.data_limits()
        if limits is None:
            return
        y_min, y_max = limits
        if not np.isfinite(y_min) or not np.isfinite(y_max):
            return
        span = y_max - y_min
        if span <= 0:
            span = max(abs(y_min), abs(y_max), 1.0)
        padding = span * 0.05
        self._set_ylim_internal(
            float(y_min - padding),
            float(y_max + padding),
            preserve_autoscale=True,
        )

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
        self._plot_item.showGrid(
            x=bool(visible),
            y=bool(visible),
            alpha=get_pyqtgraph_style().grid_alpha,
        )

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
        self._reposition_y_axis_controls()

    def set_title(self, _title: str) -> None:
        """Plot titles are intentionally disabled; keep title area collapsed."""
        self._disable_plot_title()

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

        self._event_layer.set_line_style(
            width=self._event_line_width,
            style=self._event_line_style,
            color=self._event_line_color,
            alpha=self._event_line_alpha,
        )

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
            pen = pg.mkPen(color=style["trace_color"], width=1.2)
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
            self._event_layer.set_line_style(
                width=self._event_line_width,
                style=self._event_line_style,
                color=self._event_line_color,
                alpha=self._event_line_alpha,
            )

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
        if not enabled:
            self._event_layer.set_display_mode(EventDisplayMode.OFF)
        else:
            self._event_layer.set_display_mode(self._event_display_mode)
        self._event_layer.set_labels_visible(bool(enabled))
        if enabled and self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 1)
            self._event_layer.refresh_for_view(xlim[0], xlim[1], pixel_width)

    def set_event_labels_visible(self, visible: bool) -> None:
        """Public setter for event label visibility."""
        self.enable_event_labels(bool(visible), options=None)

    def are_event_labels_visible(self) -> bool:
        """Return whether event labels are currently visible."""
        return bool(self._event_labels_visible)

    def event_label_options(self) -> LayoutOptionsV3 | None:
        """Return current event labeler options if available."""
        return None

    def update_event_labels(self) -> None:
        """Update event label positions after view change."""
        if self._event_labels_visible and self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 1)
            self._event_layer.refresh_for_view(xlim[0], xlim[1], pixel_width)

    def set_event_label_mode(self, mode: str) -> None:
        """Compatibility bridge for legacy label-mode calls."""
        normalized = str(mode or "").strip().lower()
        if normalized in {"none", "off", "hidden"}:
            self.set_event_display_mode(EventDisplayMode.OFF)
            return
        self.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        if self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 1)
            self._event_layer.refresh_for_view(xlim[0], xlim[1], pixel_width)

    def set_event_display_mode(self, mode: EventDisplayMode | str) -> None:
        self._event_display_mode = coerce_event_display_mode(mode)
        if self._event_labels_visible:
            self._event_layer.set_display_mode(self._event_display_mode)
        else:
            self._event_layer.set_display_mode(EventDisplayMode.OFF)
        if self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 1)
            self._event_layer.refresh_for_view(xlim[0], xlim[1], pixel_width)

    def set_event_hover_handler(self, handler: Callable[[int | None], None] | None) -> None:
        self._event_hover_handler = handler

    def set_selected_event_index(self, index: int | None) -> None:
        """Highlight a selected event in the marker layer."""
        self._event_layer.set_selected_event(index)
        if self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 1)
            self._event_layer.refresh_for_view(xlim[0], xlim[1], pixel_width)

    def set_hovered_event_index(self, index: int | None) -> None:
        self._hovered_event_index = None if index is None else int(index)
        self._event_layer.set_hovered_event(self._hovered_event_index)
        if self._event_entries:
            xlim = self.get_xlim()
            pixel_width = max(int(self._plot_widget.width()), 1)
            self._event_layer.refresh_for_view(xlim[0], xlim[1], pixel_width)

    def refresh_event_markers(self) -> None:
        """Refresh marker label layout for the current view."""
        if not self._event_entries:
            return
        xlim = self.get_xlim()
        pixel_width = max(int(self._plot_widget.width()), 1)
        self._event_layer.refresh_for_view(xlim[0], xlim[1], pixel_width)

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
        try:
            button = mouse_event.button()
        except Exception:
            return
        if button not in (Qt.LeftButton, Qt.RightButton):
            return
        try:
            scene_pos = mouse_event.scenePos()
            widget_pos = self._plot_widget.mapFromScene(scene_pos)
        except Exception:
            scene_pos = None
            widget_pos = None

        if widget_pos is not None and self._point_in_left_axis(widget_pos):
            is_double = False
            with contextlib.suppress(Exception):
                is_double = bool(mouse_event.double())
            if button == Qt.LeftButton and is_double and self._trigger_y_axis_autoscale_once():
                with contextlib.suppress(Exception):
                    mouse_event.accept()
                return
            if button == Qt.RightButton and self._show_y_axis_menu(QCursor.pos()):
                with contextlib.suppress(Exception):
                    mouse_event.accept()
                return

        if self._click_handler is None:
            return
        vb = self._plot_item.vb
        if vb is None:
            return
        try:
            point = vb.mapSceneToView(scene_pos)
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
        self._update_cursor_for_position(point)
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
        self._update_hovered_event_from_x(x_value)
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

    def _event_index_near_x(self, x_value: float, *, tolerance_px: float = 8.0) -> int | None:
        if self._event_times_np.size == 0 or not np.isfinite(x_value):
            return None
        x_range = self.get_xlim()
        x_min = float(x_range[0])
        x_max = float(x_range[1])
        span = max(x_max - x_min, 1e-9)
        pixel_width = max(int(self._plot_widget.width()), 1)
        tolerance_data = (float(tolerance_px) / float(pixel_width)) * span

        idx = int(np.searchsorted(self._event_times_np, x_value))
        candidates = []
        if idx > 0:
            candidates.append(idx - 1)
        if idx < self._event_times_np.size:
            candidates.append(idx)
        if not candidates:
            return None
        best = min(candidates, key=lambda i: abs(float(self._event_times_np[i]) - x_value))
        delta = abs(float(self._event_times_np[best]) - x_value)
        if delta <= tolerance_data:
            return int(best)
        return None

    def _update_hovered_event_from_x(self, x_value: float) -> None:
        new_index = self._event_index_near_x(x_value)
        if new_index == self._hovered_event_index:
            return
        self._hovered_event_index = new_index
        self._event_layer.set_hovered_event(new_index)
        handler = self._event_hover_handler
        if callable(handler):
            try:
                handler(new_index)
            except Exception:
                pass

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
        hovered_idx = self._hovered_event_index
        if hovered_idx is not None and 0 <= hovered_idx < len(self._event_entries):
            event_entry = self._event_entries[hovered_idx]
            event_text = str(event_entry.text or "").strip()
            if event_text:
                lines.append(f"Event: {event_text}")
            try:
                event_time = float(event_entry.t)
            except Exception:
                event_time = None
            if event_time is not None and np.isfinite(event_time):
                lines.append(f"Event time: {fmt.format(event_time)} s")

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
        if self._hovered_event_index is not None:
            self._hovered_event_index = None
            self._event_layer.set_hovered_event(None)
            handler = self._event_hover_handler
            if callable(handler):
                with contextlib.suppress(Exception):
                    handler(None)
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


class _YAxisControlsFilter(QObject):
    """Handle axis-control overlay positioning and axis gesture shortcuts."""

    def __init__(self, owner: PyQtGraphTraceView, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._owner = owner

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        with contextlib.suppress(Exception):
            if self._owner._process_axis_mouse_event(obj, event):
                return True
        return False


# Ensure ABC is satisfied even if abstractmethod metadata lingers.
PyQtGraphTraceView.__abstractmethods__ = frozenset()
