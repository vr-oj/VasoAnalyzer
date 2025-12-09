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
from typing import TYPE_CHECKING, Any
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.artist import Artist
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .renderer import create_annotation_artists, render_figure, render_into_axes
from .spec_io import (
    apply_template_structure,
    list_templates,
    load_figure_spec,
    load_dataset_figure_spec,
    load_template,
    save_figure_spec,
    save_dataset_figure_spec,
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


class ComposerNavigationToolbar(NavigationToolbar):
    """Navigation toolbar limited to core pan/zoom actions."""

    toolitems = [
        t
        for t in NavigationToolbar.toolitems
        if t[0] in ("Home", "Back", "Forward", "Pan", "Zoom")
    ]

    def __init__(self, canvas, parent, on_view_changed=None):
        super().__init__(canvas, parent)
        self._on_view_changed = on_view_changed

    def _notify_view_changed(self):
        if self._on_view_changed is not None:
            try:
                self._on_view_changed()
            except Exception:
                pass

    def release_zoom(self, event):
        super().release_zoom(event)
        self._notify_view_changed()

    def release_pan(self, event):
        super().release_pan(event)
        self._notify_view_changed()

    def home(self, *args, **kwargs):
        super().home(*args, **kwargs)
        self._notify_view_changed()

    def back(self, *args, **kwargs):
        super().back(*args, **kwargs)
        self._notify_view_changed()

    def forward(self, *args, **kwargs):
        super().forward(*args, **kwargs)
        self._notify_view_changed()


class PureMplFigureComposer(QMainWindow):
    """Pure Matplotlib Figure Composer window with full annotation support."""

    def __init__(
        self,
        trace_model: TraceModel | None = None,
        parent=None,
        *,
        project=None,
        dataset_id: Any | None = None,
        event_times: list[float] | None = None,
        event_labels: list[str] | None = None,
        event_colors: list[str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Pure Matplotlib Figure Composer")
        self.trace_model = trace_model
        self.project = project
        self.dataset_id = dataset_id
        self.event_times = event_times or []
        self.event_labels = event_labels or []
        self.event_colors = event_colors or []

        # Typography baseline
        mpl.rcParams["font.family"] = "Arial"
        mpl.rcParams["font.size"] = 9

        # Undo/redo stacks
        self._undo_stack: list[FigureSpec] = []
        self._redo_stack: list[FigureSpec] = []
        self._max_undo = 50

        # Current spec (single source of truth)
        self.spec = self._create_default_spec()
        self._aspect_ratio = self.spec.layout.height_in / max(
            self.spec.layout.width_in, 1e-6
        )

        # Preview settings
        self.preview_dpi = 100
        self.zoom_factor = 1.0

        # Annotation interaction state
        self.annotation_mode: str | None = "select"
        self.selected_annotation_id: str | None = None
        self._annotation_artists: dict[str, list[Artist]] = {}
        self._dragging_annotation_id: str | None = None
        self._dragging_mode: str | None = None
        self._drag_start_data: Any = None
        self._preview_axes_map: dict[str, Axes] = {}
        self._axes_instance_lookup: dict[Axes, str] = {}
        self._suppress_size_events = False
        self._current_event_index: int = 0
        self._current_trace_name: str | None = None
        self.selected_instance_id: str | None = (
            self.spec.layout.graph_instances[0].instance_id
            if self.spec.layout.graph_instances
            else None
        )
        self.spec.metadata.setdefault("extra_export_png", False)
        self.spec.metadata.setdefault("extra_export_tiff", False)
        self._lock_aspect_ratio = False
        self._applying_style_preset = False

        # UI widget references
        self.control_widgets: dict[str, any] = {}

        # Build UI
        self._setup_ui()
        self._connect_toolbar_signals()
        self._connect_events()
        self._init_spec_from_dataset()
        self._refresh_tabs()

        # Initial render
        self._push_undo()
        self._update_preview()
        self._resize_to_available_screen()

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

    def _init_spec_from_dataset(self) -> None:
        """Load a saved FigureSpec for the active dataset if available."""
        if self.project is None or self.dataset_id is None:
            return
        loaded = load_dataset_figure_spec(self.project, self.dataset_id)
        if loaded is None:
            return
        self.spec = loaded
        self.spec.metadata.setdefault("extra_export_png", False)
        self.spec.metadata.setdefault("extra_export_tiff", False)
        self._aspect_ratio = self.spec.layout.height_in / max(
            self.spec.layout.width_in, 1e-6
        )
        if self.spec.layout.graph_instances:
            self.selected_instance_id = self.spec.layout.graph_instances[0].instance_id

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
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(2)

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
        self.preview_ax.set_zorder(1)

        # Overlay axes for annotations so they render above panels
        self._annotation_overlay_ax = self.ui_figure.add_axes(
            self.preview_ax.get_position(), facecolor="none"
        )
        self._annotation_overlay_ax.set_axis_off()
        self._annotation_overlay_ax.set_zorder(10)
        self._annotation_overlay_ax.set_navigate(False)
        try:
            self.ui_figure.axes.remove(self._annotation_overlay_ax)
            self.ui_figure.axes.insert(0, self._annotation_overlay_ax)
        except Exception:
            pass

        self.preview_ax.callbacks.connect(
            "xlim_changed", self._sync_annotation_overlay_limits
        )
        self.preview_ax.callbacks.connect(
            "ylim_changed", self._sync_annotation_overlay_limits
        )

        self.nav_toolbar = ComposerNavigationToolbar(self.canvas, left, on_view_changed=self._on_nav_view_changed)
        left_layout.addWidget(self.nav_toolbar)

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
            btn.setFixedHeight(32)
            toolbar_row.addWidget(btn)
        left_layout.addLayout(toolbar_row)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            'color: #6c757d; font-family: "Menlo", "Courier New", monospace;'
        )
        left_layout.addWidget(self.status_label)

        splitter.addWidget(left)
        splitter.setStretchFactor(0, 3)

        # Right pane: tabbed controls wrapped in a scroll area
        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(6)

        self.tab_widget = QTabWidget()
        self.layout_tab = self._build_layout_tab()
        self.fonts_tab = self._build_fonts_tab()
        self.traces_events_tab = self._build_traces_events_tab()
        self.annotation_tab = self._build_annotation_tab()
        self.export_tab = self._build_export_tab()
        self.tab_widget.addTab(self.layout_tab, "Layout")
        self.tab_widget.addTab(self.fonts_tab, "Fonts / Style")
        self.tab_widget.addTab(self.traces_events_tab, "Traces & Events")
        self.tab_widget.addTab(self.annotation_tab, "Annotation")
        self.tab_widget.addTab(self.export_tab, "Export")
        controls_layout.addWidget(self.tab_widget)

        scroll = QScrollArea()
        scroll.setWidget(controls_container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 2)

        self.canvas.draw()

    def _resize_to_available_screen(self):
        """Resize the window to fit the available screen geometry."""
        app = QApplication.instance()
        if app is None:
            return
        screen = self.screen() or app.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        # Leave a small margin so window chrome is visible
        margin = 12
        target = geom.adjusted(margin, margin, -margin, -margin)
        self.setGeometry(target)

    # ------------------------------------------------------------------
    # Qt toolbar wiring
    # ------------------------------------------------------------------
    def _connect_toolbar_signals(self):
        self.btn_mode_select.clicked.connect(
            lambda: self._set_annotation_mode("select")
        )
        self.btn_mode_text.clicked.connect(lambda: self._set_annotation_mode("text"))
        self.btn_mode_box.clicked.connect(lambda: self._set_annotation_mode("box"))
        self.btn_mode_arrow.clicked.connect(lambda: self._set_annotation_mode("arrow"))
        self.btn_mode_line.clicked.connect(lambda: self._set_annotation_mode("line"))

        self.btn_delete.clicked.connect(lambda: self._set_annotation_mode("delete"))
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
            "delete": self.btn_delete,
        }
        for mode, btn in mode_buttons.items():
            if mode == self.annotation_mode:
                btn.setStyleSheet(
                    "background-color: #4da3ff; color: white; font-weight: bold;"
                )
            else:
                btn.setStyleSheet("")

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _build_layout_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # Size
        grp_size = QGroupBox("Figure size")
        size_form = QFormLayout(grp_size)
        size_form.addRow(QLabel("Figure area (not page)"))
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(2.0, 24.0)
        self.spin_width.setSingleStep(0.1)
        self.spin_width.setValue(self.spec.layout.width_in)
        self.label_width_mm = QLabel("")
        self.label_width_mm.setStyleSheet("color: #6c757d;")
        row_w = QHBoxLayout()
        row_w.addWidget(self.spin_width)
        row_w.addWidget(self.label_width_mm)
        row_w.addStretch(1)
        size_form.addRow("Width (in)", row_w)

        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(1.0, 24.0)
        self.spin_height.setSingleStep(0.1)
        self.spin_height.setValue(self.spec.layout.height_in)
        self.label_height_mm = QLabel("")
        self.label_height_mm.setStyleSheet("color: #6c757d;")
        row_h = QHBoxLayout()
        row_h.addWidget(self.spin_height)
        row_h.addWidget(self.label_height_mm)
        row_h.addStretch(1)
        size_form.addRow("Height (in)", row_h)
        self.cb_lock_aspect = QCheckBox("Lock aspect ratio")
        size_form.addRow(self.cb_lock_aspect)
        layout.addWidget(grp_size)

        # Grid
        grp_grid = QGroupBox("Panel grid")
        grid_form = QFormLayout(grp_grid)
        grid_form.addRow(QLabel("Panel grid inside figure (LayoutSpec.nrows/ncols)"))
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 8)
        self.spin_rows.setValue(self.spec.layout.nrows)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 8)
        self.spin_cols.setValue(self.spec.layout.ncols)
        self.spin_hspace = QDoubleSpinBox()
        self.spin_hspace.setRange(0.0, 2.0)
        self.spin_hspace.setSingleStep(0.05)
        self.spin_hspace.setValue(self.spec.layout.hspace)
        self.spin_wspace = QDoubleSpinBox()
        self.spin_wspace.setRange(0.0, 2.0)
        self.spin_wspace.setSingleStep(0.05)
        self.spin_wspace.setValue(self.spec.layout.wspace)
        grid_form.addRow("Rows", self.spin_rows)
        grid_form.addRow("Columns", self.spin_cols)
        grid_form.addRow("Vertical spacing", self.spin_hspace)
        grid_form.addRow("Horizontal spacing", self.spin_wspace)
        presets_row = QHBoxLayout()
        for r, c, label in [(1, 1, "1×1"), (1, 2, "1×2"), (2, 1, "2×1"), (2, 2, "2×2")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, rr=r, cc=c: self._set_grid_preset(rr, cc))
            presets_row.addWidget(btn)
        presets_row.addStretch(1)
        grid_form.addRow("Quick presets", presets_row)
        layout.addWidget(grp_grid)

        # Panel mapping
        grp_map = QGroupBox("Panel mapping")
        map_layout = QVBoxLayout(grp_map)
        self.table_panel_map = QTableWidget(0, 6)
        self.table_panel_map.setHorizontalHeaderLabels(
            ["Label", "Graph", "Row (0-based)", "Col (0-based)", "Rowspan", "Colspan"]
        )
        self.table_panel_map.verticalHeader().setVisible(False)
        self.table_panel_map.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_panel_map.setSelectionMode(QTableWidget.SingleSelection)
        self.table_panel_map.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        map_layout.addWidget(self.table_panel_map)

        btn_row = QHBoxLayout()
        self.btn_panel_up = QPushButton("Swap up")
        self.btn_panel_down = QPushButton("Swap down")
        self.btn_panel_dup = QPushButton("Duplicate panel")
        self.btn_panel_remove = QPushButton("Remove panel")
        for btn in [
            self.btn_panel_up,
            self.btn_panel_down,
            self.btn_panel_dup,
            self.btn_panel_remove,
        ]:
            btn_row.addWidget(btn)
        map_layout.addLayout(btn_row)
        layout.addWidget(grp_map)

        # Panel labels
        grp_labels = QGroupBox("Panel labels (A, B, C…) applied to all panels")
        labels_form = QFormLayout(grp_labels)
        self.cb_panel_labels = QCheckBox("Show panel labels")
        labels_form.addRow(self.cb_panel_labels)
        self.spin_panel_label_size = QDoubleSpinBox()
        self.spin_panel_label_size.setRange(6.0, 32.0)
        self.combo_panel_label_weight = QComboBox()
        self.combo_panel_label_weight.addItems(["normal", "bold"])
        self.spin_panel_label_x = QDoubleSpinBox()
        self.spin_panel_label_x.setRange(-1.0, 2.0)
        self.spin_panel_label_x.setSingleStep(0.01)
        self.spin_panel_label_y = QDoubleSpinBox()
        self.spin_panel_label_y.setRange(-1.0, 2.0)
        self.spin_panel_label_y.setSingleStep(0.01)
        labels_form.addRow("Font size", self.spin_panel_label_size)
        labels_form.addRow("Weight", self.combo_panel_label_weight)
        labels_form.addRow("X offset", self.spin_panel_label_x)
        labels_form.addRow("Y offset", self.spin_panel_label_y)
        layout.addWidget(grp_labels)

        # Templates (save/load)
        grp_tpl = QGroupBox("Templates")
        tpl_layout = QHBoxLayout()
        self.combo_templates = QComboBox()
        self._refresh_template_list()
        tpl_layout.addWidget(self.combo_templates)
        btn_apply_tpl = QPushButton("Apply")
        btn_save_tpl = QPushButton("Save current")
        tpl_layout.addWidget(btn_apply_tpl)
        tpl_layout.addWidget(btn_save_tpl)
        tpl_layout2 = QVBoxLayout()
        tpl_layout2.addLayout(tpl_layout)
        note = QLabel(
            "Templates apply: size, grid, panel mapping, panel labels. Data/annotations preserved."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6c757d;")
        tpl_layout2.addWidget(note)
        grp_tpl.setLayout(tpl_layout2)
        layout.addWidget(grp_tpl)

        layout.addStretch(1)

        # Signals
        self.spin_width.valueChanged.connect(self._on_size_changed_qt)
        self.spin_height.valueChanged.connect(self._on_size_changed_qt)
        self.cb_lock_aspect.toggled.connect(self._on_lock_aspect_toggled)
        self.spin_rows.valueChanged.connect(self._on_grid_changed)
        self.spin_cols.valueChanged.connect(self._on_grid_changed)
        self.spin_hspace.valueChanged.connect(self._on_spacing_changed)
        self.spin_wspace.valueChanged.connect(self._on_spacing_changed)
        self.table_panel_map.itemSelectionChanged.connect(
            self._on_panel_table_selection
        )
        self.btn_panel_up.clicked.connect(self._on_panel_swap_up)
        self.btn_panel_down.clicked.connect(self._on_panel_swap_down)
        self.btn_panel_dup.clicked.connect(self._on_panel_duplicate)
        self.btn_panel_remove.clicked.connect(self._on_panel_remove)
        self.cb_panel_labels.toggled.connect(self._on_panel_label_toggled)
        self.spin_panel_label_size.valueChanged.connect(self._on_panel_label_changed)
        self.combo_panel_label_weight.currentTextChanged.connect(
            self._on_panel_label_changed
        )
        self.spin_panel_label_x.valueChanged.connect(self._on_panel_label_changed)
        self.spin_panel_label_y.valueChanged.connect(self._on_panel_label_changed)
        btn_apply_tpl.clicked.connect(self._on_apply_template)
        btn_save_tpl.clicked.connect(self._on_save_template)

        self._refresh_layout_tab()
        return w

    def _build_fonts_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        grp_fonts = QGroupBox("Typography")
        fonts_layout = QVBoxLayout(grp_fonts)
        form_family = QFormLayout()
        self.combo_font_family = QComboBox()
        common_fonts = [
            "DejaVu Sans",
            "Helvetica",
            "Arial",
            "Times New Roman",
            "Calibri",
            "Liberation Sans",
            "Computer Modern",
            "Verdana",
        ]
        self.combo_font_family.addItems(common_fonts)
        self.combo_font_family.setEditable(True)
        if self.spec.font.family not in common_fonts:
            self.combo_font_family.addItem(self.spec.font.family)
        self.combo_font_family.setCurrentText(self.spec.font.family)
        self.combo_font_family.setToolTip("Global font family used for all text.")
        form_family.addRow("Font family", self.combo_font_family)
        fonts_layout.addLayout(form_family)

        grid = QGridLayout()
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.addWidget(QLabel("Role"), 0, 0)
        grid.addWidget(QLabel("Size"), 0, 1)
        bold_header = QLabel("B")
        bf = bold_header.font()
        bf.setBold(True)
        bold_header.setFont(bf)
        grid.addWidget(bold_header, 0, 2)
        italic_header = QLabel("I")
        itf = italic_header.font()
        itf.setItalic(True)
        italic_header.setFont(itf)
        grid.addWidget(italic_header, 0, 3)
        self.font_role_controls: dict[str, dict[str, any]] = {}
        roles = [
            ("figure_title", "Figure title"),
            ("panel_label", "Panel labels"),
            ("axis_title", "Axis titles"),
            ("tick_label", "Tick labels"),
            ("legend", "Legend text"),
            ("annotation", "Annotation text"),
        ]
        for row_idx, (role_key, role_label) in enumerate(roles, start=1):
            lbl = QLabel(role_label)
            spin = QDoubleSpinBox()
            spin.setRange(4.0, 32.0)
            spin.setDecimals(1)
            spin.setSingleStep(0.5)
            spin.setMaximumWidth(80)
            bold_cb = QCheckBox()
            bold_cb.setMaximumWidth(40)
            italic_cb = QCheckBox()
            italic_cb.setMaximumWidth(40)
            grid.addWidget(lbl, row_idx, 0)
            grid.addWidget(spin, row_idx, 1)
            grid.addWidget(bold_cb, row_idx, 2)
            grid.addWidget(italic_cb, row_idx, 3)
            self.font_role_controls[role_key] = {
                "spin": spin,
                "bold": bold_cb,
                "italic": italic_cb,
            }
            spin.valueChanged.connect(
                lambda v, rk=role_key: self._on_role_font_size_changed(rk, v)
            )
            bold_cb.toggled.connect(
                lambda checked, rk=role_key: self._on_role_font_weight_changed(
                    rk, checked
                )
            )
            italic_cb.toggled.connect(
                lambda checked, rk=role_key: self._on_role_font_style_changed(
                    rk, checked
                )
            )

        fonts_layout.addLayout(grid)
        layout.addWidget(grp_fonts)

        grp_style = QGroupBox("Line / axis style")
        style_form = QFormLayout(grp_style)
        self.spin_default_linewidth = QDoubleSpinBox()
        self.spin_default_linewidth.setRange(0.1, 5.0)
        self.spin_default_linewidth.setSingleStep(0.1)
        self.spin_default_linewidth.setValue(self.spec.style.default_linewidth)
        self.spin_spine_width = QDoubleSpinBox()
        self.spin_spine_width.setRange(0.1, 5.0)
        self.spin_spine_width.setSingleStep(0.1)
        self.spin_spine_width.setValue(self.spec.style.axis_spine_width)
        self.combo_tick_dir = QComboBox()
        self.combo_tick_dir.addItems(["in", "out", "inout"])
        self.combo_tick_dir.setCurrentText(self.spec.style.tick_direction)
        self.spin_tick_major = QDoubleSpinBox()
        self.spin_tick_major.setRange(0.1, 20.0)
        self.spin_tick_major.setSingleStep(0.5)
        self.spin_tick_major.setValue(self.spec.style.tick_major_length)
        self.spin_tick_minor = QDoubleSpinBox()
        self.spin_tick_minor.setRange(0.1, 20.0)
        self.spin_tick_minor.setSingleStep(0.5)
        self.spin_tick_minor.setValue(self.spec.style.tick_minor_length)
        self.spin_default_linewidth.setToolTip(
            "Line width used for traces unless overridden in the Traces & Events tab."
        )
        self.spin_spine_width.setToolTip(
            "Thickness of axis lines (spines) around each panel."
        )
        self.combo_tick_dir.setToolTip(
            "Direction of tick marks (inside, outside, or both)."
        )
        self.spin_tick_major.setToolTip("Length of major tick marks.")
        self.spin_tick_minor.setToolTip("Length of minor tick marks.")
        style_form.addRow("Default trace linewidth", self.spin_default_linewidth)
        style_form.addRow("Axis spine width", self.spin_spine_width)
        style_form.addRow("Tick direction", self.combo_tick_dir)
        style_form.addRow("Tick length (major)", self.spin_tick_major)
        style_form.addRow("Tick length (minor)", self.spin_tick_minor)
        layout.addWidget(grp_style)

        grp_presets = QGroupBox("Style presets")
        preset_layout = QHBoxLayout()
        self.combo_style_preset = QComboBox()
        self.combo_style_preset.addItems(list(STYLE_PRESETS.keys()) + ["Custom"])
        preset_layout.addWidget(self.combo_style_preset)
        self.btn_apply_style_preset = QPushButton("Apply preset")
        preset_layout.addWidget(self.btn_apply_style_preset)
        self.label_style_desc = QLabel("")
        self.label_style_desc.setStyleSheet("color: #6c757d;")
        preset_wrap = QVBoxLayout()
        preset_wrap.addLayout(preset_layout)
        preset_wrap.addWidget(self.label_style_desc)
        grp_presets.setLayout(preset_wrap)
        layout.addWidget(grp_presets)

        layout.addStretch(1)

        self.combo_font_family.currentTextChanged.connect(self._on_font_family_changed)

        self.spin_default_linewidth.valueChanged.connect(self._on_style_changed)
        self.spin_spine_width.valueChanged.connect(self._on_style_changed)
        self.combo_tick_dir.currentTextChanged.connect(self._on_style_changed)
        self.spin_tick_major.valueChanged.connect(self._on_style_changed)
        self.spin_tick_minor.valueChanged.connect(self._on_style_changed)
        self.btn_apply_style_preset.clicked.connect(self._on_apply_style_preset)
        self.combo_style_preset.currentTextChanged.connect(
            self._on_style_preset_changed
        )

        return w

    def _build_traces_events_tab(self) -> QWidget:
        """Traces & Events tab – GraphPad-style controls for the active panel."""
        w = QWidget()
        layout = QVBoxLayout(w)

        group_panel = QGroupBox("Panel")
        panel_layout = QVBoxLayout(group_panel)
        panel_row = QHBoxLayout()
        panel_row.addWidget(QLabel("Panel"))
        self.combo_panel_select = QComboBox()
        panel_row.addWidget(self.combo_panel_select, stretch=1)
        panel_layout.addLayout(panel_row)
        hint = QLabel("Editing settings for this panel only.")
        hint.setStyleSheet("color: #6c757d;")
        panel_layout.addWidget(hint)
        layout.addWidget(group_panel)

        group_display = QGroupBox("Display & spines")
        disp_layout = QVBoxLayout(group_display)
        self.cb_grid = QCheckBox("Show grid")
        self.cb_legend = QCheckBox("Show legend")
        disp_layout.addWidget(self.cb_grid)
        disp_layout.addWidget(self.cb_legend)
        legend_row = QHBoxLayout()
        legend_row.addWidget(QLabel("Legend position"))
        self.combo_legend_loc = QComboBox()
        self.combo_legend_loc.addItems(
            [
                "best",
                "upper right",
                "upper left",
                "lower left",
                "lower right",
                "center right",
                "center left",
                "upper center",
                "lower center",
                "center",
            ]
        )
        legend_row.addWidget(self.combo_legend_loc)
        disp_layout.addLayout(legend_row)
        spine_layout = QHBoxLayout()
        self.cb_spine_left = QCheckBox("Left spine")
        self.cb_spine_right = QCheckBox("Right spine")
        self.cb_spine_top = QCheckBox("Top spine")
        self.cb_spine_bottom = QCheckBox("Bottom spine")
        for cb in [
            self.cb_spine_left,
            self.cb_spine_right,
            self.cb_spine_top,
            self.cb_spine_bottom,
        ]:
            spine_layout.addWidget(cb)
        disp_layout.addLayout(spine_layout)
        layout.addWidget(group_display)

        group_axes = QGroupBox("Axes & ranges")
        axes_form = QFormLayout(group_axes)
        self.combo_x_scale = QComboBox()
        self.combo_x_scale.addItems(["linear", "log"])
        self.combo_y_scale = QComboBox()
        self.combo_y_scale.addItems(["linear", "log"])
        self.cb_x_auto = QCheckBox("Auto")
        self.cb_y_auto = QCheckBox("Auto")
        self.edit_x_min = QLineEdit()
        self.edit_x_max = QLineEdit()
        self.edit_y_min = QLineEdit()
        self.edit_y_max = QLineEdit()
        axes_form.addRow("X scale", self.combo_x_scale)
        axes_form.addRow("X auto", self.cb_x_auto)
        axes_form.addRow("X min", self.edit_x_min)
        axes_form.addRow("X max", self.edit_x_max)
        axes_form.addRow("Y scale", self.combo_y_scale)
        axes_form.addRow("Y auto", self.cb_y_auto)
        axes_form.addRow("Y min", self.edit_y_min)
        axes_form.addRow("Y max", self.edit_y_max)
        layout.addWidget(group_axes)

        group_ticks = QGroupBox("Ticks")
        ticks_form = QFormLayout(group_ticks)
        self.spin_x_tick_every = QDoubleSpinBox()
        self.spin_x_tick_every.setRange(0.0, 1e6)
        self.spin_x_tick_every.setSingleStep(10.0)
        self.spin_x_tick_every.setDecimals(3)
        ticks_form.addRow("X tick every (s)", self.spin_x_tick_every)
        self.spin_x_max_ticks = QSpinBox()
        self.spin_x_max_ticks.setRange(0, 50)
        ticks_form.addRow("Max X ticks", self.spin_x_max_ticks)
        self.spin_y_max_ticks = QSpinBox()
        self.spin_y_max_ticks.setRange(0, 50)  # 0 = auto
        ticks_form.addRow("Max Y ticks", self.spin_y_max_ticks)
        layout.addWidget(group_ticks)

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
        self.spin_event_lw.setRange(0.1, 10.0)
        self.spin_event_lw.setSingleStep(0.1)
        self.combo_event_ls = QComboBox()
        self.combo_event_ls.addItems(["solid", "dashed", "dotted", "dashdot"])
        self.spin_event_rotation = QDoubleSpinBox()
        self.spin_event_rotation.setRange(-180.0, 180.0)
        self.spin_event_rotation.setSingleStep(5.0)
        style_form.addRow("Line color", self.edit_event_color)
        style_form.addRow("Line width", self.spin_event_lw)
        style_form.addRow("Line style", self.combo_event_ls)
        style_form.addRow("Label rotation (°)", self.spin_event_rotation)
        events_layout.addLayout(style_form)
        if self.event_times:
            label_form = QFormLayout()
            self.spin_event_index = QSpinBox()
            self.spin_event_index.setRange(0, max(len(self.event_times) - 1, 0))
            self.edit_event_label = QLineEdit()
            label_form.addRow("Event index", self.spin_event_index)
            label_form.addRow("Label", self.edit_event_label)
            events_layout.addLayout(label_form)
        else:
            no_events = QLabel("No events in this figure.")
            no_events.setStyleSheet("color: #6c757d;")
            events_layout.addWidget(no_events)
        layout.addWidget(group_events)

        group_traces = QGroupBox("Traces & Y-axes")
        traces_layout = QVBoxLayout(group_traces)
        trace_row = QHBoxLayout()
        self.cb_trace_inner = QCheckBox("Inner diameter")
        self.cb_trace_outer = QCheckBox("Outer diameter")
        self.cb_trace_avg_pressure = QCheckBox("Avg pressure")
        self.cb_trace_set_pressure = QCheckBox("Set pressure")
        for cb in [
            self.cb_trace_inner,
            self.cb_trace_outer,
            self.cb_trace_avg_pressure,
            self.cb_trace_set_pressure,
        ]:
            trace_row.addWidget(cb)
        traces_layout.addLayout(trace_row)
        self.cb_twin_y = QCheckBox("Use right Y-axis (twin Y)")
        traces_layout.addWidget(self.cb_twin_y)
        self.edit_y2_label = QLineEdit()
        self.edit_y2_label.setPlaceholderText("Right Y label")
        self.combo_y2_scale = QComboBox()
        self.combo_y2_scale.addItems(["linear", "log"])
        self.edit_y2_min = QLineEdit()
        self.edit_y2_max = QLineEdit()
        y2_form = QFormLayout()
        y2_form.addRow("Right Y label", self.edit_y2_label)
        y2_form.addRow("Right Y scale", self.combo_y2_scale)
        y2_form.addRow("Right Y min", self.edit_y2_min)
        y2_form.addRow("Right Y max", self.edit_y2_max)
        traces_layout.addLayout(y2_form)

        style_group = QGroupBox("Trace style")
        style_form = QFormLayout(style_group)
        self.combo_trace_select = QComboBox()
        self.edit_trace_color = QLineEdit()
        self.spin_trace_lw = QDoubleSpinBox()
        self.spin_trace_lw.setRange(0.1, 10.0)
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
        """Annotation manager tab."""
        w = QWidget()
        root = QHBoxLayout(w)

        # Left: list of annotations
        left = QVBoxLayout()
        left.addWidget(QLabel("Annotations"))
        self.list_annotations = QListWidget()
        left.addWidget(self.list_annotations, stretch=1)
        btn_row = QHBoxLayout()
        self.btn_annot_duplicate = QPushButton("Duplicate")
        self.btn_annot_delete = QPushButton("Delete")
        btn_row.addWidget(self.btn_annot_duplicate)
        btn_row.addWidget(self.btn_annot_delete)
        left.addLayout(btn_row)
        root.addLayout(left, stretch=1)

        # Right: property editors
        right = QVBoxLayout()

        # Style/content group
        self.group_style = QGroupBox("Style & Content")
        text_form = QFormLayout(self.group_style)
        self.edit_annot_text = QPlainTextEdit()
        self.spin_annot_font = QDoubleSpinBox()
        self.spin_annot_font.setRange(6.0, 48.0)
        self.spin_annot_font.setSingleStep(0.5)
        self.combo_annot_weight = QComboBox()
        self.combo_annot_weight.addItems(["normal", "bold", "light"])
        self.combo_annot_style = QComboBox()
        self.combo_annot_style.addItems(["normal", "italic", "oblique"])
        self.edit_annot_color = QLineEdit()
        self.combo_annot_ha = QComboBox()
        self.combo_annot_ha.addItems(["left", "center", "right"])
        self.combo_annot_va = QComboBox()
        self.combo_annot_va.addItems(["bottom", "center", "top"])
        self.spin_annot_rotation = QDoubleSpinBox()
        self.spin_annot_rotation.setRange(-180.0, 180.0)
        self.spin_annot_rotation.setSingleStep(1.0)

        text_form.addRow("Content", self.edit_annot_text)
        text_form.addRow("Font size", self.spin_annot_font)
        text_form.addRow("Weight", self.combo_annot_weight)
        text_form.addRow("Style", self.combo_annot_style)
        text_form.addRow("Color", self.edit_annot_color)
        text_form.addRow("H align", self.combo_annot_ha)
        text_form.addRow("V align", self.combo_annot_va)
        text_form.addRow("Rotation", self.spin_annot_rotation)

        self.edit_annot_edgecolor = QLineEdit()
        self.edit_annot_facecolor = QLineEdit()
        self.spin_annot_alpha = QDoubleSpinBox()
        self.spin_annot_alpha.setRange(0.0, 1.0)
        self.spin_annot_alpha.setSingleStep(0.05)
        self.spin_annot_linewidth = QDoubleSpinBox()
        self.spin_annot_linewidth.setRange(0.1, 5.0)
        self.spin_annot_linewidth.setSingleStep(0.1)
        self.combo_annot_linestyle = QComboBox()
        self.combo_annot_linestyle.addItems(["solid", "dashed", "dotted", "dashdot"])
        self.combo_annot_arrowstyle = QComboBox()
        self.combo_annot_arrowstyle.addItems(["->", "-|>", "<->", "<|-|>", "simple"])
        text_form.addRow("Line width", self.spin_annot_linewidth)
        text_form.addRow("Line style", self.combo_annot_linestyle)
        text_form.addRow("Edge color", self.edit_annot_edgecolor)
        text_form.addRow("Fill color", self.edit_annot_facecolor)
        text_form.addRow("Alpha", self.spin_annot_alpha)
        text_form.addRow("Arrow style", self.combo_annot_arrowstyle)
        right.addWidget(self.group_style)

        self.group_defaults = QGroupBox("Defaults for new annotations")
        defaults_form = QFormLayout(self.group_defaults)
        self.spin_default_annot_font = QDoubleSpinBox()
        self.spin_default_annot_font.setRange(6.0, 48.0)
        self.spin_default_annot_font.setSingleStep(0.5)
        self.combo_default_annot_weight = QComboBox()
        self.combo_default_annot_weight.addItems(["normal", "bold", "light"])
        self.combo_default_annot_style = QComboBox()
        self.combo_default_annot_style.addItems(["normal", "italic", "oblique"])
        self.edit_default_annot_color = QLineEdit()
        self.edit_default_edgecolor = QLineEdit()
        self.edit_default_facecolor = QLineEdit()
        self.spin_default_alpha = QDoubleSpinBox()
        self.spin_default_alpha.setRange(0.0, 1.0)
        self.spin_default_alpha.setSingleStep(0.05)
        self.spin_default_linewidth = QDoubleSpinBox()
        self.spin_default_linewidth.setRange(0.1, 5.0)
        self.spin_default_linewidth.setSingleStep(0.1)
        self.combo_default_linestyle = QComboBox()
        self.combo_default_linestyle.addItems(["solid", "dashed", "dotted", "dashdot"])
        defaults_form.addRow("Font size", self.spin_default_annot_font)
        defaults_form.addRow("Weight", self.combo_default_annot_weight)
        defaults_form.addRow("Style", self.combo_default_annot_style)
        defaults_form.addRow("Text color", self.edit_default_annot_color)
        defaults_form.addRow("Edge color", self.edit_default_edgecolor)
        defaults_form.addRow("Face color", self.edit_default_facecolor)
        defaults_form.addRow("Alpha", self.spin_default_alpha)
        defaults_form.addRow("Line width", self.spin_default_linewidth)
        defaults_form.addRow("Line style", self.combo_default_linestyle)
        right.addWidget(self.group_defaults)

        right.addStretch(1)
        root.addLayout(right, stretch=2)

        self._connect_annotation_signals()
        self._refresh_annotation_ui()

        return w

    def _build_export_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        grp_export = QGroupBox("Output format")
        form = QFormLayout(grp_export)
        self.combo_format = QComboBox()
        self.combo_format.addItems(["pdf", "svg", "png", "tiff"])
        self.combo_format.setCurrentText(self.spec.export.format)
        form.addRow("Format", self.combo_format)

        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 1200)
        self.spin_dpi.setSingleStep(50)
        self.spin_dpi.setValue(self.spec.export.dpi)
        self.spin_dpi.setToolTip(
            "DPI affects raster exports; vector formats ignore this value."
        )
        form.addRow("DPI", self.spin_dpi)
        self.radio_bg_white = QRadioButton("White")
        self.radio_bg_transparent = QRadioButton("Transparent")
        if self.spec.export.transparent:
            self.radio_bg_transparent.setChecked(True)
        else:
            self.radio_bg_white.setChecked(True)
        bg_layout = QHBoxLayout()
        bg_layout.addWidget(self.radio_bg_white)
        bg_layout.addWidget(self.radio_bg_transparent)
        form.addRow("Background", bg_layout)
        layout.addWidget(grp_export)

        grp_presets = QGroupBox("Figure width presets (mm)")
        h = QHBoxLayout()
        for mm in (85, 120, 180, 260):
            btn = QPushButton(f"{mm} mm")
            btn.clicked.connect(lambda _, v=mm: self._on_width_preset_mm(v))
            h.addWidget(btn)
        h.addStretch(1)
        presets_wrap = QVBoxLayout(grp_presets)
        presets_wrap.addLayout(h)
        self.label_width_status = QLabel("")
        self.label_width_status.setStyleSheet("color: #6c757d;")
        presets_wrap.addWidget(self.label_width_status)
        layout.addWidget(grp_presets)

        grp_profiles = QGroupBox("Export profiles")
        prof_layout = QVBoxLayout(grp_profiles)
        row_prof = QHBoxLayout()
        self.combo_export_profile = QComboBox()
        self.combo_export_profile.addItems(
            ["Lab default", "Journal single-column", "Journal double-column", "Custom"]
        )
        self.btn_apply_export_profile = QPushButton("Apply profile")
        row_prof.addWidget(QLabel("Profile"))
        row_prof.addWidget(self.combo_export_profile, stretch=1)
        row_prof.addWidget(self.btn_apply_export_profile)
        prof_layout.addLayout(row_prof)
        self.label_export_profile_desc = QLabel("")
        self.label_export_profile_desc.setStyleSheet("color: #6c757d;")
        prof_layout.addWidget(self.label_export_profile_desc)
        layout.addWidget(grp_profiles)

        grp_multi = QGroupBox("Additional formats")
        multi_layout = QVBoxLayout(grp_multi)
        self.cb_export_png = QCheckBox("Also export PNG (300 dpi)")
        self.cb_export_tiff = QCheckBox("Also export TIFF (600 dpi)")
        multi_layout.addWidget(self.cb_export_png)
        multi_layout.addWidget(self.cb_export_tiff)
        layout.addWidget(grp_multi)

        grp_io = QGroupBox("Figure definition & export")
        io_layout = QVBoxLayout(grp_io)
        self.btn_save_fig = QPushButton("Save figure definition…")
        self.btn_load_fig = QPushButton("Load figure definition…")
        self.btn_save_to_project = QPushButton("Save to Project")
        self.btn_export_fig = QPushButton("Export…")
        io_layout.addWidget(self.btn_save_fig)
        io_layout.addWidget(self.btn_load_fig)
        io_layout.addWidget(self.btn_save_to_project)
        io_layout.addWidget(self.btn_export_fig)
        layout.addWidget(grp_io)
        layout.addStretch(1)

        self.combo_format.currentTextChanged.connect(self._on_export_format_changed)
        self.spin_dpi.valueChanged.connect(self._on_export_dpi_changed)
        self.radio_bg_white.toggled.connect(self._on_export_bg_changed)
        self.btn_apply_export_profile.clicked.connect(self._on_apply_export_profile)
        self.cb_export_png.toggled.connect(self._on_extra_export_changed)
        self.cb_export_tiff.toggled.connect(self._on_extra_export_changed)
        self.btn_save_fig.clicked.connect(self._on_save_spec)
        self.btn_load_fig.clicked.connect(self._on_load_spec)
        self.btn_save_to_project.clicked.connect(self._on_save_to_project_clicked)
        self.btn_export_fig.clicked.connect(self.export_figure)

        self._refresh_export_profile_description(
            self.combo_export_profile.currentText()
        )
        self._update_width_status_label()

        return w

    def _refresh_template_list(self):
        templates = list_templates()
        if hasattr(self, "combo_templates"):
            self.combo_templates.clear()
            if templates:
                self.combo_templates.addItems(templates)

    def _panel_label_from_index(self, idx: int) -> str:
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        label = ""
        n = idx
        while True:
            label = letters[n % 26] + label
            n = n // 26 - 1
            if n < 0:
                break
        return label

    def _refresh_panel_table(self):
        if not hasattr(self, "table_panel_map"):
            return
        self.table_panel_map.setRowCount(0)
        instances = list(self.spec.layout.graph_instances)
        graph_items = []
        for gid, gspec in self.spec.graphs.items():
            label = f"{gspec.name} ({gid})" if gspec and gspec.name else gid
            graph_items.append((label, gid))
        for row, inst in enumerate(instances):
            self.table_panel_map.insertRow(row)
            label_item = QTableWidgetItem(self._panel_label_from_index(row))
            label_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            label_item.setData(Qt.UserRole, inst.instance_id)
            font = label_item.font()
            font.setBold(inst.instance_id == self.selected_instance_id)
            label_item.setFont(font)
            self.table_panel_map.setItem(row, 0, label_item)

            combo = QComboBox()
            if not graph_items:
                combo.addItem(inst.graph_id, inst.graph_id)
            else:
                for label, gid in graph_items:
                    combo.addItem(label, gid)
            idx = combo.findData(inst.graph_id)
            combo.setCurrentIndex(max(idx, 0))
            combo.currentIndexChanged.connect(
                lambda _, c=combo, iid=inst.instance_id: self._on_panel_graph_changed(
                    iid, c.currentData()
                )
            )
            self.table_panel_map.setCellWidget(row, 1, combo)

            row_spin = QSpinBox()
            row_spin.setRange(0, max(self.spec.layout.nrows - 1, 0))
            row_spin.setValue(inst.row)
            row_spin.valueChanged.connect(
                lambda val, iid=inst.instance_id: self._on_panel_position_changed(
                    iid, "row", val
                )
            )
            self.table_panel_map.setCellWidget(row, 2, row_spin)

            col_spin = QSpinBox()
            col_spin.setRange(0, max(self.spec.layout.ncols - 1, 0))
            col_spin.setValue(inst.col)
            col_spin.valueChanged.connect(
                lambda val, iid=inst.instance_id: self._on_panel_position_changed(
                    iid, "col", val
                )
            )
            self.table_panel_map.setCellWidget(row, 3, col_spin)

            rowspan_spin = QSpinBox()
            rowspan_spin.setRange(1, max(self.spec.layout.nrows, 1))
            rowspan_spin.setValue(inst.rowspan)
            rowspan_spin.valueChanged.connect(
                lambda val, iid=inst.instance_id: self._on_panel_position_changed(
                    iid, "rowspan", val
                )
            )
            self.table_panel_map.setCellWidget(row, 4, rowspan_spin)

            colspan_spin = QSpinBox()
            colspan_spin.setRange(1, max(self.spec.layout.ncols, 1))
            colspan_spin.setValue(inst.colspan)
            colspan_spin.valueChanged.connect(
                lambda val, iid=inst.instance_id: self._on_panel_position_changed(
                    iid, "colspan", val
                )
            )
            self.table_panel_map.setCellWidget(row, 5, colspan_spin)

            if inst.instance_id == self.selected_instance_id:
                self.table_panel_map.selectRow(row)
        self._update_panel_buttons_enabled()

    def _refresh_layout_tab(self):
        if not hasattr(self, "spin_width"):
            return
        widgets = [
            self.spin_width,
            self.spin_height,
            self.spin_rows,
            self.spin_cols,
            self.spin_hspace,
            self.spin_wspace,
            self.cb_panel_labels,
            self.spin_panel_label_size,
            self.combo_panel_label_weight,
            self.spin_panel_label_x,
            self.spin_panel_label_y,
        ]
        for w in widgets:
            w.blockSignals(True)

        layout = self.spec.layout
        self.spin_width.setValue(layout.width_in)
        self.spin_height.setValue(layout.height_in)
        self.label_width_mm.setText(f"{layout.width_in * 25.4:.1f} mm")
        self.label_height_mm.setText(f"{layout.height_in * 25.4:.1f} mm")
        self.cb_lock_aspect.setChecked(self._lock_aspect_ratio)
        self.spin_rows.setValue(layout.nrows)
        self.spin_cols.setValue(layout.ncols)
        self.spin_hspace.setValue(layout.hspace)
        self.spin_wspace.setValue(layout.wspace)

        pls = layout.panel_labels
        self.cb_panel_labels.setChecked(pls.show)
        self.spin_panel_label_size.setValue(pls.font_size)
        self.combo_panel_label_weight.setCurrentText(pls.weight)
        self.spin_panel_label_x.setValue(pls.x_offset)
        self.spin_panel_label_y.setValue(pls.y_offset)
        if hasattr(self.spec, "font") and hasattr(self.spec.font, "panel_label"):
            self.spec.font.panel_label.size = pls.font_size
            self.spec.font.panel_label.weight = pls.weight

        self._refresh_panel_table()

        for w in widgets:
            w.blockSignals(False)

    def _get_graph_instance(self, instance_id: str) -> GraphInstance | None:
        return next(
            (
                gi
                for gi in self.spec.layout.graph_instances
                if gi.instance_id == instance_id
            ),
            None,
        )

    def _on_grid_changed(self, *_):
        layout = self.spec.layout
        layout.nrows = int(self.spin_rows.value())
        layout.ncols = int(self.spin_cols.value())
        for inst in layout.graph_instances:
            inst.row = min(inst.row, layout.nrows - 1)
            inst.col = min(inst.col, layout.ncols - 1)
            inst.rowspan = min(inst.rowspan, max(layout.nrows - inst.row, 1))
            inst.colspan = min(inst.colspan, max(layout.ncols - inst.col, 1))
        self._push_undo()
        self._refresh_panel_table()
        self._update_preview()

    def _set_grid_preset(self, rows: int, cols: int):
        """Quickly set a grid preset and refresh."""
        self.spin_rows.setValue(rows)
        self.spin_cols.setValue(cols)
        if rows >= 2 or cols >= 2:
            if self.spin_hspace.value() < 0.3:
                self.spin_hspace.setValue(0.3)
            if self.spin_wspace.value() < 0.3:
                self.spin_wspace.setValue(0.3)
        self._on_grid_changed()

    def _on_spacing_changed(self, *_):
        self.spec.layout.hspace = float(self.spin_hspace.value())
        self.spec.layout.wspace = float(self.spin_wspace.value())
        self._push_undo()
        self._update_preview()

    def _update_panel_buttons_enabled(self):
        if not hasattr(self, "btn_panel_up"):
            return
        has_selection = self.table_panel_map.currentRow() >= 0
        for btn in [
            self.btn_panel_up,
            self.btn_panel_down,
            self.btn_panel_dup,
            self.btn_panel_remove,
        ]:
            btn.setEnabled(has_selection)

    def _on_panel_table_selection(self):
        row = self.table_panel_map.currentRow()
        if row < 0 or row >= len(self.spec.layout.graph_instances):
            self._update_panel_buttons_enabled()
            return
        item = self.table_panel_map.item(row, 0)
        if item:
            self.selected_instance_id = item.data(Qt.UserRole)
            if hasattr(self, "combo_panel_select"):
                self._refresh_traces_events_tab()
                self._update_preview()
        self._update_panel_buttons_enabled()

    def _on_panel_graph_changed(self, instance_id: str, graph_id: str):
        inst = self._get_graph_instance(instance_id)
        if inst is None:
            return
        if graph_id is None and self.spec.graphs:
            graph_id = next(iter(self.spec.graphs.keys()))
        if graph_id is None:
            return
        inst.graph_id = graph_id
        self._push_undo()
        self._update_preview()

    def _on_panel_position_changed(self, instance_id: str, field: str, value: int):
        inst = self._get_graph_instance(instance_id)
        if inst is None:
            return
        setattr(inst, field, int(value))
        layout = self.spec.layout
        inst.row = min(inst.row, layout.nrows - 1)
        inst.col = min(inst.col, layout.ncols - 1)
        inst.rowspan = min(max(inst.rowspan, 1), max(layout.nrows - inst.row, 1))
        inst.colspan = min(max(inst.colspan, 1), max(layout.ncols - inst.col, 1))
        self._push_undo()
        self._refresh_panel_table()
        self._update_preview()

    def _on_panel_swap_up(self):
        row = self.table_panel_map.currentRow()
        if row <= 0:
            return
        instances = self.spec.layout.graph_instances
        instances[row - 1], instances[row] = instances[row], instances[row - 1]
        self.selected_instance_id = instances[row - 1].instance_id
        self._push_undo()
        self._refresh_panel_table()
        self.table_panel_map.selectRow(row - 1)
        self._refresh_traces_events_tab()
        self._update_preview()

    def _on_panel_swap_down(self):
        row = self.table_panel_map.currentRow()
        instances = self.spec.layout.graph_instances
        if row < 0 or row >= len(instances) - 1:
            return
        instances[row + 1], instances[row] = instances[row], instances[row + 1]
        self.selected_instance_id = instances[row + 1].instance_id
        self._push_undo()
        self._refresh_panel_table()
        self.table_panel_map.selectRow(row + 1)
        self._refresh_traces_events_tab()
        self._update_preview()

    def _on_panel_duplicate(self):
        row = self.table_panel_map.currentRow()
        instances = self.spec.layout.graph_instances
        if row < 0 or row >= len(instances):
            return
        inst = instances[row]
        new_inst = copy.deepcopy(inst)
        new_inst.instance_id = f"inst_{uuid.uuid4().hex[:6]}"
        new_inst.col = min(inst.col + 1, max(self.spec.layout.ncols - 1, 0))
        instances.insert(row + 1, new_inst)
        self.selected_instance_id = new_inst.instance_id
        self._push_undo()
        self._refresh_panel_table()
        self.table_panel_map.selectRow(row + 1)
        self._refresh_traces_events_tab()
        self._update_preview()

    def _on_panel_remove(self):
        row = self.table_panel_map.currentRow()
        instances = self.spec.layout.graph_instances
        if row < 0 or row >= len(instances):
            return
        inst = instances.pop(row)
        # Drop graph spec if unused elsewhere
        still_used = any(gi.graph_id == inst.graph_id for gi in instances)
        if not still_used and inst.graph_id in self.spec.graphs:
            self.spec.graphs.pop(inst.graph_id, None)
        self.selected_instance_id = instances[0].instance_id if instances else None
        self._push_undo()
        self._refresh_panel_table()
        if instances:
            self.table_panel_map.selectRow(min(row, len(instances) - 1))
        self._refresh_traces_events_tab()
        self._update_preview()

    def _on_panel_label_toggled(self, checked: bool):
        pls = self.spec.layout.panel_labels
        pls.show = checked
        self._push_undo()
        self._update_preview()

    def _on_panel_label_changed(self, *_):
        pls = self.spec.layout.panel_labels
        pls.font_size = float(self.spin_panel_label_size.value())
        pls.weight = self.combo_panel_label_weight.currentText()
        pls.x_offset = float(self.spin_panel_label_x.value())
        pls.y_offset = float(self.spin_panel_label_y.value())
        if hasattr(self.spec.font, "panel_label"):
            self.spec.font.panel_label.size = pls.font_size
            self.spec.font.panel_label.weight = pls.weight
        self._push_undo()
        self._update_preview()

    # ------------------------------------------------------------------
    # Tab callbacks
    # ------------------------------------------------------------------
    def _on_layout_template_changed(self, idx: int):
        if not hasattr(self, "combo_layout_template"):
            return
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
                graph_id = (
                    graph_ids[idx_counter % len(graph_ids)] if graph_ids else "graph1"
                )
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
        if self._suppress_size_events:
            return
        sender = self.sender()
        width = float(self.spin_width.value())
        height = float(self.spin_height.value())
        if self._lock_aspect_ratio and width > 0 and height > 0:
            self._suppress_size_events = True
            if sender is self.spin_width:
                new_h = width * (
                    self._aspect_ratio
                    if hasattr(self, "_aspect_ratio")
                    else height / max(width, 1e-6)
                )
                self.spin_height.setValue(new_h)
                height = new_h
            elif (
                sender is self.spin_height
                and hasattr(self, "_aspect_ratio")
                and self._aspect_ratio > 0
            ):
                new_w = height / self._aspect_ratio
                self.spin_width.setValue(new_w)
                width = new_w
            self._suppress_size_events = False
        self.spec.layout.width_in = width
        self.spec.layout.height_in = height
        if hasattr(self, "label_width_mm"):
            self.label_width_mm.setText(f"{self.spec.layout.width_in * 25.4:.1f} mm")
        if hasattr(self, "label_height_mm"):
            self.label_height_mm.setText(f"{self.spec.layout.height_in * 25.4:.1f} mm")
        if width > 0:
            self._aspect_ratio = self.spec.layout.height_in / width
        self._update_width_status_label()
        self._push_undo()
        self._update_preview()
        self._update_footer()

    def _on_lock_aspect_toggled(self, checked: bool):
        self._lock_aspect_ratio = checked
        width = float(self.spin_width.value())
        if width > 0:
            self._aspect_ratio = float(self.spin_height.value()) / width

    def _on_apply_template(self):
        name = self.combo_templates.currentText()
        if not name:
            return
        try:
            tmpl = load_template(name)
            apply_template_structure(self.spec, tmpl)
            if self.spec.layout.graph_instances:
                self.selected_instance_id = self.spec.layout.graph_instances[
                    0
                ].instance_id
            self._push_undo()
            self._refresh_tabs()
            self._update_preview()
        except Exception as exc:
            QMessageBox.critical(
                self, "Template Error", f"Failed to apply template:\n{exc}"
            )

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
            QMessageBox.critical(
                self, "Template Error", f"Failed to save template:\n{exc}"
            )

    def _on_font_family_changed(self, *_):
        f = self.spec.font
        f.family = self.combo_font_family.currentText().strip() or f.family
        if not self._applying_style_preset:
            self.spec.metadata["style_preset"] = "Custom"
            if hasattr(self, "combo_style_preset"):
                self.combo_style_preset.setCurrentText("Custom")
        self._push_undo()
        self._update_preview()

    def _on_role_font_size_changed(self, role: str, value: float):
        f_role = getattr(self.spec.font, role, None)
        if f_role is None:
            return
        f_role.size = float(value)
        if role == "tick_label":
            self.spec.font.base_size = float(value)
        if role == "panel_label" and hasattr(self.spec.layout, "panel_labels"):
            self.spec.layout.panel_labels.font_size = float(value)
        if not self._applying_style_preset:
            self.spec.metadata["style_preset"] = "Custom"
            if hasattr(self, "combo_style_preset"):
                self.combo_style_preset.setCurrentText("Custom")
        self._push_undo()
        self._update_preview()

    def _on_role_font_weight_changed(self, role: str, checked: bool):
        f_role = getattr(self.spec.font, role, None)
        if f_role is None:
            return
        f_role.weight = "bold" if checked else "normal"
        if role == "panel_label" and hasattr(self.spec.layout, "panel_labels"):
            self.spec.layout.panel_labels.weight = f_role.weight
        if not self._applying_style_preset:
            self.spec.metadata["style_preset"] = "Custom"
            if hasattr(self, "combo_style_preset"):
                self.combo_style_preset.setCurrentText("Custom")
        self._push_undo()
        self._update_preview()

    def _on_role_font_style_changed(self, role: str, checked: bool):
        f_role = getattr(self.spec.font, role, None)
        if f_role is None:
            return
        f_role.style = "italic" if checked else "normal"
        if not self._applying_style_preset:
            self.spec.metadata["style_preset"] = "Custom"
            if hasattr(self, "combo_style_preset"):
                self.combo_style_preset.setCurrentText("Custom")
        self._push_undo()
        self._update_preview()

    def _on_style_changed(self, *_):
        s = self.spec.style
        s.default_linewidth = float(self.spin_default_linewidth.value())
        s.axis_spine_width = float(self.spin_spine_width.value())
        s.tick_direction = self.combo_tick_dir.currentText()
        s.tick_major_length = float(self.spin_tick_major.value())
        s.tick_minor_length = float(self.spin_tick_minor.value())
        for graph in self.spec.graphs.values():
            graph.default_linewidth = s.default_linewidth
        if not self._applying_style_preset:
            self.spec.metadata["style_preset"] = "Custom"
            if hasattr(self, "combo_style_preset"):
                self.combo_style_preset.setCurrentText("Custom")
        self._push_undo()
        self._update_preview()

    def _on_apply_style_preset(self):
        name = self.combo_style_preset.currentText()
        preset = STYLE_PRESETS.get(name)
        if preset is None:
            return
        self._applying_style_preset = True
        apply_style_preset(self.spec, preset)
        self.spec.metadata["style_preset"] = name
        self._mark_export_profile_custom()
        self._push_undo()
        self._refresh_tabs()
        self._update_preview()
        self._applying_style_preset = False

    def _on_style_preset_changed(self, name: str):
        self._refresh_style_description(name)

    def _refresh_style_description(self, name: str | None = None):
        if not hasattr(self, "label_style_desc"):
            return
        preset_name = name or self.combo_style_preset.currentText()
        preset = STYLE_PRESETS.get(preset_name)
        if preset:
            self.label_style_desc.setText(preset.description)
        else:
            self.label_style_desc.setText("Custom style")

    def _refresh_export_profile_description(self, name: str | None = None):
        if not hasattr(self, "label_export_profile_desc"):
            return
        preset_name = name or self.combo_export_profile.currentText()
        preset = STYLE_PRESETS.get(preset_name)
        if preset:
            self.label_export_profile_desc.setText(preset.description)
        else:
            self.label_export_profile_desc.setText("Custom export profile")

    def _mark_export_profile_custom(self):
        """Mark export profile as custom when manual tweaks occur."""
        self.spec.metadata["export_profile"] = "Custom"
        if hasattr(self, "combo_export_profile"):
            self.combo_export_profile.blockSignals(True)
            self.combo_export_profile.setCurrentText("Custom")
            self.combo_export_profile.blockSignals(False)
            self._refresh_export_profile_description("Custom")

    def _update_width_status_label(self):
        if hasattr(self, "label_width_status"):
            self.label_width_status.setText(
                f"Current width: {self.spec.layout.width_in * 25.4:.1f} mm"
            )

    # ------------------------------------------------------------------
    # Traces & Events tab helpers
    # ------------------------------------------------------------------
    def _connect_traces_events_signals(self):
        self.combo_panel_select.currentIndexChanged.connect(
            self._on_panel_selector_changed
        )
        # Display
        self.cb_grid.toggled.connect(self._on_grid_toggled)
        self.cb_legend.toggled.connect(self._on_legend_toggled)
        self.combo_legend_loc.currentTextChanged.connect(self._on_legend_loc_changed)

        # Spines
        self.cb_spine_left.toggled.connect(lambda v: self._on_spine_toggled("left", v))
        self.cb_spine_right.toggled.connect(
            lambda v: self._on_spine_toggled("right", v)
        )
        self.cb_spine_top.toggled.connect(lambda v: self._on_spine_toggled("top", v))
        self.cb_spine_bottom.toggled.connect(
            lambda v: self._on_spine_toggled("bottom", v)
        )

        # Axes
        self.combo_x_scale.currentTextChanged.connect(
            lambda v: self._on_scale_changed("x", v)
        )
        self.combo_y_scale.currentTextChanged.connect(
            lambda v: self._on_scale_changed("y", v)
        )
        self.cb_x_auto.toggled.connect(lambda checked: self._on_axis_auto_toggled("x", checked))
        self.cb_y_auto.toggled.connect(lambda checked: self._on_axis_auto_toggled("y", checked))
        self.edit_x_min.editingFinished.connect(
            lambda: self._on_axis_limits_changed("x")
        )
        self.edit_x_max.editingFinished.connect(
            lambda: self._on_axis_limits_changed("x")
        )
        self.edit_y_min.editingFinished.connect(
            lambda: self._on_axis_limits_changed("y")
        )
        self.edit_y_max.editingFinished.connect(
            lambda: self._on_axis_limits_changed("y")
        )

        # Ticks
        self.spin_x_tick_every.valueChanged.connect(self._on_x_tick_interval_changed)
        self.spin_x_max_ticks.valueChanged.connect(self._on_x_max_ticks_changed)
        self.spin_y_max_ticks.valueChanged.connect(self._on_y_max_ticks_changed)

        # Events
        self.cb_show_event_lines.toggled.connect(self._on_show_event_lines_toggled)
        self.cb_show_event_labels.toggled.connect(self._on_show_event_labels_toggled)
        self.edit_event_color.editingFinished.connect(self._on_event_style_changed)
        self.spin_event_lw.valueChanged.connect(self._on_event_style_changed)
        self.combo_event_ls.currentTextChanged.connect(self._on_event_style_changed)
        self.spin_event_rotation.valueChanged.connect(self._on_event_style_changed)
        if self.event_times:
            self.spin_event_index.valueChanged.connect(self._on_event_index_changed)
            self.edit_event_label.editingFinished.connect(self._on_event_label_changed)

        # Traces
        self.cb_trace_inner.toggled.connect(lambda v: self._on_trace_toggle("inner", v))
        self.cb_trace_outer.toggled.connect(lambda v: self._on_trace_toggle("outer", v))
        self.cb_trace_avg_pressure.toggled.connect(
            lambda v: self._on_trace_toggle("avg_pressure", v)
        )
        self.cb_trace_set_pressure.toggled.connect(
            lambda v: self._on_trace_toggle("set_pressure", v)
        )
        self.cb_twin_y.toggled.connect(self._on_twin_y_toggled)
        self.edit_y2_label.editingFinished.connect(self._on_y2_label_changed)
        self.combo_y2_scale.currentTextChanged.connect(self._on_y2_scale_changed)
        self.edit_y2_min.editingFinished.connect(lambda: self._on_y2_limits_changed())
        self.edit_y2_max.editingFinished.connect(lambda: self._on_y2_limits_changed())

        # Trace styles
        self.combo_trace_select.currentTextChanged.connect(
            self._on_trace_style_target_changed
        )
        self.edit_trace_color.editingFinished.connect(self._on_trace_style_changed)
        self.spin_trace_lw.valueChanged.connect(self._on_trace_style_changed)
        self.combo_trace_ls.currentTextChanged.connect(self._on_trace_style_changed)
        self.combo_trace_marker.currentTextChanged.connect(self._on_trace_style_changed)

    def _with_graph_spec(self) -> GraphSpec | None:
        graph = self._get_active_graph_spec()
        return graph

    def _get_active_graph_and_axes(self):
        """Return (graph_spec, axes) for the selected panel, or (None, None)."""
        graph = self._get_active_graph_spec()
        if graph is None:
            return None, None

        inst_id = getattr(self, "selected_instance_id", None)
        if inst_id is None and self.spec.layout.graph_instances:
            inst_id = self.spec.layout.graph_instances[0].instance_id

        ax = None
        if inst_id is not None:
            ax = self._preview_axes_map.get(inst_id)
        return graph, ax

    def _refresh_traces_events_tab(self):
        if not hasattr(self, "combo_panel_select"):
            return
        graph, ax = self._get_active_graph_and_axes()
        if not graph:
            return

        widgets = [
            self.combo_panel_select,
            self.cb_grid,
            self.cb_legend,
            self.combo_legend_loc,
            self.cb_spine_left,
            self.cb_spine_right,
            self.cb_spine_top,
            self.cb_spine_bottom,
            self.combo_x_scale,
            self.combo_y_scale,
            self.cb_x_auto,
            self.cb_y_auto,
            self.edit_x_min,
            self.edit_x_max,
            self.edit_y_min,
            self.edit_y_max,
            self.spin_x_tick_every,
            self.spin_x_max_ticks,
            self.spin_y_max_ticks,
            self.cb_show_event_lines,
            self.cb_show_event_labels,
            self.edit_event_color,
            self.spin_event_lw,
            self.combo_event_ls,
            self.spin_event_rotation,
            self.cb_trace_inner,
            self.cb_trace_outer,
            self.cb_trace_avg_pressure,
            self.cb_trace_set_pressure,
            self.cb_twin_y,
            self.edit_y2_label,
            self.combo_y2_scale,
            self.edit_y2_min,
            self.edit_y2_max,
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

        # Panel selector
        self.combo_panel_select.clear()
        for idx, inst in enumerate(self.spec.layout.graph_instances):
            g = self.spec.graphs.get(inst.graph_id)
            label = f"{self._panel_label_from_index(idx)} – {g.name if g else inst.graph_id}"
            self.combo_panel_select.addItem(label, inst.instance_id)
        if self.spec.layout.graph_instances:
            if self.selected_instance_id is None:
                self.selected_instance_id = self.spec.layout.graph_instances[
                    0
                ].instance_id
            idx = self.combo_panel_select.findData(self.selected_instance_id)
            if idx < 0:
                idx = 0
                self.selected_instance_id = self.spec.layout.graph_instances[
                    0
                ].instance_id
            self.combo_panel_select.setCurrentIndex(idx)

        # Display
        self.cb_grid.setChecked(graph.grid)
        self.cb_legend.setChecked(graph.show_legend)
        idx = self.combo_legend_loc.findText(graph.legend_loc)
        if idx >= 0:
            self.combo_legend_loc.setCurrentIndex(idx)

        # Spines
        self.cb_spine_left.setChecked(graph.show_spines.get("left", True))
        self.cb_spine_right.setChecked(graph.show_spines.get("right", True))
        self.cb_spine_top.setChecked(graph.show_spines.get("top", False))
        self.cb_spine_bottom.setChecked(graph.show_spines.get("bottom", True))

        # Axes
        self._set_axis_controls(graph, ax)

        # Ticks
        self.spin_x_tick_every.setValue(
            0.0 if graph.x_tick_interval is None else graph.x_tick_interval
        )
        self.spin_x_max_ticks.setValue(
            0 if graph.x_max_ticks is None else graph.x_max_ticks
        )
        self.spin_y_max_ticks.setValue(
            0 if graph.y_max_ticks is None else graph.y_max_ticks
        )

        # Events
        self.cb_show_event_lines.setChecked(graph.show_event_markers)
        self.cb_show_event_labels.setChecked(graph.show_event_labels)
        self.edit_event_color.setText(graph.event_line_color)
        self.spin_event_lw.setValue(graph.event_line_width)
        ls_map_inv = {"-": "solid", "--": "dashed", ":": "dotted", "-.": "dashdot"}
        ls_display = ls_map_inv.get(graph.event_line_style, graph.event_line_style)
        idx = self.combo_event_ls.findText(ls_display)
        if idx >= 0:
            self.combo_event_ls.setCurrentIndex(idx)
        self.spin_event_rotation.setValue(graph.event_label_rotation)
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
        self.combo_y2_scale.setCurrentText(graph.y2_scale)
        self.edit_y2_min.setText("" if graph.y2_lim is None else str(graph.y2_lim[0]))
        self.edit_y2_max.setText("" if graph.y2_lim is None else str(graph.y2_lim[1]))
        for ctrl in [
            self.edit_y2_label,
            self.combo_y2_scale,
            self.edit_y2_min,
            self.edit_y2_max,
        ]:
            ctrl.setEnabled(graph.twin_y)

        self._refresh_trace_style_selector(graph)

        for w in widgets:
            w.blockSignals(False)

    def _parse_optional_float(self, text: str) -> float | None:
        text = text.strip()
        if text == "":
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _set_axis_auto_checkbox(self, axis: str, checked: bool):
        cb = self.cb_x_auto if axis == "x" else self.cb_y_auto
        if not cb:
            return
        cb.blockSignals(True)
        cb.setChecked(checked)
        cb.blockSignals(False)

    def _set_axis_controls(self, graph: GraphSpec, ax: Axes | None = None) -> None:
        """Update axis control widgets from a GraphSpec and optional live Axes."""
        controls = [
            self.combo_x_scale,
            self.combo_y_scale,
            self.cb_x_auto,
            self.cb_y_auto,
            self.edit_x_min,
            self.edit_x_max,
            self.edit_y_min,
            self.edit_y_max,
        ]
        for ctrl in controls:
            ctrl.blockSignals(True)

        self.combo_x_scale.setCurrentText(graph.x_scale)
        self.combo_y_scale.setCurrentText(graph.y_scale)

        if ax is not None:
            x_min, x_max = ax.get_xlim()
            y_min, y_max = ax.get_ylim()
        else:
            if graph.x_lim is not None:
                x_min, x_max = graph.x_lim
            else:
                x_min, x_max = 0.0, 0.0
            if graph.y_lim is not None:
                y_min, y_max = graph.y_lim
            else:
                y_min, y_max = 0.0, 0.0

        auto_x = graph.x_lim is None
        auto_y = graph.y_lim is None
        self.cb_x_auto.setChecked(auto_x)
        self.cb_y_auto.setChecked(auto_y)

        self.edit_x_min.setText(str(float(x_min)))
        self.edit_x_max.setText(str(float(x_max)))
        self.edit_y_min.setText(str(float(y_min)))
        self.edit_y_max.setText(str(float(y_max)))

        for ctrl in (self.edit_x_min, self.edit_x_max):
            ctrl.setEnabled(not auto_x)
        for ctrl in (self.edit_y_min, self.edit_y_max):
            ctrl.setEnabled(not auto_y)

        for ctrl in controls:
            ctrl.blockSignals(False)

    def _on_grid_toggled(self, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.grid = checked
        self._push_undo()
        self._update_preview()

    def _on_panel_selector_changed(self, idx: int):
        inst_id = self.combo_panel_select.itemData(idx)
        if not inst_id:
            return
        self.selected_instance_id = inst_id
        self._refresh_panel_table()
        self._refresh_traces_events_tab()
        self._update_preview()

    def _on_legend_toggled(self, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.show_legend = checked
        self._push_undo()
        self._update_preview()

    def _on_legend_loc_changed(self, loc: str):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.legend_loc = loc
        self._push_undo()
        self._update_preview()

    def _on_spine_toggled(self, spine: str, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.show_spines[spine] = checked
        self._push_undo()
        self._update_preview()

    def _on_scale_changed(self, axis: str, value: str):
        graph = self._with_graph_spec()
        if not graph:
            return
        if axis == "x":
            graph.x_scale = value
        else:
            graph.y_scale = value
        self._push_undo()
        self._update_preview()

    def _on_axis_auto_toggled(self, axis: str, checked: bool):
        graph = self._with_graph_spec()
        if not graph:
            return
        if axis == "x":
            if checked:
                graph.x_lim = None
            elif graph.x_lim is None:
                ax = self._preview_axes_map.get(self.selected_instance_id)
                if ax is not None:
                    graph.x_lim = tuple(map(float, ax.get_xlim()))
            for ctrl in (self.edit_x_min, self.edit_x_max):
                ctrl.setEnabled(not checked)
        else:
            if checked:
                graph.y_lim = None
            elif graph.y_lim is None:
                ax = self._preview_axes_map.get(self.selected_instance_id)
                if ax is not None:
                    graph.y_lim = tuple(map(float, ax.get_ylim()))
            for ctrl in (self.edit_y_min, self.edit_y_max):
                ctrl.setEnabled(not checked)
        self._push_undo()
        self._update_preview()
        self._refresh_traces_events_tab()

    def _on_axis_limits_changed(self, axis: str):
        graph = self._with_graph_spec()
        if not graph:
            return
        if axis == "x":
            vmin = self._parse_optional_float(self.edit_x_min.text())
            vmax = self._parse_optional_float(self.edit_x_max.text())
            graph.x_lim = None if vmin is None or vmax is None else (vmin, vmax)
            self._set_axis_auto_checkbox("x", graph.x_lim is None)
            for ctrl in (self.edit_x_min, self.edit_x_max):
                ctrl.setEnabled(graph.x_lim is not None)
        else:
            vmin = self._parse_optional_float(self.edit_y_min.text())
            vmax = self._parse_optional_float(self.edit_y_max.text())
            graph.y_lim = None if vmin is None or vmax is None else (vmin, vmax)
            self._set_axis_auto_checkbox("y", graph.y_lim is None)
            for ctrl in (self.edit_y_min, self.edit_y_max):
                ctrl.setEnabled(graph.y_lim is not None)
        self._push_undo()
        self._update_preview()

    def _on_x_tick_interval_changed(self, value: float):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.x_tick_interval = None if value <= 0 else float(value)
        self._push_undo()
        self._update_preview()

    def _on_x_max_ticks_changed(self, value: int):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.x_max_ticks = None if value == 0 else int(value)
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
        ls_map = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-."}
        graph.event_line_style = ls_map.get(
            self.combo_event_ls.currentText(), self.combo_event_ls.currentText()
        )
        graph.event_label_rotation = float(self.spin_event_rotation.value())
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
                    bindings.append(TraceBinding(name=k, kind=k))
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
        self._refresh_traces_events_tab()
        self._update_preview()

    def _on_y2_label_changed(self):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.y2_label = self.edit_y2_label.text()
        self._push_undo()
        self._update_preview()

    def _on_y2_scale_changed(self, scale: str):
        graph = self._with_graph_spec()
        if not graph:
            return
        graph.y2_scale = scale
        self._push_undo()
        self._update_preview()

    def _on_y2_limits_changed(self):
        graph = self._with_graph_spec()
        if not graph:
            return
        ymin = self._parse_optional_float(self.edit_y2_min.text())
        ymax = self._parse_optional_float(self.edit_y2_max.text())
        graph.y2_lim = None if ymin is None or ymax is None else (ymin, ymax)
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
        self.combo_trace_ls.setCurrentText(
            ls_map_inv.get(style.get("linestyle", "-"), "solid")
        )
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

    def _on_export_format_changed(self, fmt: str):
        self.spec.export.format = fmt
        self._mark_export_profile_custom()
        self._push_undo()
        self._update_footer()

    def _on_export_dpi_changed(self, dpi: int):
        self.spec.export.dpi = int(dpi)
        self._mark_export_profile_custom()
        self._push_undo()
        self._update_footer()

    def _on_export_bg_changed(self, checked: bool):
        # Radio buttons share the slot; transparent is tied to radio_bg_transparent
        btn = getattr(self, "radio_bg_transparent", None)
        if btn is None:
            return
        self.spec.export.transparent = btn.isChecked()
        self._push_undo()
        self._update_preview()

    def _on_apply_export_profile(self):
        name = self.combo_export_profile.currentText()
        preset = STYLE_PRESETS.get(name)
        if preset:
            apply_style_preset(self.spec, preset)
        self.spec.export.format = "pdf"
        self.spec.metadata["export_profile"] = name
        self.combo_export_profile.setCurrentText(name)
        self._refresh_export_profile_description(name)
        self._push_undo()
        self._refresh_tabs()
        self._update_preview()

    def _on_extra_export_changed(self, *_):
        self.spec.metadata["extra_export_png"] = self.cb_export_png.isChecked()
        self.spec.metadata["extra_export_tiff"] = self.cb_export_tiff.isChecked()
        self._push_undo()

    def _on_width_preset_mm(self, mm: int):
        inches = mm / 25.4
        self.spec.layout.width_in = inches
        self.spec.layout.height_in = max(self.spec.layout.height_in, 1.0)
        if hasattr(self, "spin_width"):
            self.spin_width.setValue(inches)
        self._mark_export_profile_custom()
        self._update_width_status_label()
        self._push_undo()
        self._update_preview()

    def _refresh_tabs(self):
        """Sync Qt controls with current spec."""
        self._refresh_layout_tab()
        if hasattr(self, "combo_font_family"):
            self.combo_font_family.blockSignals(True)
            self.combo_font_family.setCurrentText(self.spec.font.family)
            self.combo_font_family.blockSignals(False)
            if hasattr(self, "font_role_controls"):
                for role, controls in self.font_role_controls.items():
                    role_font = getattr(self.spec.font, role, None)
                    if role_font is None:
                        continue
                    for w in controls.values():
                        w.blockSignals(True)
                    controls["spin"].setValue(role_font.size)
                    controls["bold"].setChecked(role_font.weight == "bold")
                    controls["italic"].setChecked(
                        role_font.style in ("italic", "oblique")
                    )
                    for w in controls.values():
                        w.blockSignals(False)
        if hasattr(self, "spin_default_linewidth"):
            style_widgets = [
                self.spin_default_linewidth,
                self.spin_spine_width,
                self.combo_tick_dir,
                self.spin_tick_major,
                self.spin_tick_minor,
            ]
            for w in style_widgets:
                w.blockSignals(True)
            self.spin_default_linewidth.setValue(self.spec.style.default_linewidth)
            self.spin_spine_width.setValue(self.spec.style.axis_spine_width)
            self.combo_tick_dir.setCurrentText(self.spec.style.tick_direction)
            self.spin_tick_major.setValue(self.spec.style.tick_major_length)
            self.spin_tick_minor.setValue(self.spec.style.tick_minor_length)
            for w in style_widgets:
                w.blockSignals(False)
            if hasattr(self, "combo_style_preset"):
                preset_name = self.spec.metadata.get("style_preset", "Custom")
                if preset_name not in STYLE_PRESETS:
                    preset_name = "Custom"
                self.combo_style_preset.setCurrentText(preset_name)
                self._refresh_style_description(preset_name)
        self._refresh_traces_events_tab()
        if hasattr(self, "combo_format"):
            self.combo_format.blockSignals(True)
            self.spin_dpi.blockSignals(True)
            self.combo_format.setCurrentText(self.spec.export.format)
            self.spin_dpi.setValue(self.spec.export.dpi)
            self.combo_format.blockSignals(False)
            self.spin_dpi.blockSignals(False)
        if hasattr(self, "radio_bg_transparent"):
            self.radio_bg_white.blockSignals(True)
            self.radio_bg_transparent.blockSignals(True)
            self.radio_bg_transparent.setChecked(self.spec.export.transparent)
            self.radio_bg_white.setChecked(not self.spec.export.transparent)
            self.radio_bg_white.blockSignals(False)
            self.radio_bg_transparent.blockSignals(False)
        if hasattr(self, "combo_export_profile"):
            profile = self.spec.metadata.get("export_profile", "Lab default")
            if profile not in [
                "Lab default",
                "Journal single-column",
                "Journal double-column",
                "Custom",
            ]:
                profile = "Custom"
            self.combo_export_profile.setCurrentText(profile)
            self._refresh_export_profile_description(profile)
        if hasattr(self, "cb_export_png"):
            self.cb_export_png.blockSignals(True)
            self.cb_export_tiff.blockSignals(True)
            self.cb_export_png.setChecked(
                bool(self.spec.metadata.get("extra_export_png", False))
            )
            self.cb_export_tiff.setChecked(
                bool(self.spec.metadata.get("extra_export_tiff", False))
            )
            self.cb_export_png.blockSignals(False)
            self.cb_export_tiff.blockSignals(False)
        self._update_width_status_label()
        self._refresh_annotation_ui()

    # ------------------------------------------------------------------
    # Annotation tab helpers
    # ------------------------------------------------------------------
    def _connect_annotation_signals(self):
        self.list_annotations.currentItemChanged.connect(
            self._on_annotation_list_selection
        )
        self.btn_annot_delete.clicked.connect(self._on_annotation_delete)
        self.btn_annot_duplicate.clicked.connect(self._on_annotation_duplicate)

        # Text
        self.edit_annot_text.textChanged.connect(self._on_annotation_text_changed)
        self.spin_annot_font.valueChanged.connect(self._on_annotation_font_changed)
        self.combo_annot_weight.currentTextChanged.connect(
            self._on_annotation_font_changed
        )
        self.combo_annot_style.currentTextChanged.connect(
            self._on_annotation_font_changed
        )
        self.edit_annot_color.editingFinished.connect(
            self._on_annotation_text_style_changed
        )
        self.combo_annot_ha.currentTextChanged.connect(
            self._on_annotation_text_style_changed
        )
        self.combo_annot_va.currentTextChanged.connect(
            self._on_annotation_text_style_changed
        )
        self.spin_annot_rotation.valueChanged.connect(
            self._on_annotation_text_style_changed
        )

        # Box / line
        self.edit_annot_edgecolor.editingFinished.connect(
            self._on_annotation_boxline_changed
        )
        self.edit_annot_facecolor.editingFinished.connect(
            self._on_annotation_boxline_changed
        )
        self.spin_annot_alpha.valueChanged.connect(self._on_annotation_boxline_changed)
        self.spin_annot_linewidth.valueChanged.connect(
            self._on_annotation_boxline_changed
        )
        self.combo_annot_linestyle.currentTextChanged.connect(
            self._on_annotation_boxline_changed
        )

        # Arrow
        self.combo_annot_arrowstyle.currentTextChanged.connect(
            self._on_annotation_arrow_changed
        )

        # Defaults
        self.spin_default_annot_font.valueChanged.connect(
            self._on_annotation_defaults_changed
        )
        self.combo_default_annot_weight.currentTextChanged.connect(
            self._on_annotation_defaults_changed
        )
        self.combo_default_annot_style.currentTextChanged.connect(
            self._on_annotation_defaults_changed
        )
        self.edit_default_annot_color.editingFinished.connect(
            self._on_annotation_defaults_changed
        )
        self.edit_default_edgecolor.editingFinished.connect(
            self._on_annotation_defaults_changed
        )
        self.edit_default_facecolor.editingFinished.connect(
            self._on_annotation_defaults_changed
        )
        self.spin_default_alpha.valueChanged.connect(
            self._on_annotation_defaults_changed
        )
        self.spin_default_linewidth.valueChanged.connect(
            self._on_annotation_defaults_changed
        )
        self.combo_default_linestyle.currentTextChanged.connect(
            self._on_annotation_defaults_changed
        )

    def _annotation_display_label(self, annot: AnnotationSpec) -> str:
        prefix = {
            "text": "[T]",
            "box": "[□]",
            "arrow": "[→]",
            "line": "[—]",
        }.get(annot.kind, "[?]")
        text = (annot.text_content or "").strip().replace("\n", " ")
        if text:
            text = (text[:30] + "…") if len(text) > 30 else text
            return f"{prefix} {text}"
        return f"{prefix} {annot.annotation_id[:6]}"

    def _annotation_defaults(self) -> dict[str, Any]:
        annot_font = getattr(self.spec.font, "annotation", None)
        defaults = {
            "font_size": getattr(
                annot_font, "size", getattr(self.spec.font, "annotation_size", 8.0)
            ),
            "font_weight": getattr(annot_font, "weight", "normal"),
            "font_style": getattr(annot_font, "style", "normal"),
            "color": "#000000",
            "edgecolor": "#000000",
            "facecolor": "none",
            "alpha": 1.0,
            "linewidth": 1.0,
            "linestyle": "solid",
        }
        stored = self.spec.metadata.get("annotation_defaults")
        if isinstance(stored, dict):
            defaults.update({k: v for k, v in stored.items() if k in defaults})
        return defaults

    def _get_annotation_by_id(self, annot_id: str | None) -> AnnotationSpec | None:
        if annot_id is None:
            return None
        return next(
            (a for a in self.spec.annotations if a.annotation_id == annot_id), None
        )

    def _get_selected_annotation(self) -> AnnotationSpec | None:
        return self._get_annotation_by_id(self.selected_annotation_id)

    def _refresh_annotation_list(self):
        if not hasattr(self, "list_annotations"):
            return
        self.list_annotations.blockSignals(True)
        self.list_annotations.clear()
        for annot in self.spec.annotations:
            item = QListWidgetItem(self._annotation_display_label(annot))
            item.setData(Qt.UserRole, annot.annotation_id)
            self.list_annotations.addItem(item)
            if annot.annotation_id == self.selected_annotation_id:
                item.setSelected(True)
        self.list_annotations.blockSignals(False)

    def _refresh_annotation_editor(self):
        if not hasattr(self, "group_style"):
            return
        annot = self._get_selected_annotation()
        enabled = annot is not None
        self.group_style.setEnabled(enabled)
        if not enabled:
            return

        # Block signals during populate
        blockers = [
            self.edit_annot_text,
            self.spin_annot_font,
            self.combo_annot_weight,
            self.combo_annot_style,
            self.edit_annot_color,
            self.combo_annot_ha,
            self.combo_annot_va,
            self.spin_annot_rotation,
            self.edit_annot_edgecolor,
            self.edit_annot_facecolor,
            self.spin_annot_alpha,
            self.spin_annot_linewidth,
            self.combo_annot_linestyle,
            self.combo_annot_arrowstyle,
        ]
        for w in blockers:
            w.blockSignals(True)

        # Text
        self.edit_annot_text.setPlainText(annot.text_content or "")
        self.spin_annot_font.setValue(annot.font_size)
        self.combo_annot_weight.setCurrentText(annot.font_weight)
        self.combo_annot_style.setCurrentText(annot.font_style)
        self.edit_annot_color.setText(annot.color or "")
        self.combo_annot_ha.setCurrentText(annot.ha)
        self.combo_annot_va.setCurrentText(annot.va)
        self.spin_annot_rotation.setValue(annot.rotation)

        # Box/line
        self.edit_annot_edgecolor.setText(annot.edgecolor or "")
        self.edit_annot_facecolor.setText(annot.facecolor or "")
        self.spin_annot_alpha.setValue(annot.alpha)
        self.spin_annot_linewidth.setValue(annot.linewidth)
        ls_map_inv = {"-": "solid", "--": "dashed", ":": "dotted", "-.": "dashdot"}
        self.combo_annot_linestyle.setCurrentText(
            ls_map_inv.get(annot.linestyle, "solid")
        )

        # Arrow
        self.combo_annot_arrowstyle.setCurrentText(annot.arrowstyle or "->")

        for w in blockers:
            w.blockSignals(False)

        # Enable/disable groups based on kind
        is_text = annot.kind in ("text", "arrow")
        is_boxline = annot.kind in ("box", "line", "arrow")
        self.edit_annot_text.setEnabled(is_text)
        self.spin_annot_font.setEnabled(is_text)
        self.combo_annot_weight.setEnabled(is_text)
        self.combo_annot_style.setEnabled(is_text)
        self.edit_annot_color.setEnabled(True)
        self.combo_annot_ha.setEnabled(is_text)
        self.combo_annot_va.setEnabled(is_text)
        self.spin_annot_rotation.setEnabled(is_text)
        self.spin_annot_linewidth.setEnabled(is_boxline or annot.kind == "arrow")
        self.combo_annot_linestyle.setEnabled(is_boxline or annot.kind == "arrow")
        self.edit_annot_edgecolor.setEnabled(is_boxline)
        self.edit_annot_facecolor.setEnabled(annot.kind in ("box", "arrow"))
        self.spin_annot_alpha.setEnabled(is_boxline or is_text)
        self.combo_annot_arrowstyle.setEnabled(annot.kind == "arrow")

    def _refresh_annotation_defaults_ui(self):
        defaults = self._annotation_defaults()
        widgets = [
            self.spin_default_annot_font,
            self.combo_default_annot_weight,
            self.combo_default_annot_style,
            self.edit_default_annot_color,
            self.edit_default_edgecolor,
            self.edit_default_facecolor,
            self.spin_default_alpha,
            self.spin_default_linewidth,
            self.combo_default_linestyle,
        ]
        for w in widgets:
            w.blockSignals(True)
        self.spin_default_annot_font.setValue(
            defaults.get(
                "font_size",
                getattr(getattr(self.spec.font, "annotation", None), "size", 8.0),
            )
        )
        self.combo_default_annot_weight.setCurrentText(
            defaults.get(
                "font_weight",
                getattr(
                    getattr(self.spec.font, "annotation", None), "weight", "normal"
                ),
            )
        )
        self.combo_default_annot_style.setCurrentText(
            defaults.get(
                "font_style",
                getattr(getattr(self.spec.font, "annotation", None), "style", "normal"),
            )
        )
        self.edit_default_annot_color.setText(defaults.get("color", "#000000"))
        self.edit_default_edgecolor.setText(defaults.get("edgecolor", "#000000"))
        self.edit_default_facecolor.setText(defaults.get("facecolor", "none"))
        self.spin_default_alpha.setValue(float(defaults.get("alpha", 1.0)))
        self.spin_default_linewidth.setValue(float(defaults.get("linewidth", 1.0)))
        ls_map_inv = {"-": "solid", "--": "dashed", ":": "dotted", "-.": "dashdot"}
        self.combo_default_linestyle.setCurrentText(
            ls_map_inv.get(
                defaults.get("linestyle", "solid"), defaults.get("linestyle", "solid")
            )
        )
        for w in widgets:
            w.blockSignals(False)

    def _refresh_annotation_ui(self):
        self._refresh_annotation_list()
        self._refresh_annotation_editor()
        self._refresh_annotation_defaults_ui()
        # Compatibility with legacy callers

    def _refresh_annotation_controls(self):
        self._refresh_annotation_ui()

    def _on_annotation_list_selection(
        self, current: QListWidgetItem, previous: QListWidgetItem | None
    ):
        self.selected_annotation_id = current.data(Qt.UserRole) if current else None
        self._refresh_annotation_editor()

    def _on_annotation_delete(self):
        self._delete_selected_annotation()

    def _on_annotation_duplicate(self):
        annot = self._get_selected_annotation()
        if not annot:
            return
        new_annot = copy.deepcopy(annot)
        new_annot.annotation_id = str(uuid.uuid4())
        new_annot.x0 += 0.02
        new_annot.x1 += 0.02
        new_annot.y0 -= 0.02
        new_annot.y1 -= 0.02
        self.spec.annotations.append(new_annot)
        self.selected_annotation_id = new_annot.annotation_id
        self._push_undo()
        self._refresh_annotation_ui()
        self._create_annotation_artists_for_preview(new_annot)
        self.canvas.draw_idle()

    def _on_annotation_text_changed(self):
        annot = self._get_selected_annotation()
        if not annot:
            return
        annot.text_content = self.edit_annot_text.toPlainText()
        self._refresh_annotation_list()
        self._update_annotation_artists_from_spec(annot)
        self.canvas.draw_idle()

    def _on_annotation_font_changed(self, *_):
        annot = self._get_selected_annotation()
        if not annot:
            return
        annot.font_size = float(self.spin_annot_font.value())
        annot.font_weight = self.combo_annot_weight.currentText()
        annot.font_style = self.combo_annot_style.currentText()
        self._push_undo()
        self._update_annotation_artists_from_spec(annot)
        self.canvas.draw_idle()

    def _on_annotation_text_style_changed(self, *_):
        annot = self._get_selected_annotation()
        if not annot:
            return
        color = self.edit_annot_color.text().strip()
        if color:
            annot.color = color
        annot.ha = self.combo_annot_ha.currentText()
        annot.va = self.combo_annot_va.currentText()
        annot.rotation = float(self.spin_annot_rotation.value())
        self._push_undo()
        self._update_annotation_artists_from_spec(annot)
        self.canvas.draw_idle()

    def _on_annotation_boxline_changed(self, *_):
        annot = self._get_selected_annotation()
        if not annot:
            return
        edge = self.edit_annot_edgecolor.text().strip()
        face = self.edit_annot_facecolor.text().strip()
        if edge:
            annot.edgecolor = edge
        if face:
            annot.facecolor = face
        annot.alpha = float(self.spin_annot_alpha.value())
        annot.linewidth = float(self.spin_annot_linewidth.value())
        ls_map = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-."}
        annot.linestyle = ls_map.get(self.combo_annot_linestyle.currentText(), "-")
        self._push_undo()
        self._update_annotation_artists_from_spec(annot)
        self.canvas.draw_idle()

    def _on_annotation_arrow_changed(self, *_):
        annot = self._get_selected_annotation()
        if not annot:
            return
        annot.arrowstyle = self.combo_annot_arrowstyle.currentText()
        self._push_undo()
        self._update_annotation_artists_from_spec(annot)
        self.canvas.draw_idle()

    def _on_annotation_defaults_changed(self, *_):
        ls_map = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-."}
        defaults = {
            "font_size": float(self.spin_default_annot_font.value()),
            "font_weight": self.combo_default_annot_weight.currentText(),
            "font_style": self.combo_default_annot_style.currentText(),
            "color": self.edit_default_annot_color.text().strip() or "#000000",
            "edgecolor": self.edit_default_edgecolor.text().strip() or "#000000",
            "facecolor": self.edit_default_facecolor.text().strip() or "none",
            "alpha": float(self.spin_default_alpha.value()),
            "linewidth": float(self.spin_default_linewidth.value()),
            "linestyle": ls_map.get(
                self.combo_default_linestyle.currentText(), "solid"
            ),
        }
        self.spec.metadata["annotation_defaults"] = defaults
        self._push_undo()

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
        if self.selected_instance_id:
            inst = self._get_graph_instance(self.selected_instance_id)
        if inst is None and self.spec.layout.graph_instances:
            inst = self.spec.layout.graph_instances[0]
            self.selected_instance_id = inst.instance_id
        if inst is None:
            return next(iter(self.spec.graphs.values()), None)
        graph = self.spec.graphs.get(inst.graph_id)
        if graph is None and self.spec.graphs:
            graph = next(iter(self.spec.graphs.values()))
        return graph

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
                self._push_undo()
                self._update_annotation_artists_from_spec(annot)
                self.canvas.draw_idle()
                break

    def _update_export_property(self, prop, value):
        """Update an export spec property."""
        setattr(self.spec.export, prop, value)
        self._update_footer()
        self.canvas.draw_idle()

    def _refocus_self(self):
        """Bring this window back to the front after dialogs."""
        try:
            self.raise_()
            self.activateWindow()
            self.setFocus(Qt.ActiveWindowFocusReason)
        except Exception:
            pass

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

    def _clear_annotation_artists(self):
        """Remove all live annotation artists from the preview."""
        for artists in self._annotation_artists.values():
            for art in artists:
                try:
                    art.remove()
                except Exception:
                    pass
        self._annotation_artists.clear()

    def _create_annotation_artists_for_preview(self, annot: AnnotationSpec):
        artists = create_annotation_artists(
            self.ui_figure,
            self._preview_axes_map,
            annot,
            figure_transform=self._annotation_overlay_ax.transAxes,
            figure_axes=self._annotation_overlay_ax,
        )
        self._annotation_artists[annot.annotation_id] = artists

    def _connect_events(self):
        """Connect Matplotlib events."""
        self.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_motion)
        self.canvas.mpl_connect("key_press_event", self._on_key_press)

    def _sync_annotation_overlay_limits(self, *_):
        """Keep the overlay axes aligned with the preview view limits."""
        if not getattr(self, "_annotation_overlay_ax", None):
            return
        self._annotation_overlay_ax.set_xlim(self.preview_ax.get_xlim())
        self._annotation_overlay_ax.set_ylim(self.preview_ax.get_ylim())

    def _sync_axes_limits_from_view(self, ax):
        """Persist the current view limits of a preview axis back to the FigureSpec."""
        inst_id = self._axes_instance_lookup.get(ax)
        if inst_id is None:
            return
        inst = self._get_graph_instance(inst_id)
        if inst is None:
            return
        graph = self.spec.graphs.get(inst.graph_id)
        if graph is None:
            return

        new_x_lim = tuple(map(float, ax.get_xlim()))
        new_y_lim = tuple(map(float, ax.get_ylim()))

        changed = False
        if graph.x_lim != new_x_lim:
            graph.x_lim = new_x_lim
            changed = True
        if graph.y_lim != new_y_lim:
            graph.y_lim = new_y_lim
            changed = True

        if changed:
            self._push_undo()
            self._update_footer()
            if inst_id == self.selected_instance_id:
                self._set_axis_controls(graph, ax)

    def _on_nav_view_changed(self):
        """Handle pan/zoom/home/back/forward updates from the navigation toolbar."""
        graph, ax = self._get_active_graph_and_axes()
        if graph is None or ax is None:
            return
        self._sync_axes_limits_from_view(ax)
        self._refresh_traces_events_tab()

    def _event_in_preview(self, event) -> bool:
        """Return True if event occurred inside the preview/page bbox."""
        bbox = self.preview_ax.get_window_extent()
        return bbox.contains(event.x, event.y)

    def _event_to_page_fraction(self, event) -> tuple[float, float]:
        """Convert an event position to page-relative 0-1 coordinates."""
        inv = self.preview_ax.transData.inverted()
        x_page, y_page = inv.transform((event.x, event.y))
        width = max(self.preview_ax.get_xlim()[1] - self.preview_ax.get_xlim()[0], 1e-6)
        height = max(
            self.preview_ax.get_ylim()[1] - self.preview_ax.get_ylim()[0], 1e-6
        )
        return x_page / width, y_page / height

    def _instance_id_at_event(self, event) -> str | None:
        """Return graph instance id under the event, if any."""
        for inst_id, ax in self._preview_axes_map.items():
            try:
                if ax.bbox.contains(event.x, event.y):
                    return inst_id
            except Exception:
                continue
        return None

    def _annotation_transform_for_preview(self, annot: AnnotationSpec):
        """Return transform/target used to draw an annotation in preview."""
        figure_transform = self._annotation_overlay_ax.transAxes
        figure_axes = self._annotation_overlay_ax
        ax = None
        if annot.target_type == "graph" and annot.target_id:
            ax = self._preview_axes_map.get(annot.target_id)
        if ax is None:
            return figure_transform, figure_axes
        if annot.coord_system == "axes":
            return ax.transAxes, ax
        if annot.coord_system == "figure":
            return figure_transform, figure_axes
        return ax.transData, ax

    def _event_to_annotation_coords(
        self, event, annot: AnnotationSpec
    ) -> tuple[float, float]:
        """Convert an event position into an annotation's coordinate system."""
        transform, _ = self._annotation_transform_for_preview(annot)
        inv = transform.inverted()
        return inv.transform((event.x, event.y))

    def _hit_test_annotations(self, event) -> str | None:
        """Return annotation id if event hits an annotation artist."""
        for annot_id, artists in reversed(list(self._annotation_artists.items())):
            for art in artists:
                try:
                    contains, _ = art.contains(event)
                except Exception:
                    continue
                if contains:
                    return annot_id
        return None

    def _remove_annotation_artists(self, annot_id: str):
        """Remove artists for an annotation id."""
        artists = self._annotation_artists.pop(annot_id, [])
        for art in artists:
            try:
                art.remove()
            except Exception:
                pass

    def _update_annotation_artists_from_spec(self, annot: AnnotationSpec):
        """Sync live artists with the current AnnotationSpec values."""
        artists = self._annotation_artists.get(annot.annotation_id)
        if not artists:
            return

        transform, _ = self._annotation_transform_for_preview(annot)
        if annot.kind == "text":
            for art in artists:
                art.set_position((annot.x0, annot.y0))
                art.set_text(annot.text_content)
                art.set_fontsize(annot.font_size)
                art.set_fontfamily(annot.font_family)
                art.set_fontstyle(annot.font_style)
                art.set_fontweight(annot.font_weight)
                art.set_color(annot.color)
                art.set_ha(annot.ha)
                art.set_va(annot.va)
                art.set_rotation(annot.rotation)
                art.set_alpha(annot.alpha)
                art.set_transform(transform)
        elif annot.kind == "box":
            for art in artists:
                if hasattr(art, "set_transform"):
                    art.set_transform(transform)
                if hasattr(art, "set_xy"):
                    art.set_xy((min(annot.x0, annot.x1), min(annot.y0, annot.y1)))
                if hasattr(art, "set_width"):
                    art.set_width(abs(annot.x1 - annot.x0))
                if hasattr(art, "set_height"):
                    art.set_height(abs(annot.y1 - annot.y0))
                if hasattr(art, "set_edgecolor"):
                    art.set_edgecolor(annot.edgecolor)
                if hasattr(art, "set_facecolor"):
                    art.set_facecolor(annot.facecolor)
                if hasattr(art, "set_alpha"):
                    art.set_alpha(annot.alpha)
                if hasattr(art, "set_linewidth"):
                    art.set_linewidth(annot.linewidth)
                if hasattr(art, "set_linestyle"):
                    art.set_linestyle(annot.linestyle)
        elif annot.kind == "arrow":
            for art in artists:
                try:
                    art.xy = (annot.x1, annot.y1)
                    art.set_position((annot.x0, annot.y0))
                    art.set_transform(transform)
                except Exception:
                    pass
                arrow_patch = getattr(art, "arrow_patch", None)
                target_patch = arrow_patch if arrow_patch is not None else art
                if hasattr(target_patch, "set_color"):
                    target_patch.set_color(annot.color)
                if hasattr(target_patch, "set_linewidth"):
                    target_patch.set_linewidth(annot.linewidth)
                if hasattr(target_patch, "set_alpha"):
                    target_patch.set_alpha(annot.alpha)
                if hasattr(target_patch, "set_arrowstyle"):
                    try:
                        target_patch.set_arrowstyle(annot.arrowstyle)
                    except Exception:
                        pass
        elif annot.kind == "line":
            for art in artists:
                if hasattr(art, "set_data"):
                    art.set_data([annot.x0, annot.x1], [annot.y0, annot.y1])
                if hasattr(art, "set_transform"):
                    art.set_transform(transform)
                if hasattr(art, "set_color"):
                    art.set_color(annot.color)
                if hasattr(art, "set_linewidth"):
                    art.set_linewidth(annot.linewidth)
                if hasattr(art, "set_linestyle"):
                    art.set_linestyle(annot.linestyle)
                if hasattr(art, "set_alpha"):
                    art.set_alpha(annot.alpha)

    def _on_mouse_press(self, event):
        """Handle mouse press for annotation creation/selection."""
        toolbar = getattr(self, "nav_toolbar", None)
        if toolbar is not None and getattr(toolbar, "mode", ""):
            return

        if not self._event_in_preview(event):
            return

        inst_id = self._instance_id_at_event(event)
        if inst_id and inst_id != self.selected_instance_id:
            self.selected_instance_id = inst_id
            if hasattr(self, "combo_panel_select"):
                self._refresh_traces_events_tab()

        x_norm, y_norm = self._event_to_page_fraction(event)

        if self.annotation_mode == "select":
            hit_id = self._hit_test_annotations(event)
            if hit_id:
                self.selected_annotation_id = hit_id
                self._dragging_annotation_id = hit_id
                self._dragging_mode = "moving"
                annot = self._get_annotation_by_id(hit_id)
                if annot:
                    start_x, start_y = self._event_to_annotation_coords(event, annot)
                    self._drag_start_data = {
                        "start_event": (start_x, start_y),
                        "coords": (annot.x0, annot.y0, annot.x1, annot.y1),
                    }
                self._refresh_annotation_ui()
            else:
                self.selected_annotation_id = None
                self._dragging_annotation_id = None
                self._dragging_mode = None
                self._drag_start_data = None
                self._refresh_annotation_ui()
            self.canvas.draw_idle()
        elif self.annotation_mode == "delete":
            hit_id = self._hit_test_annotations(event)
            if hit_id:
                self._remove_annotation_artists(hit_id)
                self.spec.annotations = [
                    a for a in self.spec.annotations if a.annotation_id != hit_id
                ]
                if self.selected_annotation_id == hit_id:
                    self.selected_annotation_id = None
                self._dragging_annotation_id = None
                self._dragging_mode = None
                self._drag_start_data = None
                self._push_undo()
                self._refresh_annotation_ui()
                self.canvas.draw_idle()
        elif self.annotation_mode == "text":
            defaults = self._annotation_defaults()
            annot = AnnotationSpec(
                annotation_id=str(uuid.uuid4()),
                kind="text",
                target_type="figure",
                coord_system="axes",
                x0=x_norm,
                y0=y_norm,
                text_content="Text",
                font_size=defaults.get(
                    "font_size",
                    getattr(getattr(self.spec.font, "annotation", None), "size", 8.0),
                ),
                font_weight=defaults.get(
                    "font_weight",
                    getattr(
                        getattr(self.spec.font, "annotation", None), "weight", "normal"
                    ),
                ),
                font_style=defaults.get(
                    "font_style",
                    getattr(
                        getattr(self.spec.font, "annotation", None), "style", "normal"
                    ),
                ),
                color=defaults.get("color", "#000000"),
                edgecolor=defaults.get("edgecolor", "#000000"),
                facecolor=defaults.get("facecolor", "none"),
                linewidth=defaults.get("linewidth", 1.0),
                linestyle=defaults.get("linestyle", "solid"),
                alpha=float(defaults.get("alpha", 1.0)),
            )
            self.spec.annotations.append(annot)
            self._create_annotation_artists_for_preview(annot)
            self.selected_annotation_id = annot.annotation_id
            self._push_undo()
            self._refresh_annotation_ui()
            self.canvas.draw_idle()
        elif self.annotation_mode in ("box", "arrow", "line"):
            defaults = self._annotation_defaults()
            new_annot = AnnotationSpec(
                annotation_id=str(uuid.uuid4()),
                kind=self.annotation_mode,
                target_type="figure",
                coord_system="axes",
                x0=x_norm,
                y0=y_norm,
                x1=x_norm,
                y1=y_norm,
                color=defaults.get("color", "#000000"),
                edgecolor=defaults.get("edgecolor", "#000000"),
                facecolor=defaults.get("facecolor", "none"),
                linewidth=defaults.get("linewidth", 1.0),
                linestyle=defaults.get("linestyle", "solid"),
                alpha=float(defaults.get("alpha", 1.0)),
            )
            self.spec.annotations.append(new_annot)
            self._create_annotation_artists_for_preview(new_annot)
            self.selected_annotation_id = new_annot.annotation_id
            self._dragging_annotation_id = new_annot.annotation_id
            self._dragging_mode = "creating"
            self._drag_start_data = (new_annot.x0, new_annot.y0)
            self._refresh_annotation_ui()
            self.canvas.draw_idle()

    def _on_mouse_release(self, event):
        """Handle mouse release to finalize annotation creation/move."""
        toolbar = getattr(self, "nav_toolbar", None)
        if toolbar is not None and getattr(toolbar, "mode", ""):
            return

        if self._dragging_mode == "creating":
            annot = self._get_annotation_by_id(self._dragging_annotation_id)
            if annot:
                self._update_annotation_artists_from_spec(annot)
            self._dragging_annotation_id = None
            self._dragging_mode = None
            self._drag_start_data = None
            self._push_undo()
            self._refresh_annotation_ui()
            self.canvas.draw_idle()
        elif self._dragging_mode == "moving":
            annot = self._get_annotation_by_id(self._dragging_annotation_id)
            start_coords = None
            if isinstance(self._drag_start_data, dict):
                start_coords = self._drag_start_data.get("coords")
            moved = False
            if annot and start_coords:
                if annot.kind in ("box", "arrow", "line"):
                    moved = any(
                        abs(a - b) > 1e-9
                        for a, b in zip(
                            start_coords, (annot.x0, annot.y0, annot.x1, annot.y1)
                        )
                    )
                else:
                    moved = (
                        abs(start_coords[0] - annot.x0) > 1e-9
                        or abs(start_coords[1] - annot.y0) > 1e-9
                    )
            self._dragging_annotation_id = None
            self._dragging_mode = None
            self._drag_start_data = None
            if moved:
                self._push_undo()
                self._refresh_annotation_ui()
            self.canvas.draw_idle()

    def _on_mouse_motion(self, event):
        """Handle mouse motion for drag operations."""
        toolbar = getattr(self, "nav_toolbar", None)
        if toolbar is not None and getattr(toolbar, "mode", ""):
            return

        if not self._event_in_preview(event):
            return

        if self._dragging_mode == "creating" and self._dragging_annotation_id:
            annot = self._get_annotation_by_id(self._dragging_annotation_id)
            if annot is None or self._drag_start_data is None:
                return
            x, y = self._event_to_annotation_coords(event, annot)
            anchor_x, anchor_y = self._drag_start_data
            if annot.kind in ("line", "arrow"):
                dx = x - anchor_x
                dy = y - anchor_y
                key = (event.key or "").lower() if hasattr(event, "key") else ""
                if "shift" in key:
                    if abs(dx) > abs(dy):
                        y = anchor_y
                    else:
                        x = anchor_x
            annot.x1 = x
            annot.y1 = y
            self._update_annotation_artists_from_spec(annot)
            self.canvas.draw_idle()
        elif self._dragging_mode == "moving" and self._dragging_annotation_id:
            annot = self._get_annotation_by_id(self._dragging_annotation_id)
            if annot is None or not isinstance(self._drag_start_data, dict):
                return
            start_event = self._drag_start_data.get("start_event")
            start_coords = self._drag_start_data.get("coords")
            if start_event is None or start_coords is None:
                return
            cur_x, cur_y = self._event_to_annotation_coords(event, annot)
            dx = cur_x - start_event[0]
            dy = cur_y - start_event[1]
            x0, y0, x1, y1 = start_coords
            annot.x0 = x0 + dx
            annot.y0 = y0 + dy
            if annot.kind in ("box", "arrow", "line"):
                annot.x1 = x1 + dx
                annot.y1 = y1 + dy
            self._update_annotation_artists_from_spec(annot)
            self.canvas.draw_idle()

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
            self._clear_annotation_artists()
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
                max(
                    self.spec.layout.height_in / max(self.spec.layout.width_in, 1e-6),
                    0.01,
                )
            )
            for spine in self.preview_ax.spines.values():
                spine.set_visible(True)
                spine.set_color("#d0d0d0")
                spine.set_linewidth(1.0)
            self.preview_ax.set_xticks([])
            self.preview_ax.set_yticks([])
            self.preview_ax.tick_params(
                left=False, labelleft=False, bottom=False, labelbottom=False
            )
            self.preview_ax.set_frame_on(True)
            self.preview_ax.patch.set_alpha(0.0)
            if self._annotation_overlay_ax:
                self._annotation_overlay_ax.set_position(self.preview_ax.get_position())
                self._annotation_overlay_ax.set_xlim(self.preview_ax.get_xlim())
                self._annotation_overlay_ax.set_ylim(self.preview_ax.get_ylim())

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
                self._axes_instance_lookup = {}
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
            self._axes_instance_lookup = {}
            for inst_id, ax in self._preview_axes_map.items():
                self._axes_instance_lookup[ax] = inst_id
                for other_ax in ax.figure.axes:
                    if other_ax is ax:
                        continue
                    if hasattr(self, "preview_ax") and other_ax is self.preview_ax:
                        continue
                    if other_ax.get_position().bounds == ax.get_position().bounds:
                        self._axes_instance_lookup[other_ax] = inst_id

            for annot in self.spec.annotations:
                self._create_annotation_artists_for_preview(annot)

            self._update_footer()
            self._refresh_traces_events_tab()
            self.canvas.draw_idle()

        except Exception as e:
            log.error(f"Preview error: {e}", exc_info=True)
            self.preview_ax.text(
                0.5,
                0.5,
                f"Error:\n{str(e)[:100]}",
                ha="center",
                va="center",
                fontsize=10,
                color="#cc0000",
            )
            self.canvas.draw_idle()

    def _delete_selected_annotation(self):
        """Delete selected annotation."""
        if self.selected_annotation_id is None:
            return

        annot_id = self.selected_annotation_id
        self._remove_annotation_artists(annot_id)
        self.spec.annotations = [
            a for a in self.spec.annotations if a.annotation_id != annot_id
        ]
        self.selected_annotation_id = None
        self._dragging_annotation_id = None
        self._dragging_mode = None
        self._drag_start_data = None
        self._push_undo()
        self._refresh_annotation_ui()
        self.canvas.draw_idle()

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
        self._refresh_annotation_ui()

    def _redo(self):
        """Redo last undone action."""
        if not self._redo_stack:
            return

        self.spec = copy.deepcopy(self._redo_stack.pop())
        self._undo_stack.append(copy.deepcopy(self.spec))
        self._update_preview()
        self._refresh_annotation_ui()

    def export_figure(self):
        """Export figure at target DPI."""
        if self.trace_model is None:
            QMessageBox.warning(self, "No data", "No trace model loaded for export.")
            return
        current_format = self.spec.export.format
        filters = [
            "PDF (*.pdf)",
            "SVG (*.svg)",
            "PNG (*.png)",
            "TIFF (*.tiff *.tif)",
            "All Files (*)",
        ]
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Figure",
            f"figure.{current_format}",
            ";;".join(filters),
            f"{current_format.upper()} (*.{current_format})",
        )

        if not file_path:
            self._refocus_self()
            return

        base_path = Path(file_path)
        if base_path.suffix.lower().lstrip(".") != current_format:
            base_path = base_path.with_suffix(f".{current_format}")

        outputs = [(base_path, current_format, self.spec.export.dpi)]
        if self.cb_export_png.isChecked():
            outputs.append(
                (
                    base_path.with_name(base_path.stem + "_png").with_suffix(".png"),
                    "png",
                    300,
                )
            )
        if self.cb_export_tiff.isChecked():
            outputs.append(
                (
                    base_path.with_name(base_path.stem + "_tiff").with_suffix(".tiff"),
                    "tiff",
                    600,
                )
            )

        try:

            def trace_provider(sample_id: str):
                return self.trace_model

            for out_path, fmt, dpi in outputs:
                export_fig = render_figure(
                    self.spec,
                    trace_provider,
                    dpi=dpi,
                    event_times=self.event_times,
                    event_labels=self.event_labels,
                    event_colors=self.event_colors,
                )
                export_fig.savefig(
                    out_path,
                    format=fmt,
                    dpi=dpi if fmt in ("png", "tiff") else None,
                    bbox_inches="tight",
                    transparent=self.spec.export.transparent,
                )
                plt.close(export_fig)

            QMessageBox.information(
                self,
                "Export Complete",
                "Figure exported:\n" + "\n".join(str(p) for p, _, _ in outputs),
            )
            for out_path, _, _ in outputs:
                log.info(f"Exported: {out_path}")

        except Exception as e:
            log.error(f"Export failed: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export:\n{str(e)}",
            )
        finally:
            self._refocus_self()

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
        self.selected_instance_id = (
            self.spec.layout.graph_instances[0].instance_id
            if self.spec.layout.graph_instances
            else None
        )
        self.spec.metadata.setdefault("extra_export_png", False)
        self.spec.metadata.setdefault("extra_export_tiff", False)
        self._aspect_ratio = self.spec.layout.height_in / max(
            self.spec.layout.width_in, 1e-6
        )
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._refresh_tabs()
        self._update_preview()
        QMessageBox.information(self, "Figure Loaded", f"Loaded:\n{file_path}")

    def _on_save_to_project_clicked(self):
        """Save the current FigureSpec into the active project dataset."""
        if self.project is None or self.dataset_id is None:
            QMessageBox.information(
                self,
                "Save to Project",
                "No project/dataset context is available for this figure.",
            )
            return

        try:
            save_dataset_figure_spec(self.project, self.dataset_id, self.spec)
            parent_window = self.parent()
            if parent_window is not None and hasattr(
                parent_window, "mark_session_dirty"
            ):
                try:
                    parent_window.mark_session_dirty(reason="figure spec saved")
                except Exception:
                    pass
            if hasattr(self, "status_label"):
                self.status_label.setText("Saved figure definition to project.")
        except Exception as exc:
            log.error("Failed to save FigureSpec to project: %s", exc, exc_info=True)
            QMessageBox.critical(
                self, "Save Error", f"Failed to save to project:\n{exc}"
            )
