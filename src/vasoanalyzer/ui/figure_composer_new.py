"""New Figure Composer - Clean architecture with publication-ready features.

Phase 1 Implementation:
- Trace selection (inner/outer/both/pressure)
- Axis controls (labels, limits, grid)
- Line style controls (width, colors)
- Event markers
- Font controls
- Multi-format export (PNG, PDF, SVG, TIFF)
"""

from __future__ import annotations

import contextlib
import copy
import logging
import uuid
from datetime import datetime
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colors as mcolors
from matplotlib import patches as mpatches
from matplotlib import transforms as mtransforms
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeySequence, QPalette, QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.core.trace_model import TraceModel

__all__ = ["NewFigureComposerWindow"]

log = logging.getLogger(__name__)

TRACE_KEYS = ["inner", "outer", "avg_pressure", "set_pressure"]
_BOX_SNAP_TOLERANCE_PX = 8.0
# Page / document background colors (preview + export)
PAGE_BG_COLOR = "#ffffff"  # main page / axes background
PAGE_PATCH_COLOR = "#f8f8f8"  # subtle page rectangle fill
PAGE_EDGE_COLOR = "#cccccc"  # page border
# Figure chrome colors (axes text, spines, grid)
FIG_TEXT_COLOR = "#000000"  # Axis labels & tick labels
FIG_SPINE_COLOR = "#000000"  # Axes frame lines
FIG_GRID_COLOR = "#d0d0d0"  # Grid lines on white background


def _normalize_trace_selection(config: dict[str, Any]) -> dict[str, bool]:
    """Return a normalized trace selection map, handling legacy single-trace configs."""
    selection = config.get("trace_selection")
    sel_map = {k: False for k in TRACE_KEYS}

    if isinstance(selection, dict):
        for k in TRACE_KEYS:
            sel_map[k] = bool(selection.get(k, False))
    else:
        legacy = config.get("trace")
        if legacy == "both":
            sel_map["inner"] = True
            sel_map["outer"] = True
        elif legacy in sel_map:
            sel_map[legacy] = True

    # Guarantee at least one trace so the plot has content
    if not any(sel_map.values()):
        sel_map["inner"] = True

    return sel_map


class NewFigureComposerWindow(QMainWindow):
    """New Figure Composer with clean architecture and publication-ready features.

    Architecture: Config dict → SimpleRenderer → Shared Figure ← Canvas
    """

    # Signal emitted when figure is saved to project (figure_id, figure_data)
    figure_saved = pyqtSignal(str, dict)

    def __init__(self, trace_model: TraceModel | None = None, parent=None):
        super().__init__(parent)
        self.trace_model = trace_model
        self.parent_window = parent

        # Undo/redo history
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._max_history: int = 50
        self._restoring_state: bool = False

        # Get event data from parent if available
        self.event_times = []
        self.event_labels = []
        self.event_colors = []
        if parent is not None and hasattr(parent, "event_times"):
            self.event_times = list(getattr(parent, "event_times", []))
            self.event_labels = list(getattr(parent, "event_labels", []))
            self.event_colors = list(getattr(parent, "event_colors", []))

        # Page/page canvas settings (GraphPad-style layout)
        self.screen_dpi = 100  # Fixed DPI for screen display
        self.page_size_name = "Letter"
        self.page_orientation = "Portrait"
        self.page_width_in, self.page_height_in = self._get_page_dimensions()

        # Page-sized figure for display (represents the sheet of paper)
        self.page_figure = Figure(
            figsize=(self.page_width_in, self.page_height_in),
            dpi=self.screen_dpi,
            facecolor=PAGE_BG_COLOR,
        )
        self.canvas = FigureCanvasQTAgg(self.page_figure)
        self.canvas.setStyleSheet("background-color: #ffffff;")  # White canvas
        self._canvas_release_cid = self.canvas.mpl_connect(
            "button_release_event", self._on_canvas_mouse_release
        )
        self.renderer = SimpleRenderer(self.page_figure)

        # Alias for any code that still references self.figure
        self.figure = self.page_figure

        # Initialize config with defaults
        self.config = self._get_default_config()
        self.annotations: list[dict[str, Any]] = self.config.setdefault("annotations", [])
        self._next_annotation_id = max((a.get("id", 0) for a in self.annotations), default=0) + 1
        self._normalize_annotations()
        self.annotation_mode: str | None = None  # None, 'select', 'text', 'box', 'arrow', 'line'
        self._active_annotation_id: int | None = None
        self._annotation_drag_state: dict[str, Any] = {}
        self._annotation_form_lock = False
        self._axes_rect_page: tuple[float, float, float, float] | None = None
        self.plot_axes = None
        self._layout_dirty = True
        self._xlim_cid = None
        self._ylim_cid = None
        self.figure_id: str | None = None
        self.figure_name: str = "Untitled Figure"
        self.figure_metadata: dict[str, Any] = {
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
        }
        # Zoom drag state (Matplotlib canvas)
        self._auto_zoom_active = False
        self._zoom_press_cid = None
        self._zoom_motion_cid = None
        self._zoom_release_cid = None
        # Track whether a user-driven zoom/pan just occurred
        self._user_view_change_pending = False

        # Apply initial page sizing before creating the UI
        self._apply_page_canvas_size()

        self._setup_ui()
        self._resize_to_available_screen()
        self._refresh_annotation_list()

        # Apply stylesheet for better appearance
        self._apply_stylesheet()

        # Setup keyboard shortcuts
        self._setup_shortcuts()
        self._setup_zoom_drag()

        # Initial render after page layout is configured
        self._render()
        self._push_undo_state()

    def _capture_state(self) -> dict:
        """Capture a snapshot of the current composer state for undo/redo."""
        config_copy = copy.deepcopy(self.config)

        snapshot = {
            "config": config_copy,
            "page_size_name": getattr(self, "page_size_name", None),
            "page_orientation": getattr(self, "page_orientation", None),
            "next_annotation_id": getattr(self, "_next_annotation_id", None),
            "active_annotation_id": getattr(self, "_active_annotation_id", None),
            "annotation_mode": getattr(self, "annotation_mode", None),
        }
        return snapshot

    def _restore_state(self, snapshot: dict) -> None:
        """Restore composer state from a snapshot created by _capture_state."""
        if not snapshot:
            return

        self._restoring_state = True
        try:
            page_size_name = snapshot.get("page_size_name")
            page_orientation = snapshot.get("page_orientation")
            if page_size_name is not None:
                self.page_size_name = page_size_name
            if page_orientation is not None:
                self.page_orientation = page_orientation

            self.config = copy.deepcopy(snapshot.get("config", {}))
            self.annotations = self.config.setdefault("annotations", [])
            next_id = snapshot.get("next_annotation_id")
            if next_id is not None:
                self._next_annotation_id = next_id
            self._normalize_annotations()

            self._active_annotation_id = snapshot.get("active_annotation_id")

            mode = snapshot.get("annotation_mode")
            if hasattr(self, "_activate_annotation_mode") and mode is not None:
                self._activate_annotation_mode(mode)

            self._layout_dirty = True

            if hasattr(self, "_apply_page_canvas_size"):
                self._apply_page_canvas_size()

            if hasattr(self, "_apply_config_to_controls"):
                self._apply_config_to_controls()

            if hasattr(self, "_refresh_annotation_list"):
                self._refresh_annotation_list()

            if hasattr(self, "_render"):
                self._render()
        finally:
            self._restoring_state = False

    def _push_undo_state(self) -> None:
        """Push the current state onto the undo stack, clearing redo."""
        if self._restoring_state:
            return

        snapshot = self._capture_state()
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self) -> None:
        """Undo the last change to the composer."""
        if not self._undo_stack:
            return

        current = self._capture_state()
        last = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_state(last)

    def _redo(self) -> None:
        """Redo the last undone change."""
        if not self._redo_stack:
            return

        current = self._capture_state()
        next_state = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_state(next_state)

    def _get_default_config(self) -> dict[str, Any]:
        """Get default configuration."""
        return {
            # Figure size on the page
            "width_mm": 150,
            "height_mm": 75,
            "dpi": 600,
            # Position on page (fractions of page width/height)
            "fig_left": 0.15,
            "fig_top": 0.63,
            # Data
            "trace_selection": {k: (k == "inner") for k in TRACE_KEYS},
            # Axes
            "x_label": "Time (s)",
            "y_label": "Diameter (μm)",
            "x_auto": True,
            "x_min": 0.0,
            "x_max": 60.0,
            "y_auto": True,
            "y_min": 0.0,
            "y_max": 200.0,
            "show_grid": True,
            # Style
            "line_width": 1.0,
            "inner_color": "#000000",
            "outer_color": "#FF0000",
            "pressure_color": "#00AA00",
            # Events
            "show_events": True,
            "event_style": "lines",  # 'lines', 'markers', 'both'
            "event_label_pos": "top",  # 'top', 'bottom', 'none'
            "event_font_size": 10,
            "event_visible_indices": None,  # None = all
            # Layout padding (space for labels/annotations inside figure box)
            "axes_pad_left_mm": 6.0,
            "axes_pad_right_mm": 4.0,
            "axes_pad_top_mm": 4.0,
            "axes_pad_bottom_mm": 6.0,
            "export_margin_in": 0.5,  # extra blank space around figure when exporting
            # Simple axes-relative annotations (e.g., mmHg header boxes)
            "annotations": [],
            # Fonts
            "axis_label_size": 12,
            "tick_label_size": 10,
            "font_family": "Arial",
            "axis_label_bold": False,
            "axis_label_italic": False,
            "tick_label_bold": False,
            "tick_label_italic": False,
            # Time
            "time_unit": "Seconds",  # 'Seconds', 'Minutes', 'Hours'
            "time_divisor": 1.0,  # Conversion factor
            # Spines
            "show_top_spine": False,  # Hide top border (publication style)
            "show_right_spine": False,  # Hide right border (publication style)
        }

    def _get_page_dimensions(self) -> tuple[float, float]:
        """Return page width/height in inches for the current size + orientation."""
        sizes = {
            "Letter": (8.5, 11.0),
            "A4": (8.27, 11.69),
            "Legal": (8.5, 14.0),
        }
        width, height = sizes.get(self.page_size_name, sizes["Letter"])
        if self.page_orientation == "Landscape":
            width, height = height, width
        return width, height

    def _apply_page_canvas_size(self):
        """Apply page size to the display canvas."""
        self.page_width_in, self.page_height_in = self._get_page_dimensions()

        # Update figure and canvas size in pixels using screen DPI
        self.page_figure.set_size_inches(self.page_width_in, self.page_height_in)
        width_px = int(self.page_width_in * self.screen_dpi)
        height_px = int(self.page_height_in * self.screen_dpi)
        self.canvas.setFixedSize(width_px, height_px)

        # Update the scroll area
        if hasattr(self, "canvas_scroll"):
            self.canvas_scroll.widget().updateGeometry()

        # Refresh info bar if it exists
        if hasattr(self, "info_bar"):
            self._update_info_bar()

        # Mark layout dirty so axes get repositioned
        self._layout_dirty = True

    def _apply_page_layout(self):
        """Set up the page canvas and place the plot axes on it."""
        self.page_figure.clear()
        self.page_figure.patch.set_facecolor(PAGE_BG_COLOR)

        # Page background to show the sheet bounds
        page_rect = plt.Rectangle(
            (0, 0),
            1,
            1,
            transform=self.page_figure.transFigure,
            facecolor=PAGE_PATCH_COLOR,
            edgecolor=PAGE_EDGE_COLOR,
            linewidth=0.5,
            zorder=-5,  # keep behind axes/plot
            clip_on=False,
        )
        self.page_figure.patches.append(page_rect)

        # Figure size converted to page fraction
        fig_width_in = self.config["width_mm"] / 25.4
        fig_height_in = self.config["height_mm"] / 25.4
        fig_width_frac = fig_width_in / self.page_width_in
        fig_height_frac = fig_height_in / self.page_height_in

        left = self.config.get("fig_left", 0.1)
        top = self.config.get("fig_top", 0.8)
        bottom = top - fig_height_frac

        # Keep the axes inside soft margins
        margin = 0.03
        left = max(margin, left)
        bottom = max(margin, bottom)
        if left + fig_width_frac > 1 - margin:
            left = (1 - margin) - fig_width_frac
        if bottom + fig_height_frac > 1 - margin:
            bottom = (1 - margin) - fig_height_frac
        left = max(margin, left)
        bottom = max(margin, bottom)

        # Persist adjusted position back to config
        self.config["fig_left"] = left
        self.config["fig_top"] = bottom + fig_height_frac

        # Inset the drawing axes to leave room for labels/annotations within the figure box
        pad_left, pad_right, pad_top, pad_bottom = self._get_axes_padding_fracs(
            base_width_in=self.page_width_in,
            base_height_in=self.page_height_in,
        )
        axes_left = left + pad_left
        axes_bottom = bottom + pad_bottom
        axes_width = max(fig_width_frac - (pad_left + pad_right), 0.02)
        axes_height = max(fig_height_frac - (pad_top + pad_bottom), 0.02)

        # Axes where the actual data is drawn
        self.plot_axes = self.page_figure.add_axes(
            [axes_left, axes_bottom, axes_width, axes_height]
        )
        self._axes_rect_page = (axes_left, axes_bottom, axes_width, axes_height)
        self.plot_axes.set_facecolor(PAGE_BG_COLOR)
        # For simple axes-relative annotations, we can use the same axes
        self.annotation_axes = self.plot_axes

        # Share axes with renderer and tools
        self.renderer.set_axes(self.plot_axes)
        self.page_figure.plot_axes = self.plot_axes

        # Connect Matplotlib view events (zoom/pan) to our config/state
        self._connect_axes_view_events()

        self._sync_position_controls()
        self._layout_dirty = False

    def _get_axes_padding_fracs(
        self, base_width_in: float, base_height_in: float
    ) -> tuple[float, float, float, float]:
        """Return padding fractions (left, right, top, bottom) for the given base size."""
        pad_left_frac = (self.config.get("axes_pad_left_mm", 6.0) / 25.4) / max(base_width_in, 1e-6)
        pad_right_frac = (self.config.get("axes_pad_right_mm", 4.0) / 25.4) / max(
            base_width_in, 1e-6
        )
        pad_top_frac = (self.config.get("axes_pad_top_mm", 4.0) / 25.4) / max(base_height_in, 1e-6)
        pad_bottom_frac = (self.config.get("axes_pad_bottom_mm", 6.0) / 25.4) / max(
            base_height_in, 1e-6
        )
        return pad_left_frac, pad_right_frac, pad_top_frac, pad_bottom_frac

    def _connect_axes_view_events(self) -> None:
        """Connect Matplotlib view limit events so zoom/pan updates our config.

        Safe to call multiple times; it will disconnect previous handlers.
        """
        if self.plot_axes is None:
            return

        # Disconnect previous callbacks if they exist
        with contextlib.suppress(Exception):
            if self._xlim_cid is not None:
                self.plot_axes.callbacks.disconnect(self._xlim_cid)
            if self._ylim_cid is not None:
                self.plot_axes.callbacks.disconnect(self._ylim_cid)

        # Connect new callbacks
        self._xlim_cid = self.plot_axes.callbacks.connect(
            "xlim_changed", self._on_view_limits_changed
        )
        self._ylim_cid = self.plot_axes.callbacks.connect(
            "ylim_changed", self._on_view_limits_changed
        )

    def _add_dimension_labels(self, left, bottom, width, height):
        """Add dimension annotations on the page."""
        self.page_figure.text(
            left + width / 2,
            bottom - 0.02,
            f"{self.config['width_mm']:.1f} mm",
            transform=self.page_figure.transFigure,
            ha="center",
            va="top",
            fontsize=8,
            color="#666666",
        )

        self.page_figure.text(
            left - 0.02,
            bottom + height / 2,
            f"{self.config['height_mm']:.1f} mm",
            transform=self.page_figure.transFigure,
            ha="right",
            va="center",
            rotation=90,
            fontsize=8,
            color="#666666",
        )

    def _sync_position_controls(self):
        """Update position spinners without triggering callbacks."""
        if hasattr(self, "pos_x_spin"):
            self.pos_x_spin.blockSignals(True)
            self.pos_x_spin.setValue(int(round(self.config.get("fig_left", 0) * 100)))
            self.pos_x_spin.blockSignals(False)
        if hasattr(self, "pos_y_spin"):
            self.pos_y_spin.blockSignals(True)
            self.pos_y_spin.setValue(int(round(self.config.get("fig_top", 0) * 100)))
            self.pos_y_spin.blockSignals(False)

    def _apply_config_to_controls(self) -> None:
        """Sync the control panel to the current config without mutating it."""

        cfg = self.config

        # Figure size
        if hasattr(self, "width_spin"):
            self.width_spin.blockSignals(True)
            self.width_spin.setValue(cfg.get("width_mm", self.width_spin.value()))
            self.width_spin.blockSignals(False)
        if hasattr(self, "height_spin"):
            self.height_spin.blockSignals(True)
            self.height_spin.setValue(cfg.get("height_mm", self.height_spin.value()))
            self.height_spin.blockSignals(False)
        self._sync_position_controls()

        # Time units
        if hasattr(self, "time_unit_combo"):
            self.time_unit_combo.blockSignals(True)
            unit = cfg.get("time_unit", self.time_unit_combo.currentText())
            idx = self.time_unit_combo.findText(unit)
            if idx >= 0:
                self.time_unit_combo.setCurrentIndex(idx)
            self.time_unit_combo.blockSignals(False)

        # Axis labels and limits
        if hasattr(self, "x_label_edit"):
            self.x_label_edit.blockSignals(True)
            self.x_label_edit.setText(cfg.get("x_label", "Time (s)"))
            self.x_label_edit.blockSignals(False)
        if hasattr(self, "y_label_edit"):
            self.y_label_edit.blockSignals(True)
            self.y_label_edit.setText(cfg.get("y_label", "Diameter (μm)"))
            self.y_label_edit.blockSignals(False)

        x_auto = bool(cfg.get("x_auto", True))
        y_auto = bool(cfg.get("y_auto", True))

        if hasattr(self, "x_auto_check"):
            self.x_auto_check.blockSignals(True)
            self.x_auto_check.setChecked(x_auto)
            self.x_auto_check.blockSignals(False)
        if hasattr(self, "y_auto_check"):
            self.y_auto_check.blockSignals(True)
            self.y_auto_check.setChecked(y_auto)
            self.y_auto_check.blockSignals(False)

        if hasattr(self, "x_min_spin"):
            self.x_min_spin.blockSignals(True)
            self.x_min_spin.setValue(cfg.get("x_min", self.x_min_spin.value()))
            self.x_min_spin.setEnabled(not x_auto)
            self.x_min_spin.blockSignals(False)
        if hasattr(self, "x_max_spin"):
            self.x_max_spin.blockSignals(True)
            self.x_max_spin.setValue(cfg.get("x_max", self.x_max_spin.value()))
            self.x_max_spin.setEnabled(not x_auto)
            self.x_max_spin.blockSignals(False)
        if hasattr(self, "y_min_spin"):
            self.y_min_spin.blockSignals(True)
            self.y_min_spin.setValue(cfg.get("y_min", self.y_min_spin.value()))
            self.y_min_spin.setEnabled(not y_auto)
            self.y_min_spin.blockSignals(False)
        if hasattr(self, "y_max_spin"):
            self.y_max_spin.blockSignals(True)
            self.y_max_spin.setValue(cfg.get("y_max", self.y_max_spin.value()))
            self.y_max_spin.setEnabled(not y_auto)
            self.y_max_spin.blockSignals(False)

        # Grid and spines
        if hasattr(self, "grid_check"):
            self.grid_check.blockSignals(True)
            self.grid_check.setChecked(cfg.get("show_grid", True))
            self.grid_check.blockSignals(False)
        if hasattr(self, "show_top_spine_check"):
            self.show_top_spine_check.blockSignals(True)
            self.show_top_spine_check.setChecked(cfg.get("show_top_spine", False))
            self.show_top_spine_check.blockSignals(False)
        if hasattr(self, "show_right_spine_check"):
            self.show_right_spine_check.blockSignals(True)
            self.show_right_spine_check.setChecked(cfg.get("show_right_spine", False))
            self.show_right_spine_check.blockSignals(False)

        # Trace selection and colors
        if hasattr(self, "trace_checks"):
            selection = _normalize_trace_selection(cfg)
            for key, cb in self.trace_checks.items():
                cb.blockSignals(True)
                cb.setChecked(selection.get(key, False))
                cb.blockSignals(False)
            for key, btn in getattr(self, "trace_color_btns", {}).items():
                color_key = {
                    "inner": "inner_color",
                    "outer": "outer_color",
                    "avg_pressure": "pressure_color",
                    "set_pressure": "pressure_color",
                }.get(key)
                if color_key:
                    btn.setStyleSheet(f"background-color: {cfg.get(color_key, '#000000')}")

        # Styles and fonts
        if hasattr(self, "line_width_spin"):
            self.line_width_spin.blockSignals(True)
            self.line_width_spin.setValue(cfg.get("line_width", self.line_width_spin.value()))
            self.line_width_spin.blockSignals(False)
        if hasattr(self, "axis_label_size_spin"):
            self.axis_label_size_spin.blockSignals(True)
            self.axis_label_size_spin.setValue(cfg.get("axis_label_size", 12))
            self.axis_label_size_spin.blockSignals(False)
        if hasattr(self, "tick_label_size_spin"):
            self.tick_label_size_spin.blockSignals(True)
            self.tick_label_size_spin.setValue(cfg.get("tick_label_size", 10))
            self.tick_label_size_spin.blockSignals(False)
        if hasattr(self, "font_combo"):
            self.font_combo.blockSignals(True)
            family = cfg.get("font_family", self.font_combo.currentFont().family())
            idx = self.font_combo.findText(family)
            if idx >= 0:
                self.font_combo.setCurrentIndex(idx)
            self.font_combo.blockSignals(False)
        for attr, key in (
            ("axis_label_bold_check", "axis_label_bold"),
            ("axis_label_italic_check", "axis_label_italic"),
            ("tick_label_bold_check", "tick_label_bold"),
            ("tick_label_italic_check", "tick_label_italic"),
        ):
            chk = getattr(self, attr, None)
            if chk is not None:
                chk.blockSignals(True)
                chk.setChecked(bool(cfg.get(key, False)))
                chk.blockSignals(False)

        # Event controls
        if hasattr(self, "show_events_check"):
            self.show_events_check.blockSignals(True)
            self.show_events_check.setChecked(cfg.get("show_events", True))
            self.show_events_check.blockSignals(False)
        if hasattr(self, "event_style_combo"):
            self.event_style_combo.blockSignals(True)
            style = cfg.get("event_style", "lines")
            idx = next(
                (
                    i
                    for i in range(self.event_style_combo.count())
                    if self.event_style_combo.itemData(i) == style
                ),
                -1,
            )
            if idx >= 0:
                self.event_style_combo.setCurrentIndex(idx)
            self.event_style_combo.blockSignals(False)
        if hasattr(self, "event_label_combo"):
            self.event_label_combo.blockSignals(True)
            label_pos = cfg.get("event_label_pos", "top")
            idx = next(
                (
                    i
                    for i in range(self.event_label_combo.count())
                    if self.event_label_combo.itemData(i) == label_pos
                ),
                -1,
            )
            if idx >= 0:
                self.event_label_combo.setCurrentIndex(idx)
            self.event_label_combo.blockSignals(False)
        if hasattr(self, "event_font_size_spin"):
            self.event_font_size_spin.blockSignals(True)
            self.event_font_size_spin.setValue(cfg.get("event_font_size", 10))
            self.event_font_size_spin.blockSignals(False)

        # Annotations
        self._normalize_annotations()
        self._refresh_annotation_list()

    def _apply_stylesheet(self):
        """Apply stylesheet for better control panel visibility."""
        self.setStyleSheet(
            """
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 5px;
                margin-top: 6px;
                padding-top: 8px;
                padding-bottom: 4px;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }

            QDoubleSpinBox, QSpinBox {
                min-width: 60px;
                max-width: 120px;
            }

            QLineEdit {
                min-width: 80px;
            }

            QComboBox {
                min-width: 100px;
            }

            QPushButton {
                min-height: 25px;
                padding: 4px 8px;
            }
        """
        )

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        QShortcut(QKeySequence.Undo, self, activated=self._undo)
        QShortcut(QKeySequence.Redo, self, activated=self._redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._redo)

    def _resize_to_available_screen(self) -> None:
        """
        Resize this window to the available geometry of the screen
        it will appear on (without necessarily using true fullscreen).
        """
        app = QApplication.instance()
        if app is None:
            return

        if not isinstance(app, QApplication):
            return

        screen = self.screen() or app.primaryScreen()
        if screen is None:
            return

        geom = screen.availableGeometry()
        self.setGeometry(geom)

    def _setup_zoom_drag(self):
        """Enable box-zoom by click-drag on the plot (no toolbar toggle needed)."""
        # Disconnect old handlers if re-run
        for cid_attr in ["_zoom_press_cid", "_zoom_motion_cid", "_zoom_release_cid"]:
            cid = getattr(self, cid_attr, None)
            if cid:
                self.canvas.mpl_disconnect(cid)
                setattr(self, cid_attr, None)
        self._zoom_press_cid = self.canvas.mpl_connect("button_press_event", self._on_zoom_press)
        self._zoom_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_zoom_motion)
        self._zoom_release_cid = self.canvas.mpl_connect(
            "button_release_event", self._on_zoom_release
        )

    def _update_info_bar(self):
        """Update info bar with current figure dimensions."""
        width_mm = self.config["width_mm"]
        height_mm = self.config["height_mm"]
        width_in = width_mm / 25.4
        height_in = height_mm / 25.4
        export_dpi = self.config["dpi"]
        width_px = int(width_in * export_dpi)
        height_px = int(height_in * export_dpi)

        page_label = (
            f"Page: {self.page_size_name} {self.page_orientation} "
            f"({self.page_width_in:.2f} × {self.page_height_in:.2f} in @ {self.screen_dpi} DPI)"
        )

        figure_pos = (
            f"{self.config.get('fig_left', 0) * 100:.0f}% × "
            f"{self.config.get('fig_top', 0) * 100:.0f}%"
        )

        self.info_bar.setText(
            f"{page_label}  |  "
            f"Figure: {width_mm:.1f} × {height_mm:.1f} mm @ {figure_pos}  |  "
            f"Export: {width_px} × {height_px} px @ {export_dpi} DPI"
        )

    def _setup_ui(self):
        """Set up the user interface with improved layout."""
        self.setWindowTitle("Figure Composer (New)")
        self.setGeometry(100, 100, 1400, 900)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # LEFT: Canvas with toolbars
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(2)

        # Matplotlib navigation toolbar (zoom/pan)
        self.nav_toolbar = NavigationToolbar2QT(self.canvas, self)
        # Remove unwanted buttons
        for action in self.nav_toolbar.actions():
            if action.text() in ["Subplots", "Customize", "Save"]:
                self.nav_toolbar.removeAction(action)

        # Annotation toolbar (opt-in)
        canvas_layout.addWidget(self._create_annotation_toolbar())

        # Canvas in scroll area with gray background
        self.canvas_scroll = QScrollArea()
        self.canvas_scroll.setWidget(self.canvas)
        self.canvas_scroll.setWidgetResizable(False)  # Keep canvas at its natural size
        self.canvas_scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.canvas_scroll.setStyleSheet(
            """
            QScrollArea {
                background-color: #e8e8e8;
                border: 1px solid #cccccc;
            }
        """
        )
        canvas_layout.addWidget(self.canvas_scroll)

        # Info bar showing dimensions
        self.info_bar = QLabel()
        self.info_bar.setStyleSheet("padding: 5px;")
        self._update_info_bar()
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)
        status_layout.addWidget(self.nav_toolbar)
        status_layout.addSpacing(12)
        status_layout.addWidget(self.info_bar)
        status_layout.addStretch()

        # Match the status bar background/text to the nav toolbar palette for theme consistency
        status_widget.setAutoFillBackground(True)
        nav_palette = self.nav_toolbar.palette()
        bg_color = nav_palette.color(QPalette.Window)
        status_palette = status_widget.palette()
        status_palette.setColor(QPalette.Window, bg_color)
        status_widget.setPalette(status_palette)

        label_palette = self.info_bar.palette()
        fg_color = nav_palette.color(QPalette.ButtonText)
        label_palette.setColor(QPalette.WindowText, fg_color)
        self.info_bar.setPalette(label_palette)

        canvas_layout.addWidget(status_widget)

        # RIGHT: Control panel
        control_panel = self._create_control_panel()

        # Use splitter with better proportions
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(canvas_container)
        splitter.addWidget(control_panel)

        # Set initial splitter position (70% canvas, 30% controls)
        splitter.setSizes([980, 420])  # For 1400px window

        # Prevent control panel from becoming too narrow
        splitter.setCollapsible(1, False)
        control_panel.setMinimumWidth(380)
        control_panel.setMaximumWidth(500)

        main_layout.addWidget(splitter)

    def _ensure_annotation_property_widgets(self, parent: QWidget) -> None:
        """Lazily create annotation property widgets for the Properties dialog."""
        if not hasattr(self, "annotation_list"):
            self.annotation_list = QListWidget(parent)
            self.annotation_list.currentRowChanged.connect(
                self._on_annotation_list_selection_changed
            )

            self.ann_space_combo = QComboBox(parent)
            self.ann_space_combo.addItem("Inside Axes", "axes")
            self.ann_space_combo.addItem("On Page", "figure")
            self.ann_space_combo.addItem("Data", "data")
            self.ann_space_combo.setEnabled(False)
            self.ann_space_combo.currentIndexChanged.connect(self._on_annotation_property_changed)

            self.ann_text_edit = QLineEdit(parent)
            self.ann_text_edit.setPlaceholderText("Label/Text")
            self.ann_text_edit.editingFinished.connect(self._on_annotation_property_changed)

            self.ann_font_size_spin = QSpinBox(parent)
            self.ann_font_size_spin.setRange(6, 48)
            self.ann_font_size_spin.setSuffix(" pt")
            self.ann_font_size_spin.setValue(12)
            self.ann_font_size_spin.valueChanged.connect(self._on_annotation_property_changed)

            self.ann_font_bold_check = QCheckBox("Bold", parent)
            self.ann_font_bold_check.stateChanged.connect(self._on_annotation_property_changed)
            self.ann_font_italic_check = QCheckBox("Italic", parent)
            self.ann_font_italic_check.stateChanged.connect(self._on_annotation_property_changed)

            self.ann_line_width_spin = QDoubleSpinBox(parent)
            self.ann_line_width_spin.setRange(0.2, 10.0)
            self.ann_line_width_spin.setSingleStep(0.2)
            self.ann_line_width_spin.valueChanged.connect(self._on_annotation_property_changed)

            self.ann_alpha_spin = QSpinBox(parent)
            self.ann_alpha_spin.setRange(0, 100)
            self.ann_alpha_spin.setSuffix("%")
            self.ann_alpha_spin.setValue(100)
            self.ann_alpha_spin.valueChanged.connect(self._on_annotation_property_changed)

            self.ann_fill_alpha_spin = QSpinBox(parent)
            self.ann_fill_alpha_spin.setRange(0, 100)
            self.ann_fill_alpha_spin.setSuffix("%")
            self.ann_fill_alpha_spin.setValue(30)
            self.ann_fill_alpha_spin.valueChanged.connect(self._on_annotation_property_changed)

            self.ann_line_color_btn = QPushButton(parent)
            self.ann_line_color_btn.setToolTip("Stroke color")
            self.ann_line_color_btn.clicked.connect(lambda: self._pick_annotation_color("color"))

            self.ann_fill_color_btn = QPushButton(parent)
            self.ann_fill_color_btn.setToolTip("Fill color")
            self.ann_fill_color_btn.clicked.connect(
                lambda: self._pick_annotation_color("facecolor")
            )

            self.ann_text_color_btn = QPushButton(parent)
            self.ann_text_color_btn.setToolTip("Text color")
            self.ann_text_color_btn.clicked.connect(
                lambda: self._pick_annotation_color("text_color")
            )

            self.ann_x_spin = QDoubleSpinBox(parent)
            self.ann_y_spin = QDoubleSpinBox(parent)
            self.ann_x2_spin = QDoubleSpinBox(parent)
            self.ann_y2_spin = QDoubleSpinBox(parent)
            for spin in (self.ann_x_spin, self.ann_y_spin, self.ann_x2_spin, self.ann_y2_spin):
                spin.setRange(-1e6, 1e6)
                spin.setDecimals(4)
                spin.valueChanged.connect(self._on_annotation_position_changed)

        if not hasattr(self, "ann_halign_combo"):
            self.ann_halign_combo = QComboBox(parent)
            self.ann_halign_combo.addItem("Left", "left")
            self.ann_halign_combo.addItem("Center", "center")
            self.ann_halign_combo.addItem("Right", "right")
            self.ann_halign_combo.currentIndexChanged.connect(self._on_annotation_property_changed)

        if not hasattr(self, "ann_valign_combo"):
            self.ann_valign_combo = QComboBox(parent)
            self.ann_valign_combo.addItem("Top", "top")
            self.ann_valign_combo.addItem("Center", "center")
            self.ann_valign_combo.addItem("Bottom", "bottom")
            self.ann_valign_combo.currentIndexChanged.connect(self._on_annotation_property_changed)

    def _create_annotation_toolbar(self) -> QWidget:
        """Create annotation toolbar with common tools."""
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        self.annotation_buttons: dict[str, QToolButton] = {}

        def add_btn(key: str, label: str, tooltip: str):
            btn = QToolButton(bar)
            btn.setText(label)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.toggled.connect(
                lambda checked, mode=key: self._on_annotation_tool_toggled(mode, checked)
            )
            self.annotation_buttons[key] = btn
            layout.addWidget(btn)

        add_btn("select", "Select", "Select and move annotations")
        add_btn("text", "Text", "Click to place a text label")
        add_btn("box", "Box", "Drag to draw a highlight box")
        add_btn("arrow", "Arrow", "Drag to draw an arrow callout")
        add_btn("line", "Line", "Drag to draw a simple line")

        layout.addStretch()

        self.ann_duplicate_btn = QPushButton("Duplicate")
        self.ann_duplicate_btn.clicked.connect(self._duplicate_selected_annotation)
        self.ann_delete_btn = QPushButton("Delete")
        self.ann_delete_btn.clicked.connect(self._delete_selected_annotation)
        self.ann_forward_btn = QPushButton("Front")
        self.ann_forward_btn.clicked.connect(lambda: self._reorder_selected_annotation("front"))
        self.ann_backward_btn = QPushButton("Back")
        self.ann_backward_btn.clicked.connect(lambda: self._reorder_selected_annotation("back"))

        self.ann_properties_btn = QPushButton("Properties…")
        self.ann_properties_btn.setToolTip("Edit annotation properties")
        self.ann_properties_btn.clicked.connect(self._show_annotation_properties_dialog)

        layout.addWidget(self.ann_duplicate_btn)
        layout.addWidget(self.ann_delete_btn)
        layout.addWidget(self.ann_forward_btn)
        layout.addWidget(self.ann_backward_btn)
        layout.addWidget(self.ann_properties_btn)

        return bar

    def _create_control_panel(self) -> QWidget:
        """Create control panel with improved layout."""
        # Main control widget
        control_widget = QWidget()

        # Scroll area for vertical scrolling only
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Inner widget that holds all controls
        inner_widget = QWidget()
        inner_layout = QVBoxLayout(inner_widget)
        inner_layout.setSpacing(3)
        inner_layout.setContentsMargins(5, 5, 5, 5)

        # Add control groups (reordered by frequency of use)
        inner_layout.addWidget(self._create_data_visualization_group())
        inner_layout.addWidget(self._create_axes_group())
        inner_layout.addWidget(self._create_document_layout_group())
        inner_layout.addWidget(self._create_typography_group())
        inner_layout.addWidget(self._create_events_group())
        inner_layout.addWidget(self._create_export_group())
        inner_layout.addStretch()

        # Set the inner widget as scroll area content
        scroll_area.setWidget(inner_widget)

        # Main layout for control panel
        panel_layout = QVBoxLayout(control_widget)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(scroll_area)

        return control_widget

    def _create_document_layout_group(self) -> QGroupBox:
        """Create combined document and layout controls (page + figure size)."""
        group = QGroupBox("Document & Layout")
        layout = QFormLayout()

        # Page size selector
        self.page_combo = QComboBox()
        self.page_combo.addItem("Letter (8.5×11 in)", "Letter")
        self.page_combo.addItem("A4 (210×297 mm)", "A4")
        self.page_combo.addItem("Legal (8.5×14 in)", "Legal")
        self.page_combo.setCurrentIndex(self.page_combo.findData(self.page_size_name))
        self.page_combo.currentTextChanged.connect(self._on_page_size_changed)

        # Orientation selector
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItems(["Portrait", "Landscape"])
        self.orientation_combo.setCurrentText(self.page_orientation)
        self.orientation_combo.currentTextChanged.connect(self._on_orientation_changed)

        # Figure size controls in grid layout (2 columns)
        size_widget = QWidget()
        size_layout = QGridLayout(size_widget)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(5)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(20, 400)
        self.width_spin.setValue(self.config["width_mm"])
        self.width_spin.setSuffix(" mm")
        self.width_spin.setDecimals(1)
        self.width_spin.setSingleStep(1.0)
        self.width_spin.valueChanged.connect(self._on_size_changed)

        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(20, 400)
        self.height_spin.setValue(self.config["height_mm"])
        self.height_spin.setSuffix(" mm")
        self.height_spin.setDecimals(1)
        self.height_spin.setSingleStep(1.0)
        self.height_spin.valueChanged.connect(self._on_size_changed)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(self.config["dpi"])
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.valueChanged.connect(self._on_dpi_changed)

        size_layout.addWidget(QLabel("Width:"), 0, 0)
        size_layout.addWidget(self.width_spin, 0, 1)
        size_layout.addWidget(QLabel("Height:"), 0, 2)
        size_layout.addWidget(self.height_spin, 0, 3)
        size_layout.addWidget(QLabel("DPI:"), 1, 0)
        size_layout.addWidget(self.dpi_spin, 1, 1)

        # Position controls (% of page)
        position_widget = QWidget()
        pos_layout = QGridLayout(position_widget)
        pos_layout.setContentsMargins(0, 0, 0, 0)

        self.pos_x_spin = QSpinBox()
        self.pos_x_spin.setRange(0, 100)
        self.pos_x_spin.setValue(int(self.config.get("fig_left", 0.15) * 100))
        self.pos_x_spin.setSuffix("%")
        self.pos_x_spin.valueChanged.connect(self._on_position_changed)

        self.pos_y_spin = QSpinBox()
        self.pos_y_spin.setRange(0, 100)
        self.pos_y_spin.setValue(int(self.config.get("fig_top", 0.7) * 100))
        self.pos_y_spin.setSuffix("%")
        self.pos_y_spin.valueChanged.connect(self._on_position_changed)

        pos_layout.addWidget(QLabel("X:"), 0, 0)
        pos_layout.addWidget(self.pos_x_spin, 0, 1)
        pos_layout.addWidget(QLabel("Y:"), 0, 2)
        pos_layout.addWidget(self.pos_y_spin, 0, 3)

        # Center button
        center_btn = QPushButton("Center on Page")
        center_btn.clicked.connect(self._center_figure)

        layout.addRow("Page Size:", self.page_combo)
        layout.addRow("Orientation:", self.orientation_combo)
        layout.addRow("Figure Size:", size_widget)
        layout.addRow("Position:", position_widget)
        layout.addRow("", center_btn)

        group.setLayout(layout)
        return group

    def _populate_event_filter(self):
        """Populate the event selector with checkable items."""
        if not hasattr(self, "event_filter_model"):
            return

        self.event_filter_model.blockSignals(True)
        self.event_filter_model.clear()

        count = len(self.event_times)
        labels = (
            self.event_labels
            if self.event_labels and len(self.event_labels) == count
            else [f"E{i+1}" for i in range(count)]
        )
        selected = self.config.get("event_visible_indices")
        selected_set = None if selected is None else set(selected)

        for idx, label in enumerate(labels):
            item = QStandardItem(f"{idx + 1}: {label}")
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            checked = Qt.Checked if selected_set is None or idx in selected_set else Qt.Unchecked
            item.setData(checked, Qt.CheckStateRole)
            self.event_filter_model.appendRow(item)

        self.event_filter_model.blockSignals(False)
        self.event_filter_combo.setEnabled(count > 0)
        self._update_event_filter_summary()

    def _update_event_filter_summary(self):
        """Update the summary text for the event selector."""
        if not hasattr(self, "event_filter_combo") or not self.event_filter_combo.isEditable():
            return

        total = self.event_filter_model.rowCount()
        if total == 0:
            self.event_filter_combo.lineEdit().setText("No events")
            return

        checked = 0
        for i in range(total):
            item = self.event_filter_model.item(i)
            if item.checkState() == Qt.Checked:
                checked += 1

        summary = f"All events ({total})" if checked == total else f"{checked}/{total} events"

        self.event_filter_combo.lineEdit().setText(summary)

    def _on_event_filter_changed(self, item):
        """Handle selection changes in the event filter dropdown."""
        if item is None:
            return

        self._push_undo_state()
        total = self.event_filter_model.rowCount()
        selected = []
        for i in range(total):
            it = self.event_filter_model.item(i)
            if it.checkState() == Qt.Checked:
                selected.append(i)

        if len(selected) == total:
            self.config["event_visible_indices"] = None  # all
        else:
            self.config["event_visible_indices"] = selected

        self._update_event_filter_summary()
        self._render()

    def _create_data_visualization_group(self) -> QGroupBox:
        """Create combined data selection and line style controls."""
        group = QGroupBox("Data & Visualization")
        layout = QVBoxLayout(group)
        selection = _normalize_trace_selection(self.config)

        # Trace selection with inline color pickers in 2x2 grid
        self.trace_checks: dict[str, QCheckBox] = {}
        self.trace_color_btns: dict[str, QPushButton] = {}

        check_specs = [
            ("inner", "Inner Dia.", "inner_color"),
            ("outer", "Outer Dia.", "outer_color"),
            ("avg_pressure", "Avg. Pressure", "pressure_color"),
            ("set_pressure", "Set Pressure", "pressure_color"),
        ]

        # Create 2x2 grid layout for traces
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(8)
        grid_layout.setVerticalSpacing(5)

        for idx, (key, label, color_key) in enumerate(check_specs):
            row = idx // 2
            col = (idx % 2) * 2  # Each cell takes 2 columns (checkbox + color)

            cb = QCheckBox(label)
            cb.setChecked(selection.get(key, False))
            cb.toggled.connect(lambda checked, k=key: self._on_trace_checkbox_changed(k, checked))
            self.trace_checks[key] = cb
            grid_layout.addWidget(cb, row, col)

            # Color button (compact)
            color_btn = QPushButton()
            color_btn.setFixedSize(40, 20)
            color_btn.setStyleSheet(f"background-color: {self.config[color_key]}")
            color_btn.clicked.connect(
                lambda checked=False, ck=color_key, btn=color_btn: self._pick_color(ck, btn)
            )
            self.trace_color_btns[key] = color_btn
            grid_layout.addWidget(color_btn, row, col + 1)

        # Make columns stretch proportionally
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 0)
        grid_layout.setColumnStretch(2, 1)
        grid_layout.setColumnStretch(3, 0)

        layout.addWidget(grid_widget)

        # Line width control
        width_widget = QWidget()
        width_layout = QHBoxLayout(width_widget)
        width_layout.setContentsMargins(0, 0, 0, 0)
        width_layout.addWidget(QLabel("Line Width:"))

        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setRange(0.1, 10.0)
        self.line_width_spin.setSingleStep(0.1)
        self.line_width_spin.setValue(self.config["line_width"])
        self.line_width_spin.setMaximumWidth(80)
        self.line_width_spin.valueChanged.connect(self._on_style_changed)
        width_layout.addWidget(self.line_width_spin)
        width_layout.addStretch()

        layout.addWidget(width_widget)

        return group

    def _create_axes_group(self) -> QGroupBox:
        """Create axis control group with compact layout."""
        group = QGroupBox("Axes")
        layout = QFormLayout()

        # Time unit selector (compact)
        self.time_unit_combo = QComboBox()
        self.time_unit_combo.addItems(["Seconds", "Minutes", "Hours"])
        self.time_unit_combo.setCurrentText(self.config["time_unit"])
        self.time_unit_combo.currentTextChanged.connect(self._on_time_unit_changed)

        # Labels in compact grid (2 columns)
        labels_widget = QWidget()
        labels_layout = QGridLayout(labels_widget)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(5)

        self.x_label_edit = QLineEdit(self.config["x_label"])
        self.x_label_edit.editingFinished.connect(self._on_axis_changed)

        self.y_label_edit = QLineEdit(self.config["y_label"])
        self.y_label_edit.editingFinished.connect(self._on_axis_changed)

        labels_layout.addWidget(QLabel("X:"), 0, 0)
        labels_layout.addWidget(self.x_label_edit, 0, 1)
        labels_layout.addWidget(QLabel("Y:"), 0, 2)
        labels_layout.addWidget(self.y_label_edit, 0, 3)

        # X limits (compact single row)
        x_limit_widget = QWidget()
        x_limit_layout = QHBoxLayout(x_limit_widget)
        x_limit_layout.setContentsMargins(0, 0, 0, 0)
        x_limit_layout.setSpacing(5)

        self.x_auto_check = QCheckBox("Auto")
        self.x_auto_check.setChecked(self.config["x_auto"])
        self.x_auto_check.toggled.connect(self._on_x_auto_toggled)

        self.x_min_spin = QDoubleSpinBox()
        self.x_min_spin.setRange(-1e9, 1e9)
        self.x_min_spin.setValue(self.config["x_min"])
        self.x_min_spin.setEnabled(not self.config["x_auto"])
        self.x_min_spin.setMaximumWidth(70)
        self.x_min_spin.valueChanged.connect(self._on_axis_changed)

        self.x_max_spin = QDoubleSpinBox()
        self.x_max_spin.setRange(-1e9, 1e9)
        self.x_max_spin.setValue(self.config["x_max"])
        self.x_max_spin.setEnabled(not self.config["x_auto"])
        self.x_max_spin.setMaximumWidth(70)
        self.x_max_spin.valueChanged.connect(self._on_axis_changed)

        x_limit_layout.addWidget(self.x_auto_check)
        x_limit_layout.addWidget(QLabel("Min:"))
        x_limit_layout.addWidget(self.x_min_spin)
        x_limit_layout.addWidget(QLabel("Max:"))
        x_limit_layout.addWidget(self.x_max_spin)
        x_limit_layout.addStretch()

        # Y limits (compact single row)
        y_limit_widget = QWidget()
        y_limit_layout = QHBoxLayout(y_limit_widget)
        y_limit_layout.setContentsMargins(0, 0, 0, 0)
        y_limit_layout.setSpacing(5)

        self.y_auto_check = QCheckBox("Auto")
        self.y_auto_check.setChecked(self.config["y_auto"])
        self.y_auto_check.toggled.connect(self._on_y_auto_toggled)

        self.y_min_spin = QDoubleSpinBox()
        self.y_min_spin.setRange(-1e9, 1e9)
        self.y_min_spin.setValue(self.config["y_min"])
        self.y_min_spin.setEnabled(not self.config["y_auto"])
        self.y_min_spin.setMaximumWidth(70)
        self.y_min_spin.valueChanged.connect(self._on_axis_changed)

        self.y_max_spin = QDoubleSpinBox()
        self.y_max_spin.setRange(-1e9, 1e9)
        self.y_max_spin.setValue(self.config["y_max"])
        self.y_max_spin.setEnabled(not self.config["y_auto"])
        self.y_max_spin.setMaximumWidth(70)
        self.y_max_spin.valueChanged.connect(self._on_axis_changed)

        y_limit_layout.addWidget(self.y_auto_check)
        y_limit_layout.addWidget(QLabel("Min:"))
        y_limit_layout.addWidget(self.y_min_spin)
        y_limit_layout.addWidget(QLabel("Max:"))
        y_limit_layout.addWidget(self.y_max_spin)
        y_limit_layout.addStretch()

        # Options (grid, spines) in single row
        options_widget = QWidget()
        options_layout = QHBoxLayout(options_widget)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(10)

        self.grid_check = QCheckBox("Grid")
        self.grid_check.setChecked(self.config["show_grid"])
        self.grid_check.toggled.connect(self._on_axis_changed)

        self.show_top_spine_check = QCheckBox("Top Spine")
        self.show_top_spine_check.setChecked(self.config["show_top_spine"])
        self.show_top_spine_check.toggled.connect(self._on_axis_changed)

        self.show_right_spine_check = QCheckBox("Right Spine")
        self.show_right_spine_check.setChecked(self.config["show_right_spine"])
        self.show_right_spine_check.toggled.connect(self._on_axis_changed)

        options_layout.addWidget(self.grid_check)
        options_layout.addWidget(self.show_top_spine_check)
        options_layout.addWidget(self.show_right_spine_check)
        options_layout.addStretch()

        layout.addRow("Time Units:", self.time_unit_combo)
        layout.addRow("Labels:", labels_widget)
        layout.addRow("X Limits:", x_limit_widget)
        layout.addRow("Y Limits:", y_limit_widget)
        layout.addRow("Options:", options_widget)

        group.setLayout(layout)
        return group

    def _create_events_group(self) -> QGroupBox:
        """Create event marker controls."""
        group = QGroupBox("Events")
        layout = QFormLayout(group)

        self.show_events_check = QCheckBox("Show Events")
        self.show_events_check.setChecked(self.config["show_events"])
        self.show_events_check.toggled.connect(self._on_events_changed)

        self.event_style_combo = QComboBox()
        self.event_style_combo.addItem("Vertical Lines", "lines")
        self.event_style_combo.addItem("Markers", "markers")
        self.event_style_combo.addItem("Both", "both")
        self.event_style_combo.currentIndexChanged.connect(self._on_events_changed)

        self.event_label_combo = QComboBox()
        self.event_label_combo.addItem("Top", "top")
        self.event_label_combo.addItem("Bottom", "bottom")
        self.event_label_combo.addItem("None", "none")
        self.event_label_combo.currentIndexChanged.connect(self._on_events_changed)

        self.event_font_size_spin = QSpinBox()
        self.event_font_size_spin.setRange(6, 24)
        self.event_font_size_spin.setValue(self.config.get("event_font_size", 10))
        self.event_font_size_spin.valueChanged.connect(self._on_events_changed)

        # Event selection dropdown with checkable items
        self.event_filter_model = QStandardItemModel()
        self.event_filter_model.itemChanged.connect(self._on_event_filter_changed)

        self.event_filter_combo = QComboBox()
        self.event_filter_combo.setModel(self.event_filter_model)
        self.event_filter_combo.setEditable(True)
        self.event_filter_combo.lineEdit().setReadOnly(True)
        self.event_filter_combo.lineEdit().setAlignment(Qt.AlignLeft)
        self.event_filter_combo.setInsertPolicy(QComboBox.NoInsert)
        self._populate_event_filter()

        layout.addRow(self.show_events_check)
        layout.addRow("Style:", self.event_style_combo)
        layout.addRow("Labels:", self.event_label_combo)
        layout.addRow("Font Size:", self.event_font_size_spin)
        layout.addRow("Events:", self.event_filter_combo)

        return group

    def _create_annotations_group(self) -> QGroupBox:
        """Create annotation management controls."""
        group = QGroupBox("Annotations")
        layout = QVBoxLayout(group)

        # List of annotations
        self.annotation_list = QListWidget()
        self.annotation_list.currentRowChanged.connect(self._on_annotation_list_selection_changed)
        layout.addWidget(self.annotation_list, stretch=1)

        # Management buttons
        manage_row = QHBoxLayout()
        self.ann_duplicate_btn = QPushButton("Duplicate")
        self.ann_duplicate_btn.clicked.connect(self._duplicate_selected_annotation)
        self.ann_delete_btn = QPushButton("Delete")
        self.ann_delete_btn.clicked.connect(self._delete_selected_annotation)
        self.ann_forward_btn = QPushButton("Bring to Front")
        self.ann_forward_btn.clicked.connect(lambda: self._reorder_selected_annotation("front"))
        self.ann_backward_btn = QPushButton("Send Back")
        self.ann_backward_btn.clicked.connect(lambda: self._reorder_selected_annotation("back"))
        manage_row.addWidget(self.ann_duplicate_btn)
        manage_row.addWidget(self.ann_delete_btn)
        manage_row.addWidget(self.ann_forward_btn)
        manage_row.addWidget(self.ann_backward_btn)
        layout.addLayout(manage_row)

        # Property editors
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.ann_space_combo = QComboBox()
        self.ann_space_combo.addItem("Inside Axes", "axes")
        self.ann_space_combo.addItem("On Page", "figure")
        self.ann_space_combo.addItem("Data (tracks zoom)", "data")
        self.ann_space_combo.currentIndexChanged.connect(self._on_annotation_property_changed)
        self.ann_space_combo.setEnabled(False)
        self.ann_space_combo.setVisible(False)

        self.ann_text_edit = QLineEdit()
        self.ann_text_edit.editingFinished.connect(self._on_annotation_property_changed)

        self.ann_font_size_spin = QSpinBox()
        self.ann_font_size_spin.setRange(6, 48)
        self.ann_font_size_spin.setValue(12)
        self.ann_font_size_spin.valueChanged.connect(self._on_annotation_property_changed)

        self.ann_line_width_spin = QDoubleSpinBox()
        self.ann_line_width_spin.setRange(0.2, 10.0)
        self.ann_line_width_spin.setSingleStep(0.2)
        self.ann_line_width_spin.valueChanged.connect(self._on_annotation_property_changed)

        self.ann_alpha_spin = QSpinBox()
        self.ann_alpha_spin.setRange(0, 100)
        self.ann_alpha_spin.setValue(100)
        self.ann_alpha_spin.valueChanged.connect(self._on_annotation_property_changed)

        self.ann_fill_alpha_spin = QSpinBox()
        self.ann_fill_alpha_spin.setRange(0, 100)
        self.ann_fill_alpha_spin.setValue(30)
        self.ann_fill_alpha_spin.valueChanged.connect(self._on_annotation_property_changed)

        # Color pickers
        self.ann_line_color_btn = QPushButton()
        self.ann_line_color_btn.setFixedWidth(60)
        self.ann_line_color_btn.clicked.connect(lambda: self._pick_annotation_color("color"))

        self.ann_fill_color_btn = QPushButton()
        self.ann_fill_color_btn.setFixedWidth(60)
        self.ann_fill_color_btn.clicked.connect(lambda: self._pick_annotation_color("facecolor"))

        self.ann_text_color_btn = QPushButton()
        self.ann_text_color_btn.setFixedWidth(60)
        self.ann_text_color_btn.clicked.connect(lambda: self._pick_annotation_color("text_color"))

        # Position controls
        self.ann_x_spin = QDoubleSpinBox()
        self.ann_x_spin.setRange(-1e6, 1e6)
        self.ann_x_spin.setDecimals(4)
        self.ann_x_spin.valueChanged.connect(self._on_annotation_position_changed)

        self.ann_y_spin = QDoubleSpinBox()
        self.ann_y_spin.setRange(-1e6, 1e6)
        self.ann_y_spin.setDecimals(4)
        self.ann_y_spin.valueChanged.connect(self._on_annotation_position_changed)

        self.ann_x2_spin = QDoubleSpinBox()
        self.ann_x2_spin.setRange(-1e6, 1e6)
        self.ann_x2_spin.setDecimals(4)
        self.ann_x2_spin.valueChanged.connect(self._on_annotation_position_changed)

        self.ann_y2_spin = QDoubleSpinBox()
        self.ann_y2_spin.setRange(-1e6, 1e6)
        self.ann_y2_spin.setDecimals(4)
        self.ann_y2_spin.valueChanged.connect(self._on_annotation_position_changed)

        form_layout.addRow("Anchor:", self.ann_space_combo)
        form_layout.addRow("Label/Text:", self.ann_text_edit)
        form_layout.addRow("Font Size:", self.ann_font_size_spin)
        form_layout.addRow("Stroke Width:", self.ann_line_width_spin)
        form_layout.addRow("Stroke Alpha:", self.ann_alpha_spin)
        form_layout.addRow("Fill Alpha:", self.ann_fill_alpha_spin)
        form_layout.addRow("Stroke Color:", self.ann_line_color_btn)
        form_layout.addRow("Fill Color:", self.ann_fill_color_btn)
        form_layout.addRow("Text Color:", self.ann_text_color_btn)

        # Position rows as compact grid
        pos_widget = QWidget()
        pos_layout = QGridLayout(pos_widget)
        pos_layout.setContentsMargins(0, 0, 0, 0)
        pos_layout.setSpacing(4)
        pos_layout.addWidget(QLabel("X / Start X"), 0, 0)
        pos_layout.addWidget(self.ann_x_spin, 0, 1)
        pos_layout.addWidget(QLabel("Y / Start Y"), 0, 2)
        pos_layout.addWidget(self.ann_y_spin, 0, 3)
        pos_layout.addWidget(QLabel("X2 / End X"), 1, 0)
        pos_layout.addWidget(self.ann_x2_spin, 1, 1)
        pos_layout.addWidget(QLabel("Y2 / End Y"), 1, 2)
        pos_layout.addWidget(self.ann_y2_spin, 1, 3)
        form_layout.addRow("Position:", pos_widget)

        layout.addWidget(form_widget)
        return group

    def _create_typography_group(self) -> QGroupBox:
        """Create typography controls."""
        group = QGroupBox("Typography")
        layout = QFormLayout(group)

        self.axis_label_size_spin = QSpinBox()
        self.axis_label_size_spin.setRange(6, 24)
        self.axis_label_size_spin.setValue(self.config["axis_label_size"])
        self.axis_label_size_spin.valueChanged.connect(self._on_font_changed)

        self.tick_label_size_spin = QSpinBox()
        self.tick_label_size_spin.setRange(6, 18)
        self.tick_label_size_spin.setValue(self.config["tick_label_size"])
        self.tick_label_size_spin.valueChanged.connect(self._on_font_changed)

        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self.config["font_family"]))
        self.font_combo.currentFontChanged.connect(self._on_font_changed)

        self.axis_label_bold_check = QCheckBox("Bold")
        self.axis_label_bold_check.setChecked(self.config.get("axis_label_bold", False))
        self.axis_label_bold_check.toggled.connect(self._on_font_changed)

        self.axis_label_italic_check = QCheckBox("Italic")
        self.axis_label_italic_check.setChecked(self.config.get("axis_label_italic", False))
        self.axis_label_italic_check.toggled.connect(self._on_font_changed)

        self.tick_label_bold_check = QCheckBox("Bold")
        self.tick_label_bold_check.setChecked(self.config.get("tick_label_bold", False))
        self.tick_label_bold_check.toggled.connect(self._on_font_changed)

        self.tick_label_italic_check = QCheckBox("Italic")
        self.tick_label_italic_check.setChecked(self.config.get("tick_label_italic", False))
        self.tick_label_italic_check.toggled.connect(self._on_font_changed)

        # Inline bold/italic controls for axis labels
        axis_label_row = QWidget()
        axis_label_layout = QHBoxLayout(axis_label_row)
        axis_label_layout.setContentsMargins(0, 0, 0, 0)
        axis_label_layout.addWidget(self.axis_label_size_spin)
        axis_label_layout.addWidget(self.axis_label_bold_check)
        axis_label_layout.addWidget(self.axis_label_italic_check)
        axis_label_layout.addStretch()

        # Inline bold/italic controls for tick labels
        tick_label_row = QWidget()
        tick_label_layout = QHBoxLayout(tick_label_row)
        tick_label_layout.setContentsMargins(0, 0, 0, 0)
        tick_label_layout.addWidget(self.tick_label_size_spin)
        tick_label_layout.addWidget(self.tick_label_bold_check)
        tick_label_layout.addWidget(self.tick_label_italic_check)
        tick_label_layout.addStretch()

        layout.addRow("Axis Labels:", axis_label_row)
        layout.addRow("Tick Labels:", tick_label_row)
        layout.addRow("Font Family:", self.font_combo)

        return group

    def _create_export_group(self) -> QGroupBox:
        """Create export controls (consolidated)."""
        group = QGroupBox("Export & Actions")
        layout = QVBoxLayout(group)

        # Export format selector and button in single row
        export_widget = QWidget()
        export_layout = QHBoxLayout(export_widget)
        export_layout.setContentsMargins(0, 0, 0, 0)
        export_layout.setSpacing(5)

        self.export_format_combo = QComboBox()
        self.export_format_combo.addItem("PNG", "png")
        self.export_format_combo.addItem("PDF", "pdf")
        self.export_format_combo.addItem("SVG", "svg")
        self.export_format_combo.addItem("TIFF", "tiff")
        export_layout.addWidget(self.export_format_combo)

        export_btn = QPushButton("Export...")
        export_btn.clicked.connect(self._export_current_format)
        export_layout.addWidget(export_btn)

        layout.addWidget(export_widget)

        # Save to project button (prominent)
        save_btn = QPushButton("Save to Project")
        save_btn.clicked.connect(self._save_to_project)
        layout.addWidget(save_btn)

        return group

    # Event handlers
    def _export_current_format(self):
        """Export using the currently selected format from the dropdown."""
        format_type = self.export_format_combo.currentData()
        self._export(format_type)

    def _on_page_size_changed(self):
        """Handle page size selection."""
        self._push_undo_state()
        self.page_size_name = self.page_combo.currentData()
        self._apply_page_canvas_size()
        self._render()

    def _on_orientation_changed(self):
        """Handle page orientation toggle."""
        self._push_undo_state()
        self.page_orientation = self.orientation_combo.currentText()
        self._apply_page_canvas_size()
        self._render()

    def _on_position_changed(self):
        """Handle plot position changes."""
        self._push_undo_state()
        self.config["fig_left"] = self.pos_x_spin.value() / 100.0
        self.config["fig_top"] = self.pos_y_spin.value() / 100.0
        self._layout_dirty = True
        self._render()

    def _center_figure(self):
        """Center the figure on the page."""
        self._push_undo_state()
        fig_width_in = self.config["width_mm"] / 25.4
        fig_height_in = self.config["height_mm"] / 25.4
        fig_width_frac = fig_width_in / self.page_width_in
        fig_height_frac = fig_height_in / self.page_height_in

        left = (1.0 - fig_width_frac) / 2
        top = (1.0 + fig_height_frac) / 2

        self.config["fig_left"] = left
        self.config["fig_top"] = top
        self._sync_position_controls()
        self._layout_dirty = True
        self._render()

    # ------------------------------------------------------------------
    # Annotation helpers and interactions
    # ------------------------------------------------------------------
    def _normalize_annotations(self) -> None:
        """Ensure stored annotations carry consistent defaults."""
        normalized: list[dict[str, Any]] = []
        for ann in list(self.annotations):
            if not isinstance(ann, dict):
                continue
            ann = copy.deepcopy(ann)
            ann.setdefault("type", "box")
            ann.setdefault("space", "axes")
            ann.setdefault("id", self._next_annotation_id)
            ann.setdefault("color", ann.get("edgecolor", "#000000"))
            ann.setdefault("text_color", ann.get("text_color", ann.get("color", "#000000")))
            ann.setdefault("facecolor", ann.get("facecolor", "#ffffff"))
            ann.setdefault("face_alpha", ann.get("face_alpha", 0.25))
            ann.setdefault("alpha", ann.get("alpha", 1.0))
            ann.setdefault("linewidth", float(ann.get("linewidth", 1.0)))
            ann.setdefault("fontsize", ann.get("fontsize", self.config.get("tick_label_size", 10)))
            ann.setdefault(
                "fontfamily", ann.get("fontfamily", self.config.get("font_family", "Arial"))
            )
            ann.setdefault("fontweight", ann.get("fontweight", "normal"))
            ann.setdefault("fontstyle", ann.get("fontstyle", "normal"))
            ann.setdefault("ha", "center")
            ann.setdefault("va", "center")
            self._next_annotation_id = max(self._next_annotation_id, ann["id"] + 1)
            normalized.append(ann)
        self.annotations[:] = normalized

    def _activate_annotation_mode(self, mode: str):
        """Programmatically toggle a canvas tool button."""
        if hasattr(self, "annotation_buttons"):
            for key, btn in self.annotation_buttons.items():
                btn.blockSignals(True)
                btn.setChecked(key == mode)
                btn.blockSignals(False)
        self.annotation_mode = mode
        # keep the canvas focused for immediate use
        if hasattr(self, "canvas"):
            self.canvas.setFocus()

    def _on_annotation_tool_toggled(self, mode: str, checked: bool):
        """Update annotation mode when toolbar buttons change."""
        if checked:
            self._activate_annotation_mode(mode)
        elif self.annotation_mode == mode:
            self.annotation_mode = None

    def _annotation_display_name(self, ann: dict[str, Any]) -> str:
        label = (ann.get("text") or "").strip()
        kind = ann.get("type", "box").capitalize()
        anchor = ann.get("space", "axes")
        anchor_name = {"axes": "Axes", "figure": "Page", "data": "Data"}.get(anchor, anchor)
        return f"[{kind}] {label or 'Annotation'} ({anchor_name})"

    def _refresh_annotation_list(self, select_id: int | None = None) -> None:
        """Refresh the annotations list widget and selection."""
        if not hasattr(self, "annotation_list"):
            return

        if select_id is None:
            select_id = self._active_annotation_id

        self.annotation_list.blockSignals(True)
        self.annotation_list.clear()
        for ann in self.annotations:
            item = QListWidgetItem(self._annotation_display_name(ann))
            item.setData(Qt.UserRole, ann.get("id"))
            self.annotation_list.addItem(item)

        # Restore selection
        selected_row = -1
        if select_id is not None:
            for row in range(self.annotation_list.count()):
                selected_item = self.annotation_list.item(row)
                if selected_item is not None and selected_item.data(Qt.UserRole) == select_id:
                    selected_row = row
                    break
        self.annotation_list.setCurrentRow(selected_row)
        self.annotation_list.blockSignals(False)
        self._sync_annotation_controls()

    def _on_annotation_list_selection_changed(self, row: int):
        """Handle list selection -> active annotation."""
        item = self.annotation_list.item(row) if hasattr(self, "annotation_list") else None
        ann_id = item.data(Qt.UserRole) if item else None
        self._set_active_annotation(ann_id)
        self._render()

    def _get_annotation_by_id(self, ann_id: int | None) -> dict[str, Any] | None:
        if ann_id is None:
            return None
        for ann in self.annotations:
            if ann.get("id") == ann_id:
                return ann
        return None

    def _set_active_annotation(self, ann_id: int | None) -> None:
        """Set the active annotation id and sync UI."""
        self._active_annotation_id = ann_id
        self._refresh_annotation_list(select_id=ann_id)

    def _set_annotation_controls_enabled(self, enabled: bool) -> None:
        for widget in [
            getattr(self, "ann_text_edit", None),
            getattr(self, "ann_font_size_spin", None),
            getattr(self, "ann_line_width_spin", None),
            getattr(self, "ann_alpha_spin", None),
            getattr(self, "ann_fill_alpha_spin", None),
            getattr(self, "ann_line_color_btn", None),
            getattr(self, "ann_fill_color_btn", None),
            getattr(self, "ann_text_color_btn", None),
            getattr(self, "ann_font_bold_check", None),
            getattr(self, "ann_font_italic_check", None),
            getattr(self, "ann_halign_combo", None),
            getattr(self, "ann_valign_combo", None),
            getattr(self, "ann_x_spin", None),
            getattr(self, "ann_y_spin", None),
            getattr(self, "ann_x2_spin", None),
            getattr(self, "ann_y2_spin", None),
            getattr(self, "annotation_list", None),
            getattr(self, "ann_space_combo", None),
            getattr(self, "ann_properties_btn", None),
            getattr(self, "ann_duplicate_btn", None),
            getattr(self, "ann_delete_btn", None),
            getattr(self, "ann_forward_btn", None),
            getattr(self, "ann_backward_btn", None),
        ]:
            if widget is not None:
                widget.setEnabled(enabled)

    def _apply_color_to_button(self, button: QPushButton | None, color: str):
        if button is not None:
            button.setStyleSheet(f"background-color: {color}")

    def _sync_annotation_controls(self):
        """Sync property editors with the selected annotation."""
        if not hasattr(self, "ann_space_combo"):
            return
        ann = self._get_annotation_by_id(self._active_annotation_id)
        if ann is None:
            self._annotation_form_lock = True
            self.ann_space_combo.setCurrentIndex(0)
            self.ann_text_edit.setText("")
            combo = getattr(self, "ann_halign_combo", None)
            if combo is not None:
                idx = combo.findData("center")
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo = getattr(self, "ann_valign_combo", None)
            if combo is not None:
                idx = combo.findData("center")
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self._annotation_form_lock = False
            self._set_annotation_controls_enabled(False)
            return

        self._set_annotation_controls_enabled(True)
        self._annotation_form_lock = True

        def _set_combo_by_data(combo: QComboBox | None, value: str, default: str = "center"):
            if combo is None:
                return
            idx = combo.findData(value)
            if idx < 0:
                idx = combo.findData(default)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        space_idx = self.ann_space_combo.findData(ann.get("space", "axes"))
        if space_idx >= 0:
            self.ann_space_combo.setCurrentIndex(space_idx)

        self.ann_text_edit.setText(ann.get("text", ""))
        self.ann_font_size_spin.setValue(int(round(ann.get("fontsize", 12))))
        is_bold = str(ann.get("fontweight", "normal")).lower() in (
            "bold",
            "heavy",
            "semibold",
            "demibold",
        )
        is_italic = str(ann.get("fontstyle", "normal")).lower() == "italic"
        if hasattr(self, "ann_font_bold_check"):
            self.ann_font_bold_check.setChecked(is_bold)
        if hasattr(self, "ann_font_italic_check"):
            self.ann_font_italic_check.setChecked(is_italic)
        self.ann_line_width_spin.setValue(float(ann.get("linewidth", 1.0)))
        self.ann_alpha_spin.setValue(int(round(float(ann.get("alpha", 1.0)) * 100)))
        self.ann_fill_alpha_spin.setValue(
            int(round(float(ann.get("face_alpha", ann.get("facealpha", 0.25))) * 100))
        )
        _set_combo_by_data(getattr(self, "ann_halign_combo", None), ann.get("ha", "center"))
        _set_combo_by_data(getattr(self, "ann_valign_combo", None), ann.get("va", "center"))

        self._apply_color_to_button(self.ann_line_color_btn, ann.get("color", "#000000"))
        self._apply_color_to_button(self.ann_fill_color_btn, ann.get("facecolor", "#ffffff"))
        self._apply_color_to_button(self.ann_text_color_btn, ann.get("text_color", "#000000"))

        ann_type = ann.get("type", "box")
        fill_enabled = ann_type == "box"
        stroke_enabled = ann_type in ("box", "line", "arrow")
        self.ann_fill_color_btn.setEnabled(fill_enabled)
        self.ann_fill_alpha_spin.setEnabled(fill_enabled)
        self.ann_line_width_spin.setEnabled(stroke_enabled)
        self.ann_alpha_spin.setEnabled(stroke_enabled)
        self.ann_line_color_btn.setEnabled(stroke_enabled)
        self.ann_text_edit.setEnabled(True)
        self.ann_font_size_spin.setEnabled(True)
        if hasattr(self, "ann_font_bold_check"):
            self.ann_font_bold_check.setEnabled(True)
        if hasattr(self, "ann_font_italic_check"):
            self.ann_font_italic_check.setEnabled(True)
        combo = getattr(self, "ann_halign_combo", None)
        if combo is not None:
            combo.setEnabled(True)
        combo = getattr(self, "ann_valign_combo", None)
        if combo is not None:
            combo.setEnabled(True)

        if ann_type == "text":
            self.ann_x_spin.setValue(float(ann.get("x", 0.5)))
            self.ann_y_spin.setValue(float(ann.get("y", 0.5)))
            self.ann_x2_spin.setEnabled(False)
            self.ann_y2_spin.setEnabled(False)
        elif ann_type == "box":
            self.ann_x_spin.setValue(float(ann.get("x0", 0.2)))
            self.ann_y_spin.setValue(float(ann.get("y0", 0.2)))
            self.ann_x2_spin.setValue(float(ann.get("x1", 0.4)))
            self.ann_y2_spin.setValue(float(ann.get("y1", 0.4)))
            self.ann_x2_spin.setEnabled(True)
            self.ann_y2_spin.setEnabled(True)
        else:  # line / arrow
            self.ann_x_spin.setValue(float(ann.get("x0", 0.1)))
            self.ann_y_spin.setValue(float(ann.get("y0", 0.1)))
            self.ann_x2_spin.setValue(float(ann.get("x1", 0.4)))
            self.ann_y2_spin.setValue(float(ann.get("y1", 0.4)))
            self.ann_x2_spin.setEnabled(True)
            self.ann_y2_spin.setEnabled(True)

        self._annotation_form_lock = False

    def _pick_annotation_color(self, key: str):
        """Open a color picker for the selected annotation."""
        ann = self._get_annotation_by_id(self._active_annotation_id)
        if ann is None:
            return
        current = QColor(ann.get(key, "#000000"))
        color = QColorDialog.getColor(current, self)
        if color.isValid():
            self._push_undo_state()
            ann[key] = color.name()
            if key == "color":
                ann["edgecolor"] = ann[key]
            self._sync_annotation_controls()
            self._render()

    def _on_annotation_property_changed(self):
        """Persist annotation property edits from the form."""
        if self._annotation_form_lock:
            return
        ann = self._get_annotation_by_id(self._active_annotation_id)
        if ann is None:
            return
        self._push_undo_state()
        ann["text"] = self.ann_text_edit.text()
        ann["fontsize"] = self.ann_font_size_spin.value()
        ann["linewidth"] = self.ann_line_width_spin.value()
        ann["alpha"] = self.ann_alpha_spin.value() / 100.0
        if hasattr(self, "ann_font_bold_check"):
            ann["fontweight"] = "bold" if self.ann_font_bold_check.isChecked() else "normal"
        if hasattr(self, "ann_font_italic_check"):
            ann["fontstyle"] = "italic" if self.ann_font_italic_check.isChecked() else "normal"
        ha = self.ann_halign_combo.currentData() if hasattr(self, "ann_halign_combo") else None
        va = self.ann_valign_combo.currentData() if hasattr(self, "ann_valign_combo") else None
        if ha is not None:
            ann["ha"] = ha
        if va is not None:
            ann["va"] = va
        if ann.get("type") == "box":
            ann["face_alpha"] = self.ann_fill_alpha_spin.value() / 100.0
        self._refresh_annotation_list(select_id=ann.get("id"))
        self._render()

    def _on_annotation_position_changed(self):
        """Handle coordinate edits from the form."""
        if self._annotation_form_lock:
            return
        ann = self._get_annotation_by_id(self._active_annotation_id)
        if ann is None:
            return
        self._push_undo_state()
        ann_type = ann.get("type", "box")
        if ann_type == "text":
            ann["x"] = self.ann_x_spin.value()
            ann["y"] = self.ann_y_spin.value()
        elif ann_type == "box":
            x0 = self.ann_x_spin.value()
            y0 = self.ann_y_spin.value()
            x1 = self.ann_x2_spin.value()
            y1 = self.ann_y2_spin.value()
            ann["x0"], ann["x1"] = sorted([x0, x1])
            ann["y0"], ann["y1"] = sorted([y0, y1])
        else:
            ann["x0"] = self.ann_x_spin.value()
            ann["y0"] = self.ann_y_spin.value()
            ann["x1"] = self.ann_x2_spin.value()
            ann["y1"] = self.ann_y2_spin.value()
        self._render()

    def _show_annotation_position_dialog(self):
        """Show a small dialog for editing annotation position fields."""
        ann = self._get_annotation_by_id(self._active_annotation_id)
        if ann is None:
            return

        dlg = getattr(self, "_position_dialog", None)
        if dlg is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Annotation Position")
            layout = QFormLayout(dlg)
            layout.addRow("X / Start X:", self.ann_x_spin)
            layout.addRow("Y / Start Y:", self.ann_y_spin)
            layout.addRow("X2 / End X:", self.ann_x2_spin)
            layout.addRow("Y2 / End Y:", self.ann_y2_spin)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
            buttons.accepted.connect(dlg.accept)
            buttons.rejected.connect(dlg.reject)
            layout.addRow(buttons)
            self._position_dialog = dlg
        else:
            dlg = self._position_dialog

        original = copy.deepcopy(ann)
        self._sync_annotation_controls()
        result = dlg.exec()
        if result == QDialog.Rejected:
            self._annotation_form_lock = True
            ann_type = original.get("type", "box")
            if ann_type == "text":
                ann["x"] = original.get("x", ann.get("x", 0.5))
                ann["y"] = original.get("y", ann.get("y", 0.5))
            else:
                ann["x0"] = original.get("x0", ann.get("x0", 0.0))
                ann["y0"] = original.get("y0", ann.get("y0", 0.0))
                ann["x1"] = original.get("x1", ann.get("x1", 0.0))
                ann["y1"] = original.get("y1", ann.get("y1", 0.0))
            self._annotation_form_lock = False
            self._sync_annotation_controls()
            self._render()

    def _show_annotation_properties_dialog(self) -> None:
        """Open the Annotation Properties dialog."""
        dlg = getattr(self, "_annotation_properties_dialog", None)
        if dlg is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Annotation Properties")
            self._ensure_annotation_property_widgets(parent=dlg)
            main_layout = QVBoxLayout(dlg)

            main_layout.addWidget(QLabel("Annotations:", dlg))
            main_layout.addWidget(self.annotation_list)

            label_group = QGroupBox("Label & Text", dlg)
            label_form = QFormLayout(label_group)
            label_form.addRow("Label/Text:", self.ann_text_edit)

            font_row = QWidget(label_group)
            font_row_layout = QHBoxLayout(font_row)
            font_row_layout.setContentsMargins(0, 0, 0, 0)
            font_row_layout.setSpacing(6)
            font_row_layout.addWidget(self.ann_font_size_spin)
            font_row_layout.addWidget(self.ann_font_bold_check)
            font_row_layout.addWidget(self.ann_font_italic_check)
            label_form.addRow("Font size:", font_row)

            align_row = QWidget(label_group)
            align_row_layout = QHBoxLayout(align_row)
            align_row_layout.setContentsMargins(0, 0, 0, 0)
            align_row_layout.setSpacing(6)
            align_row_layout.addWidget(QLabel("H:", align_row))
            align_row_layout.addWidget(self.ann_halign_combo)
            align_row_layout.addSpacing(8)
            align_row_layout.addWidget(QLabel("V:", align_row))
            align_row_layout.addWidget(self.ann_valign_combo)
            label_form.addRow("Alignment:", align_row)
            main_layout.addWidget(label_group)

            style_group = QGroupBox("Style", dlg)
            style_form = QFormLayout(style_group)
            style_form.addRow("Stroke width:", self.ann_line_width_spin)
            style_form.addRow("Stroke alpha:", self.ann_alpha_spin)
            style_form.addRow("Fill alpha:", self.ann_fill_alpha_spin)

            colors_widget = QWidget(style_group)
            colors_layout = QHBoxLayout(colors_widget)
            colors_layout.setContentsMargins(0, 0, 0, 0)
            colors_layout.setSpacing(4)
            colors_layout.addWidget(QLabel("Stroke:", style_group))
            colors_layout.addWidget(self.ann_line_color_btn)
            colors_layout.addSpacing(6)
            colors_layout.addWidget(QLabel("Fill:", style_group))
            colors_layout.addWidget(self.ann_fill_color_btn)
            colors_layout.addSpacing(6)
            colors_layout.addWidget(QLabel("Text:", style_group))
            colors_layout.addWidget(self.ann_text_color_btn)
            style_form.addRow("Colors:", colors_widget)
            main_layout.addWidget(style_group)

            pos_group = QGroupBox("Position", dlg)
            pos_form = QFormLayout(pos_group)
            self.ann_space_combo.setEnabled(False)
            self.ann_space_combo.setVisible(True)
            pos_form.addRow("Anchor:", self.ann_space_combo)
            pos_form.addRow("X / Start X:", self.ann_x_spin)
            pos_form.addRow("Y / Start Y:", self.ann_y_spin)
            pos_form.addRow("X2 / End X:", self.ann_x2_spin)
            pos_form.addRow("Y2 / End Y:", self.ann_y2_spin)
            main_layout.addWidget(pos_group)

            buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
            buttons.rejected.connect(dlg.reject)
            main_layout.addWidget(buttons)

            self._annotation_properties_dialog = dlg
        else:
            dlg = self._annotation_properties_dialog

        self._refresh_annotation_list()
        self._sync_annotation_controls()
        dlg.exec()

    def _duplicate_selected_annotation(self):
        """Duplicate the current annotation with a slight offset."""
        ann = self._get_annotation_by_id(self._active_annotation_id)
        if ann is None:
            return
        self._push_undo_state()
        new_ann = copy.deepcopy(ann)
        new_ann["id"] = self._next_annotation_id
        self._next_annotation_id += 1
        # offset gently so the copy is visible
        self._offset_annotation_for_visibility(new_ann)
        self.annotations.append(new_ann)
        self._set_active_annotation(new_ann["id"])
        self._render()

    def _delete_selected_annotation(self):
        """Remove the active annotation."""
        ann = self._get_annotation_by_id(self._active_annotation_id)
        if ann is None:
            return
        self._push_undo_state()
        # Mutate in place so config["annotations"] stays in sync with self.annotations
        self.annotations[:] = [a for a in self.annotations if a.get("id") != ann.get("id")]
        self._set_active_annotation(None)
        self._render()

    def _reorder_selected_annotation(self, direction: str):
        """Send annotation forward/backwards in z-order."""
        ann = self._get_annotation_by_id(self._active_annotation_id)
        if ann is None:
            return
        self._push_undo_state()
        # Mutate in place to keep config["annotations"] reference valid
        remaining = [a for a in self.annotations if a.get("id") != ann.get("id")]
        if direction == "front":
            remaining.append(ann)
        else:
            remaining.insert(0, ann)
        self.annotations[:] = remaining
        self._refresh_annotation_list(select_id=ann.get("id"))
        self._render()

    def _prompt_annotation_text(self, ann: dict[str, Any]) -> None:
        """Prompt for editing annotation text."""
        current = ann.get("text", "")
        text, ok = QInputDialog.getText(
            self, "Annotation Text", "Enter text:", QLineEdit.Normal, current
        )
        if ok:
            ann["text"] = text
            self._sync_annotation_controls()

    def _offset_annotation_for_visibility(self, ann: dict[str, Any]) -> None:
        """Offset an annotation so a duplicate is visibly separated."""
        space = ann.get("space", "axes")
        ann_type = ann.get("type", "box")

        # Pick an offset based on space
        if space == "data" and self.plot_axes is not None:
            xlim = self.plot_axes.get_xlim()
            ylim = self.plot_axes.get_ylim()
            dx = 0.05 * (xlim[1] - xlim[0])
            dy = 0.05 * (ylim[1] - ylim[0])
        else:
            dx = dy = 0.04

        def clamp01(val: float) -> float:
            return max(0.0, min(1.0, val))

        if ann_type == "text":
            ann["x"] = ann.get("x", 0.5) + dx
            ann["y"] = ann.get("y", 0.5) + dy
            if space != "data":
                ann["x"] = clamp01(ann["x"])
                ann["y"] = clamp01(ann["y"])
        elif ann_type == "box":
            ann["x0"] = ann.get("x0", 0.0) + dx
            ann["x1"] = ann.get("x1", 0.0) + dx
            ann["y0"] = ann.get("y0", 0.0) + dy
            ann["y1"] = ann.get("y1", 0.0) + dy
            if space != "data":
                ann["x0"] = clamp01(ann["x0"])
                ann["x1"] = clamp01(ann["x1"])
                ann["y0"] = clamp01(ann["y0"])
                ann["y1"] = clamp01(ann["y1"])
        else:  # line / arrow
            ann["x0"] = ann.get("x0", 0.0) + dx
            ann["x1"] = ann.get("x1", 0.0) + dx
            ann["y0"] = ann.get("y0", 0.0) + dy
            ann["y1"] = ann.get("y1", 0.0) + dy
            if space != "data":
                ann["x0"] = clamp01(ann["x0"])
                ann["x1"] = clamp01(ann["x1"])
                ann["y0"] = clamp01(ann["y0"])
                ann["y1"] = clamp01(ann["y1"])

    def _build_annotation(self, kind: str, space: str, **overrides) -> dict[str, Any]:
        """Create a new annotation dict with sensible defaults."""
        base = {
            "id": self._next_annotation_id,
            "type": kind,
            "space": space,
            "color": "#111111",
            "text_color": "#111111",
            "facecolor": "#fff8d8",
            "face_alpha": 0.25,
            "alpha": 1.0,
            "linewidth": 1.0,
            "fontsize": self.config.get("tick_label_size", 10),
            "fontfamily": self.config.get("font_family", "Arial"),
            "fontweight": "normal",
            "fontstyle": "normal",
            "ha": "center",
            "va": "center",
        }
        if kind == "text":
            base.update({"x": 0.5, "y": 0.5, "text": "Annotation"})
        elif kind == "box":
            base.update({"x0": 0.2, "y0": 0.2, "x1": 0.4, "y1": 0.35, "text": ""})
        else:  # line / arrow
            base.update({"x0": 0.1, "y0": 0.1, "x1": 0.4, "y1": 0.4, "text": ""})
            if kind == "arrow":
                base.setdefault("arrowstyle", "->")
        base.update(overrides)
        return base

    def _choose_space_for_event(self, event) -> str:
        """Choose annotation space based on click location (axes vs page)."""
        coords = self._event_coords(event)
        fig_coords = coords.get("figure")
        axes_rect = getattr(self, "_axes_rect_page", None)

        inside_axes_rect = False
        if fig_coords and axes_rect:
            fx, fy = fig_coords
            ax_left, ax_bottom, ax_w, ax_h = axes_rect
            inside_axes_rect = (
                ax_left <= fx <= ax_left + ax_w and ax_bottom <= fy <= ax_bottom + ax_h
            )

        if inside_axes_rect:
            if self.annotation_mode in ("arrow", "line"):
                return "data"
            return "axes"

        if fig_coords is not None and 0.0 <= fig_coords[0] <= 1.0 and 0.0 <= fig_coords[1] <= 1.0:
            return "figure"

        if event.inaxes == self.plot_axes:
            if self.annotation_mode in ("arrow", "line"):
                return "data"
            return "axes"
        return "figure"

    def _event_coords(self, event) -> dict[str, tuple[float, float] | None]:
        """Return axes/figure/data coords for an event."""
        coords: dict[str, tuple[float, float] | None] = {"axes": None, "figure": None, "data": None}
        if self.plot_axes is not None:
            inv_axes = self.plot_axes.transAxes.inverted()
            coords["axes"] = tuple(inv_axes.transform((event.x, event.y)))
            if (
                event.inaxes == self.plot_axes
                and event.xdata is not None
                and event.ydata is not None
            ):
                coords["data"] = (event.xdata, event.ydata)
        if self.page_figure is not None:
            inv_fig = self.page_figure.transFigure.inverted()
            coords["figure"] = tuple(inv_fig.transform((event.x, event.y)))
        return coords

    def _coords_for_space(self, event, space: str) -> tuple[float, float] | None:
        """Get coords in requested space ('axes', 'figure', or 'data')."""
        coords = self._event_coords(event)
        val = coords.get(space)
        if val is None:
            return None
        if space in ("axes", "figure"):
            x, y = val
            return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
        return val

    def _get_transform_for_space(self, space: str):
        if self.plot_axes is None:
            return None
        if space == "axes":
            return self.plot_axes.transAxes
        if space == "figure":
            return self.page_figure.transFigure
        return self.plot_axes.transData

    def _snap_box_edges(self, ann: dict[str, Any], drag_state: dict[str, Any]) -> None:
        """Snap box edges to nearby box/layout edges within a pixel tolerance."""
        if ann.get("type") != "box":
            return

        space = ann.get("space", "axes")
        transform = self._get_transform_for_space(space)
        if transform is None:
            return
        inv_transform = transform.inverted()

        x0 = float(ann.get("x0", 0.0))
        x1 = float(ann.get("x1", 0.0))
        y0 = float(ann.get("y0", 0.0))
        y1 = float(ann.get("y1", 0.0))

        corners = [
            transform.transform((x0, y0)),
            transform.transform((x0, y1)),
            transform.transform((x1, y0)),
            transform.transform((x1, y1)),
        ]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        left_px, right_px = min(xs), max(xs)
        bottom_px, top_px = min(ys), max(ys)

        candidates_x: list[float] = []
        candidates_y: list[float] = []

        for other in self.annotations:
            if other is ann or other.get("type") != "box" or other.get("space", space) != space:
                continue
            ox0 = float(other.get("x0", 0.0))
            ox1 = float(other.get("x1", 0.0))
            oy0 = float(other.get("y0", 0.0))
            oy1 = float(other.get("y1", 0.0))
            other_corners = [
                transform.transform((ox0, oy0)),
                transform.transform((ox0, oy1)),
                transform.transform((ox1, oy0)),
                transform.transform((ox1, oy1)),
            ]
            oxs = [p[0] for p in other_corners]
            oys = [p[1] for p in other_corners]
            candidates_x.extend([min(oxs), max(oxs)])
            candidates_y.extend([min(oys), max(oys)])

        if space in ("axes", "figure"):
            candidates_x.extend(
                [
                    transform.transform((0.0, 0.0))[0],
                    transform.transform((1.0, 0.0))[0],
                ]
            )
            candidates_y.extend(
                [
                    transform.transform((0.0, 0.0))[1],
                    transform.transform((0.0, 1.0))[1],
                ]
            )
            if space == "figure":
                axes_rect = getattr(self, "_axes_rect_page", None)
                if axes_rect:
                    ax_left, ax_bottom, ax_w, ax_h = axes_rect
                    candidates_x.extend(
                        [
                            transform.transform((ax_left, 0.0))[0],
                            transform.transform((ax_left + ax_w, 0.0))[0],
                        ]
                    )
                    candidates_y.extend(
                        [
                            transform.transform((0.0, ax_bottom))[1],
                            transform.transform((0.0, ax_bottom + ax_h))[1],
                        ]
                    )

        tol = _BOX_SNAP_TOLERANCE_PX
        mode = drag_state.get("mode")
        handle = drag_state.get("handle", "")

        moving_left = mode == "move" or ("w" in handle)
        moving_right = mode == "move" or ("e" in handle)
        moving_bottom = mode == "move" or ("s" in handle)
        moving_top = mode == "move" or ("n" in handle)

        new_left_px = left_px
        new_right_px = right_px
        new_bottom_px = bottom_px
        new_top_px = top_px

        if moving_left or moving_right:
            dx_candidates: list[float] = []
            if moving_left:
                dx_candidates.extend(
                    [cx - left_px for cx in candidates_x if abs(cx - left_px) <= tol]
                )
            if moving_right:
                dx_candidates.extend(
                    [cx - right_px for cx in candidates_x if abs(cx - right_px) <= tol]
                )
            if dx_candidates:
                best_dx = min(dx_candidates, key=lambda v: abs(v))
                new_left_px = left_px + best_dx if moving_left else new_left_px
                new_right_px = right_px + best_dx if moving_right else new_right_px

        if moving_bottom or moving_top:
            dy_candidates: list[float] = []
            if moving_bottom:
                dy_candidates.extend(
                    [cy - bottom_px for cy in candidates_y if abs(cy - bottom_px) <= tol]
                )
            if moving_top:
                dy_candidates.extend(
                    [cy - top_px for cy in candidates_y if abs(cy - top_px) <= tol]
                )
            if dy_candidates:
                best_dy = min(dy_candidates, key=lambda v: abs(v))
                new_bottom_px = bottom_px + best_dy if moving_bottom else new_bottom_px
                new_top_px = top_px + best_dy if moving_top else new_top_px

        if mode == "resize_box":
            if moving_left and not moving_right:
                best = None
                for cx in candidates_x:
                    dist = abs(cx - left_px)
                    if dist <= tol and (best is None or dist < abs(best - left_px)):
                        best = cx
                if best is not None:
                    new_left_px = best
            if moving_right and not moving_left:
                best = None
                for cx in candidates_x:
                    dist = abs(cx - right_px)
                    if dist <= tol and (best is None or dist < abs(best - right_px)):
                        best = cx
                if best is not None:
                    new_right_px = best
            if moving_bottom and not moving_top:
                best = None
                for cy in candidates_y:
                    dist = abs(cy - bottom_px)
                    if dist <= tol and (best is None or dist < abs(best - bottom_px)):
                        best = cy
                if best is not None:
                    new_bottom_px = best
            if moving_top and not moving_bottom:
                best = None
                for cy in candidates_y:
                    dist = abs(cy - top_px)
                    if dist <= tol and (best is None or dist < abs(best - top_px)):
                        best = cy
                if best is not None:
                    new_top_px = best

        new_corners = [
            (new_left_px, new_bottom_px),
            (new_left_px, new_top_px),
            (new_right_px, new_bottom_px),
            (new_right_px, new_top_px),
        ]
        inv_corners = [inv_transform.transform(pt) for pt in new_corners]
        xs_new = [pt[0] for pt in inv_corners]
        ys_new = [pt[1] for pt in inv_corners]
        new_x0, new_x1 = min(xs_new), max(xs_new)
        new_y0, new_y1 = min(ys_new), max(ys_new)

        if space in ("axes", "figure"):
            new_x0 = max(0.0, min(1.0, new_x0))
            new_x1 = max(0.0, min(1.0, new_x1))
            new_y0 = max(0.0, min(1.0, new_y0))
            new_y1 = max(0.0, min(1.0, new_y1))

        ann["x0"], ann["x1"] = sorted([new_x0, new_x1])
        ann["y0"], ann["y1"] = sorted([new_y0, new_y1])

    def _distance_point_to_segment(
        self, px: float, py: float, x0: float, y0: float, x1: float, y1: float
    ) -> float:
        """Distance from a point (px,py) to a line segment in pixels."""
        vx: float = x1 - x0
        vy: float = y1 - y0
        wx: float = px - x0
        wy: float = py - y0
        seg_len_sq: float = vx * vx + vy * vy
        if seg_len_sq == 0:
            return float((wx * wx + wy * wy) ** 0.5)
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / seg_len_sq))
        proj_x: float = x0 + t * vx
        proj_y: float = y0 + t * vy
        dx: float = px - proj_x
        dy: float = py - proj_y
        return float((dx * dx + dy * dy) ** 0.5)

    def _hit_test_annotation(self, event) -> dict[str, Any] | None:
        """Return topmost annotation under the cursor."""
        ex, ey = event.x, event.y
        for ann in reversed(self.annotations):
            space = ann.get("space", "axes")
            transform = self._get_transform_for_space(space)
            if transform is None:
                continue
            ann_type = ann.get("type", "box")
            if ann_type == "text":
                dist = self._distance_point_to_segment(
                    ex,
                    ey,
                    *transform.transform((ann.get("x", 0.0), ann.get("y", 0.0))),
                    *transform.transform((ann.get("x", 0.0), ann.get("y", 0.0))),
                )
                if dist <= 10:
                    return {"annotation": ann, "handle": "move"}
            elif ann_type == "box":
                x0, y0 = transform.transform((ann.get("x0", 0.0), ann.get("y0", 0.0)))
                x1, y1 = transform.transform((ann.get("x1", 0.0), ann.get("y1", 0.0)))
                left, right = sorted([x0, x1])
                bottom, top = sorted([y0, y1])
                handles = {
                    "nw": (left, top),
                    "ne": (right, top),
                    "se": (right, bottom),
                    "sw": (left, bottom),
                }
                for handle, (hx, hy) in handles.items():
                    if ((hx - ex) ** 2 + (hy - ey) ** 2) ** 0.5 <= 8:
                        return {"annotation": ann, "handle": handle}
                if left - 2 <= ex <= right + 2 and bottom - 2 <= ey <= top + 2:
                    return {"annotation": ann, "handle": "move"}
            else:  # line / arrow
                x0, y0 = transform.transform((ann.get("x0", 0.0), ann.get("y0", 0.0)))
                x1, y1 = transform.transform((ann.get("x1", 0.0), ann.get("y1", 0.0)))
                start_dist = ((ex - x0) ** 2 + (ey - y0) ** 2) ** 0.5
                end_dist = ((ex - x1) ** 2 + (ey - y1) ** 2) ** 0.5
                if start_dist <= 8:
                    return {"annotation": ann, "handle": "start"}
                if end_dist <= 8:
                    return {"annotation": ann, "handle": "end"}
                if self._distance_point_to_segment(ex, ey, x0, y0, x1, y1) <= 6:
                    return {"annotation": ann, "handle": "move"}
        return None

    def _on_annotation_press(self, event) -> bool:
        """Handle mouse press for annotation tools. Returns True if handled."""
        if event.button != 1:
            return False

        # Double-click on select opens text editor
        if getattr(event, "dblclick", False) and self.annotation_mode in (None, "select"):
            hit = self._hit_test_annotation(event)
            if hit:
                ann = hit["annotation"]
                self._push_undo_state()
                self._set_active_annotation(ann.get("id"))
                self._prompt_annotation_text(ann)
                self._render()
                return True

        mode = self.annotation_mode
        if mode in ("box", "arrow", "line"):
            space = self._choose_space_for_event(event)
            coords = self._coords_for_space(event, space)
            if coords is None:
                return False
            self._push_undo_state()
            x0, y0 = coords
            ann = self._build_annotation("box" if mode == "box" else mode, space, x0=x0, y0=y0)
            if mode in ("arrow", "line"):
                ann["x1"] = x0
                ann["y1"] = y0
            else:
                ann["x1"] = x0
                ann["y1"] = y0
            self.annotations.append(ann)
            self._next_annotation_id += 1
            self._set_active_annotation(ann["id"])
            drag_mode = "resize_box" if mode == "box" else "adjust_line"
            self._annotation_drag_state = {
                "mode": drag_mode,
                "space": space,
                "ann_id": ann["id"],
                "handle": "se" if mode == "box" else "end",
                "new": True,
                "press_x": x0,
                "press_y": y0,
                "start": copy.deepcopy(ann),
            }
            self._render()
            return True

        if mode == "text":
            space = self._choose_space_for_event(event)
            coords = self._coords_for_space(event, space)
            if coords is None:
                return False
            default_text = "Annotation"
            text, ok = QInputDialog.getText(
                self, "Add Text", "Enter annotation text:", QLineEdit.Normal, default_text
            )
            if not ok:
                return False
            self._push_undo_state()
            ann = self._build_annotation(
                "text", space, x=coords[0], y=coords[1], text=text or default_text
            )
            self.annotations.append(ann)
            self._next_annotation_id += 1
            self._set_active_annotation(ann["id"])
            self._render()
            # Snap back to select for quick adjustments
            self._activate_annotation_mode("select")
            return True

        # Select / move mode
        if mode in (None, "select"):
            hit = self._hit_test_annotation(event)
            if not hit:
                self._set_active_annotation(None)
                return False
            self._push_undo_state()
            ann = hit["annotation"]
            handle = hit.get("handle", "move")
            self._set_active_annotation(ann.get("id"))
            space = ann.get("space", "axes")
            coords = self._coords_for_space(event, space)
            drag_mode = "move"
            if handle in ("nw", "ne", "sw", "se"):
                drag_mode = "resize_box"
            elif handle in ("start", "end"):
                drag_mode = "adjust_line"
            self._annotation_drag_state = {
                "mode": drag_mode,
                "space": space,
                "ann_id": ann.get("id"),
                "handle": handle,
                "press_x": coords[0] if coords else None,
                "press_y": coords[1] if coords else None,
                "start": copy.deepcopy(ann),
            }
            self._render()
            return True
        return False

    def _on_annotation_motion(self, event) -> bool:
        """Handle mouse move events for annotation interaction."""
        state = self._annotation_drag_state
        if not state:
            return False
        ann = self._get_annotation_by_id(state.get("ann_id"))
        if ann is None:
            return False

        space = state.get("space", ann.get("space", "axes"))
        coords = self._coords_for_space(event, space)
        if coords is None:
            return False
        x, y = coords
        mode = state.get("mode")

        if mode == "move":
            start = state.get("start", {})
            ann_type = ann.get("type", "box")
            if ann_type == "box":
                dx = x - state.get("press_x", x)
                dy = y - state.get("press_y", y)
                w = start.get("x1", 0) - start.get("x0", 0)
                h = start.get("y1", 0) - start.get("y0", 0)
                ann["x0"] = start.get("x0", 0) + dx
                ann["y0"] = start.get("y0", 0) + dy
                ann["x1"] = ann["x0"] + w
                ann["y1"] = ann["y0"] + h
                self._snap_box_edges(ann, self._annotation_drag_state)
            elif ann_type == "text":
                dx = x - state.get("press_x", x)
                dy = y - state.get("press_y", y)
                ann["x"] = start.get("x", 0.5) + dx
                ann["y"] = start.get("y", 0.5) + dy
            else:  # line / arrow
                dx = x - state.get("press_x", x)
                dy = y - state.get("press_y", y)
                ann["x0"] = start.get("x0", 0) + dx
                ann["y0"] = start.get("y0", 0) + dy
                ann["x1"] = start.get("x1", 0) + dx
                ann["y1"] = start.get("y1", 0) + dy
        elif mode == "resize_box":
            # Move the relevant corner
            handle = state.get("handle", "se")
            x0 = state.get("start", {}).get("x0", ann.get("x0", 0))
            x1 = state.get("start", {}).get("x1", ann.get("x1", 0))
            y0 = state.get("start", {}).get("y0", ann.get("y0", 0))
            y1 = state.get("start", {}).get("y1", ann.get("y1", 0))
            if "w" in handle:
                x0 = x
            if "e" in handle:
                x1 = x
            if "n" in handle:
                y1 = y
            if "s" in handle:
                y0 = y
            ann["x0"], ann["x1"] = sorted([x0, x1])
            ann["y0"], ann["y1"] = sorted([y0, y1])
            self._snap_box_edges(ann, self._annotation_drag_state)
        elif mode == "adjust_line":
            handle = state.get("handle")
            if handle == "start":
                ann["x0"] = x
                ann["y0"] = y
            elif handle == "end":
                ann["x1"] = x
                ann["y1"] = y
        self._sync_annotation_controls()
        self._render()
        return True

    def _on_annotation_release(self, event) -> bool:
        """Finalize annotation drag operations."""
        state = self._annotation_drag_state
        if not state:
            return False
        ann = self._get_annotation_by_id(state.get("ann_id"))
        if state.get("new") and ann:
            ann_type = ann.get("type")
            is_degenerate_box = ann_type == "box" and (
                abs(ann.get("x1", 0) - ann.get("x0", 0)) < 0.001
                or abs(ann.get("y1", 0) - ann.get("y0", 0)) < 0.001
            )
            is_degenerate_line = ann_type in ("line", "arrow") and (
                abs(ann.get("x1", 0) - ann.get("x0", 0)) < 1e-6
                and abs(ann.get("y1", 0) - ann.get("y0", 0)) < 1e-6
            )
            if is_degenerate_box or is_degenerate_line:
                self._delete_selected_annotation()
        self._annotation_drag_state = {}
        self._render()
        return True

    # ------------------------------------------------------------------
    # Project integration helpers (load existing figure configs)
    # ------------------------------------------------------------------
    def load_from_project(self, figure_id: str | None, figure_data: dict[str, Any] | None) -> None:
        """Load a saved figure configuration from a project entry."""
        if not figure_data:
            return

        self.figure_id = figure_id or figure_data.get("figure_id")
        self.figure_name = figure_data.get("figure_name", self.figure_name)
        self.figure_metadata = figure_data.get("metadata", self.figure_metadata)

        # Load config if provided
        if "config" in figure_data:
            merged = self._get_default_config()
            merged.update(copy.deepcopy(figure_data["config"]))
            self.config = merged
            self.annotations = self.config.setdefault("annotations", [])
            self._next_annotation_id = (
                max((a.get("id", 0) for a in self.annotations), default=0) + 1
            )
            self._normalize_annotations()
            self._layout_dirty = True

        # Load page settings
        page_settings = figure_data.get("page_settings", {})
        size_name = page_settings.get("size_name")
        orientation = page_settings.get("orientation")
        if size_name:
            self.page_size_name = size_name
        if orientation:
            self.page_orientation = orientation
        self._apply_page_canvas_size()
        self._apply_config_to_controls()
        self._refresh_annotation_list()

        # Refresh UI and canvas
        self._render()
        self.setWindowTitle(f"Figure Composer - {self.figure_name}")
        if hasattr(self, "_undo_stack"):
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._push_undo_state()

    def _save_to_project(self) -> None:
        """Save the current figure configuration into the parent project's sample."""
        parent = self.parent_window
        if parent is None:
            QMessageBox.warning(
                self, "No Project", "Open the composer from a project to save figures."
            )
            return

        current_sample = getattr(parent, "current_sample", None)
        if current_sample is None:
            QMessageBox.warning(
                self, "No Sample Selected", "Select a sample in the project tree first."
            )
            return

        # Ensure storage exists
        if getattr(current_sample, "figure_configs", None) is None:
            current_sample.figure_configs = {}

        # Prompt for name when creating new
        if self.figure_id is None:
            name, ok = QInputDialog.getText(
                self,
                "Save Figure",
                "Enter figure name:",
                QLineEdit.Normal,
                self.figure_name,
            )
            if not ok or not name.strip():
                return
            self.figure_name = name.strip()
            self.figure_id = f"fig_{uuid.uuid4().hex[:8]}"
            self.figure_metadata["created"] = datetime.now().isoformat()

        # Update modified timestamp
        self.figure_metadata["modified"] = datetime.now().isoformat()

        figure_data = {
            "figure_id": self.figure_id,
            "figure_name": self.figure_name,
            "metadata": copy.deepcopy(self.figure_metadata),
            "config": copy.deepcopy(self.config),
            "page_settings": {
                "size_name": self.page_size_name,
                "orientation": self.page_orientation,
            },
        }

        current_sample.figure_configs[self.figure_id] = figure_data
        # Notify project and tree
        if hasattr(parent, "mark_session_dirty"):
            parent.mark_session_dirty(reason="figure saved")
        if self.figure_saved:
            self.figure_saved.emit(self.figure_id, figure_data)
        self.setWindowTitle(f"Figure Composer - {self.figure_name}")

    def _on_size_changed(self):
        """Handle width/height changes properly."""
        # Update config
        self._push_undo_state()
        self.config["width_mm"] = self.width_spin.value()
        self.config["height_mm"] = self.height_spin.value()

        self._layout_dirty = True
        self._update_info_bar()
        self._render()

    def _on_dpi_changed(self):
        """Handle DPI changes (doesn't affect figure size, just export quality)."""
        self._push_undo_state()
        self.config["dpi"] = self.dpi_spin.value()
        self._update_info_bar()
        # No need to re-render for DPI change - it only affects export

    def _on_time_unit_changed(self):
        """Handle time unit changes."""
        self._push_undo_state()
        unit = self.time_unit_combo.currentText()

        # Update config
        self.config["time_unit"] = unit

        # Set divisor and update X label
        if unit == "Seconds":
            self.config["time_divisor"] = 1.0
            self.x_label_edit.setText("Time (s)")
        elif unit == "Minutes":
            self.config["time_divisor"] = 60.0
            self.x_label_edit.setText("Time (min)")
        elif unit == "Hours":
            self.config["time_divisor"] = 3600.0
            self.x_label_edit.setText("Time (h)")

        self.config["x_label"] = self.x_label_edit.text()
        self._render()

    def _on_trace_checkbox_changed(self, key: str, checked: bool):
        """Handle trace checkbox changes (multi-select)."""
        if not hasattr(self, "trace_checks"):
            return

        selection = {k: cb.isChecked() for k, cb in self.trace_checks.items()}

        # Ensure at least one trace remains selected
        if not any(selection.values()):
            # Re-enable the toggled box to keep one trace active
            sender_cb = self.trace_checks.get(key)
            if sender_cb is not None:
                sender_cb.blockSignals(True)
                sender_cb.setChecked(True)
                sender_cb.blockSignals(False)
                selection[key] = True

        self._push_undo_state()
        self.config["trace_selection"] = selection

        # Update Y label based on whether only pressure traces are selected
        pressure_only = selection.get("avg_pressure") or selection.get("set_pressure")
        diameter_present = selection.get("inner") or selection.get("outer")
        if pressure_only and not diameter_present:
            self.y_label_edit.setText("Pressure (mmHg)")
            self.config["y_label"] = "Pressure (mmHg)"
        else:
            self.y_label_edit.setText("Diameter (μm)")
            self.config["y_label"] = "Diameter (μm)"

        self._render()

    def _on_view_limits_changed(self, ax) -> None:
        """Sync zoom/pan changes from the Matplotlib axes back to config/UI.

        Whenever the Matplotlib toolbar changes the view (zoom/pan), we treat
        that as a user-defined window and copy the current limits into the
        composer config. This also turns off autoscale and updates the axis
        controls to match.
        """
        # Ignore programmatic limit changes; only sync after user zoom/pan.
        if not (
            self._user_view_change_pending or self._nav_mode_active() or self._auto_zoom_active
        ):
            return
        if self.plot_axes is None:
            return
        if ax is not None and ax is not self.plot_axes:
            return

        self._push_undo_state()

        # Read current view limits from the plot axes
        x_min, x_max = self.plot_axes.get_xlim()
        y_min, y_max = self.plot_axes.get_ylim()

        # Store limits in config and disable autoscale
        self.config["x_auto"] = False
        self.config["y_auto"] = False
        self.config["x_min"] = float(x_min)
        self.config["x_max"] = float(x_max)
        self.config["y_min"] = float(y_min)
        self.config["y_max"] = float(y_max)

        # Update axis controls without emitting valueChanged/toggled signals
        if hasattr(self, "x_auto_check"):
            self.x_auto_check.blockSignals(True)
            self.x_auto_check.setChecked(False)
            self.x_auto_check.blockSignals(False)
        if hasattr(self, "y_auto_check"):
            self.y_auto_check.blockSignals(True)
            self.y_auto_check.setChecked(False)
            self.y_auto_check.blockSignals(False)

        if hasattr(self, "x_min_spin"):
            self.x_min_spin.setEnabled(True)
            self.x_min_spin.blockSignals(True)
            self.x_min_spin.setValue(self.config["x_min"])
            self.x_min_spin.blockSignals(False)
        if hasattr(self, "x_max_spin"):
            self.x_max_spin.setEnabled(True)
            self.x_max_spin.blockSignals(True)
            self.x_max_spin.setValue(self.config["x_max"])
            self.x_max_spin.blockSignals(False)
        if hasattr(self, "y_min_spin"):
            self.y_min_spin.setEnabled(True)
            self.y_min_spin.blockSignals(True)
            self.y_min_spin.setValue(self.config["y_min"])
            self.y_min_spin.blockSignals(False)
        if hasattr(self, "y_max_spin"):
            self.y_max_spin.setEnabled(True)
            self.y_max_spin.blockSignals(True)
            self.y_max_spin.setValue(self.config["y_max"])
            self.y_max_spin.blockSignals(False)
        self._user_view_change_pending = False

    def _on_axis_changed(self):
        """Handle axis control changes."""
        self._push_undo_state()
        self.config["x_label"] = self.x_label_edit.text()
        self.config["y_label"] = self.y_label_edit.text()
        self.config["x_min"] = self.x_min_spin.value()
        self.config["x_max"] = self.x_max_spin.value()
        self.config["y_min"] = self.y_min_spin.value()
        self.config["y_max"] = self.y_max_spin.value()
        self.config["show_grid"] = self.grid_check.isChecked()
        self.config["show_top_spine"] = self.show_top_spine_check.isChecked()
        self.config["show_right_spine"] = self.show_right_spine_check.isChecked()
        self._render()

    def _on_x_auto_toggled(self, checked):
        """Handle X auto toggle."""
        self._push_undo_state()
        self.config["x_auto"] = checked
        self.x_min_spin.setEnabled(not checked)
        self.x_max_spin.setEnabled(not checked)
        self._render()

    def _on_y_auto_toggled(self, checked):
        """Handle Y auto toggle."""
        self._push_undo_state()
        self.config["y_auto"] = checked
        self.y_min_spin.setEnabled(not checked)
        self.y_max_spin.setEnabled(not checked)
        self._render()

    def _on_canvas_mouse_release(self, event):
        """After zoom/pan completes, sync the current view into config/UI."""
        if event.inaxes in (self.plot_axes, self.annotation_axes) and self._nav_mode_active():
            # Defer to after Matplotlib applies the new limits
            self._user_view_change_pending = True
            QTimer.singleShot(0, lambda: self._on_view_limits_changed(self.plot_axes))

    def _nav_mode_active(self) -> bool:
        """Return True if the Matplotlib toolbar is in zoom or pan mode."""
        toolbar = getattr(self, "nav_toolbar", None)
        if toolbar is None:
            return False

        active = getattr(toolbar, "_active", None)
        if active in ("ZOOM", "PAN"):
            return True

        # Fallback: check checked actions by text label
        for action in toolbar.actions():
            if action.text() in ["Zoom", "Pan"] and action.isChecked():
                return True

        return False

    def _on_style_changed(self):
        """Handle style control changes."""
        self._push_undo_state()
        self.config["line_width"] = self.line_width_spin.value()
        self._render()

    def _pick_color(self, config_key: str, button: QPushButton):
        """Open color picker and update config."""
        current_color = QColor(self.config[config_key])
        color = QColorDialog.getColor(current_color, self)
        if color.isValid():
            self._push_undo_state()
            self.config[config_key] = color.name()
            button.setStyleSheet(f"background-color: {color.name()}")
            self._render()

    def _on_events_changed(self):
        """Handle event control changes."""
        self._push_undo_state()
        self.config["show_events"] = self.show_events_check.isChecked()
        self.config["event_style"] = self.event_style_combo.currentData()
        self.config["event_label_pos"] = self.event_label_combo.currentData()
        self.config["event_font_size"] = self.event_font_size_spin.value()
        self._render()

    def _on_font_changed(self):
        """Handle font control changes."""
        self._push_undo_state()
        self.config["axis_label_size"] = self.axis_label_size_spin.value()
        self.config["tick_label_size"] = self.tick_label_size_spin.value()
        self.config["font_family"] = self.font_combo.currentFont().family()
        self.config["axis_label_bold"] = self.axis_label_bold_check.isChecked()
        self.config["axis_label_italic"] = self.axis_label_italic_check.isChecked()
        self.config["tick_label_bold"] = self.tick_label_bold_check.isChecked()
        self.config["tick_label_italic"] = self.tick_label_italic_check.isChecked()
        self._render()

    def _render(self):
        """Render with current settings."""
        if self._layout_dirty or self.plot_axes is None:
            self._apply_page_layout()

        self.renderer.render(
            trace_model=self.trace_model,
            config=self.config,
            event_times=self.event_times,
            event_labels=self.event_labels,
            event_colors=self.event_colors,
            axes=self.plot_axes,
            active_annotation_id=self._active_annotation_id,
            show_selection=True,
        )
        self.canvas.draw_idle()
        self._update_info_bar()

    # ------------------------------------------------------------------
    # Mouse-driven zoom (box select)
    # ------------------------------------------------------------------
    def _on_zoom_press(self, event):
        # Annotation tools take full precedence over zoom anywhere on the page
        if self.annotation_mode is not None:
            self._on_annotation_press(event)
            return
        if event.button != 1 or event.inaxes not in (self.plot_axes, self.annotation_axes):
            return
        if self._nav_mode_active():  # let toolbar zoom/pan take precedence
            return
        toolbar = getattr(self, "nav_toolbar", None)
        if toolbar is None:
            return
        # One-shot activation of the built-in Matplotlib zoom tool
        self._auto_zoom_active = True
        with contextlib.suppress(Exception):
            toolbar.zoom()  # toggle on
            toolbar.press_zoom(event)

    def _on_zoom_motion(self, event):
        if (
            self.annotation_mode is not None or self._annotation_drag_state
        ) and self._on_annotation_motion(event):
            return
        if not self._auto_zoom_active or event.inaxes not in (self.plot_axes, self.annotation_axes):
            return
        toolbar = getattr(self, "nav_toolbar", None)
        if toolbar is None:
            return
        with contextlib.suppress(Exception):
            # Matplotlib NavigationToolbar2 implements drag_zoom
            if hasattr(toolbar, "drag_zoom"):
                toolbar.drag_zoom(event)

    def _on_zoom_release(self, event):
        if event.button != 1:
            return
        if (
            self.annotation_mode is not None or self._annotation_drag_state
        ) and self._on_annotation_release(event):
            return
        if not self._auto_zoom_active:
            return
        toolbar = getattr(self, "nav_toolbar", None)
        if toolbar is None:
            return
        with contextlib.suppress(Exception):
            toolbar.release_zoom(event)
            toolbar.zoom()  # toggle off
        # Capture the post-zoom limits as an explicit user window
        self._user_view_change_pending = True
        QTimer.singleShot(0, lambda: self._on_view_limits_changed(self.plot_axes))
        self._auto_zoom_active = False

    def _export(self, format_type: str):
        """Export with EXACT dimensions in specified format.

        Creates a new figure at export DPI for high-quality output without
        affecting the display figure.
        """
        # File dialog
        filters = {
            "png": "PNG Files (*.png);;All Files (*)",
            "pdf": "PDF Files (*.pdf);;All Files (*)",
            "svg": "SVG Files (*.svg);;All Files (*)",
            "tiff": "TIFF Files (*.tiff *.tif);;All Files (*)",
        }

        filepath, _ = QFileDialog.getSaveFileName(
            self, f"Export Figure as {format_type.upper()}", "", filters[format_type]
        )

        if not filepath:
            return

        # Add extension if missing
        if not any(filepath.endswith(ext) for ext in [f".{format_type}", ".tif"]):
            filepath += f".{format_type}"

        # Get exact dimensions
        width_inch = self.config["width_mm"] / 25.4
        height_inch = self.config["height_mm"] / 25.4
        export_dpi = self.config["dpi"]
        margin_in = max(float(self.config.get("export_margin_in", 0.5)), 0.0)
        canvas_width_in = width_inch + 2 * margin_in
        canvas_height_in = height_inch + 2 * margin_in

        # Make sure the on-screen view is up-to-date before copying
        if self._layout_dirty or self.plot_axes is None:
            self._render()

        # Create a NEW figure at export DPI (don't modify display figure)
        export_fig = Figure(
            figsize=(canvas_width_in, canvas_height_in),
            dpi=export_dpi,
            facecolor=PAGE_BG_COLOR,
        )
        pad_left, pad_right, pad_top, pad_bottom = self._get_axes_padding_fracs(
            base_width_in=canvas_width_in, base_height_in=canvas_height_in
        )
        fig_left_frac = margin_in / canvas_width_in
        fig_bottom_frac = margin_in / canvas_height_in
        fig_width_frac = width_inch / canvas_width_in
        fig_height_frac = height_inch / canvas_height_in
        export_ax = export_fig.add_axes(
            (
                fig_left_frac + pad_left,
                fig_bottom_frac + pad_bottom,
                max(fig_width_frac - (pad_left + pad_right), 0.02),
                max(fig_height_frac - (pad_top + pad_bottom), 0.02),
            )
        )
        export_ax.set_facecolor(PAGE_BG_COLOR)

        # Copy the visible plot into the export axes
        self._copy_plot_to_axes(self.plot_axes, export_ax)

        # Export with format-specific settings (no bbox_inches - use exact size)
        try:
            if format_type == "pdf":
                export_fig.savefig(
                    filepath,
                    format="pdf",
                    dpi=export_dpi,
                    facecolor=PAGE_BG_COLOR,
                    edgecolor=PAGE_BG_COLOR,
                )
            elif format_type == "svg":
                export_fig.savefig(
                    filepath,
                    format="svg",
                    dpi=export_dpi,
                    facecolor=PAGE_BG_COLOR,
                    edgecolor=PAGE_BG_COLOR,
                )
            elif format_type == "tiff":
                export_fig.savefig(
                    filepath,
                    format="tiff",
                    dpi=export_dpi,
                    pil_kwargs={"compression": "tiff_lzw"},
                    facecolor=PAGE_BG_COLOR,
                    edgecolor=PAGE_BG_COLOR,
                )
            else:  # png
                export_fig.savefig(
                    filepath,
                    format="png",
                    dpi=export_dpi,
                    facecolor=PAGE_BG_COLOR,
                    edgecolor=PAGE_BG_COLOR,
                )

            log.info(f"Exported figure to {filepath} at {export_dpi} DPI ({format_type.upper()})")
        except Exception as e:
            log.error(f"Export failed: {e}")
        finally:
            # Clean up export figure
            plt.close(export_fig)

    def _set_tick_label_style(self, ax, config: dict[str, Any]) -> None:
        """Apply tick label weight/style/family to the given axes."""
        weight = "bold" if config.get("tick_label_bold") else "normal"
        style = "italic" if config.get("tick_label_italic") else "normal"
        family = config.get("font_family", "Arial")
        for label in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            label.set_fontweight(weight)
            label.set_fontstyle(style)
            label.set_fontfamily(family)

    def _copy_plot_to_axes(self, source_ax, target_ax):
        """Render the current visible plot view into a new axes (used for export)."""
        if source_ax is None or target_ax is None:
            return

        # Freeze the current view so export matches what is on screen
        x_min, x_max = source_ax.get_xlim()
        y_min, y_max = source_ax.get_ylim()

        export_config = copy.deepcopy(self.config)
        export_config.update(
            {
                "x_auto": False,
                "y_auto": False,
                "x_min": float(x_min),
                "x_max": float(x_max),
                "y_min": float(y_min),
                "y_max": float(y_max),
            }
        )

        export_renderer = SimpleRenderer(target_ax.figure)

        # Remap page-space annotations so they stay anchored relative to the axes region
        export_axes_rect = (
            target_ax.get_position().x0,
            target_ax.get_position().y0,
            target_ax.get_position().width,
            target_ax.get_position().height,
        )
        export_config = self._remap_figure_annotations_for_export(export_config, export_axes_rect)

        export_renderer.render(
            trace_model=self.trace_model,
            config=export_config,
            event_times=self.event_times,
            event_labels=self.event_labels,
            event_colors=self.event_colors,
            axes=target_ax,
        )

        # Mirror scale settings explicitly
        target_ax.set_xscale(source_ax.get_xscale())
        target_ax.set_yscale(source_ax.get_yscale())

    def _remap_figure_annotations_for_export(
        self,
        config: dict[str, Any],
        export_axes_rect: tuple[float, float, float, float] | None,
    ) -> dict[str, Any]:
        """Map page-space annotations onto the export canvas so they stay aligned."""
        src_rect = getattr(self, "_axes_rect_page", None)
        if not src_rect or not export_axes_rect:
            return config

        sx, sy, sw, sh = src_rect
        dx, dy, dw, dh = export_axes_rect
        if sw == 0 or sh == 0 or dw == 0 or dh == 0:
            return config

        def map_point(x: float, y: float) -> tuple[float, float]:
            rx = (x - sx) / sw
            ry = (y - sy) / sh
            return dx + rx * dw, dy + ry * dh

        mapped = copy.deepcopy(config)
        for ann in mapped.get("annotations", []) or []:
            if ann.get("space") != "figure":
                continue
            ann_type = ann.get("type", "box")
            if ann_type == "text":
                ann["x"], ann["y"] = map_point(float(ann.get("x", 0.5)), float(ann.get("y", 0.5)))
            elif ann_type == "box":
                ann["x0"], ann["y0"] = map_point(
                    float(ann.get("x0", 0.0)), float(ann.get("y0", 0.0))
                )
                ann["x1"], ann["y1"] = map_point(
                    float(ann.get("x1", 0.0)), float(ann.get("y1", 0.0))
                )
            else:
                ann["x0"], ann["y0"] = map_point(
                    float(ann.get("x0", 0.0)), float(ann.get("y0", 0.0))
                )
                ann["x1"], ann["y1"] = map_point(
                    float(ann.get("x1", 0.0)), float(ann.get("y1", 0.0))
                )
        return mapped


class SimpleRenderer:
    """Renderer that uses configuration dict to render publication-ready figures.

    This renderer demonstrates clean separation:
    - Takes configuration as a dict
    - Renders directly to a shared Figure object
    - No complex state management
    """

    def __init__(self, figure: Figure):
        self.figure = figure  # Use the SAME figure object as the canvas
        self.axes = None

    def set_axes(self, axes):
        """Set the axes to render into (supplied by page layout)."""
        self.axes = axes

    def render(
        self,
        trace_model: TraceModel | None,
        config: dict[str, Any],
        event_times: list[float] | None = None,
        event_labels: list[str] | None = None,
        event_colors: list[str] | None = None,
        axes=None,
        active_annotation_id: int | None = None,
        show_selection: bool = False,
    ):
        """Clear and redraw the figure with current config.

        Args:
            trace_model: The trace data to plot (can be None for testing)
            config: Configuration dict with all settings
            event_times: Event time points (in seconds)
            event_labels: Event labels
            event_colors: Event colors
            active_annotation_id: Currently selected annotation id (for edit overlay)
            show_selection: If True, draw selection handles for the active annotation
        """
        ax = axes or self.axes
        if ax is None:
            ax = self.figure.add_axes((0.15, 0.12, 0.80, 0.83))
            self.axes = ax
        else:
            self.axes = ax

        ax.clear()

        # Set font properties
        plt.rcParams["font.family"] = config.get("font_family", "sans-serif")
        plt.rcParams["font.size"] = config.get("tick_label_size", 10)

        # Plot trace data if available
        if trace_model is not None:
            time_sec = getattr(trace_model, "time_full", None)
            inner = getattr(trace_model, "inner_full", None)
            outer = getattr(trace_model, "outer_full", None)
            avg_pressure = getattr(trace_model, "avg_pressure_full", None)
            set_pressure = getattr(trace_model, "set_pressure_full", None)

            if time_sec is not None:
                # Convert time using configured divisor
                time_divisor = config.get("time_divisor", 1.0)
                time = time_sec / time_divisor

                trace_sel = _normalize_trace_selection(config)
                line_width = config.get("line_width", 1.5)
                trace_handles = []

                # Plot based on trace type
                if trace_sel.get("inner") and inner is not None:
                    trace_handles.append(
                        ax.plot(
                            time,
                            inner,
                            color=config.get("inner_color", "#0000FF"),
                            linewidth=line_width,
                            label="Inner Diameter",
                        )[0]
                    )
                if trace_sel.get("outer") and outer is not None:
                    trace_handles.append(
                        ax.plot(
                            time,
                            outer,
                            color=config.get("outer_color", "#FF0000"),
                            linewidth=line_width,
                            label="Outer Diameter",
                        )[0]
                    )

                if trace_sel.get("avg_pressure") and avg_pressure is not None:
                    trace_handles.append(
                        ax.plot(
                            time,
                            avg_pressure,
                            color=config.get("pressure_color", "#00AA00"),
                            linewidth=line_width,
                            label="Average Pressure",
                        )[0]
                    )
                if trace_sel.get("set_pressure") and set_pressure is not None:
                    trace_handles.append(
                        ax.plot(
                            time,
                            set_pressure,
                            color=config.get("pressure_color", "#00AA00"),
                            linewidth=line_width,
                            label="Set Pressure",
                        )[0]
                    )
                if len(trace_handles) > 1:
                    ax.legend(handles=trace_handles, fontsize=config.get("tick_label_size", 10))
                if not trace_handles:
                    ax.text(
                        0.5,
                        0.5,
                        "No data for selected traces",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                    )
                if not any(trace_sel.values()):
                    ax.text(
                        0.5,
                        0.5,
                        "No trace selected",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                    )

                # Draw events if enabled and available
                if (
                    config.get("show_events", False)
                    and event_times is not None
                    and len(event_times) > 0
                ):
                    self._draw_events(ax, event_times, event_labels, event_colors, config)

        else:
            # Test pattern if no trace model
            x = np.linspace(0, 10, 100)
            y = np.sin(x) * 50 + 100
            ax.plot(x, y, "b-", linewidth=config.get("line_width", 1.5))
            ax.text(
                0.5,
                0.95,
                "No trace data loaded - Test pattern",
                ha="center",
                va="top",
                transform=ax.transAxes,
                fontsize=10,
                style="italic",
            )

        # Apply axis settings
        axis_label_kwargs = {
            "fontsize": config.get("axis_label_size", 12),
            "fontweight": "bold" if config.get("axis_label_bold") else "normal",
            "fontstyle": "italic" if config.get("axis_label_italic") else "normal",
            "fontfamily": config.get("font_family", "Arial"),
        }
        ax.set_xlabel(
            config.get("x_label", "Time (min)"),
            **axis_label_kwargs,
        )
        ax.set_ylabel(
            config.get("y_label", "Diameter (μm)"),
            **axis_label_kwargs,
        )
        ax.xaxis.label.set_color(FIG_TEXT_COLOR)
        ax.yaxis.label.set_color(FIG_TEXT_COLOR)

        # Set axis limits
        if not config.get("x_auto", True):
            ax.set_xlim(config.get("x_min", 0), config.get("x_max", 60))
        if not config.get("y_auto", True):
            ax.set_ylim(config.get("y_min", 0), config.get("y_max", 200))

        # Grid - explicitly toggle to ensure state matches checkbox
        show_grid = config.get("show_grid", True)
        ax.grid(False)
        if show_grid:
            ax.grid(True, which="both", axis="both", alpha=0.3, color=FIG_GRID_COLOR)

        # Tick label size
        ax.tick_params(labelsize=config.get("tick_label_size", 10))
        ax.tick_params(axis="both", colors=FIG_TEXT_COLOR)
        self._set_tick_label_style(ax, config)

        # Spine visibility (publication style - hide top/right by default)
        for spine in ax.spines.values():
            spine.set_color(FIG_SPINE_COLOR)
        ax.spines["top"].set_visible(config.get("show_top_spine", False))
        ax.spines["right"].set_visible(config.get("show_right_spine", False))
        ax.spines["left"].set_visible(True)
        ax.spines["bottom"].set_visible(True)

        # Annotations (text, boxes, arrows)
        self._draw_annotations(
            ax, config, active_annotation_id=active_annotation_id, show_selection=show_selection
        )

    def _draw_events(
        self,
        ax,
        event_times: list[float],
        event_labels: list[str] | None,
        event_colors: list[str] | None,
        config: dict[str, Any],
    ):
        """Draw event markers on the axes.

        Args:
            ax: Matplotlib axes
            event_times: Event times in seconds
            event_labels: Event labels
            event_colors: Event colors
            config: Configuration dict
        """
        # Convert event times using configured divisor
        time_divisor = config.get("time_divisor", 1.0)
        event_times_converted = [t / time_divisor for t in event_times]

        # Filter events to visible x-range
        xlim = ax.get_xlim()
        visible_indices = [
            i for i, t in enumerate(event_times_converted) if xlim[0] <= t <= xlim[1]
        ]

        # Apply manual selection filter
        selected_indices = config.get("event_visible_indices")
        if selected_indices is not None:
            selected_set = set(selected_indices)
            visible_indices = [i for i in visible_indices if i in selected_set]

        if not visible_indices:
            return  # No events in visible range

        event_style = config.get("event_style", "lines")
        label_pos = config.get("event_label_pos", "top")
        event_font_size = config.get("event_font_size", config.get("tick_label_size", 10))

        # Default colors if not provided
        if event_colors is None or len(event_colors) == 0:
            event_colors = ["#888888"] * len(event_times)

        # Default labels if not provided
        if event_labels is None or len(event_labels) == 0:
            event_labels = [f"E{i+1}" for i in range(len(event_times))]

        # Draw vertical lines if needed
        if event_style in ["lines", "both"]:
            for i in visible_indices:
                time = event_times_converted[i]
                color = event_colors[i]
                ax.axvline(
                    time,
                    color=color,
                    linestyle="--",
                    linewidth=1,
                    alpha=0.7,
                    clip_on=True,
                )

        # Draw markers if needed
        if event_style in ["markers", "both"]:
            ylim = ax.get_ylim()
            span = ylim[1] - ylim[0]
            y_offset = span * 0.02  # nudge markers a bit above the trace point
            primary_line = None
            for line in ax.get_lines():
                xdata = line.get_xdata()
                ydata = line.get_ydata()
                if len(xdata) > 0 and len(ydata) == len(xdata):
                    primary_line = line
                    break

            for i in visible_indices:
                time = event_times_converted[i]
                color = event_colors[i]
                y_marker = None
                if primary_line is not None:
                    xdata = np.asarray(primary_line.get_xdata())
                    ydata = np.asarray(primary_line.get_ydata())
                    if xdata.size > 0:
                        idx = int(np.argmin(np.abs(xdata - time)))
                        if 0 <= idx < ydata.size:
                            y_marker = float(ydata[idx]) + y_offset
                if y_marker is None:
                    y_marker = ylim[0] + span * 0.05  # fallback near bottom

                ax.plot(time, y_marker, "v", color=color, markersize=8, clip_on=True)

        # Draw labels if needed
        if label_pos != "none":
            y_pos = 1.0 if label_pos == "top" else 0.0
            va = "top" if label_pos == "top" else "bottom"
            offset_points = -5.0 if label_pos == "top" else 5.0  # 5 pt inset from edge
            base_transform = ax.get_xaxis_transform()  # data x, axes-fraction y
            text_transform = base_transform + mtransforms.ScaledTranslation(
                0, offset_points / 72.0, ax.figure.dpi_scale_trans
            )

            for i in visible_indices:
                time = event_times_converted[i]
                label = event_labels[i]
                color = event_colors[i]
                ax.text(
                    time,
                    y_pos,
                    label,
                    rotation=90,
                    ha="right",
                    va=va,
                    fontsize=event_font_size,
                    color=color,
                    transform=text_transform,
                    clip_on=True,  # Keep text within plot area
                )

    def _set_tick_label_style(self, ax, config: dict[str, Any]) -> None:
        """Apply tick label weight/style/family to the given axes."""
        weight = "bold" if config.get("tick_label_bold") else "normal"
        style = "italic" if config.get("tick_label_italic") else "normal"
        family = config.get("font_family", "Arial")
        for label in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            label.set_fontweight(weight)
            label.set_fontstyle(style)
            label.set_fontfamily(family)

    def _transform_for_space(self, ax, space: str):
        if space == "axes":
            return ax.transAxes
        if space == "figure":
            return ax.figure.transFigure
        return ax.transData

    def _draw_annotations(
        self,
        ax,
        config: dict[str, Any],
        active_annotation_id: int | None = None,
        show_selection: bool = False,
    ) -> None:
        """Render annotations from config."""
        annotations = config.get("annotations") or []
        if not annotations:
            return

        for ann in annotations:
            ann_type = ann.get("type", "box")
            space = ann.get("space", "axes")
            transform = self._transform_for_space(ax, space)
            if transform is None:
                continue
            clip = space == "data"
            color = ann.get("color", "#000000")
            text_color = ann.get("text_color", color)
            lw = float(ann.get("linewidth", 1.0))
            alpha = float(ann.get("alpha", 1.0))
            zorder = ann.get("zorder", 12)

            if ann_type == "box":
                x0 = float(ann.get("x0", 0.0))
                y0 = float(ann.get("y0", 0.0))
                x1 = float(ann.get("x1", 0.0))
                y1 = float(ann.get("y1", 0.0))
                if x1 <= x0 or y1 <= y0:
                    continue
                width = x1 - x0
                height = y1 - y0
                face = mcolors.to_rgba(ann.get("facecolor", "#ffffff"), ann.get("face_alpha", 0.25))
                rect = mpatches.Rectangle(
                    (x0, y0),
                    width,
                    height,
                    transform=transform,
                    facecolor=face,
                    edgecolor=color,
                    linewidth=lw,
                    alpha=alpha,
                    zorder=zorder,
                    clip_on=clip,
                )
                ax.add_patch(rect)

                text = ann.get("text", "")
                if text:
                    ax.text(
                        x0 + width / 2.0,
                        y0 + height / 2.0,
                        text,
                        ha=ann.get("ha", "center"),
                        va=ann.get("va", "center"),
                        fontsize=ann.get("fontsize", config.get("tick_label_size", 10)),
                        fontfamily=ann.get("fontfamily", config.get("font_family", "Arial")),
                        fontweight=ann.get("fontweight", "normal"),
                        fontstyle=ann.get("fontstyle", "normal"),
                        color=text_color,
                        transform=transform,
                        zorder=zorder + 1,
                        clip_on=clip,
                    )

                if show_selection and ann.get("id") == active_annotation_id:
                    highlight = mpatches.Rectangle(
                        (x0, y0),
                        width,
                        height,
                        transform=transform,
                        facecolor="none",
                        edgecolor="#1976d2",
                        linewidth=max(1.0, lw),
                        linestyle="--",
                        zorder=zorder + 2,
                        clip_on=False,
                    )
                    ax.add_patch(highlight)
                    corners_x = [x0, x1, x1, x0]
                    corners_y = [y0, y0, y1, y1]
                    ax.plot(
                        corners_x,
                        corners_y,
                        linestyle="",
                        marker="s",
                        markersize=6,
                        color="#1976d2",
                        markerfacecolor="#e3f2fd",
                        transform=transform,
                        zorder=zorder + 3,
                        clip_on=False,
                    )

            elif ann_type == "text":
                bbox = None
                face_alpha = ann.get("face_alpha", 0.0)
                if face_alpha > 0:
                    bbox = {
                        "boxstyle": "round,pad=0.2",
                        "facecolor": mcolors.to_rgba(
                            ann.get("facecolor", "#ffffff"), float(face_alpha)
                        ),
                        "edgecolor": "none",
                    }
                    ax.text(
                        float(ann.get("x", 0.5)),
                        float(ann.get("y", 0.5)),
                        ann.get("text", ""),
                        ha=ann.get("ha", "center"),
                        va=ann.get("va", "center"),
                        fontsize=ann.get("fontsize", config.get("tick_label_size", 10)),
                        fontfamily=ann.get("fontfamily", config.get("font_family", "Arial")),
                        fontweight=ann.get("fontweight", "normal"),
                        fontstyle=ann.get("fontstyle", "normal"),
                        color=text_color,
                        transform=transform,
                        zorder=zorder,
                        clip_on=clip,
                        bbox=bbox,
                    )
                if show_selection and ann.get("id") == active_annotation_id:
                    ax.plot(
                        [ann.get("x", 0.5)],
                        [ann.get("y", 0.5)],
                        marker="o",
                        markersize=6,
                        color="#1976d2",
                        markerfacecolor="#e3f2fd",
                        linestyle="",
                        transform=transform,
                        zorder=zorder + 2,
                        clip_on=False,
                    )
            else:  # line / arrow
                arrowstyle = ann.get("arrowstyle", "->" if ann_type == "arrow" else "-")
                arrow = mpatches.FancyArrowPatch(
                    (float(ann.get("x0", 0.0)), float(ann.get("y0", 0.0))),
                    (float(ann.get("x1", 0.0)), float(ann.get("y1", 0.0))),
                    arrowstyle=arrowstyle,
                    color=color,
                    linewidth=lw,
                    alpha=alpha,
                    mutation_scale=10 + lw * 3,
                    transform=transform,
                    zorder=zorder,
                    clip_on=clip,
                )
                ax.add_patch(arrow)
                label = ann.get("text", "")
                if label:
                    mid_x = (float(ann.get("x0", 0.0)) + float(ann.get("x1", 0.0))) / 2.0
                    mid_y = (float(ann.get("y0", 0.0)) + float(ann.get("y1", 0.0))) / 2.0
                    ax.text(
                        mid_x,
                        mid_y,
                        label,
                        ha=ann.get("ha", "center"),
                        va=ann.get("va", "center"),
                        fontsize=ann.get("fontsize", config.get("tick_label_size", 10)),
                        fontfamily=ann.get("fontfamily", config.get("font_family", "Arial")),
                        fontweight=ann.get("fontweight", "normal"),
                        fontstyle=ann.get("fontstyle", "normal"),
                        color=text_color,
                        transform=transform,
                        zorder=zorder + 1,
                        clip_on=clip,
                    )
                if show_selection and ann.get("id") == active_annotation_id:
                    ax.plot(
                        [ann.get("x0", 0.0), ann.get("x1", 0.0)],
                        [ann.get("y0", 0.0), ann.get("y1", 0.0)],
                        marker="s",
                        linestyle="",
                        color="#1976d2",
                        markerfacecolor="#e3f2fd",
                        markersize=6,
                        transform=transform,
                        zorder=zorder + 2,
                        clip_on=False,
                    )
