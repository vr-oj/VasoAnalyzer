"""Single Figure Studio composer window (Phase 1 single-axes core)."""

from __future__ import annotations

import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict, Optional

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QColor, QShowEvent, QKeySequence
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from .renderer import (
    AnnotationSpec,
    AxesSpec,
    EventSpec,
    FigureSpec,
    PageSpec,
    RenderContext,
    TraceSpec,
    build_figure,
    export_figure,
)

log = logging.getLogger(__name__)


@contextmanager
def signals_blocked(widget):
    """Context manager to safely block/unblock signals."""
    widget.blockSignals(True)
    try:
        yield widget
    finally:
        widget.blockSignals(False)


class PureMplFigureComposer(QMainWindow):
    """Minimal composer window wired to the single-axes FigureSpec."""

    DEFAULT_WIDTH_IN = 6.0
    DEFAULT_HEIGHT_IN = 3.0
    DEFAULT_DPI = 300.0

    def __init__(
        self,
        trace_model: Any | None = None,
        parent=None,
        *,
        project=None,
        dataset_id: Any | None = None,
        event_times: list[float] | None = None,
        event_labels: list[str] | None = None,
        event_colors: list[str] | None = None,
        visible_channels: dict[str, bool] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Single Figure Studio")
        self.trace_model = trace_model
        self.project = project
        self.dataset_id = dataset_id
        self.event_times = event_times or []
        self.event_labels = event_labels or []
        self.event_colors = event_colors or []
        self.visible_channels = visible_channels or {}

        # Build initial spec from defaults; UI will be synced from it before preview
        self._fig_spec: FigureSpec = self._build_initial_fig_spec(trace_model)
        self._export_transparent = False

        self._figure = None
        self._canvas = None
        self._scroll: Optional[QScrollArea] = None
        self._preview_zoom: float = 1.0
        # zoom mode: "fit" means we auto-fit after each rebuild; "manual" means user controls zoom
        self._zoom_mode: str = "fit"
        self._preview_initialized = False
        self._first_show_done = False

        self.spin_label_fontsize = None
        self.spin_tick_fontsize = None
        self.spin_legend_fontsize = None
        self.spin_linewidth_scale = None

        self._trace_controls: Dict[str, Dict[str, Any]] = {}
        self._event_controls: list[Dict[str, Any]] = []
        self._anno_mode: str | None = "select"
        self._box_start: tuple[float, float] | None = None

        self._page_update_timer = QTimer()
        self._page_update_timer.setSingleShot(True)
        self._page_update_timer.setInterval(150)  # 150ms debounce
        self._page_update_timer.timeout.connect(self._apply_page_changes)

        self._setup_ui()

    # ------------------------------------------------------------------
    # Spec / context helpers
    # ------------------------------------------------------------------
    def _build_initial_fig_spec(self, trace_model: Any | None) -> FigureSpec:
        """Create the initial FigureSpec based on available data/UI defaults."""
        page = PageSpec(
            width_in=self.DEFAULT_WIDTH_IN,
            height_in=self.DEFAULT_HEIGHT_IN,
            dpi=self.DEFAULT_DPI,
        )
        axes = AxesSpec(
            x_range=None,
            y_range=None,
            xlabel="Time (s)",
            ylabel="Diameter (µm)",
            show_grid=True,
            grid_linestyle="--",
            grid_color="#c0c0c0",
            grid_alpha=0.7,
            show_event_labels=False,
        )

        traces: list[TraceSpec] = []
        available_keys: list[str] = []
        tm = trace_model
        for key in ["inner", "outer", "avg_pressure", "set_pressure"]:
            arr = getattr(tm, f"{key}_full", None) if tm is not None else None
            if arr is not None:
                if key in self.visible_channels and not self.visible_channels.get(key, True):
                    continue
                available_keys.append(key)
        if not available_keys:
            available_keys = ["inner"]

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
        for idx, key in enumerate(available_keys):
            traces.append(
                TraceSpec(
                    key=key,
                    visible=True,
                    color=colors[idx % len(colors)],
                    linewidth=1.5,
                    linestyle="-",
                    marker="",
                )
            )

        events: list[EventSpec] = []
        for idx, t in enumerate(self.event_times):
            color = (
                self.event_colors[idx]
                if idx < len(self.event_colors)
                else "#444444"
            )
            label = self.event_labels[idx] if idx < len(self.event_labels) else ""
            events.append(
                EventSpec(
                    visible=True,
                    time_s=float(t),
                    color=color,
                    linewidth=1.0,
                    linestyle="--",
                    label=label,
                    label_above=True,
                )
            )

        return FigureSpec(
            page=page,
            axes=axes,
            traces=traces,
            events=events,
            annotations=[],
            legend_visible=True,
            legend_fontsize=9.0,
            legend_loc="upper right",
            line_width_scale=1.0,
        )

    def _render_context(self, *, is_preview: bool) -> RenderContext:
        return RenderContext(
            is_preview=is_preview,
            trace_model=self.trace_model,
            series_map=None,
        )

    def _sync_ui_from_spec(self) -> None:
        """Populate UI controls from the current FigureSpec without firing signals."""
        if not hasattr(self, "spin_width"):
            return
        blocks = [
            self.spin_width,
            self.spin_height,
            self.spin_dpi,
            self.cb_axes_first,
            self.spin_axes_margin,
            self.edit_xlabel,
            self.edit_ylabel,
            self.cb_grid,
            self.combo_grid_style,
            self.edit_grid_color,
            self.spin_grid_alpha,
            self.cb_legend,
            self.spin_label_fontsize,
            self.spin_tick_fontsize,
            self.spin_legend_fontsize,
            self.combo_legend_loc,
            self.cb_event_labels,
            self.spin_linewidth_scale,
        ]
        for widget in blocks:
            if widget is not None:
                widget.blockSignals(True)

        page = self._fig_spec.page
        axes = self._fig_spec.axes
        self.spin_width.setValue(page.width_in)
        self.spin_height.setValue(page.height_in)
        self.spin_dpi.setValue(int(page.dpi))
        self.cb_axes_first.setChecked(page.axes_first)
        self.spin_axes_margin.setValue(page.min_margin_in)
        self.edit_xlabel.setText(axes.xlabel)
        self.edit_ylabel.setText(axes.ylabel)
        self.cb_grid.setChecked(axes.show_grid)
        self.combo_grid_style.setCurrentText(axes.grid_linestyle)
        self.edit_grid_color.setText(axes.grid_color)
        self.spin_grid_alpha.setValue(axes.grid_alpha)
        self.cb_legend.setChecked(self._fig_spec.legend_visible)
        self.combo_legend_loc.setCurrentText(self._fig_spec.legend_loc)
        self.cb_event_labels.setChecked(getattr(axes, "show_event_labels", False))
        if self.spin_label_fontsize is not None and axes.xlabel_fontsize is not None:
            self.spin_label_fontsize.setValue(axes.xlabel_fontsize)
        if self.spin_tick_fontsize is not None and axes.tick_label_fontsize is not None:
            self.spin_tick_fontsize.setValue(axes.tick_label_fontsize)
        if self.spin_legend_fontsize is not None and self._fig_spec.legend_fontsize is not None:
            self.spin_legend_fontsize.setValue(self._fig_spec.legend_fontsize)
        if self.spin_linewidth_scale is not None:
            self.spin_linewidth_scale.setValue(self._fig_spec.line_width_scale)

        for widget in blocks:
            if widget is not None:
                widget.blockSignals(False)
        self._update_figure_setup_labels()
        self._update_export_size_label()

    def _sync_spec_from_ui(self) -> None:
        """Update FigureSpec from current UI control values."""
        page = self._fig_spec.page
        axes = self._fig_spec.axes
        page.width_in = float(self.spin_width.value())
        page.height_in = float(self.spin_height.value())
        page.dpi = float(self.spin_dpi.value())
        page.axes_first = self.cb_axes_first.isChecked()
        page.min_margin_in = float(self.spin_axes_margin.value())
        if page.axes_first:
            page.axes_width_in = page.width_in
            page.axes_height_in = page.height_in
        else:
            page.axes_width_in = None
            page.axes_height_in = None
        axes.xlabel = self.edit_xlabel.text()
        axes.ylabel = self.edit_ylabel.text()
        axes.show_grid = self.cb_grid.isChecked()
        axes.grid_linestyle = self.combo_grid_style.currentText()
        axes.grid_color = self.edit_grid_color.text()
        axes.grid_alpha = float(self.spin_grid_alpha.value())
        if self.spin_label_fontsize is not None:
            axes.xlabel_fontsize = float(self.spin_label_fontsize.value())
            axes.ylabel_fontsize = float(self.spin_label_fontsize.value())
        if self.spin_tick_fontsize is not None:
            axes.tick_label_fontsize = float(self.spin_tick_fontsize.value())
        axes.show_event_labels = self.cb_event_labels.isChecked()
        self._fig_spec.legend_visible = self.cb_legend.isChecked()
        if self.spin_legend_fontsize is not None:
            self._fig_spec.legend_fontsize = float(self.spin_legend_fontsize.value())
        self._fig_spec.legend_loc = self.combo_legend_loc.currentText()
        if self.spin_linewidth_scale is not None:
            self._fig_spec.line_width_scale = float(self.spin_linewidth_scale.value())
        self._update_figure_setup_labels()
        self._update_export_size_label()

    def _update_figure_setup_labels(self) -> None:
        if not hasattr(self, "lbl_width"):
            return
        if self.cb_axes_first.isChecked():
            self.lbl_width.setText("Axes width (in)")
            self.lbl_height.setText("Axes height (in)")
        else:
            self.lbl_width.setText("Figure width (in)")
            self.lbl_height.setText("Figure height (in)")

    def _update_export_size_label(self) -> None:
        if not hasattr(self, "label_export_size"):
            return
        page = self._fig_spec.page
        w_in = page.effective_width_in or page.width_in
        h_in = page.effective_height_in or page.height_in
        dpi = page.dpi
        w_px = int(w_in * dpi)
        h_px = int(h_in * dpi)
        self.label_export_size.setText(f"{w_in:.2f} in × {h_in:.2f} in ({w_px} × {h_px} px @ {dpi:.0f} dpi)")

        # Also update status bar
        if hasattr(self, "status_size"):
            self.status_size.setText(f"  Figure: {w_in:.2f} × {h_in:.2f} in  ")

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        # Set reasonable initial window size
        self.resize(1400, 900)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # Left: preview + zoom/export controls
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(6)
        title = QLabel("Single Figure Studio")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        left_layout.addWidget(title)
        splitter.addWidget(left)
        splitter.setStretchFactor(0, 3)

        # Right: tabs
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(6)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_figure_tab(), "Figure Setup")
        self.tabs.addTab(self._build_axes_tab(), "Axes / Legend")
        self.tabs.addTab(self._build_traces_tab(), "Traces")
        self.tabs.addTab(self._build_events_tab(), "Events")
        self.tabs.addTab(self._build_annotations_tab(), "Annotations")
        right_layout.addWidget(self.tabs)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 2)

        # Sync UI from spec then spec from UI to guarantee a single source of truth
        self._sync_ui_from_spec()
        self._sync_spec_from_ui()

        # Build preview after controls are in place
        self._create_preview()
        if self._scroll is not None:
            left_layout.addWidget(self._scroll, stretch=1)

        # Zoom / annotation / export controls
        zoom_row = QHBoxLayout()
        self.btn_zoom_out = QPushButton("Zoom -")
        self.btn_zoom_in = QPushButton("Zoom +")
        self.btn_zoom_fit = QPushButton("Fit")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 400)
        self.zoom_slider.setValue(int(self._preview_zoom * 100))
        zoom_row.addWidget(self.btn_zoom_out)
        zoom_row.addWidget(self.zoom_slider, stretch=1)
        zoom_row.addWidget(self.btn_zoom_in)
        zoom_row.addWidget(self.btn_zoom_fit)
        left_layout.addLayout(zoom_row)

        anno_row = QHBoxLayout()
        self.btn_anno_select = QPushButton("Select")
        self.btn_anno_text = QPushButton("Text")
        self.btn_anno_box = QPushButton("Box")
        self.btn_anno_delete = QPushButton("Delete")
        for btn in [self.btn_anno_select, self.btn_anno_text, self.btn_anno_box, self.btn_anno_delete]:
            anno_row.addWidget(btn)
        anno_row.addStretch(1)
        left_layout.addLayout(anno_row)

        export_row = QHBoxLayout()
        self.btn_export = QPushButton("Export…")
        export_row.addStretch(1)
        export_row.addWidget(self.btn_export)
        left_layout.addLayout(export_row)

        # Signals
        self.btn_zoom_in.clicked.connect(lambda: self._set_zoom(self._preview_zoom * 1.25, mode="manual"))
        self.btn_zoom_out.clicked.connect(lambda: self._set_zoom(self._preview_zoom * 0.8, mode="manual"))
        self.zoom_slider.valueChanged.connect(lambda v: self._set_zoom(v / 100.0, mode="manual"))
        self.btn_zoom_fit.clicked.connect(self._on_zoom_fit_clicked)
        self.btn_export.clicked.connect(self._export_dialog)
        self.btn_anno_select.clicked.connect(lambda: self._set_anno_mode("select"))
        self.btn_anno_text.clicked.connect(lambda: self._set_anno_mode("text"))
        self.btn_anno_box.clicked.connect(lambda: self._set_anno_mode("box"))
        self.btn_anno_delete.clicked.connect(self._delete_selected_annotation)
        self._update_anno_button_styles()

        # Status bar at bottom of window
        self.status_bar = self.statusBar()
        self.status_zoom = QLabel("Zoom: 100%")
        self.status_size = QLabel("Figure: 6.0 × 3.0 in")
        self.status_coords = QLabel("")

        # Style status widgets
        for widget in [self.status_zoom, self.status_size, self.status_coords]:
            widget.setStyleSheet("padding: 0 8px; color: #555;")

        self.status_bar.addPermanentWidget(self.status_zoom)
        self.status_bar.addPermanentWidget(QLabel("|"))
        self.status_bar.addPermanentWidget(self.status_size)
        self.status_bar.addPermanentWidget(QLabel("|"))
        self.status_bar.addPermanentWidget(self.status_coords)

        # Set up keyboard shortcuts
        self._setup_shortcuts()

        # Add tooltips
        self._add_tooltips()

    def _create_preview(self) -> None:
        if self._preview_initialized:
            return

        ctx = self._render_context(is_preview=True)
        fig = build_figure(self._fig_spec, ctx, fig=None)
        self._figure = fig
        self._canvas = FigureCanvasQTAgg(fig)
        self._canvas.mpl_connect("button_press_event", self._on_canvas_press)
        self._canvas.mpl_connect("button_release_event", self._on_canvas_release)
        self._canvas.mpl_connect("motion_notify_event", self._on_canvas_motion)

        scroll = QScrollArea(self)
        scroll.setWidget(self._canvas)
        scroll.setWidgetResizable(False)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #d0d0d0;
                background-color: #e8e8e8;
            }
        """)

        # Install event filter for mouse wheel zoom
        scroll.viewport().installEventFilter(self)

        self._scroll = scroll

        self._preview_initialized = True
        # Defer initial fit until the window is shown (handled in showEvent)

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _build_figure_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setLabelAlignment(Qt.AlignRight)

        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(1.0, 30.0)
        self.spin_width.setSingleStep(0.1)
        self.spin_width.setValue(self._fig_spec.page.width_in)
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(1.0, 30.0)
        self.spin_height.setSingleStep(0.1)
        self.spin_height.setValue(self._fig_spec.page.height_in)
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(50, 1200)
        self.spin_dpi.setValue(int(self._fig_spec.page.dpi))
        self.cb_transparent = QCheckBox("Transparent export background")
        self.cb_axes_first = QCheckBox("Axes-first sizing")
        self.cb_axes_first.setChecked(self._fig_spec.page.axes_first)
        self.spin_axes_margin = QDoubleSpinBox()
        self.spin_axes_margin.setRange(0.0, 2.0)
        self.spin_axes_margin.setSingleStep(0.1)
        self.spin_axes_margin.setDecimals(2)
        self.spin_axes_margin.setValue(self._fig_spec.page.min_margin_in)

        self.lbl_width = QLabel("Figure width (in)")
        self.lbl_height = QLabel("Figure height (in)")
        form.addRow(self.lbl_width, self.spin_width)
        form.addRow(self.lbl_height, self.spin_height)
        form.addRow("DPI", self.spin_dpi)
        form.addRow(self.cb_axes_first)
        form.addRow("Min margin (in)", self.spin_axes_margin)
        form.addRow("", self.cb_transparent)
        self.label_export_size = QLabel("")
        self.label_export_size.setStyleSheet("color: #6c757d;")
        form.addRow("Export size", self.label_export_size)

        self.spin_width.valueChanged.connect(self._on_page_dimension_changed)
        self.spin_height.valueChanged.connect(self._on_page_dimension_changed)
        self.spin_dpi.valueChanged.connect(self._on_page_dimension_changed)
        self.cb_axes_first.toggled.connect(self._on_page_dimension_changed)
        self.cb_axes_first.toggled.connect(lambda _: self._update_figure_setup_labels())
        self.spin_axes_margin.valueChanged.connect(self._on_page_dimension_changed)
        self.cb_transparent.toggled.connect(self._on_export_bg_changed)
        return tab

    def _build_axes_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        grp_axes = QGroupBox("Axes")
        form_axes = QFormLayout(grp_axes)
        self.edit_xlabel = QLineEdit(self._fig_spec.axes.xlabel)
        self.edit_ylabel = QLineEdit(self._fig_spec.axes.ylabel)
        self.cb_grid = QCheckBox("Show grid")
        self.cb_grid.setChecked(self._fig_spec.axes.show_grid)
        self.combo_grid_style = QComboBox()
        self.combo_grid_style.addItems(["-", "--", "-.", ":"])
        self.combo_grid_style.setCurrentText(self._fig_spec.axes.grid_linestyle)
        self.edit_grid_color = QLineEdit(self._fig_spec.axes.grid_color)
        self.spin_grid_alpha = QDoubleSpinBox()
        self.spin_grid_alpha.setRange(0.0, 1.0)
        self.spin_grid_alpha.setSingleStep(0.05)
        self.spin_grid_alpha.setValue(self._fig_spec.axes.grid_alpha)
        form_axes.addRow("X label", self.edit_xlabel)
        form_axes.addRow("Y label", self.edit_ylabel)
        form_axes.addRow(self.cb_grid)
        form_axes.addRow("Grid style", self.combo_grid_style)
        form_axes.addRow("Grid color", self.edit_grid_color)
        form_axes.addRow("Grid alpha", self.spin_grid_alpha)

        fonts_group = QGroupBox("Fonts", self)
        fonts_layout = QFormLayout(fonts_group)

        self.spin_label_fontsize = QDoubleSpinBox(self)
        self.spin_label_fontsize.setDecimals(1)
        self.spin_label_fontsize.setRange(6.0, 24.0)
        self.spin_label_fontsize.setSingleStep(0.5)
        self.spin_label_fontsize.setValue(11.0)
        fonts_layout.addRow(QLabel("Axis labels (pt):", self), self.spin_label_fontsize)

        self.spin_tick_fontsize = QDoubleSpinBox(self)
        self.spin_tick_fontsize.setDecimals(1)
        self.spin_tick_fontsize.setRange(6.0, 20.0)
        self.spin_tick_fontsize.setSingleStep(0.5)
        self.spin_tick_fontsize.setValue(9.0)
        fonts_layout.addRow(QLabel("Tick labels (pt):", self), self.spin_tick_fontsize)

        self.spin_legend_fontsize = QDoubleSpinBox(self)
        self.spin_legend_fontsize.setDecimals(1)
        self.spin_legend_fontsize.setRange(6.0, 20.0)
        self.spin_legend_fontsize.setSingleStep(0.5)
        self.spin_legend_fontsize.setValue(9.0)
        fonts_layout.addRow(QLabel("Legend (pt):", self), self.spin_legend_fontsize)

        grp_legend = QGroupBox("Legend")
        form_leg = QFormLayout(grp_legend)
        self.cb_legend = QCheckBox("Show legend")
        self.cb_legend.setChecked(self._fig_spec.legend_visible)
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
        self.combo_legend_loc.setCurrentText(self._fig_spec.legend_loc)
        form_leg.addRow(self.cb_legend)
        form_leg.addRow("Location", self.combo_legend_loc)

        layout.addWidget(grp_axes)
        layout.addWidget(fonts_group)
        layout.addWidget(grp_legend)
        layout.addStretch(1)

        self.edit_xlabel.textChanged.connect(self._on_axes_changed)
        self.edit_ylabel.textChanged.connect(self._on_axes_changed)
        self.cb_grid.toggled.connect(self._on_axes_changed)
        self.combo_grid_style.currentTextChanged.connect(self._on_axes_changed)
        self.edit_grid_color.textChanged.connect(self._validate_grid_color)
        self.edit_grid_color.textChanged.connect(self._on_axes_changed)
        self.spin_grid_alpha.valueChanged.connect(self._on_axes_changed)
        self.spin_label_fontsize.valueChanged.connect(self._on_axes_fonts_changed)
        self.spin_tick_fontsize.valueChanged.connect(self._on_axes_fonts_changed)
        self.spin_legend_fontsize.valueChanged.connect(self._on_axes_fonts_changed)
        self.cb_legend.toggled.connect(self._on_legend_changed)
        self.combo_legend_loc.currentTextChanged.connect(self._on_legend_changed)
        return tab

    def _build_traces_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)

        self._trace_controls.clear()
        for trace in self._fig_spec.traces:
            row = QHBoxLayout()
            cb_visible = QCheckBox(trace.key)
            cb_visible.setChecked(trace.visible)
            btn_color = QPushButton()
            btn_color.setFixedWidth(32)
            btn_color.setStyleSheet(f"background-color: {trace.color};")
            btn_color.setProperty("color", trace.color)
            spin_width = QDoubleSpinBox()
            spin_width.setRange(0.1, 10.0)
            spin_width.setSingleStep(0.1)
            spin_width.setValue(trace.linewidth)
            combo_ls = QComboBox()
            combo_ls.addItems(["-", "--", "-.", ":"])
            combo_ls.setCurrentText(trace.linestyle)
            combo_marker = QComboBox()
            combo_marker.addItems(["", "o", "s", "^", ".", "x"])
            combo_marker.setCurrentText(trace.marker)

            row.addWidget(cb_visible)
            row.addWidget(QLabel("Color"))
            row.addWidget(btn_color)
            row.addWidget(QLabel("Line width"))
            row.addWidget(spin_width)
            row.addWidget(QLabel("Style"))
            row.addWidget(combo_ls)
            row.addWidget(QLabel("Marker"))
            row.addWidget(combo_marker)
            row.addStretch(1)
            layout.addLayout(row)

            self._trace_controls[trace.key] = {
                "visible": cb_visible,
                "color": btn_color,
                "linewidth": spin_width,
                "linestyle": combo_ls,
                "marker": combo_marker,
            }

            cb_visible.toggled.connect(lambda checked, k=trace.key: self._on_trace_changed(k))
            btn_color.clicked.connect(lambda _, k=trace.key: self._pick_trace_color(k))
            spin_width.valueChanged.connect(lambda _, k=trace.key: self._on_trace_changed(k))
            combo_ls.currentTextChanged.connect(lambda _, k=trace.key: self._on_trace_changed(k))
            combo_marker.currentTextChanged.connect(lambda _, k=trace.key: self._on_trace_changed(k))

        lw_group = QGroupBox("Line thickness (scale)", self)
        lw_layout = QFormLayout(lw_group)

        self.spin_linewidth_scale = QDoubleSpinBox(self)
        self.spin_linewidth_scale.setDecimals(2)
        self.spin_linewidth_scale.setRange(0.5, 2.0)
        self.spin_linewidth_scale.setSingleStep(0.1)
        self.spin_linewidth_scale.setValue(self._fig_spec.line_width_scale)
        lw_layout.addRow(QLabel("Scale factor:", self), self.spin_linewidth_scale)

        layout.addWidget(lw_group)

        if not self._fig_spec.traces:
            layout.addWidget(QLabel("No traces configured."))
        layout.addStretch(1)

        self.spin_linewidth_scale.valueChanged.connect(self._on_linewidth_scale_changed)
        return tab

    def _build_events_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)

        self.cb_event_labels = QCheckBox("Show labels")
        self.cb_event_labels.setChecked(self._fig_spec.axes.show_event_labels)
        layout.addWidget(self.cb_event_labels)

        self.events_table = QTableWidget(0, 7)
        self.events_table.setHorizontalHeaderLabels(
            ["Visible", "Time (s)", "Label", "Above", "Color", "Style", "Linewidth"]
        )
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.events_table.setSelectionMode(QTableWidget.SingleSelection)
        self.events_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.events_table)

        btn_row = QHBoxLayout()
        self.btn_events_from_dataset = QPushButton("Add from VasoAnalyzer events…")
        self.btn_event_add = QPushButton("+ Add")
        self.btn_event_delete = QPushButton("Delete")
        btn_row.addWidget(self.btn_events_from_dataset)
        btn_row.addWidget(self.btn_event_add)
        btn_row.addWidget(self.btn_event_delete)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.btn_events_from_dataset.clicked.connect(self._add_events_from_dataset)
        self.btn_event_add.clicked.connect(self._add_event)
        self.btn_event_delete.clicked.connect(self._delete_event)
        self.cb_event_labels.toggled.connect(self._on_event_labels_toggled)

        self._refresh_events_table()
        return tab

    def _build_annotations_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        self.annotation_list = QListWidget()
        layout.addWidget(self.annotation_list)
        hint = QLabel("Use the toolbar (Text/Box) then click on the canvas to add annotations.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        delete_row = QHBoxLayout()
        btn_delete = QPushButton("Delete selected")
        delete_row.addWidget(btn_delete)
        delete_row.addStretch(1)
        layout.addLayout(delete_row)
        btn_delete.clicked.connect(self._delete_selected_annotation)
        self._refresh_annotation_list()
        return tab

    def _refresh_events_table(self) -> None:
        if not hasattr(self, "events_table"):
            return
        with signals_blocked(self.events_table) as table:
            table.setRowCount(len(self._fig_spec.events))
            self._event_controls = []
            for row, ev in enumerate(self._fig_spec.events):
                self._populate_event_row(row, ev)

    def _populate_event_row(self, row: int, ev: EventSpec) -> None:
        table = self.events_table
        controls: Dict[str, Any] = {}

        cb_vis = QCheckBox()
        cb_vis.setChecked(ev.visible)
        table.setCellWidget(row, 0, cb_vis)
        controls["visible"] = cb_vis

        spin_time = QDoubleSpinBox()
        spin_time.setRange(-1e6, 1e6)
        spin_time.setDecimals(3)
        spin_time.setSingleStep(0.1)
        spin_time.setValue(ev.time_s)
        table.setCellWidget(row, 1, spin_time)
        controls["time"] = spin_time

        edit_label = QLineEdit(ev.label)
        table.setCellWidget(row, 2, edit_label)
        controls["label"] = edit_label

        cb_above = QCheckBox()
        cb_above.setChecked(ev.label_above)
        table.setCellWidget(row, 3, cb_above)
        controls["above"] = cb_above

        btn_color = QPushButton()
        btn_color.setFixedWidth(32)
        btn_color.setStyleSheet(f"background-color: {ev.color};")
        btn_color.setProperty("color", ev.color)
        table.setCellWidget(row, 4, btn_color)
        controls["color"] = btn_color

        combo_style = QComboBox()
        combo_style.addItems(["-", "--", "-.", ":"])
        combo_style.setCurrentText(ev.linestyle)
        table.setCellWidget(row, 5, combo_style)
        controls["style"] = combo_style

        spin_width = QDoubleSpinBox()
        spin_width.setRange(0.1, 10.0)
        spin_width.setSingleStep(0.1)
        spin_width.setValue(ev.linewidth)
        table.setCellWidget(row, 6, spin_width)
        controls["linewidth"] = spin_width

        cb_vis.toggled.connect(lambda _=None, r=row: self._on_event_changed(r))
        spin_time.valueChanged.connect(lambda _=None, r=row: self._on_event_changed(r))
        edit_label.editingFinished.connect(lambda r=row: self._on_event_changed(r))
        cb_above.toggled.connect(lambda _=None, r=row: self._on_event_changed(r))
        combo_style.currentTextChanged.connect(lambda _=None, r=row: self._on_event_changed(r))
        spin_width.valueChanged.connect(lambda _=None, r=row: self._on_event_changed(r))
        btn_color.clicked.connect(lambda _=None, r=row: self._pick_event_color(r))

        self._event_controls.append(controls)

    def _on_event_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._fig_spec.events):
            return
        ev = self._fig_spec.events[row]
        controls = self._event_controls[row]
        ev.visible = controls["visible"].isChecked()
        ev.time_s = float(controls["time"].value())
        ev.label = controls["label"].text()
        ev.label_above = controls["above"].isChecked()
        ev.linestyle = controls["style"].currentText()
        ev.linewidth = float(controls["linewidth"].value())
        color = controls["color"].property("color")
        if color:
            ev.color = str(color)
        self._refresh_preview()

    def _pick_event_color(self, row: int) -> None:
        if row < 0 or row >= len(self._fig_spec.events):
            return
        controls = self._event_controls[row]
        color = QColorDialog.getColor()
        if not color.isValid():
            return
        controls["color"].setStyleSheet(f"background-color: {color.name()};")
        controls["color"].setProperty("color", color.name())
        self._on_event_changed(row)

    def _add_event(self) -> None:
        self._fig_spec.events.append(
            EventSpec(
                visible=True,
                time_s=0.0,
                color="#444444",
                linewidth=1.0,
                linestyle="--",
                label="",
                label_above=True,
            )
        )
        self._refresh_events_table()
        self._refresh_preview()

    def _add_events_from_dataset(self) -> None:
        if not self.event_times:
            QMessageBox.information(self, "No events", "No dataset events available to add.")
            return
        for idx, t in enumerate(self.event_times):
            color = self.event_colors[idx] if idx < len(self.event_colors) else "#444444"
            label = self.event_labels[idx] if idx < len(self.event_labels) else ""
            self._fig_spec.events.append(
                EventSpec(
                    visible=True,
                    time_s=float(t),
                    color=color,
                    linewidth=1.0,
                    linestyle="--",
                    label=label,
                    label_above=True,
                )
            )
        self._refresh_events_table()
        self._refresh_preview()

    def _delete_event(self) -> None:
        if not hasattr(self, "events_table"):
            return
        row = self.events_table.currentRow()
        if row < 0 or row >= len(self._fig_spec.events):
            return
        del self._fig_spec.events[row]
        self._refresh_events_table()
        self._refresh_preview()

    def _on_event_labels_toggled(self, checked: bool) -> None:
        self._fig_spec.axes.show_event_labels = checked
        self._refresh_preview()

    def _refresh_annotation_list(self) -> None:
        if not hasattr(self, "annotation_list"):
            return
        self.annotation_list.clear()
        for idx, ann in enumerate(self._fig_spec.annotations):
            label = f"{idx+1}: {ann.kind} ({ann.coord_space})"
            if ann.text:
                label += f" \"{ann.text}\""
            item = QListWidgetItem(label)
            self.annotation_list.addItem(item)

    def _delete_selected_annotation(self) -> None:
        if not hasattr(self, "annotation_list"):
            return
        row = self.annotation_list.currentRow()
        if row < 0 or row >= len(self._fig_spec.annotations):
            return
        del self._fig_spec.annotations[row]
        self._refresh_annotation_list()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Preview helpers
    # ------------------------------------------------------------------
    def _refresh_preview(self) -> None:
        if not self._preview_initialized or self._figure is None or self._canvas is None:
            return
        ctx = self._render_context(is_preview=True)

        # Log artist count for debugging
        if log.isEnabledFor(logging.DEBUG):
            before = len(self._figure.get_axes())
            build_figure(self._fig_spec, ctx, fig=self._figure)
            after = len(self._figure.get_axes())
            log.debug(f"Figure rebuild: {before} axes before, {after} after (should be 0→1)")
        else:
            build_figure(self._fig_spec, ctx, fig=self._figure)

        self._canvas.draw()
        if self._zoom_mode == "fit":
            z = self._compute_fit_zoom()
            self._set_zoom(z, mode="fit")
        else:
            self._apply_zoom()
        self._update_export_size_label()

    def _base_pixels(self) -> tuple[int, int]:
        page = self._fig_spec.page
        if page.axes_first and page.axes_width_in and page.axes_height_in:
            w_in = (page.effective_width_in or (page.axes_width_in + 2 * page.min_margin_in))
            h_in = (page.effective_height_in or (page.axes_height_in + 2 * page.min_margin_in))
        else:
            w_in = page.effective_width_in or page.width_in
            h_in = page.effective_height_in or page.height_in
        return int(w_in * page.dpi), int(h_in * page.dpi)

    def _compute_fit_zoom(self) -> float:
        if self._scroll is None:
            return 1.0
        base_w, base_h = self._base_pixels()
        if base_w <= 0 or base_h <= 0:
            return 1.0
        viewport = self._scroll.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return 1.0
        zw = viewport.width() / base_w
        zh = viewport.height() / base_h
        return max(0.1, min(zw, zh))

    def _initial_fit_zoom(self) -> None:
        """Run once after the layout has settled to compute initial zoom."""
        if not self._preview_initialized:
            return

        # Ensure scroll area has valid size
        if self._scroll.viewport().width() <= 1 or self._scroll.viewport().height() <= 1:
            # Layout not ready yet, try again
            QTimer.singleShot(50, self._initial_fit_zoom)
            return

        # Compute zoom based on actual viewport size
        z = self._compute_fit_zoom()

        # Ensure zoom is reasonable (not too small/large)
        z = max(0.1, min(2.0, z))  # Clamp initial zoom to 10%-200%

        self._set_zoom(z, mode="fit")

        log.debug(f"Initial fit zoom: {z:.2%}")

    def _apply_zoom(self) -> None:
        if not self._preview_initialized or self._canvas is None:
            return
        base_w, base_h = self._base_pixels()
        scaled_w = int(base_w * self._preview_zoom)
        scaled_h = int(base_h * self._preview_zoom)
        self._canvas.resize(scaled_w, scaled_h)
        self._canvas.updateGeometry()

    def _set_zoom(self, factor: float, mode: str | None = None) -> None:
        """
        Set the preview zoom factor.

        mode:
            "fit"    → enter auto-fit mode (figure kept fully visible after rebuilds)
            "manual" → user-controlled zoom; rebuilds keep the same zoom
            None     → keep current mode, just change factor
        """
        factor = max(0.25, min(4.0, factor))
        if abs(factor - self._preview_zoom) < 1e-3 and mode is None:
            return

        if mode is not None:
            self._zoom_mode = mode

        self._preview_zoom = factor
        if hasattr(self, "zoom_slider"):
            with signals_blocked(self.zoom_slider):
                self.zoom_slider.setValue(int(self._preview_zoom * 100))
        self._apply_zoom()

        # Update status bar
        if hasattr(self, "status_zoom"):
            mode_icon = "🔒" if self._zoom_mode == "manual" else "↔️"
            self.status_zoom.setText(f"{mode_icon} Zoom: {self._preview_zoom * 100:.0f}%")

    def _set_anno_mode(self, mode: str) -> None:
        self._anno_mode = mode
        self._update_anno_button_styles()

    def showEvent(self, event: QShowEvent) -> None:
        """Ensure the first refresh/fit happens after the dialog is visible."""
        super().showEvent(event)
        if self._first_show_done:
            return
        self._first_show_done = True
        if self._preview_initialized:
            self._refresh_preview()
        # Use 50ms delay for more reliable layout
        QTimer.singleShot(50, self._initial_fit_zoom)
        # Also ensure export size label is updated
        QTimer.singleShot(60, self._update_export_size_label)

    def eventFilter(self, obj, event):
        """Intercept wheel events on scroll viewport for zoom."""
        if obj == self._scroll.viewport() and event.type() == QEvent.Wheel:
            # Get wheel delta
            delta = event.angleDelta().y()
            if delta == 0:
                return super().eventFilter(obj, event)

            # Zoom in/out
            zoom_factor = 1.15 if delta > 0 else 1.0 / 1.15
            new_zoom = self._preview_zoom * zoom_factor

            # Get mouse position relative to scroll area
            scroll_pos = event.pos()

            # Get current scroll bar positions
            h_bar = self._scroll.horizontalScrollBar()
            v_bar = self._scroll.verticalScrollBar()
            old_h = h_bar.value()
            old_v = v_bar.value()

            # Apply zoom
            self._set_zoom(new_zoom, mode="manual")

            # Adjust scrollbars to zoom "into" cursor position
            new_h = old_h + scroll_pos.x() * (zoom_factor - 1)
            new_v = old_v + scroll_pos.y() * (zoom_factor - 1)
            h_bar.setValue(int(new_h))
            v_bar.setValue(int(new_v))

            return True  # Event handled

        return super().eventFilter(obj, event)

    def _update_anno_button_styles(self) -> None:
        active_style = "background-color: #4da3ff; color: white; font-weight: bold;"
        for mode, btn in [
            ("select", self.btn_anno_select),
            ("text", self.btn_anno_text),
            ("box", self.btn_anno_box),
        ]:
            if self._anno_mode == mode:
                btn.setStyleSheet(active_style)
            else:
                btn.setStyleSheet("")

    def _on_zoom_fit_clicked(self) -> None:
        """
        Reset zoom to keep the entire figure visible and re-enter auto-fit mode.
        """
        if not self._preview_initialized:
            return
        z = self._compute_fit_zoom()
        self._set_zoom(z, mode="fit")

    # ------------------------------------------------------------------
    # Canvas interactions
    # ------------------------------------------------------------------
    def _on_canvas_press(self, event) -> None:
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            return
        if self._anno_mode == "text":
            self._fig_spec.annotations.append(
                AnnotationSpec(
                    kind="text",
                    text="Text",
                    x=float(event.xdata),
                    y=float(event.ydata),
                    coord_space="data",
                    fontsize=8.0,
                    color="#000000",
                )
            )
            self._refresh_annotation_list()
            self._refresh_preview()
        elif self._anno_mode == "box":
            self._box_start = (float(event.xdata), float(event.ydata))

    def _on_canvas_release(self, event) -> None:
        if self._anno_mode != "box":
            return
        if self._box_start is None:
            return
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            self._box_start = None
            return
        x0, y0 = self._box_start
        x1, y1 = float(event.xdata), float(event.ydata)
        self._box_start = None
        self._fig_spec.annotations.append(
            AnnotationSpec(
                kind="box",
                text="",
                x=x0,
                y=y0,
                x2=x1,
                y2=y1,
                coord_space="data",
                color="#000000",
                linewidth=1.0,
            )
        )
        self._refresh_annotation_list()
        self._refresh_preview()

    def _on_canvas_motion(self, event) -> None:
        """Update status bar with mouse coordinates."""
        if not hasattr(self, "status_coords"):
            return
        if event.inaxes and event.xdata is not None and event.ydata is not None:
            self.status_coords.setText(f"  x={event.xdata:.2f}, y={event.ydata:.2f}  ")
        else:
            self.status_coords.setText("")

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------
    def _on_page_dimension_changed(self) -> None:
        """Handle dimension changes with debouncing."""
        self._page_update_timer.start()

    def _apply_page_changes(self) -> None:
        """Apply page dimension changes after debounce delay."""
        page = self._fig_spec.page
        page.width_in = float(self.spin_width.value())
        page.height_in = float(self.spin_height.value())
        page.dpi = float(self.spin_dpi.value())
        page.axes_first = self.cb_axes_first.isChecked()
        page.min_margin_in = float(self.spin_axes_margin.value())
        if page.axes_first:
            page.axes_width_in = page.width_in
            page.axes_height_in = page.height_in
        else:
            page.axes_width_in = None
            page.axes_height_in = None
        self._refresh_preview()

    def _on_export_bg_changed(self, checked: bool) -> None:
        self._export_transparent = checked

    def _on_axes_changed(self) -> None:
        axes = self._fig_spec.axes
        axes.xlabel = self.edit_xlabel.text()
        axes.ylabel = self.edit_ylabel.text()
        axes.show_grid = self.cb_grid.isChecked()
        axes.grid_linestyle = self.combo_grid_style.currentText()

        # Validate grid color before applying
        grid_color_text = self.edit_grid_color.text().strip()
        if grid_color_text:
            color = QColor(grid_color_text)
            if color.isValid():
                axes.grid_color = grid_color_text
            else:
                log.warning(f"Invalid grid color '{grid_color_text}', keeping: {axes.grid_color}")

        axes.grid_alpha = float(self.spin_grid_alpha.value())
        self._refresh_preview()

    def _on_axes_fonts_changed(self) -> None:
        axes = self._fig_spec.axes
        if self.spin_label_fontsize is not None:
            axes.xlabel_fontsize = float(self.spin_label_fontsize.value())
            axes.ylabel_fontsize = float(self.spin_label_fontsize.value())
        if self.spin_tick_fontsize is not None:
            axes.tick_label_fontsize = float(self.spin_tick_fontsize.value())
        if self.spin_legend_fontsize is not None:
            self._fig_spec.legend_fontsize = float(self.spin_legend_fontsize.value())
        self._refresh_preview()

    def _validate_grid_color(self, text: str) -> None:
        """Validate grid color input and provide visual feedback."""
        if not text.strip():
            self.edit_grid_color.setStyleSheet("")
            return

        color = QColor(text)
        if color.isValid():
            self.edit_grid_color.setStyleSheet("")
        else:
            # Invalid color - red border
            self.edit_grid_color.setStyleSheet("border: 1px solid red;")

    def _on_legend_changed(self) -> None:
        self._fig_spec.legend_visible = self.cb_legend.isChecked()
        self._fig_spec.legend_loc = self.combo_legend_loc.currentText()
        if self.spin_legend_fontsize is not None:
            self._fig_spec.legend_fontsize = float(self.spin_legend_fontsize.value())
        self._refresh_preview()

    def _on_trace_changed(self, key: str) -> None:
        trace = self._get_trace_spec(key)
        controls = self._trace_controls.get(key, {})
        if trace is None or not controls:
            return
        trace.visible = controls["visible"].isChecked()
        trace.linewidth = float(controls["linewidth"].value())
        trace.linestyle = controls["linestyle"].currentText()
        trace.marker = controls["marker"].currentText()
        trace.color = controls["color"].property("color") or trace.color
        self._refresh_preview()

    def _on_linewidth_scale_changed(self, value: float) -> None:
        self._fig_spec.line_width_scale = float(value)
        self._refresh_preview()

    def _pick_trace_color(self, key: str) -> None:
        trace = self._get_trace_spec(key)
        controls = self._trace_controls.get(key, {})
        if trace is None or not controls:
            return
        initial = trace.color
        color = QColorDialog.getColor()
        if not color.isValid():
            return
        trace.color = color.name()
        btn = controls["color"]
        btn.setStyleSheet(f"background-color: {trace.color};")
        btn.setProperty("color", trace.color)
        self._refresh_preview()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _export_dialog(self) -> None:
        suggested = Path.cwd() / "figure.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export figure",
            str(suggested),
            "Images (*.png *.tiff *.tif);;PDF (*.pdf);;SVG (*.svg)",
        )
        if not path:
            return
        self.export_figure(path)

    def export_figure(self, out_path: str) -> None:
        try:
            log.info("Exporting figure to %s", out_path)
            ctx = self._render_context(is_preview=False)
            export_figure(
                self._fig_spec,
                out_path,
                transparent=self._export_transparent,
                ctx=ctx,
            )
            log.info("Export successful: %s", out_path)
        except Exception:
            log.exception("Export failed")
            QMessageBox.critical(self, "Export failed", "Export failed; see log for details.")

    # ------------------------------------------------------------------
    # Keyboard Shortcuts & Tooltips
    # ------------------------------------------------------------------
    def _setup_shortcuts(self):
        """Set up keyboard shortcuts for common actions."""
        # Zoom shortcuts
        QShortcut(QKeySequence("Ctrl++"), self).activated.connect(
            lambda: self._set_zoom(self._preview_zoom * 1.25, mode="manual")
        )
        QShortcut(QKeySequence("Ctrl+="), self).activated.connect(  # Also handle Ctrl+=
            lambda: self._set_zoom(self._preview_zoom * 1.25, mode="manual")
        )
        QShortcut(QKeySequence("Ctrl+-"), self).activated.connect(
            lambda: self._set_zoom(self._preview_zoom * 0.8, mode="manual")
        )
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(self._on_zoom_fit_clicked)

        # Export
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self._export_dialog)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._export_dialog)

        # Annotation modes
        QShortcut(QKeySequence("T"), self).activated.connect(
            lambda: self._set_anno_mode("text")
        )
        QShortcut(QKeySequence("B"), self).activated.connect(
            lambda: self._set_anno_mode("box")
        )
        QShortcut(QKeySequence("V"), self).activated.connect(
            lambda: self._set_anno_mode("select")
        )
        QShortcut(QKeySequence("Escape"), self).activated.connect(
            lambda: self._set_anno_mode("select")
        )
        QShortcut(QKeySequence("Delete"), self).activated.connect(
            self._delete_selected_annotation
        )

        log.info("Keyboard shortcuts enabled: Ctrl+/- (zoom), Ctrl+0 (fit), Ctrl+E (export), T/B/V (tools)")

    def _add_tooltips(self):
        """Add helpful tooltips to all controls."""
        # Figure setup
        self.spin_width.setToolTip(
            "Figure width in inches\n"
            "Common sizes: 6–8 in (slides), 3–4 in (manuscript)"
        )
        self.spin_height.setToolTip(
            "Figure height in inches\n"
            "Typical aspect ratio: 1.5:1 to 2:1 (width:height)"
        )
        self.spin_dpi.setToolTip(
            "Resolution in dots per inch\n"
            "150 dpi: screen preview\n"
            "300 dpi: print quality (recommended)\n"
            "600 dpi: high-resolution publication"
        )
        self.cb_axes_first.setToolTip(
            "Size by axes dimensions instead of total figure\n"
            "Ensures exact control of plot area size\n"
            "Final figure = axes + labels + margins"
        )
        self.spin_axes_margin.setToolTip(
            "Minimum white space around axes (inches)\n"
            "Typical: 0.3–0.5 in for manuscripts"
        )

        # Axes/fonts
        self.edit_xlabel.setToolTip("Label for horizontal axis")
        self.edit_ylabel.setToolTip("Label for vertical axis")

        if self.spin_label_fontsize:
            self.spin_label_fontsize.setToolTip(
                "Font size for axis labels (points)\n"
                "Typical: 10–12 pt for manuscripts"
            )
        if self.spin_tick_fontsize:
            self.spin_tick_fontsize.setToolTip(
                "Font size for tick labels (points)\n"
                "Typical: 8–10 pt (slightly smaller than axis labels)"
            )
        if self.spin_legend_fontsize:
            self.spin_legend_fontsize.setToolTip(
                "Font size for legend text (points)\n"
                "Typical: 8–9 pt"
            )

        # Grid
        self.cb_grid.setToolTip("Show/hide grid lines")
        self.combo_grid_style.setToolTip("Grid line style: solid, dashed, dotted")
        self.edit_grid_color.setToolTip("Grid color (hex code or name)\nExample: #d0d0d0, lightgray")
        self.spin_grid_alpha.setToolTip("Grid transparency (0=invisible, 1=opaque)")

        # Line width
        if self.spin_linewidth_scale:
            self.spin_linewidth_scale.setToolTip(
                "Global multiplier for all trace line widths\n"
                "Use to make all lines thicker/thinner together\n"
                "Typical: 0.8–1.5"
            )

        # Events
        self.cb_event_labels.setToolTip("Show text labels above/below event markers")

        # Zoom controls
        self.btn_zoom_in.setToolTip("Zoom in (Ctrl++)")
        self.btn_zoom_out.setToolTip("Zoom out (Ctrl+-)")
        self.btn_zoom_fit.setToolTip(
            "Auto-fit: keep entire figure visible (Ctrl+0)\n"
            "Also re-enables auto-fit mode (figure stays fit after edits)"
        )
        self.zoom_slider.setToolTip("Zoom level (use mouse wheel over preview)")

        # Annotation tools
        self.btn_anno_select.setToolTip("Select mode (V) - click to select annotations")
        self.btn_anno_text.setToolTip("Text tool (T) - click to add text label")
        self.btn_anno_box.setToolTip("Box tool (B) - click and drag to draw rectangle")
        self.btn_anno_delete.setToolTip("Delete selected annotation (Delete)")

        # Export
        self.btn_export.setToolTip("Export to PNG/PDF/SVG (Ctrl+E)")
        self.cb_transparent.setToolTip("Export with transparent background (for overlays)")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_trace_spec(self, key: str) -> TraceSpec | None:
        for trace in self._fig_spec.traces:
            if trace.key == key:
                return trace
        return None
