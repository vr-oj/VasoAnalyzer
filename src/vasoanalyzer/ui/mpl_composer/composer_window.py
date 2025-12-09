"""Pure Matplotlib Figure Composer Window - Phase 3 Complete.

This module implements the main composer UI using ONLY Matplotlib widgets
for all controls. Qt is used solely to host the Matplotlib canvas.

Features (Phase 3):
- Full annotation creation (text, box, arrow, line)
- Annotation selection and dragging
- Annotation property editor panel
- Multi-panel layout templates
- Export functionality
"""

from __future__ import annotations

import copy
import logging
import uuid
from typing import TYPE_CHECKING
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .renderer import render_figure, render_into_axes
from .spec_io import (
    apply_template_structure,
    list_templates,
    load_figure_spec,
    load_template,
    save_figure_spec,
    save_template,
)
from .specs import (
    AnnotationSpec,
    ExportSpec,
    FigureSpec,
    GraphInstance,
    GraphSpec,
    LayoutSpec,
    TraceBinding,
)
from .theme import PAGE_BG_COLOR, THEME
from .styles import STYLE_PRESETS, apply_style_preset

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from vasoanalyzer.core.trace_model import TraceModel

__all__ = ["PureMplFigureComposer"]

log = logging.getLogger(__name__)


class PureMplFigureComposer(QMainWindow):
    """Pure Matplotlib Figure Composer window with full annotation support."""

    def __init__(
        self,
        trace_model: TraceModel | None = None,
        parent=None,
        *,
        event_times: list[float] | None = None,
        event_labels: list[str] | None = None,
        event_colors: list[str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Pure Matplotlib Figure Composer")
        self.trace_model = trace_model
        self.event_times = event_times or []
        self.event_labels = event_labels or []
        self.event_colors = event_colors or []

        # Typography baseline
        mpl.rcParams["font.family"] = "DejaVu Sans"
        mpl.rcParams["font.size"] = 9

        # Undo/redo stacks
        self._undo_stack: list[FigureSpec] = []
        self._redo_stack: list[FigureSpec] = []
        self._max_undo = 50

        # Current spec (single source of truth)
        self.spec = self._create_default_spec()

        # Preview settings
        self.preview_dpi = 100
        self.zoom_factor = 1.0

        # Annotation interaction state
        self.annotation_mode: str | None = "select"
        self.selected_annotation_id: str | None = None
        self._drag_start: tuple[float, float] | None = None
        self._creating_annotation: AnnotationSpec | None = None
        self._preview_axes_map: dict[str, Axes] = {}
        self._suppress_size_events = False
        self._current_event_index: int = 0
        self._current_trace_name: str | None = None

        # UI widget references
        self.control_widgets: dict[str, any] = {}

        # Build UI
        self._setup_ui()
        self._connect_toolbar_signals()
        self._connect_events()

        # Initial render
        self._push_undo()
        self._update_preview()

        # Set reasonable window size
        self.resize(1600, 1000)

    def _create_default_spec(self) -> FigureSpec:
        """Create a default FigureSpec for initialization."""
        if self.trace_model is not None:
            sample_id = "current_sample"
            trace_bindings = [TraceBinding(name="inner", kind="inner")]
            if self.trace_model.outer_full is not None:
                trace_bindings.append(TraceBinding(name="outer", kind="outer"))
        else:
            sample_id = "no_sample"
            trace_bindings = []

        graph_spec = GraphSpec(
            graph_id="graph1",
            name="Main Graph",
            sample_id=sample_id,
            trace_bindings=trace_bindings,
            x_label="Time (s)",
            y_label="Diameter (µm)",
        )

        graph_instance = GraphInstance(
            instance_id="inst1",
            graph_id="graph1",
            row=0,
            col=0,
        )

        layout_spec = LayoutSpec(
            width_in=5.9,  # ~150 mm
            height_in=3.0,
            graph_instances=[graph_instance],
            nrows=1,
            ncols=1,
        )

        export_spec = ExportSpec(
            format="pdf",
            dpi=600,
            preset_name="Single column (150 mm)",
        )

        return FigureSpec(
            graphs={"graph1": graph_spec},
            layout=layout_spec,
            export=export_spec,
        )

    def _setup_ui(self):
        """Set up Qt-driven layout with Matplotlib canvas."""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        # Left pane: title, canvas, toolbar, status
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        title_label = QLabel("Pure Matplotlib Figure Composer")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #212529;")
        subtitle_label = QLabel("Preview = Export • Spec-driven layout")
        subtitle_label.setStyleSheet("color: #6c757d; font-size: 11px;")
        left_layout.addWidget(title_label)
        left_layout.addWidget(subtitle_label)

        self.ui_figure = Figure(figsize=(10, 6), dpi=100, facecolor=THEME["bg_window"])
        self.canvas = FigureCanvasQTAgg(self.ui_figure)
        left_layout.addWidget(self.canvas, stretch=1)

        self.preview_ax = self.ui_figure.add_subplot(111)
        self.preview_ax.set_facecolor(PAGE_BG_COLOR)
        self.preview_ax.axis("off")

        toolbar_row = QHBoxLayout()
        toolbar_row.setSpacing(4)
        self.btn_mode_select = QToolButton(text="Select")
        self.btn_mode_text = QToolButton(text="Text")
        self.btn_mode_box = QToolButton(text="Box")
        self.btn_mode_arrow = QToolButton(text="Arrow")
        self.btn_mode_line = QToolButton(text="Line")
        self.btn_delete = QPushButton("Delete")
        self.btn_undo = QPushButton("Undo")
        self.btn_redo = QPushButton("Redo")
        self.btn_export = QPushButton("Export")
        for btn in [
            self.btn_mode_select,
            self.btn_mode_text,
            self.btn_mode_box,
            self.btn_mode_arrow,
            self.btn_mode_line,
            self.btn_delete,
            self.btn_undo,
            self.btn_redo,
            self.btn_export,
        ]:
            toolbar_row.addWidget(btn)
        left_layout.addLayout(toolbar_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6c757d; font-family: monospace;")
        left_layout.addWidget(self.status_label)

        splitter.addWidget(left)
        splitter.setStretchFactor(0, 3)

        # Right pane: tabbed controls inside scroll area
        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(6, 6, 6, 6)
        controls_layout.setSpacing(6)

        self.tabs = QTabWidget()
        controls_layout.addWidget(self.tabs)

        self.layout_tab = self._build_layout_tab()
        self.fonts_tab = self._build_fonts_tab()
        self.traces_events_tab = self._build_traces_events_tab()
        self.annotation_tab = self._build_annotation_tab()
        self.export_tab = self._build_export_tab()

        self.tabs.addTab(self.layout_tab, "Layout")
        self.tabs.addTab(self.fonts_tab, "Fonts / Style")
        self.tabs.addTab(self.traces_events_tab, "Traces & Events")
        self.tabs.addTab(self.annotation_tab, "Annotation")
        self.tabs.addTab(self.export_tab, "Export")

        scroll = QScrollArea()
        scroll.setWidget(controls_container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 2)

        self.canvas.draw()

    # ------------------------------------------------------------------
    # Qt toolbar wiring
    # ------------------------------------------------------------------
    def _connect_toolbar_signals(self):
        self.btn_mode_select.clicked.connect(lambda: self._set_annotation_mode("select"))
        self.btn_mode_text.clicked.connect(lambda: self._set_annotation_mode("text"))
        self.btn_mode_box.clicked.connect(lambda: self._set_annotation_mode("box"))
        self.btn_mode_arrow.clicked.connect(lambda: self._set_annotation_mode("arrow"))
        self.btn_mode_line.clicked.connect(lambda: self._set_annotation_mode("line"))

        self.btn_delete.clicked.connect(self._delete_selected_annotation)
        self.btn_undo.clicked.connect(self._undo)
        self.btn_redo.clicked.connect(self._redo)
        self.btn_export.clicked.connect(self.export_figure)
        self._update_toolbar_styles()

    def _set_annotation_mode(self, mode: str):
        self.annotation_mode = mode
        self._update_toolbar_styles()
        self._update_footer()

    def _update_toolbar_styles(self):
        mode_buttons = {
            "select": self.btn_mode_select,
            "text": self.btn_mode_text,
            "box": self.btn_mode_box,
            "arrow": self.btn_mode_arrow,
            "line": self.btn_mode_line,
        }
        for mode, btn in mode_buttons.items():
            if mode == self.annotation_mode:
                btn.setStyleSheet("background-color: #4da3ff; color: white; font-weight: bold;")
            else:
                btn.setStyleSheet("")

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _build_layout_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        grp_templates = QGroupBox("Layout template")
        tmpl_layout = QVBoxLayout(grp_templates)
        self.combo_layout_template = QComboBox()
        self.combo_layout_template.addItems(["1 panel", "2 horizontal", "2 vertical", "2 x 2"])
        tmpl_layout.addWidget(self.combo_layout_template)
        layout.addWidget(grp_templates)

        grp_size = QGroupBox("Size")
        size_form = QFormLayout(grp_size)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(2.0, 18.0)
        self.spin_width.setSingleStep(0.1)
        self.spin_width.setValue(self.spec.layout.width_in)
        size_form.addRow("Width (in)", self.spin_width)

        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(1.0, 18.0)
        self.spin_height.setSingleStep(0.1)
        self.spin_height.setValue(self.spec.layout.height_in)
        size_form.addRow("Height (in)", self.spin_height)
        layout.addWidget(grp_size)

        # Templates (save/load)
        grp_tpl = QGroupBox("Templates")
        tpl_layout = QHBoxLayout(grp_tpl)
        self.combo_templates = QComboBox()
        self._refresh_template_list()
        tpl_layout.addWidget(self.combo_templates)
        btn_apply_tpl = QPushButton("Apply")
        btn_save_tpl = QPushButton("Save current")
        tpl_layout.addWidget(btn_apply_tpl)
        tpl_layout.addWidget(btn_save_tpl)
        layout.addWidget(grp_tpl)

        layout.addStretch(1)

        self.combo_layout_template.currentIndexChanged.connect(self._on_layout_template_changed)
        self.spin_width.valueChanged.connect(self._on_size_changed_qt)
        self.spin_height.valueChanged.connect(self._on_size_changed_qt)
        btn_apply_tpl.clicked.connect(self._on_apply_template)
        btn_save_tpl.clicked.connect(self._on_save_template)

        return w

    def _build_fonts_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        group = QGroupBox("Fonts")
        form = QFormLayout(group)

        self.edit_font_family = QLineEdit(self.spec.font.family)
        form.addRow("Family", self.edit_font_family)

        self.spin_font_base = QDoubleSpinBox()
        self.spin_font_base.setRange(6.0, 20.0)
        self.spin_font_base.setValue(self.spec.font.base_size)
        form.addRow("Base", self.spin_font_base)

        self.spin_font_axis = QDoubleSpinBox()
        self.spin_font_axis.setRange(6.0, 20.0)
        self.spin_font_axis.setValue(self.spec.font.axis_label_size)
        form.addRow("Axis labels", self.spin_font_axis)

        self.spin_font_tick = QDoubleSpinBox()
        self.spin_font_tick.setRange(6.0, 20.0)
        self.spin_font_tick.setValue(self.spec.font.tick_label_size)
        form.addRow("Tick labels", self.spin_font_tick)

        self.spin_font_legend = QDoubleSpinBox()
        self.spin_font_legend.setRange(6.0, 20.0)
        self.spin_font_legend.setValue(self.spec.font.legend_size)
        form.addRow("Legend", self.spin_font_legend)

        self.combo_font_weight = QComboBox()
        self.combo_font_weight.addItems(["normal", "bold"])
        self.combo_font_weight.setCurrentText(self.spec.font.weight)
        form.addRow("Weight", self.combo_font_weight)

        self.combo_font_style = QComboBox()
        self.combo_font_style.addItems(["normal", "italic", "oblique"])
        self.combo_font_style.setCurrentText(self.spec.font.style)
        form.addRow("Style", self.combo_font_style)

        layout.addWidget(group)
        layout.addStretch(1)

        self.edit_font_family.editingFinished.connect(self._on_font_changed)
        self.spin_font_base.valueChanged.connect(self._on_font_changed)
        self.spin_font_axis.valueChanged.connect(self._on_font_changed)
        self.spin_font_tick.valueChanged.connect(self._on_font_changed)
        self.spin_font_legend.valueChanged.connect(self._on_font_changed)
        self.combo_font_weight.currentTextChanged.connect(self._on_font_changed)
        self.combo_font_style.currentTextChanged.connect(self._on_font_changed)

        return w

    def _build_traces_events_tab(self) -> QWidget:
        """Traces & Events tab – GraphPad-style controls for the active panel."""
        w = QWidget()
        layout = QVBoxLayout(w)

        # Display toggles
        group_display = QGroupBox("Display")
        disp_layout = QVBoxLayout(group_display)
        self.cb_grid = QCheckBox("Grid")
        self.cb_legend = QCheckBox("Legend")
        disp_layout.addWidget(self.cb_grid)
        disp_layout.addWidget(self.cb_legend)
        layout.addWidget(group_display)

        # Spines
        group_spines = QGroupBox("Spines")
        spine_layout = QVBoxLayout(group_spines)
        self.cb_spine_left = QCheckBox("Left")
        self.cb_spine_right = QCheckBox("Right")
        self.cb_spine_top = QCheckBox("Top")
        self.cb_spine_bottom = QCheckBox("Bottom")
        for cb in [
            self.cb_spine_left,
            self.cb_spine_right,
            self.cb_spine_top,
            self.cb_spine_bottom,
        ]:
            spine_layout.addWidget(cb)
        layout.addWidget(group_spines)

        # Ticks
        group_ticks = QGroupBox("Ticks")
        ticks_form = QFormLayout(group_ticks)
        self.edit_x_tick_every = QLineEdit()
        self.edit_x_tick_every.setPlaceholderText("auto")
        ticks_form.addRow("X tick every (s)", self.edit_x_tick_every)

        self.spin_y_max_ticks = QSpinBox()
        self.spin_y_max_ticks.setRange(0, 50)  # 0 = auto
        ticks_form.addRow("Y max ticks", self.spin_y_max_ticks)
        layout.addWidget(group_ticks)

        # Events
        group_events = QGroupBox("Events")
        events_layout = QVBoxLayout(group_events)
        self.cb_show_event_lines = QCheckBox("Show event lines")
        self.cb_show_event_labels = QCheckBox("Show event labels")
        events_layout.addWidget(self.cb_show_event_lines)
        events_layout.addWidget(self.cb_show_event_labels)

        style_form = QFormLayout()
        self.edit_event_color = QLineEdit()
        self.edit_event_color.setPlaceholderText("#888888 or named color")
        self.spin_event_lw = QDoubleSpinBox()
        self.spin_event_lw.setRange(0.1, 5.0)
        self.spin_event_lw.setSingleStep(0.1)
        self.combo_event_ls = QComboBox()
        self.combo_event_ls.addItems(["--", "-", ":", "-."])
        style_form.addRow("Color", self.edit_event_color)
        style_form.addRow("Line width", self.spin_event_lw)
        style_form.addRow("Line style", self.combo_event_ls)
        events_layout.addLayout(style_form)

        if self.event_times:
            label_form = QFormLayout()
            self.spin_event_index = QSpinBox()
            self.spin_event_index.setRange(0, max(len(self.event_times) - 1, 0))
            self.edit_event_label = QLineEdit()
            label_form.addRow("Event index", self.spin_event_index)
            label_form.addRow("Label", self.edit_event_label)
            events_layout.addLayout(label_form)

        layout.addWidget(group_events)

        # Traces
        group_traces = QGroupBox("Traces")
        traces_layout = QVBoxLayout(group_traces)
        self.cb_trace_inner = QCheckBox("Inner diameter")
        self.cb_trace_outer = QCheckBox("Outer diameter")
        self.cb_trace_avg_pressure = QCheckBox("Avg pressure")
        self.cb_trace_set_pressure = QCheckBox("Set pressure")
        self.cb_twin_y = QCheckBox("Twin Y (first two traces)")
        self.edit_y2_label = QLineEdit()
        self.edit_y2_label.setPlaceholderText("Right Y label")

        for cb in [
            self.cb_trace_inner,
            self.cb_trace_outer,
            self.cb_trace_avg_pressure,
            self.cb_trace_set_pressure,
            self.cb_twin_y,
        ]:
            traces_layout.addWidget(cb)
        traces_layout.addWidget(self.edit_y2_label)

        # Trace style editor
        style_group = QGroupBox("Trace style")
        style_form = QFormLayout(style_group)
        self.combo_trace_select = QComboBox()
        self.edit_trace_color = QLineEdit()
        self.spin_trace_lw = QDoubleSpinBox()
        self.spin_trace_lw.setRange(0.1, 5.0)
        self.spin_trace_lw.setSingleStep(0.1)
        self.combo_trace_ls = QComboBox()
        self.combo_trace_ls.addItems(["solid", "dashed", "dotted", "dashdot"])
        self.combo_trace_marker = QComboBox()
        self.combo_trace_marker.addItems(["(none)", "o", "s", "^", "x"])

        style_form.addRow("Trace", self.combo_trace_select)
        style_form.addRow("Color", self.edit_trace_color)
        style_form.addRow("Line width", self.spin_trace_lw)
        style_form.addRow("Line style", self.combo_trace_ls)
        style_form.addRow("Marker", self.combo_trace_marker)

        traces_layout.addWidget(style_group)
        layout.addWidget(group_traces)

        layout.addStretch(1)

        self._connect_traces_events_signals()
        self._refresh_traces_events_tab()

        return w

    def _build_annotation_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.annotation_info = QLabel("Select an annotation to edit.")
        layout.addWidget(self.annotation_info)

        self.spin_annot_font = QDoubleSpinBox()
        self.spin_annot_font.setRange(6.0, 32.0)
        self.spin_annot_font.valueChanged.connect(self._on_annotation_spin_changed)
        form = QFormLayout()
        form.addRow("Font size", self.spin_annot_font)
        layout.addLayout(form)
        layout.addStretch(1)
        return w

    def _build_export_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        grp_export = QGroupBox("Export")
        form = QFormLayout(grp_export)
        self.combo_format = QComboBox()
        self.combo_format.addItems(["pdf", "svg", "png", "tiff"])
        self.combo_format.setCurrentText(self.spec.export.format)
        form.addRow("Format", self.combo_format)

        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 1200)
        self.spin_dpi.setValue(self.spec.export.dpi)
        form.addRow("DPI", self.spin_dpi)
        layout.addWidget(grp_export)

        grp_presets = QGroupBox("Width presets (mm)")
        h = QHBoxLayout(grp_presets)
        for mm in (85, 120, 180, 260):
            btn = QPushButton(f"{mm} mm")
            btn.clicked.connect(lambda _, v=mm: self._on_width_preset_mm(v))
            h.addWidget(btn)
        layout.addWidget(grp_presets)

        button_row = QHBoxLayout()
        self.btn_save_fig = QPushButton("Save Fig (spec)")
        self.btn_load_fig = QPushButton("Load Fig (spec)")
        self.btn_export_fig = QPushButton("Export file")
        button_row.addWidget(self.btn_save_fig)
        button_row.addWidget(self.btn_load_fig)
        button_row.addWidget(self.btn_export_fig)
        layout.addLayout(button_row)
        layout.addStretch(1)

        self.combo_format.currentTextChanged.connect(self._on_export_format_changed)
        self.spin_dpi.valueChanged.connect(self._on_export_dpi_changed)
        self.btn_save_fig.clicked.connect(self._on_save_spec)
        self.btn_load_fig.clicked.connect(self._on_load_spec)
        self.btn_export_fig.clicked.connect(self.export_figure)

        return w

    def _refresh_template_list(self):
        templates = list_templates()
        if hasattr(self, "combo_templates"):
            self.combo_templates.clear()
            if templates:
                self.combo_templates.addItems(templates)

    # ------------------------------------------------------------------
    # Tab callbacks
    # ------------------------------------------------------------------
    def _on_layout_template_changed(self, idx: int):
        label = self.combo_layout_template.currentText()
        layouts = {
            "1 panel": (1, 1),
            "2 horizontal": (1, 2),
            "2 vertical": (2, 1),
            "2 x 2": (2, 2),
        }
        nrows, ncols = layouts.get(label, (1, 1))
        self.spec.layout.nrows = nrows
        self.spec.layout.ncols = ncols
        instances = []
        graph_ids = list(self.spec.graphs.keys())
        idx_counter = 0
        for r in range(nrows):
            for c in range(ncols):
                graph_id = graph_ids[idx_counter % len(graph_ids)] if graph_ids else "graph1"
                instances.append(
                    GraphInstance(
                        instance_id=f"inst_{r}_{c}",
                        graph_id=graph_id,
                        row=r,
                        col=c,
                    )
                )
                idx_counter += 1
        self.spec.layout.graph_instances = instances
        if nrows > 1:
            self.spec.layout.height_in = self.spec.layout.width_in * 0.5 * nrows
            self.spin_height.setValue(self.spec.layout.height_in)
        self._push_undo()
        self._update_preview()

    def _on_size_changed_qt(self, _):
        self.spec.layout.width_in = float(self.spin_width.value())
        self.spec.layout.height_in = float(self.spin_height.value())
        self._push_undo()
        self._update_preview()
        self._update_footer()

    def _on_apply_template(self):
        name = self.combo_templates.currentText()
        if not name:
            return
        try:
            tmpl = load_template(name)
            apply_template_structure(self.spec, tmpl)
            self._push_undo()
            self._refresh_tabs()
            self._update_preview()
        except Exception as exc:
            QMessageBox.critical(self, "Template Error", f"Failed to apply template:\n{exc}")

    def _on_save_template(self):
        name, _ = QFileDialog.getSaveFileName(
            self,
            "Save Template As",
            "template",
            "JSON files (*.json);;All Files (*)",
            "JSON files (*.json)",
        )
        if not name:
            return
        try:
            save_template(Path(name).stem, self.spec)
            self._refresh_template_list()
            QMessageBox.information(self, "Template Saved", f"Saved template:\n{name}")
        except Exception as exc:
            QMessageBox.critical(self, "Template Error", f"Failed to save template:\n{exc}")

    def _on_font_changed(self, *_):
        f = self.spec.font
        f.family = self.edit_font_family.text().strip() or f.family
        f.base_size = float(self.spin_font_base.value())
        f.axis_label_size = float(self.spin_font_axis.value())
        f.tick_label_size = float(self.spin_font_tick.value())
        f.legend_size = float(self.spin_font_legend.value())
        f.weight = self.combo_font_weight.currentText()
        f.style = self.combo_font_style.currentText()
        self._push_undo()
        self._update_preview()

    # ------------------------------------------------------------------
    # Traces & Events tab helpers
    # ------------------------------------------------------------------
    def _connect_traces_events_signals(self):
        # Display
        self.cb_grid.toggled.connect(self._on_grid_toggled)
        self.cb_legend.toggled.connect(self._on_legend_toggled)

        # Spines
        self.cb_spine_left.toggled.connect(lambda v: self._on_spine_toggled("left", v))
        self.cb_spine_right.toggled.connect(lambda v: self._on_spine_toggled("right", v))
        self.cb_spine_top.toggled.connect(lambda v: self._on_spine_toggled("top", v))
        self.cb_spine_bottom.toggled.connect(lambda v: self._on_spine_toggled("bottom", v))

        # Ticks
        self.edit_x_tick_every.editingFinished.connect(self._on_x_tick_every_changed)
        self.spin_y_max_ticks.valueChanged.connect(self._on_y_max_ticks_changed)

        # Events
        self.cb_show_event_lines.toggled.connect(self._on_show_event_lines_toggled)
        self.cb_show_event_labels.toggled.connect(self._on_show_event_labels_toggled)
        self.edit_event_color.editingFinished.connect(self._on_event_style_changed)
        self.spin_event_lw.valueChanged.connect(self._on_event_style_changed)
        self.combo_event_ls.currentTextChanged.connect(self._on_event_style_changed)
        if self.event_times:
            self.spin_event_index.valueChanged.connect(self._on_event_index_changed)
            self.edit_event_label.editingFinished.connect(self._on_event_label_changed)

        # Traces
        self.cb_trace_inner.toggled.connect(lambda v: self._on_trace_toggle("inner", v))
        self.cb_trace_outer.toggled.connect(lambda v: self._on_trace_toggle("outer", v))
        self.cb_trace_avg_pressure.toggled.connect(lambda v: self._on_trace_toggle("avg_pressure", v))
        self.cb_trace_set_pressure.toggled.connect(lambda v: self._on_trace_toggle("set_pressure", v))
        self.cb_twin_y.toggled.connect(self._on_twin_y_toggled)
        self.edit_y2_label.editingFinished.connect(self._on_y2_label_changed)

        # Trace styles
        self.combo_trace_select.currentTextChanged.connect(self._on_trace_style_target_changed)
        self.edit_trace_color.editingFinished.connect(self._on_trace_style_changed)
        self.spin_trace_lw.valueChanged.connect(self._on_trace_style_changed)
        self.combo_trace_ls.currentTextChanged.connect(self._on_trace_style_changed)
        self.combo_trace_marker.currentTextChanged.connect(self._on_trace_style_changed)

    def _with_graph_spec(self) -> GraphSpec | None:
        graph = self._get_active_graph_spec()
        return graph

    def _refresh_traces_events_tab(self):
        graph = self._with_graph_spec()
        if not graph:
            return

        widgets = [
            self.cb_grid,
            self.cb_legend,
            self.cb_spine_left,
            self.cb_spine_right,
            self.cb_spine_top,
            self.cb_spine_bottom,
            self.edit_x_tick_every,
            self.spin_y_max_ticks,
            self.cb_show_event_lines,
            self.cb_show_event_labels,
            self.edit_event_color,
            self.spin_event_lw,
            self.combo_event_ls,
            self.cb_trace_inner,
            self.cb_trace_outer,
            self.cb_trace_avg_pressure,
            self.cb_trace_set_pressure,
            self.cb_twin_y,
            self.edit_y2_label,
            self.combo_trace_select,
            self.edit_trace_color,
            self.spin_trace_lw,
            self.combo_trace_ls,
            self.combo_trace_marker,
        ]
        if self.event_times:
            widgets.extend([self.spin_event_index, self.edit_event_label])
        for w in widgets:
            w.blockSignals(True)

        # Display
        self.cb_grid.setChecked(graph.grid)
        self.cb_legend.setChecked(graph.show_legend)

        # Spines
        self.cb_spine_left.setChecked(graph.show_spines.get("left", True))
        self.cb_spine_right.setChecked(graph.show_spines.get("right", True))
        self.cb_spine_top.setChecked(graph.show_spines.get("top", False))
        self.cb_spine_bottom.setChecked(graph.show_spines.get("bottom", True))

        # Ticks
        self.edit_x_tick_every.setText("" if graph.x_tick_interval is None else str(graph.x_tick_interval))
        self.spin_y_max_ticks.setValue(0 if graph.y_max_ticks is None else graph.y_max_ticks)

        # Events
        self.cb_show_event_lines.setChecked(graph.show_event_markers)
        self.cb_show_event_labels.setChecked(graph.show_event_labels)
        self.edit_event_color.setText(graph.event_line_color)
        self.spin_event_lw.setValue(graph.event_line_width)
        idx = self.combo_event_ls.findText(graph.event_line_style)
        if idx >= 0:
            self.combo_event_ls.setCurrentIndex(idx)
        if self.event_times:
            max_idx = max(len(self.event_times) - 1, 0)
            self.spin_event_index.setMaximum(max_idx)
            current_idx = min(self._current_event_index, max_idx)
            self.spin_event_index.setValue(current_idx)
            if hasattr(self, "edit_event_label"):
                label = ""
                if 0 <= current_idx < len(self.event_labels):
                    label = self.event_labels[current_idx]
                self.edit_event_label.setText(label)

        # Traces
        kinds = {tb.kind for tb in graph.trace_bindings}
        available = self._available_trace_bindings()
        available_kinds = {b.kind for b in available}
        self.cb_trace_inner.setEnabled("inner" in available_kinds)
        self.cb_trace_outer.setEnabled("outer" in available_kinds)
        self.cb_trace_avg_pressure.setEnabled("avg_pressure" in available_kinds)
        self.cb_trace_set_pressure.setEnabled("set_pressure" in available_kinds)

        self.cb_trace_inner.setChecked("inner" in kinds)
        self.cb_trace_outer.setChecked("outer" in kinds)
        self.cb_trace_avg_pressure.setChecked("avg_pressure" in kinds)
        self.cb_trace_set_pressure.setChecked("set_pressure" in kinds)
        self.cb_twin_y.setChecked(graph.twin_y)
        self.edit_y2_label.setText(graph.y2_label)

        self._refresh_trace_style_selector(graph)

        for w in widgets:
            w.blockSignals(False)

    def _on_grid_toggled(self, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.grid = checked
        self._push_undo()
        self._update_preview()

    def _on_legend_toggled(self, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.show_legend = checked
        self._push_undo()
        self._update_preview()

    def _on_spine_toggled(self, spine: str, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.show_spines[spine] = checked
        self._push_undo()
        self._update_preview()

    def _on_x_tick_every_changed(self):
        graph = self._with_graph_spec()
        if not graph:
            return
        text = self.edit_x_tick_every.text().strip()
        if not text:
            graph.x_tick_interval = None
        else:
            try:
                graph.x_tick_interval = float(text)
            except ValueError:
                return
        self._push_undo()
        self._update_preview()

    def _on_y_max_ticks_changed(self, value: int):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.y_max_ticks = None if value == 0 else int(value)
        self._push_undo()
        self._update_preview()

    def _on_show_event_lines_toggled(self, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.show_event_markers = checked
        self._push_undo()
        self._update_preview()

    def _on_show_event_labels_toggled(self, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.show_event_labels = checked
        self._push_undo()
        self._update_preview()

    def _on_event_style_changed(self, *_):
        graph = self._with_graph_spec()
        if not graph:
            return
        color = self.edit_event_color.text().strip()
        if color:
            graph.event_line_color = color
        graph.event_line_width = float(self.spin_event_lw.value())
        graph.event_line_style = self.combo_event_ls.currentText()
        self._push_undo()
        self._update_preview()

    def _on_event_index_changed(self, idx: int):
        self._current_event_index = idx
        if self.event_labels and 0 <= idx < len(self.event_labels):
            self.edit_event_label.setText(self.event_labels[idx])

    def _on_event_label_changed(self):
        idx = getattr(self, "spin_event_index", None)
        if idx is None:
            return
        idx_val = self.spin_event_index.value()
        if not self.event_labels or not (0 <= idx_val < len(self.event_labels)):
            return
        self.event_labels[idx_val] = self.edit_event_label.text().strip()
        self._update_preview()

    def _on_trace_toggle(self, kind: str, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        # maintain consistent order
        order = ["inner", "outer", "avg_pressure", "set_pressure"]
        existing = {tb.kind: tb for tb in graph.trace_bindings}
        bindings: list[TraceBinding] = []
        for k in order:
            if k == kind:
                if checked:
                    name_map = {
                        "inner": "Inner diameter",
                        "outer": "Outer diameter",
                        "avg_pressure": "Avg pressure",
                        "set_pressure": "Set pressure",
                    }
                    bindings.append(TraceBinding(name=name_map[k], kind=k))
            elif k in existing:
                bindings.append(existing[k])
        graph.trace_bindings = bindings
        self._refresh_trace_style_selector(graph)
        self._push_undo()
        self._update_preview()

    def _on_twin_y_toggled(self, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.twin_y = checked
        self._push_undo()
        self._update_preview()

    def _on_y2_label_changed(self):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.y2_label = self.edit_y2_label.text()
        self._push_undo()
        self._update_preview()

    def _refresh_trace_style_selector(self, graph: GraphSpec | None = None):
        if graph is None:
            graph = self._with_graph_spec()
        if not graph:
            return
        self.combo_trace_select.blockSignals(True)
        self.combo_trace_select.clear()
        for tb in graph.trace_bindings:
            self.combo_trace_select.addItem(tb.name, tb.name)
        self.combo_trace_select.blockSignals(False)
        self._load_trace_style_from_spec()

    def _on_trace_style_target_changed(self, _):
        self._load_trace_style_from_spec()

    def _load_trace_style_from_spec(self):
        graph = self._with_graph_spec()
        if not graph:
            return
        name = self.combo_trace_select.currentData()
        if not name:
            return
        style = graph.trace_styles.get(name, {})
        self.edit_trace_color.blockSignals(True)
        self.spin_trace_lw.blockSignals(True)
        self.combo_trace_ls.blockSignals(True)
        self.combo_trace_marker.blockSignals(True)

        self.edit_trace_color.setText(style.get("color", ""))
        self.spin_trace_lw.setValue(style.get("linewidth", graph.default_linewidth))
        ls_map_inv = {"-": "solid", "--": "dashed", ":": "dotted", "-.": "dashdot"}
        self.combo_trace_ls.setCurrentText(ls_map_inv.get(style.get("linestyle", "-"), "solid"))
        marker = style.get("marker", "")
        self.combo_trace_marker.setCurrentText(marker if marker else "(none)")

        self.edit_trace_color.blockSignals(False)
        self.spin_trace_lw.blockSignals(False)
        self.combo_trace_ls.blockSignals(False)
        self.combo_trace_marker.blockSignals(False)

    def _on_trace_style_changed(self, *_):
        graph = self._with_graph_spec()
        if not graph:
            return
        name = self.combo_trace_select.currentData()
        if not name:
            return
        style = graph.trace_styles.setdefault(name, {})
        color = self.edit_trace_color.text().strip()
        if color:
            style["color"] = color
        style["linewidth"] = float(self.spin_trace_lw.value())
        ls_map = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-."}
        style["linestyle"] = ls_map.get(self.combo_trace_ls.currentText(), "-")
        marker = self.combo_trace_marker.currentText()
        style["marker"] = "" if marker == "(none)" else marker
        self._push_undo()
        self._update_preview()

    def _on_annotation_spin_changed(self, val: float):
        if self.selected_annotation_id is None:
            return
        for annot in self.spec.annotations:
            if annot.annotation_id == self.selected_annotation_id:
                annot.font_size = float(val)
                break
        self._push_undo()
        self._update_preview()

    def _on_export_format_changed(self, fmt: str):
        self.spec.export.format = fmt

    def _on_export_dpi_changed(self, dpi: int):
        self.spec.export.dpi = int(dpi)

    def _on_width_preset_mm(self, mm: int):
        inches = mm / 25.4
        self.spec.layout.width_in = inches
        self.spec.layout.height_in = max(self.spec.layout.height_in, 1.0)
        if hasattr(self, "spin_width"):
            self.spin_width.setValue(inches)
        self._push_undo()
        self._update_preview()

    def _refresh_tabs(self):
        """Sync Qt controls with current spec."""
        if hasattr(self, "spin_width"):
            self.spin_width.setValue(self.spec.layout.width_in)
        if hasattr(self, "spin_height"):
            self.spin_height.setValue(self.spec.layout.height_in)
        if hasattr(self, "combo_layout_template"):
            layout_key = (self.spec.layout.nrows, self.spec.layout.ncols)
            mapping = {(1, 1): 0, (1, 2): 1, (2, 1): 2, (2, 2): 3}
            if layout_key in mapping:
                self.combo_layout_template.setCurrentIndex(mapping[layout_key])
        if hasattr(self, "edit_font_family"):
            f = self.spec.font
            self.edit_font_family.setText(f.family)
            self.spin_font_base.setValue(f.base_size)
            self.spin_font_axis.setValue(f.axis_label_size)
            self.spin_font_tick.setValue(f.tick_label_size)
            self.spin_font_legend.setValue(f.legend_size)
            self.combo_font_weight.setCurrentText(f.weight)
            self.combo_font_style.setCurrentText(f.style)
        self._refresh_traces_events_tab()
        if hasattr(self, "combo_format"):
            self.combo_format.setCurrentText(self.spec.export.format)
            self.spin_dpi.setValue(self.spec.export.dpi)

    def _refresh_annotation_controls(self):
        """Sync annotation tab widgets with current selection."""
        if not hasattr(self, "annotation_info"):
            return
        if self.selected_annotation_id is None:
            self.annotation_info.setText("Select an annotation to edit.")
            self.spin_annot_font.setEnabled(False)
            return

        annot = next(
            (a for a in self.spec.annotations if a.annotation_id == self.selected_annotation_id),
            None,
        )
        if annot is None:
            self.annotation_info.setText("Annotation missing.")
            self.spin_annot_font.setEnabled(False)
            return

        self.annotation_info.setText(f"Editing {annot.kind} annotation")
        self.spin_annot_font.setEnabled(True)
        self.spin_annot_font.setValue(annot.font_size)

    def _build_title(self):
        """Title/header bar."""
        self.ax_title.clear()
        self.ax_title.set_facecolor(THEME["bg_window"])
        self.ax_title.set_xlim(0, 1)
        self.ax_title.set_ylim(0, 1)
        self.ax_title.axis("off")
        self.ax_title.text(
            0.0,
            0.55,
            "Pure Matplotlib Figure Composer",
            fontsize=14,
            weight="bold",
            color=THEME["text_primary"],
            va="center",
        )
        self.ax_title.text(
            0.0,
            0.22,
            "Preview = Export • Spec-driven layout",
            fontsize=10,
            color=THEME["text_secondary"],
            va="center",
        )


    def _active_graph(self) -> GraphSpec | None:
        if self.spec.graphs:
            return next(iter(self.spec.graphs.values()))
        return None

    def _get_active_graph_spec(self) -> GraphSpec | None:
        """Return GraphSpec for selected instance (or first)."""
        inst = None
        if getattr(self, "selected_annotation_id", None):
            # Selection currently not tied to instances; fallback to first
            pass
        if inst is None and self.spec.layout.graph_instances:
            inst = self.spec.layout.graph_instances[0]
        if inst is None:
            return next(iter(self.spec.graphs.values()), None)
        return self.spec.graphs.get(inst.graph_id)

    def _available_trace_bindings(self) -> list[TraceBinding]:
        bindings: list[TraceBinding] = []
        tm = self.trace_model
        if tm is None:
            return bindings
        if getattr(tm, "inner_full", None) is not None:
            bindings.append(TraceBinding(name="inner", kind="inner"))
        if getattr(tm, "outer_full", None) is not None:
            bindings.append(TraceBinding(name="outer", kind="outer"))
        if getattr(tm, "avg_pressure_full", None) is not None:
            bindings.append(TraceBinding(name="avg_pressure", kind="avg_pressure"))
        if getattr(tm, "set_pressure_full", None) is not None:
            bindings.append(TraceBinding(name="set_pressure", kind="set_pressure"))
        return bindings

    def _update_graph_property(self, graph: GraphSpec, prop: str, value):
        setattr(graph, prop, value)
        self._push_undo()
        self._update_preview()

    def _set_trace_style(self, graph: GraphSpec, key: str, value):
        if self._current_trace_name is None:
            return
        style = graph.trace_styles.setdefault(self._current_trace_name, {})
        style[key] = value
        self._push_undo()
        self._update_preview()

    def _update_annotation_property(self, prop, value):
        """Update a property of the selected annotation."""
        if self.selected_annotation_id is None:
            return

        for annot in self.spec.annotations:
            if annot.annotation_id == self.selected_annotation_id:
                setattr(annot, prop, value)
                self._update_preview()
                break

    def _update_export_property(self, prop, value):
        """Update an export spec property."""
        setattr(self.spec.export, prop, value)
        self._update_footer()
        self.canvas.draw_idle()

    def _build_footer(self):
        """No-op placeholder for legacy; status handled by QLabel."""
        self._update_footer()

    def _update_footer(self):
        """Update footer status."""
        w_mm = self.spec.layout.width_in * 25.4
        h_mm = self.spec.layout.height_in * 25.4
        dpi = self.spec.export.dpi
        w_px = int(self.spec.layout.width_in * dpi)
        h_px = int(self.spec.layout.height_in * dpi)
        n_annot = len(self.spec.annotations)

        mode_str = f"Mode: {self.annotation_mode or 'None'}"
        status = (
            f"{mode_str} │ "
            f"Size: {w_mm:.0f}×{h_mm:.0f} mm ({self.spec.layout.width_in:.2f}×{self.spec.layout.height_in:.2f} in) │ "
            f"Export: {w_px}×{h_px} px @ {dpi} dpi │ "
            f"Annotations: {n_annot}"
        )
        if hasattr(self, "status_label"):
            self.status_label.setText(status)

    def _connect_events(self):
        """Connect Matplotlib events."""
        self.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_motion)
        self.canvas.mpl_connect("key_press_event", self._on_key_press)

    def _event_in_preview(self, event) -> bool:
        """Return True if event occurred inside the preview/page bbox."""
        bbox = self.preview_ax.get_window_extent()
        return bbox.contains(event.x, event.y)

    def _event_to_page_fraction(self, event) -> tuple[float, float]:
        """Convert an event position to page-relative 0-1 coordinates."""
        inv = self.preview_ax.transData.inverted()
        x_page, y_page = inv.transform((event.x, event.y))
        width = max(self.preview_ax.get_xlim()[1] - self.preview_ax.get_xlim()[0], 1e-6)
        height = max(self.preview_ax.get_ylim()[1] - self.preview_ax.get_ylim()[0], 1e-6)
        return x_page / width, y_page / height

    def _on_mouse_press(self, event):
        """Handle mouse press for annotation creation/selection."""
        if not self._event_in_preview(event):
            return

        x_norm, y_norm = self._event_to_page_fraction(event)

        if self.annotation_mode == "select":
            # TODO: Implement selection by checking proximity to annotations
            self.selected_annotation_id = None
            self._refresh_annotation_controls()
        elif self.annotation_mode == "text":
            # Create text annotation at click point
            f = self.spec.font
            annot = AnnotationSpec(
                annotation_id=str(uuid.uuid4()),
                kind="text",
                target_type="figure",
                coord_system="axes",
                x0=x_norm,
                y0=y_norm,
                text_content="Text",
                font_size=f.annotation_size,
                font_weight=f.weight,
                font_style=f.style,
            )
            self.spec.annotations.append(annot)
            self.selected_annotation_id = annot.annotation_id
            self._push_undo()
            self._update_preview()
            self._refresh_annotation_controls()
        elif self.annotation_mode in ("box", "arrow", "line"):
            # Start creating box/arrow/line
            self._drag_start = (x_norm, y_norm)
            self._creating_annotation = AnnotationSpec(
                annotation_id=str(uuid.uuid4()),
                kind=self.annotation_mode,
                target_type="figure",
                coord_system="axes",
                x0=x_norm,
                y0=y_norm,
                x1=x_norm,
                y1=y_norm,
            )

    def _on_mouse_release(self, event):
        """Handle mouse release to finalize annotation creation."""
        if self._creating_annotation is not None:
            # Finalize the annotation
            self.spec.annotations.append(self._creating_annotation)
            self.selected_annotation_id = self._creating_annotation.annotation_id
            self._creating_annotation = None
            self._drag_start = None
            self._push_undo()
            self._update_preview()
            self._refresh_annotation_controls()

    def _on_mouse_motion(self, event):
        """Handle mouse motion for drag operations."""
        if not self._event_in_preview(event):
            return

        if self._creating_annotation is not None and self._drag_start is not None:
            # Update end point of creating annotation
            x_norm, y_norm = self._event_to_page_fraction(event)
            self._creating_annotation.x1 = x_norm
            self._creating_annotation.y1 = y_norm
            # Show preview (would need temp render)

    def _on_key_press(self, event):
        """Handle keyboard shortcuts."""
        if event.key == "delete":
            self._delete_selected_annotation()
        elif event.key == "ctrl+z":
            self._undo()
        elif event.key == "ctrl+y" or event.key == "ctrl+shift+z":
            self._redo()

    def _update_preview(self):
        """Re-render preview from spec."""
        try:
            # Remove previously created graph axes from prior renders
            for ax in self._preview_axes_map.values():
                try:
                    ax.remove()
                except ValueError:
                    pass
            self._preview_axes_map = {}

            self.preview_ax.set_facecolor(PAGE_BG_COLOR)
            self.preview_ax.set_xlim(0, self.spec.layout.width_in)
            self.preview_ax.set_ylim(0, self.spec.layout.height_in)
            self.preview_ax.set_box_aspect(
                max(self.spec.layout.height_in / max(self.spec.layout.width_in, 1e-6), 0.01)
            )
            for spine in self.preview_ax.spines.values():
                spine.set_visible(False)
            self.preview_ax.set_xticks([])
            self.preview_ax.set_yticks([])
            self.preview_ax.tick_params(left=False, labelleft=False, bottom=False, labelbottom=False)
            self.preview_ax.set_frame_on(False)

            if self.trace_model is None:
                self.preview_ax.text(
                    0.5,
                    0.5,
                    "No trace model loaded",
                    ha="center",
                    va="center",
                    fontsize=12,
                    color="#999999",
                )
                self._update_footer()
                self.canvas.draw_idle()
                return

            def trace_provider(sample_id: str):
                return self.trace_model

            self._preview_axes_map = render_into_axes(
                self.preview_ax,
                self.spec,
                trace_provider,
                event_times=self.event_times,
                event_labels=self.event_labels,
                event_colors=self.event_colors,
            )

            self._update_footer()
            self.canvas.draw_idle()

        except Exception as e:
            log.error(f"Preview error: {e}", exc_info=True)
            self.preview_ax.text(
                0.5, 0.5, f"Error:\n{str(e)[:100]}",
                ha="center", va="center", fontsize=10, color="#cc0000"
            )
            self.canvas.draw_idle()

    def _delete_selected_annotation(self):
        """Delete selected annotation."""
        if self.selected_annotation_id is None:
            return

        self.spec.annotations = [
            a for a in self.spec.annotations
            if a.annotation_id != self.selected_annotation_id
        ]
        self.selected_annotation_id = None
        self._push_undo()
        self._update_preview()
        self._refresh_annotation_controls()

    def _push_undo(self):
        """Push current spec to undo stack."""
        spec_copy = copy.deepcopy(self.spec)
        self._undo_stack.append(spec_copy)
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        """Undo last action."""
        if len(self._undo_stack) < 2:
            return

        current = self._undo_stack.pop()
        self._redo_stack.append(current)
        self.spec = copy.deepcopy(self._undo_stack[-1])
        self._update_preview()
        self._refresh_annotation_controls()

    def _redo(self):
        """Redo last undone action."""
        if not self._redo_stack:
            return

        self.spec = copy.deepcopy(self._redo_stack.pop())
        self._undo_stack.append(copy.deepcopy(self.spec))
        self._update_preview()
        self._refresh_annotation_controls()

    def export_figure(self):
        """Export figure at target DPI."""
        format_filters = {
            "pdf": "PDF (*.pdf)",
            "svg": "SVG (*.svg)",
            "png": "PNG (*.png)",
            "tiff": "TIFF (*.tiff *.tif)",
        }

        current_format = self.spec.export.format
        filter_str = ";;".join(format_filters.values())
        initial_filter = format_filters.get(current_format, format_filters["pdf"])

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Figure",
            f"figure.{current_format}",
            filter_str,
            initial_filter,
        )

        if not file_path:
            return

        try:
            def trace_provider(sample_id: str):
                return self.trace_model

            export_fig = render_figure(
                self.spec,
                trace_provider,
                dpi=self.spec.export.dpi,
                event_times=self.event_times,
                event_labels=self.event_labels,
                event_colors=self.event_colors,
            )

            export_fig.savefig(
                file_path,
                format=self.spec.export.format,
                dpi=self.spec.export.dpi if self.spec.export.format in ("png", "tiff") else None,
                bbox_inches="tight",
                transparent=self.spec.export.transparent,
            )

            plt.close(export_fig)

            QMessageBox.information(
                self,
                "Export Complete",
                f"Figure exported to:\n{file_path}",
            )
            log.info(f"Exported: {file_path}")

        except Exception as e:
            log.error(f"Export failed: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export:\n{str(e)}",
            )

    def _on_save_spec(self, event=None):
        """Save current FigureSpec to disk."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Figure Definition",
            "figure.json",
            "JSON files (*.json);;All Files (*)",
            "JSON files (*.json)",
        )
        if not file_path:
            return
        try:
            save_figure_spec(file_path, self.spec)
            QMessageBox.information(self, "Figure Saved", f"Saved to:\n{file_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Failed to save:\n{exc}")

    def _on_load_spec(self, event=None):
        """Load FigureSpec from disk."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Figure Definition",
            "",
            "JSON files (*.json);;All Files (*)",
            "JSON files (*.json)",
        )
        if not file_path:
            return
        try:
            spec = load_figure_spec(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load:\n{exc}")
            return

        self.spec = spec
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._refresh_tabs()
        self._update_preview()
        QMessageBox.information(self, "Figure Loaded", f"Loaded:\n{file_path}")
