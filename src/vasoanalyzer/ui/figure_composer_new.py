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
import logging
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
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
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.core.trace_model import TraceModel

__all__ = ["NewFigureComposerWindow"]

log = logging.getLogger(__name__)


class NewFigureComposerWindow(QMainWindow):
    """New Figure Composer with clean architecture and publication-ready features.

    Architecture: Config dict → SimpleRenderer → Shared Figure ← Canvas
    """

    def __init__(self, trace_model: TraceModel | None = None, parent=None):
        super().__init__(parent)
        self.trace_model = trace_model
        self.parent_window = parent

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
            facecolor="white",
        )
        self.canvas = FigureCanvasQTAgg(self.page_figure)
        self.canvas.setStyleSheet("background-color: #ffffff;")  # White canvas
        self.renderer = SimpleRenderer(self.page_figure)

        # Alias for any code that still references self.figure
        self.figure = self.page_figure

        # Initialize config with defaults
        self.config = self._get_default_config()
        self.plot_axes = None
        self._layout_dirty = True

        # Initialize annotation tools
        self.text_tool = None
        self.box_tool = None
        self.line_tool = None
        self.arrow_tool = None
        self.current_tool = None

        # Apply initial page sizing before creating the UI
        self._apply_page_canvas_size()

        self._setup_ui()

        # Apply stylesheet for better appearance
        self._apply_stylesheet()

        # Setup keyboard shortcuts
        self._setup_shortcuts()

        # Initial render after page layout is configured
        self._render()

    def _get_default_config(self) -> dict[str, Any]:
        """Get default configuration."""
        return {
            # Figure size on the page
            "width_mm": 170,
            "height_mm": 42,
            "dpi": 300,
            # Position on page (fractions of page width/height)
            "fig_left": 0.15,
            "fig_top": 0.70,
            # Data
            "trace": "inner",  # 'inner', 'outer', 'both', 'avg_pressure', 'set_pressure'
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
            "line_width": 1.5,
            "inner_color": "#0000FF",
            "outer_color": "#FF0000",
            "pressure_color": "#00AA00",
            # Events
            "show_events": True,
            "event_style": "lines",  # 'lines', 'markers', 'both'
            "event_label_pos": "top",  # 'top', 'bottom', 'none'
            # Fonts
            "axis_label_size": 12,
            "tick_label_size": 10,
            "font_family": "sans-serif",
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

        # Page background to show the sheet bounds
        page_rect = plt.Rectangle(
            (0, 0),
            1,
            1,
            transform=self.page_figure.transFigure,
            facecolor="#f8f8f8",
            edgecolor="#cccccc",
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

        # Axes where the actual data is drawn
        self.plot_axes = self.page_figure.add_axes([left, bottom, fig_width_frac, fig_height_frac])
        self.plot_axes.set_facecolor("white")

        # Visual border around the plot area
        border = plt.Rectangle(
            (left, bottom),
            fig_width_frac,
            fig_height_frac,
            transform=self.page_figure.transFigure,
            fill=False,
            edgecolor="#888888",
            linewidth=1,
            linestyle="--",
            zorder=10,
        )
        self.page_figure.patches.append(border)

        # Dimension labels
        self._add_dimension_labels(left, bottom, fig_width_frac, fig_height_frac)

        # Share axes with renderer and tools
        self.renderer.set_axes(self.plot_axes)
        self.page_figure.plot_axes = self.plot_axes
        self._sync_position_controls()
        self._layout_dirty = False

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

    def _apply_stylesheet(self):
        """Apply stylesheet for better control panel visibility."""
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cccccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }

            QDoubleSpinBox, QSpinBox {
                min-width: 80px;
                max-width: 120px;
            }

            QLineEdit {
                min-width: 100px;
            }

            QComboBox {
                min-width: 120px;
            }

            QPushButton {
                min-height: 25px;
            }
        """)

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        # Note: Undo/redo would require state management - placeholder for now
        pass

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
        canvas_layout.addWidget(self.nav_toolbar)

        # Annotation toolbar
        self.annotation_toolbar = self._create_annotation_toolbar()
        canvas_layout.addWidget(self.annotation_toolbar)

        # Canvas in scroll area with gray background
        self.canvas_scroll = QScrollArea()
        self.canvas_scroll.setWidget(self.canvas)
        self.canvas_scroll.setWidgetResizable(False)  # Keep canvas at its natural size
        self.canvas_scroll.setAlignment(Qt.AlignCenter)
        self.canvas_scroll.setStyleSheet("""
            QScrollArea {
                background-color: #e8e8e8;
                border: 1px solid #cccccc;
            }
        """)
        canvas_layout.addWidget(self.canvas_scroll)

        # Info bar showing dimensions
        self.info_bar = QLabel()
        self.info_bar.setStyleSheet(
            "padding: 5px; background: #f8f8f8; border-top: 1px solid #ccc;"
        )
        self._update_info_bar()
        canvas_layout.addWidget(self.info_bar)

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
        inner_layout.setSpacing(5)

        # Add control groups
        inner_layout.addWidget(self._create_page_group())
        inner_layout.addWidget(self._create_size_group())
        inner_layout.addWidget(self._create_data_group())
        inner_layout.addWidget(self._create_axes_group())
        inner_layout.addWidget(self._create_style_group())
        inner_layout.addWidget(self._create_events_group())
        inner_layout.addWidget(self._create_fonts_group())
        inner_layout.addWidget(self._create_export_group())
        inner_layout.addStretch()

        # Set the inner widget as scroll area content
        scroll_area.setWidget(inner_widget)

        # Main layout for control panel
        panel_layout = QVBoxLayout(control_widget)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(scroll_area)

        return control_widget

    def _create_annotation_toolbar(self) -> QToolBar:
        """Create toolbar for annotation tools."""
        toolbar = QToolBar("Annotations")
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

        # Select/Move tool (default)
        select_action = QAction("Select", self)
        select_action.setCheckable(True)
        select_action.setChecked(True)
        select_action.triggered.connect(lambda: self._set_annotation_mode(None))

        # Text tool
        text_action = QAction("Add Text", self)
        text_action.setCheckable(True)
        text_action.triggered.connect(lambda: self._set_annotation_mode("text"))

        # Box tool
        box_action = QAction("Add Box", self)
        box_action.setCheckable(True)
        box_action.triggered.connect(lambda: self._set_annotation_mode("box"))

        # Line tool
        line_action = QAction("Add Line", self)
        line_action.setCheckable(True)
        line_action.triggered.connect(lambda: self._set_annotation_mode("line"))

        # Arrow tool
        arrow_action = QAction("Add Arrow", self)
        arrow_action.setCheckable(True)
        arrow_action.triggered.connect(lambda: self._set_annotation_mode("arrow"))

        # Clear annotations
        clear_action = QAction("Clear All", self)
        clear_action.triggered.connect(self._clear_annotations)

        # Create action group for exclusive selection
        self.tool_group = QActionGroup(self)
        self.tool_group.addAction(select_action)
        self.tool_group.addAction(text_action)
        self.tool_group.addAction(box_action)
        self.tool_group.addAction(line_action)
        self.tool_group.addAction(arrow_action)

        toolbar.addAction(select_action)
        toolbar.addSeparator()
        toolbar.addAction(text_action)
        toolbar.addAction(box_action)
        toolbar.addAction(line_action)
        toolbar.addAction(arrow_action)
        toolbar.addSeparator()
        toolbar.addAction(clear_action)

        return toolbar

    def _set_annotation_mode(self, mode: str | None):
        """Switch annotation tool."""
        # Deactivate current tool
        if self.current_tool:
            self.current_tool.deactivate()

        # Get current axes
        ax = self.plot_axes
        if ax is None:
            self._render()
            ax = self.plot_axes
        if not ax:
            return

        # Keep tool references pointed at the current axes
        for tool in [self.text_tool, self.box_tool, self.line_tool, self.arrow_tool]:
            if tool:
                tool.ax = ax

        # Activate new tool
        if mode == "text":
            if not self.text_tool:
                self.text_tool = TextAnnotationTool(ax, self.figure, self.canvas)
            self.text_tool.activate()
            self.current_tool = self.text_tool
        elif mode == "box":
            if not self.box_tool:
                self.box_tool = BoxAnnotationTool(ax, self.figure, self.canvas)
            self.box_tool.activate()
            self.current_tool = self.box_tool
        elif mode == "line":
            if not self.line_tool:
                self.line_tool = LineAnnotationTool(ax, self.figure, self.canvas)
            self.line_tool.activate()
            self.current_tool = self.line_tool
        elif mode == "arrow":
            if not self.arrow_tool:
                self.arrow_tool = ArrowAnnotationTool(ax, self.figure, self.canvas)
            self.arrow_tool.activate()
            self.current_tool = self.arrow_tool
        else:
            self.current_tool = None
            self.canvas.setCursor(Qt.ArrowCursor)

    def _clear_annotations(self):
        """Remove all annotations."""
        for tool in [self.text_tool, self.box_tool, self.line_tool, self.arrow_tool]:
            if tool and tool.annotations:
                for ann in tool.annotations:
                    with contextlib.suppress(Exception):
                        ann.remove()
                tool.annotations = []
        self.canvas.draw_idle()

    def _create_page_group(self) -> QGroupBox:
        """Create page setup controls (size, orientation, placement)."""
        group = QGroupBox("Page Setup")
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
        layout.addRow("Position:", position_widget)
        layout.addRow("", center_btn)

        group.setLayout(layout)
        return group

    def _create_size_group(self) -> QGroupBox:
        """Create figure size controls with better layout."""
        group = QGroupBox("Figure Size")
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Width control
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(20, 400)
        self.width_spin.setValue(self.config["width_mm"])
        self.width_spin.setSuffix(" mm")
        self.width_spin.setDecimals(1)
        self.width_spin.setSingleStep(1.0)
        self.width_spin.valueChanged.connect(self._on_size_changed)

        # Height control
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(20, 400)
        self.height_spin.setValue(self.config["height_mm"])
        self.height_spin.setSuffix(" mm")
        self.height_spin.setDecimals(1)
        self.height_spin.setSingleStep(1.0)
        self.height_spin.valueChanged.connect(self._on_size_changed)

        # DPI control
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(self.config["dpi"])
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.valueChanged.connect(self._on_dpi_changed)

        layout.addRow("Width:", self.width_spin)
        layout.addRow("Height:", self.height_spin)
        layout.addRow("DPI:", self.dpi_spin)

        group.setLayout(layout)
        return group

    def _create_data_group(self) -> QGroupBox:
        """Create data/trace selection controls."""
        group = QGroupBox("Data")
        layout = QFormLayout(group)

        self.trace_combo = QComboBox()
        self.trace_combo.addItem("Inner Diameter", "inner")
        self.trace_combo.addItem("Outer Diameter", "outer")
        self.trace_combo.addItem("Both Diameters", "both")
        self.trace_combo.addItem("Average Pressure", "avg_pressure")
        self.trace_combo.addItem("Set Pressure", "set_pressure")
        self.trace_combo.currentIndexChanged.connect(self._on_trace_changed)

        layout.addRow("Trace:", self.trace_combo)

        return group

    def _create_axes_group(self) -> QGroupBox:
        """Create axis control group."""
        group = QGroupBox("Axes")
        layout = QVBoxLayout()

        # Time unit selector
        time_unit_container = QWidget()
        time_unit_layout = QHBoxLayout(time_unit_container)
        time_unit_layout.setContentsMargins(0, 0, 0, 0)
        time_unit_layout.addWidget(QLabel("Time Units:"))

        self.time_unit_combo = QComboBox()
        self.time_unit_combo.addItems(["Seconds", "Minutes", "Hours"])
        self.time_unit_combo.setCurrentText(self.config["time_unit"])
        self.time_unit_combo.currentTextChanged.connect(self._on_time_unit_changed)
        time_unit_layout.addWidget(self.time_unit_combo)
        time_unit_layout.addStretch()

        layout.addWidget(time_unit_container)

        # Form layout for labels and limits
        form_layout = QFormLayout()

        # Labels
        self.x_label_edit = QLineEdit(self.config["x_label"])
        self.x_label_edit.editingFinished.connect(self._on_axis_changed)

        self.y_label_edit = QLineEdit(self.config["y_label"])
        self.y_label_edit.editingFinished.connect(self._on_axis_changed)

        # X limits
        x_limit_layout = QHBoxLayout()
        self.x_auto_check = QCheckBox("Auto")
        self.x_auto_check.setChecked(self.config["x_auto"])
        self.x_auto_check.toggled.connect(self._on_x_auto_toggled)

        self.x_min_spin = QDoubleSpinBox()
        self.x_min_spin.setRange(-1e9, 1e9)
        self.x_min_spin.setValue(self.config["x_min"])
        self.x_min_spin.setEnabled(not self.config["x_auto"])
        self.x_min_spin.valueChanged.connect(self._on_axis_changed)

        self.x_max_spin = QDoubleSpinBox()
        self.x_max_spin.setRange(-1e9, 1e9)
        self.x_max_spin.setValue(self.config["x_max"])
        self.x_max_spin.setEnabled(not self.config["x_auto"])
        self.x_max_spin.valueChanged.connect(self._on_axis_changed)

        x_limit_layout.addWidget(self.x_auto_check)
        x_limit_layout.addWidget(QLabel("Min:"))
        x_limit_layout.addWidget(self.x_min_spin)
        x_limit_layout.addWidget(QLabel("Max:"))
        x_limit_layout.addWidget(self.x_max_spin)

        # Y limits
        y_limit_layout = QHBoxLayout()
        self.y_auto_check = QCheckBox("Auto")
        self.y_auto_check.setChecked(self.config["y_auto"])
        self.y_auto_check.toggled.connect(self._on_y_auto_toggled)

        self.y_min_spin = QDoubleSpinBox()
        self.y_min_spin.setRange(-1e9, 1e9)
        self.y_min_spin.setValue(self.config["y_min"])
        self.y_min_spin.setEnabled(not self.config["y_auto"])
        self.y_min_spin.valueChanged.connect(self._on_axis_changed)

        self.y_max_spin = QDoubleSpinBox()
        self.y_max_spin.setRange(-1e9, 1e9)
        self.y_max_spin.setValue(self.config["y_max"])
        self.y_max_spin.setEnabled(not self.config["y_auto"])
        self.y_max_spin.valueChanged.connect(self._on_axis_changed)

        y_limit_layout.addWidget(self.y_auto_check)
        y_limit_layout.addWidget(QLabel("Min:"))
        y_limit_layout.addWidget(self.y_min_spin)
        y_limit_layout.addWidget(QLabel("Max:"))
        y_limit_layout.addWidget(self.y_max_spin)

        # Grid
        self.grid_check = QCheckBox("Show Grid")
        self.grid_check.setChecked(self.config["show_grid"])
        self.grid_check.toggled.connect(self._on_axis_changed)

        # Spine controls (publication style)
        self.show_top_spine_check = QCheckBox("Show Top Spine")
        self.show_top_spine_check.setChecked(self.config["show_top_spine"])
        self.show_top_spine_check.toggled.connect(self._on_axis_changed)

        self.show_right_spine_check = QCheckBox("Show Right Spine")
        self.show_right_spine_check.setChecked(self.config["show_right_spine"])
        self.show_right_spine_check.toggled.connect(self._on_axis_changed)

        form_layout.addRow("X Label:", self.x_label_edit)
        form_layout.addRow("Y Label:", self.y_label_edit)
        form_layout.addRow("X Limits:", x_limit_layout)
        form_layout.addRow("Y Limits:", y_limit_layout)
        form_layout.addRow(self.grid_check)
        form_layout.addRow(self.show_top_spine_check)
        form_layout.addRow(self.show_right_spine_check)

        layout.addLayout(form_layout)

        group.setLayout(layout)
        return group

    def _create_style_group(self) -> QGroupBox:
        """Create line style controls."""
        group = QGroupBox("Line Style")
        layout = QFormLayout(group)

        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setRange(0.1, 10.0)
        self.line_width_spin.setSingleStep(0.1)
        self.line_width_spin.setValue(self.config["line_width"])
        self.line_width_spin.valueChanged.connect(self._on_style_changed)

        # Color buttons
        self.inner_color_btn = QPushButton("Inner Color")
        self.inner_color_btn.setStyleSheet(f"background-color: {self.config['inner_color']}")
        self.inner_color_btn.clicked.connect(
            lambda: self._pick_color("inner_color", self.inner_color_btn)
        )

        self.outer_color_btn = QPushButton("Outer Color")
        self.outer_color_btn.setStyleSheet(f"background-color: {self.config['outer_color']}")
        self.outer_color_btn.clicked.connect(
            lambda: self._pick_color("outer_color", self.outer_color_btn)
        )

        self.pressure_color_btn = QPushButton("Pressure Color")
        self.pressure_color_btn.setStyleSheet(f"background-color: {self.config['pressure_color']}")
        self.pressure_color_btn.clicked.connect(
            lambda: self._pick_color("pressure_color", self.pressure_color_btn)
        )

        layout.addRow("Line Width:", self.line_width_spin)
        layout.addRow(self.inner_color_btn)
        layout.addRow(self.outer_color_btn)
        layout.addRow(self.pressure_color_btn)

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

        layout.addRow(self.show_events_check)
        layout.addRow("Style:", self.event_style_combo)
        layout.addRow("Labels:", self.event_label_combo)

        # Show event count
        event_count = len(self.event_times)
        count_label = QLabel(f"{event_count} events available")
        layout.addRow(count_label)

        return group

    def _create_fonts_group(self) -> QGroupBox:
        """Create font controls."""
        group = QGroupBox("Fonts")
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

        layout.addRow("Axis Labels:", self.axis_label_size_spin)
        layout.addRow("Tick Labels:", self.tick_label_size_spin)
        layout.addRow("Font Family:", self.font_combo)

        return group

    def _create_export_group(self) -> QGroupBox:
        """Create export controls."""
        group = QGroupBox("Export")
        layout = QVBoxLayout(group)

        # Update preview button
        update_btn = QPushButton("Update Preview")
        update_btn.clicked.connect(self._render)
        layout.addWidget(update_btn)

        # Export format buttons
        png_btn = QPushButton("Export PNG...")
        png_btn.clicked.connect(lambda: self._export("png"))
        layout.addWidget(png_btn)

        pdf_btn = QPushButton("Export PDF...")
        pdf_btn.clicked.connect(lambda: self._export("pdf"))
        layout.addWidget(pdf_btn)

        svg_btn = QPushButton("Export SVG...")
        svg_btn.clicked.connect(lambda: self._export("svg"))
        layout.addWidget(svg_btn)

        tiff_btn = QPushButton("Export TIFF...")
        tiff_btn.clicked.connect(lambda: self._export("tiff"))
        layout.addWidget(tiff_btn)

        return group

    # Event handlers
    def _on_page_size_changed(self):
        """Handle page size selection."""
        self.page_size_name = self.page_combo.currentData()
        self._apply_page_canvas_size()
        self._render()

    def _on_orientation_changed(self):
        """Handle page orientation toggle."""
        self.page_orientation = self.orientation_combo.currentText()
        self._apply_page_canvas_size()
        self._render()

    def _on_position_changed(self):
        """Handle plot position changes."""
        self.config["fig_left"] = self.pos_x_spin.value() / 100.0
        self.config["fig_top"] = self.pos_y_spin.value() / 100.0
        self._layout_dirty = True
        self._render()

    def _center_figure(self):
        """Center the figure on the page."""
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

    def _on_size_changed(self):
        """Handle width/height changes properly."""
        # Update config
        self.config["width_mm"] = self.width_spin.value()
        self.config["height_mm"] = self.height_spin.value()

        self._layout_dirty = True
        self._update_info_bar()
        self._render()

    def _on_dpi_changed(self):
        """Handle DPI changes (doesn't affect figure size, just export quality)."""
        self.config["dpi"] = self.dpi_spin.value()
        self._update_info_bar()
        # No need to re-render for DPI change - it only affects export

    def _on_time_unit_changed(self):
        """Handle time unit changes."""
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

    def _on_trace_changed(self):
        """Handle trace selection change."""
        self.config["trace"] = self.trace_combo.currentData()
        # Update Y label based on trace type
        if self.config["trace"] in ["avg_pressure", "set_pressure"]:
            self.y_label_edit.setText("Pressure (mmHg)")
            self.config["y_label"] = "Pressure (mmHg)"
        else:
            self.y_label_edit.setText("Diameter (μm)")
            self.config["y_label"] = "Diameter (μm)"
        self._render()

    def _on_axis_changed(self):
        """Handle axis control changes."""
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
        self.config["x_auto"] = checked
        self.x_min_spin.setEnabled(not checked)
        self.x_max_spin.setEnabled(not checked)
        self._render()

    def _on_y_auto_toggled(self, checked):
        """Handle Y auto toggle."""
        self.config["y_auto"] = checked
        self.y_min_spin.setEnabled(not checked)
        self.y_max_spin.setEnabled(not checked)
        self._render()

    def _on_style_changed(self):
        """Handle style control changes."""
        self.config["line_width"] = self.line_width_spin.value()
        self._render()

    def _pick_color(self, config_key: str, button: QPushButton):
        """Open color picker and update config."""
        current_color = QColor(self.config[config_key])
        color = QColorDialog.getColor(current_color, self)
        if color.isValid():
            self.config[config_key] = color.name()
            button.setStyleSheet(f"background-color: {color.name()}")
            self._render()

    def _on_events_changed(self):
        """Handle event control changes."""
        self.config["show_events"] = self.show_events_check.isChecked()
        self.config["event_style"] = self.event_style_combo.currentData()
        self.config["event_label_pos"] = self.event_label_combo.currentData()
        self._render()

    def _on_font_changed(self):
        """Handle font control changes."""
        self.config["axis_label_size"] = self.axis_label_size_spin.value()
        self.config["tick_label_size"] = self.tick_label_size_spin.value()
        self.config["font_family"] = self.font_combo.currentFont().family()
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
        )
        self.canvas.draw_idle()
        self._update_info_bar()

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

        # Make sure the on-screen view is up-to-date before copying
        if self._layout_dirty or self.plot_axes is None:
            self._render()

        # Create a NEW figure at export DPI (don't modify display figure)
        export_fig = Figure(figsize=(width_inch, height_inch), dpi=export_dpi)
        export_ax = export_fig.add_axes([0.12, 0.15, 0.83, 0.80])

        # Copy the visible plot into the export axes
        self._copy_plot_to_axes(self.plot_axes, export_ax)

        # Export with format-specific settings (no bbox_inches - use exact size)
        try:
            if format_type == "pdf":
                export_fig.savefig(
                    filepath,
                    format="pdf",
                    dpi=export_dpi,
                    bbox_inches="tight",
                    pad_inches=0.02,
                )
            elif format_type == "svg":
                export_fig.savefig(
                    filepath,
                    format="svg",
                    dpi=export_dpi,
                    bbox_inches="tight",
                    pad_inches=0.02,
                )
            elif format_type == "tiff":
                export_fig.savefig(
                    filepath,
                    format="tiff",
                    dpi=export_dpi,
                    bbox_inches="tight",
                    pad_inches=0.02,
                    pil_kwargs={"compression": "tiff_lzw"},
                )
            else:  # png
                export_fig.savefig(
                    filepath,
                    format="png",
                    dpi=export_dpi,
                    bbox_inches="tight",
                    pad_inches=0.02,
                )

            log.info(f"Exported figure to {filepath} at {export_dpi} DPI ({format_type.upper()})")
        except Exception as e:
            log.error(f"Export failed: {e}")
        finally:
            # Clean up export figure
            plt.close(export_fig)

    def _copy_plot_to_axes(self, source_ax, target_ax):
        """Copy the visible plot (lines, labels, limits) to a new axes."""
        if source_ax is None or target_ax is None:
            return

        # Copy lines
        for line in source_ax.get_lines():
            target_ax.plot(
                line.get_xdata(),
                line.get_ydata(),
                color=line.get_color(),
                linewidth=line.get_linewidth(),
                linestyle=line.get_linestyle(),
                marker=line.get_marker(),
                markersize=line.get_markersize(),
            )

        # Copy patches (annotation boxes)
        for patch in source_ax.patches:
            try:
                patch_copy = type(patch)(
                    patch.get_x(),
                    patch.get_y(),
                    patch.get_width(),
                    patch.get_height(),
                    linewidth=patch.get_linewidth(),
                    edgecolor=patch.get_edgecolor(),
                    facecolor=patch.get_facecolor(),
                    linestyle=patch.get_linestyle(),
                    fill=patch.get_fill(),
                    alpha=patch.get_alpha(),
                )
                target_ax.add_patch(patch_copy)
            except Exception:
                continue

        # Copy text objects (including annotations)
        for text in source_ax.texts:
            transform = (
                target_ax.transAxes
                if text.get_transform() == source_ax.transAxes
                else target_ax.transData
            )
            target_ax.text(
                text.get_position()[0],
                text.get_position()[1],
                text.get_text(),
                ha=text.get_ha(),
                va=text.get_va(),
                rotation=text.get_rotation(),
                fontsize=text.get_fontsize(),
                color=text.get_color(),
                transform=transform,
            )

        # Axis labels and limits
        target_ax.set_xlabel(
            source_ax.get_xlabel(), fontsize=self.config.get("axis_label_size", 12)
        )
        target_ax.set_ylabel(
            source_ax.get_ylabel(), fontsize=self.config.get("axis_label_size", 12)
        )
        target_ax.set_xlim(source_ax.get_xlim())
        target_ax.set_ylim(source_ax.get_ylim())
        target_ax.set_xscale(source_ax.get_xscale())
        target_ax.set_yscale(source_ax.get_yscale())

        # Grid, ticks, and spines
        target_ax.grid(self.config.get("show_grid", True), alpha=0.3)
        target_ax.tick_params(labelsize=self.config.get("tick_label_size", 10))
        target_ax.spines["top"].set_visible(self.config.get("show_top_spine", False))
        target_ax.spines["right"].set_visible(self.config.get("show_right_spine", False))
        target_ax.spines["left"].set_visible(True)
        target_ax.spines["bottom"].set_visible(True)

        # Legend (if present)
        legend = source_ax.get_legend()
        if legend:
            labels = [t.get_text() for t in legend.get_texts()]
            handles = target_ax.get_lines()[: len(labels)]
            target_ax.legend(handles, labels, fontsize=self.config.get("tick_label_size", 10))


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
    ):
        """Clear and redraw the figure with current config.

        Args:
            trace_model: The trace data to plot (can be None for testing)
            config: Configuration dict with all settings
            event_times: Event time points (in seconds)
            event_labels: Event labels
            event_colors: Event colors
        """
        ax = axes or self.axes
        if ax is None:
            ax = self.figure.add_axes([0.15, 0.12, 0.80, 0.83])
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

                trace_type = config.get("trace", "inner")
                line_width = config.get("line_width", 1.5)

                # Plot based on trace type
                if trace_type == "inner" and inner is not None:
                    ax.plot(
                        time,
                        inner,
                        color=config.get("inner_color", "#0000FF"),
                        linewidth=line_width,
                        label="Inner Diameter",
                    )
                elif trace_type == "outer" and outer is not None:
                    ax.plot(
                        time,
                        outer,
                        color=config.get("outer_color", "#FF0000"),
                        linewidth=line_width,
                        label="Outer Diameter",
                    )
                elif trace_type == "both":
                    if inner is not None:
                        ax.plot(
                            time,
                            inner,
                            color=config.get("inner_color", "#0000FF"),
                            linewidth=line_width,
                            label="Inner Diameter",
                        )
                    if outer is not None:
                        ax.plot(
                            time,
                            outer,
                            color=config.get("outer_color", "#FF0000"),
                            linewidth=line_width,
                            label="Outer Diameter",
                        )
                    if inner is not None or outer is not None:
                        ax.legend(fontsize=config.get("tick_label_size", 10))
                elif trace_type == "avg_pressure" and avg_pressure is not None:
                    ax.plot(
                        time,
                        avg_pressure,
                        color=config.get("pressure_color", "#00AA00"),
                        linewidth=line_width,
                        label="Average Pressure",
                    )
                elif trace_type == "set_pressure" and set_pressure is not None:
                    ax.plot(
                        time,
                        set_pressure,
                        color=config.get("pressure_color", "#00AA00"),
                        linewidth=line_width,
                        label="Set Pressure",
                    )
                else:
                    # No valid data for selected trace type
                    ax.text(
                        0.5,
                        0.5,
                        f"No {trace_type} data available",
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
        ax.set_xlabel(
            config.get("x_label", "Time (min)"),
            fontsize=config.get("axis_label_size", 12),
        )
        ax.set_ylabel(
            config.get("y_label", "Diameter (μm)"),
            fontsize=config.get("axis_label_size", 12),
        )

        # Set axis limits
        if not config.get("x_auto", True):
            ax.set_xlim(config.get("x_min", 0), config.get("x_max", 60))
        if not config.get("y_auto", True):
            ax.set_ylim(config.get("y_min", 0), config.get("y_max", 200))

        # Grid
        ax.grid(config.get("show_grid", True), alpha=0.3)

        # Tick label size
        ax.tick_params(labelsize=config.get("tick_label_size", 10))

        # Spine visibility (publication style - hide top/right by default)
        ax.spines["top"].set_visible(config.get("show_top_spine", False))
        ax.spines["right"].set_visible(config.get("show_right_spine", False))
        ax.spines["left"].set_visible(True)
        ax.spines["bottom"].set_visible(True)

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

        if not visible_indices:
            return  # No events in visible range

        event_style = config.get("event_style", "lines")
        label_pos = config.get("event_label_pos", "top")

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
                ax.axvline(time, color=color, linestyle="--", linewidth=1, alpha=0.7, clip_on=True)

        # Draw markers if needed
        if event_style in ["markers", "both"]:
            ylim = ax.get_ylim()
            y_marker = ylim[0] + (ylim[1] - ylim[0]) * 0.05  # 5% from bottom
            for i in visible_indices:
                time = event_times_converted[i]
                color = event_colors[i]
                ax.plot(time, y_marker, "v", color=color, markersize=8, clip_on=True)

        # Draw labels if needed
        if label_pos != "none":
            ylim = ax.get_ylim()
            if label_pos == "top":
                y_text = ylim[1] - (ylim[1] - ylim[0]) * 0.02  # 2% from top
                va = "top"
            else:  # bottom
                y_text = ylim[0] + (ylim[1] - ylim[0]) * 0.02  # 2% from bottom
                va = "bottom"

            for i in visible_indices:
                time = event_times_converted[i]
                label = event_labels[i]
                color = event_colors[i]
                ax.text(
                    time,
                    y_text,
                    label,
                    rotation=90,
                    ha="right",
                    va=va,
                    fontsize=config.get("tick_label_size", 10),
                    color=color,
                    clip_on=True,  # Keep text within plot area
                )


# ============================================================================
# Annotation Tool Classes
# ============================================================================


class AnnotationTool:
    """Base class for annotation tools."""

    def __init__(self, ax, figure, canvas):
        self.ax = ax
        self.figure = figure
        self.canvas = canvas
        self.active = False
        self.annotations = []

    def activate(self):
        """Activate this tool."""
        self.active = True

    def deactivate(self):
        """Deactivate this tool."""
        self.active = False


class TextAnnotationTool(AnnotationTool):
    """Click to add text annotation."""

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.IBeamCursor)
        self.cid = self.canvas.mpl_connect("button_press_event", self.on_click)

    def deactivate(self):
        super().deactivate()
        self.canvas.setCursor(Qt.ArrowCursor)
        if hasattr(self, "cid"):
            self.canvas.mpl_disconnect(self.cid)

    def on_click(self, event):
        if event.inaxes != self.ax:
            return

        # Get text from dialog
        text, ok = QInputDialog.getText(None, "Add Text", "Enter annotation text:")
        if ok and text:
            # Add text annotation at click position
            annotation = self.ax.text(
                event.xdata,
                event.ydata,
                text,
                fontsize=10,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7),
            )
            self.annotations.append(annotation)
            self.canvas.draw_idle()


class BoxAnnotationTool(AnnotationTool):
    """Drag to create box annotation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rect = None
        self.press = None

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        self.cid_press = self.canvas.mpl_connect("button_press_event", self.on_press)
        self.cid_release = self.canvas.mpl_connect("button_release_event", self.on_release)
        self.cid_motion = self.canvas.mpl_connect("motion_notify_event", self.on_motion)

    def deactivate(self):
        super().deactivate()
        self.canvas.setCursor(Qt.ArrowCursor)
        for cid in ["cid_press", "cid_release", "cid_motion"]:
            if hasattr(self, cid):
                self.canvas.mpl_disconnect(getattr(self, cid))

    def on_press(self, event):
        if event.inaxes != self.ax:
            return
        self.press = (event.xdata, event.ydata)

        # Create rectangle
        import matplotlib.patches as patches

        self.rect = patches.Rectangle(
            self.press,
            0,
            0,
            linewidth=2,
            edgecolor="red",
            facecolor="none",
            linestyle="--",
        )
        self.ax.add_patch(self.rect)

    def on_motion(self, event):
        if self.press is None or event.inaxes != self.ax:
            return

        x0, y0 = self.press
        dx = event.xdata - x0
        dy = event.ydata - y0
        self.rect.set_width(dx)
        self.rect.set_height(dy)
        self.canvas.draw_idle()

    def on_release(self, event):
        if self.press is None:
            return

        # Finalize rectangle
        self.annotations.append(self.rect)
        self.press = None
        self.rect = None


class LineAnnotationTool(AnnotationTool):
    """Click twice to create line annotation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.first_point = None
        self.temp_line = None

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        self.cid = self.canvas.mpl_connect("button_press_event", self.on_click)

    def deactivate(self):
        super().deactivate()
        self.canvas.setCursor(Qt.ArrowCursor)
        if hasattr(self, "cid"):
            self.canvas.mpl_disconnect(self.cid)

    def on_click(self, event):
        if event.inaxes != self.ax:
            return

        if self.first_point is None:
            # First click - start line
            self.first_point = (event.xdata, event.ydata)
            # Show temporary marker
            (self.temp_line,) = self.ax.plot(event.xdata, event.ydata, "ro", markersize=5)
            self.canvas.draw_idle()
        else:
            # Second click - finish line
            x1, y1 = self.first_point
            x2, y2 = event.xdata, event.ydata

            # Remove temp marker
            self.temp_line.remove()

            # Draw final line
            (line,) = self.ax.plot([x1, x2], [y1, y2], "r-", linewidth=2)
            self.annotations.append(line)

            # Reset
            self.first_point = None
            self.temp_line = None
            self.canvas.draw_idle()


class ArrowAnnotationTool(AnnotationTool):
    """Click twice to create arrow annotation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.first_point = None
        self.temp_line = None

    def activate(self):
        super().activate()
        self.canvas.setCursor(Qt.CrossCursor)
        self.cid = self.canvas.mpl_connect("button_press_event", self.on_click)

    def deactivate(self):
        super().deactivate()
        self.canvas.setCursor(Qt.ArrowCursor)
        if hasattr(self, "cid"):
            self.canvas.mpl_disconnect(self.cid)

    def on_click(self, event):
        if event.inaxes != self.ax:
            return

        if self.first_point is None:
            # First click - start arrow
            self.first_point = (event.xdata, event.ydata)
            # Show temporary marker
            (self.temp_line,) = self.ax.plot(event.xdata, event.ydata, "ro", markersize=5)
            self.canvas.draw_idle()
        else:
            # Second click - finish arrow
            x1, y1 = self.first_point
            x2, y2 = event.xdata, event.ydata

            # Remove temp marker
            self.temp_line.remove()

            # Draw arrow
            arrow = self.ax.annotate(
                "",
                xy=(x2, y2),
                xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color="red", lw=2, connectionstyle="arc3"),
            )
            self.annotations.append(arrow)

            # Reset
            self.first_point = None
            self.temp_line = None
            self.canvas.draw_idle()
