"""Single Figure Studio composer window (simplified single-axes UI)."""

# NOTE:
# This is the sole maintained Matplotlib composer UI (PureMplFigureComposer).
# Legacy/parallel composers are archived under src/vasoanalyzer/ui/_archive and must not be re-wired.

from __future__ import annotations

import logging
import json
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.widgets import RectangleSelector
from PyQt5.QtCore import QSettings, Qt, QTimer
from PyQt5.QtGui import QCloseEvent, QImage, QShowEvent
from PyQt5.QtWidgets import QColorDialog, QMessageBox
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.theme import CURRENT_THEME

from .preview_viewport import PreviewViewport
from .renderer import (
    AxesSpec,
    EventSpec,
    FigureSpec,
    PageSpec,
    RenderContext,
    TraceSpec,
    build_figure,
    export_figure,
)
from .specs import GraphSpec
from .templates import (
    DEFAULT_TEMPLATE_ID,
    apply_template_preset,
    get_template_preset,
    preset_dimensions_from_base,
)
from .spec_serialization import figure_spec_from_dict, figure_spec_to_dict

log = logging.getLogger(__name__)

MIN_PREVIEW_W = 520  # Minimum usable preview width (px)
MIN_PREVIEW_H = 360  # Minimum usable preview height (px)
EXTRA_W_PAD = 48     # Window chrome/layout breathing room (px)
EXTRA_H_PAD = 140    # Header/export rows + margins (px)
CONTROL_MIN_W = 380
PREVIEW_MIN_W = 520
WINDOW_MIN_W = CONTROL_MIN_W + PREVIEW_MIN_W + 80


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
    MIN_WIDTH_IN = 2.0
    MIN_HEIGHT_IN = 1.5
    MAX_WIDTH_IN = 20.0
    MAX_HEIGHT_IN = 20.0

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
        series_map: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
        default_xlim: tuple[float, float] | None = None,
        default_ylim: tuple[float, float] | None = None,
        default_trace_key: str | None = None,
        recipe_id: str | None = None,
        figure_spec: FigureSpec | dict | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Single Figure Studio")
        self.trace_model = trace_model
        self.project = project
        self.dataset_id = dataset_id
        self._recipe_id = recipe_id
        self.event_times = event_times or []
        self.event_labels = event_labels or []
        self.event_colors = event_colors or []
        self.visible_channels = visible_channels or {}
        self._series_map_override = series_map
        self._default_xlim = default_xlim
        self._default_ylim = default_ylim
        self._default_trace_key = default_trace_key
        self._applied_default_view = False
        self._default_view_note: str | None = None
        self._template_defaults_cache: dict[str, dict[str, Any]] = {"page": {}, "axes": {}, "figure": {}}

        default_graph_spec = GraphSpec()
        provided_fig = figure_spec is not None
        if figure_spec is not None:
            if isinstance(figure_spec, dict):
                self._fig_spec = figure_spec_from_dict(figure_spec)
            else:
                self._fig_spec = figure_spec
        else:
            self._fig_spec: FigureSpec = self._build_initial_fig_spec(trace_model)
            self._template_defaults_cache = apply_template_preset(
                self._fig_spec,
                getattr(self._fig_spec, "template_id", DEFAULT_TEMPLATE_ID),
                respect_overrides=False,
            )
        axes = getattr(self._fig_spec, "axes", None)
        if axes is not None:
            if not hasattr(axes, "show_event_markers"):
                axes.show_event_markers = default_graph_spec.show_event_markers
            if not hasattr(axes, "show_event_labels"):
                axes.show_event_labels = default_graph_spec.show_event_labels
        if not hasattr(self._fig_spec, "template_id"):
            self._fig_spec.template_id = DEFAULT_TEMPLATE_ID
        if provided_fig:
            self._template_defaults_cache = self._snapshot_template_defaults_from_spec()
        elif not any(self._template_defaults_cache.get(k) for k in ("page", "axes", "figure")):
            preset = get_template_preset(self._fig_spec.template_id)
            self._template_defaults_cache = {
                "page": dict(preset.layout_defaults),
                "axes": dict(preset.style_defaults.get("axes", {})),
                "figure": dict(preset.style_defaults.get("figure", {})),
            }
        self._ensure_size_metadata()
        self._apply_size_policy_from_spec(
            force_recompute=getattr(self._fig_spec, "size_mode", "template") == "template",
            refresh=False,
            update_controls=False,
        )
        self._active_trace_key = next(
            (trace.key for trace in self._fig_spec.traces if trace.visible),
            self._fig_spec.traces[0].key if self._fig_spec.traces else "inner",
        )
        self._initial_ranges = self._guess_initial_ranges()
        if self._default_xlim is not None or self._default_ylim is not None:
            x_min, x_max, y_min, y_max = self._initial_ranges
            if self._default_xlim is not None:
                x_min = float(self._default_xlim[0])
                x_max = float(self._default_xlim[1])
            if self._default_ylim is not None:
                y_min = float(self._default_ylim[0])
                y_max = float(self._default_ylim[1])
            self._initial_ranges = (x_min, x_max, y_min, y_max)
        self._export_transparent = False
        self._size_was_clamped = False

        self._figure = None
        self._canvas = None
        self._preview_initialized = False
        self._first_show_done = False
        self._box_selector: RectangleSelector | None = None
        self._box_dragging: bool = False

        # UI widgets (assigned during setup)
        self.trace_selector: QComboBox | None = None
        self.cb_grid: QCheckBox | None = None
        self.cb_events: QCheckBox | None = None
        self.cb_event_labels: QCheckBox | None = None
        self.cb_x_auto: QCheckBox | None = None
        self.cb_y_auto: QCheckBox | None = None
        self.spin_x_min: QDoubleSpinBox | None = None
        self.spin_x_max: QDoubleSpinBox | None = None
        self.spin_y_min: QDoubleSpinBox | None = None
        self.spin_y_max: QDoubleSpinBox | None = None
        self.spin_axis_fontsize: QDoubleSpinBox | None = None
        self.spin_tick_fontsize: QDoubleSpinBox | None = None
        self.spin_event_label_fontsize: QDoubleSpinBox | None = None
        self.cb_axis_bold: QCheckBox | None = None
        self.cb_axis_italic: QCheckBox | None = None
        self.cb_tick_italic: QCheckBox | None = None
        self.cb_event_label_bold: QCheckBox | None = None
        self.cb_event_label_italic: QCheckBox | None = None
        self.combo_label_font: QComboBox | None = None
        self.combo_tick_font: QComboBox | None = None
        self.combo_event_label_font: QComboBox | None = None
        self.edit_xlabel: QLineEdit | None = None
        self.edit_ylabel: QLineEdit | None = None
        self.combo_size_mode: QComboBox | None = None
        self.combo_size_preset: QComboBox | None = None
        self.combo_template: QComboBox | None = None
        self.spin_width: QDoubleSpinBox | None = None
        self.spin_height: QDoubleSpinBox | None = None
        self.cb_legend: QCheckBox | None = None
        self.cb_export_transparent: QCheckBox | None = None
        self.spin_dpi: QSpinBox | None = None
        self.label_export_size: QLabel | None = None
        self.btn_export: QPushButton | None = None
        self.btn_save_project: QPushButton | None = None
        self.btn_box_select: QPushButton | None = None
        self.btn_trace_color: QPushButton | None = None
        self.spin_trace_width: QDoubleSpinBox | None = None
        self._canvas_container: QWidget | None = None
        self._preview_viewport: PreviewViewport | None = None
        self._preview_scale_label: QLabel | None = None
        self._right_panel: QWidget | None = None
        self._main_splitter: QSplitter | None = None
        self._last_figure_size: tuple[float, float] | None = None  # Track (width_px, height_px)
        self._export_dpi: float = float(self._fig_spec.page.dpi)
        self._splitter_initialized: bool = False
        self._splitter_retry_scheduled: bool = False
        self._in_preview_capture: bool = False
        self._persist_timer: QTimer | None = None
        self._pending_dirty: bool = False
        self._signal_emit_timer: QTimer | None = None
        self._pending_signal_emit: bool = False
        self._template_choices: list[tuple[str, str]] = [
            ("Single column", "single_column"),
            ("Double column", "double_column"),
            ("Slide", "slide"),
        ]

        self._enforce_page_bounds(update_controls=False)
        self._setup_ui()
        self._log_layout_state_once()
        self._sync_controls_from_spec()
        self._refresh_preview()
        QTimer.singleShot(0, self._apply_dynamic_minimum_size)
        QTimer.singleShot(0, self._init_splitter_sizes_once)
        try:
            left = self._main_splitter.widget(0) if self._main_splitter else None
            right = self._main_splitter.widget(1) if self._main_splitter else None
            sizes = self._main_splitter.sizes() if self._main_splitter else []
            log.info(
                "Composer init ready: splitter children=%s sizes=%s left_w=%s right_w=%s",
                self._main_splitter.count() if self._main_splitter else None,
                sizes,
                left.width() if left else None,
                right.width() if right else None,
            )
        except Exception:
            log.debug("Failed to log composer init splitter state", exc_info=True)

    # ------------------------------------------------------------------
    # Spec / context helpers
    # ------------------------------------------------------------------
    def _build_initial_fig_spec(self, trace_model: Any | None) -> FigureSpec:
        """Create the initial FigureSpec based on available data/UI defaults."""
        template_id = DEFAULT_TEMPLATE_ID
        preset = get_template_preset(template_id)
        layout_defaults = preset.layout_defaults
        style_defaults = preset.style_defaults.get("axes", {})
        figure_style_defaults = preset.style_defaults.get("figure", {})
        graph_spec = GraphSpec()
        page = PageSpec(
            width_in=float(layout_defaults.get("width_in", self.DEFAULT_WIDTH_IN)),
            height_in=float(layout_defaults.get("height_in", self.DEFAULT_HEIGHT_IN)),
            dpi=self.DEFAULT_DPI,
            sizing_mode="axes_first",
            export_background="white",
            min_margin_in=float(layout_defaults.get("min_margin_in", 0.15)),
        )
        axes = AxesSpec(
            x_range=None,
            y_range=None,
            xlabel="Time (s)",
            ylabel="Diameter (µm)",
            show_grid=True,
            grid_linestyle="--",
            grid_color=CURRENT_THEME.get("grid_color", "#c0c0c0"),
            grid_alpha=0.7,
            show_event_markers=graph_spec.show_event_markers,
            show_event_labels=graph_spec.show_event_labels,
            xlabel_fontsize=float(style_defaults.get("xlabel_fontsize", 12.0)),
            ylabel_fontsize=float(style_defaults.get("ylabel_fontsize", 12.0)),
            tick_label_fontsize=float(style_defaults.get("tick_label_fontsize", 9.0)),
            event_label_fontsize=float(style_defaults.get("event_label_fontsize", 9.0)),
            label_bold=True,
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

        preferred_key = (
            self._default_trace_key if self._default_trace_key in available_keys else None
        )
        default_key = preferred_key or ("inner" if "inner" in available_keys else available_keys[0])
        colors = ["#000000", "#ff7f0e", "#2ca02c", "#d62728"]
        for idx, key in enumerate(available_keys):
            traces.append(
                TraceSpec(
                    key=key,
                    visible=key == default_key,
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
                else CURRENT_THEME.get("text", "#444444")
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
            template_id=template_id,
            legend_visible=False,
            legend_fontsize=float(figure_style_defaults.get("legend_fontsize", 9.0)),
            legend_loc="upper right",
            line_width_scale=1.0,
            figure_width_in=page.width_in,
            figure_height_in=page.height_in,
            size_mode="template",
            size_preset=None,
        )

    def _snapshot_template_defaults_from_spec(self) -> dict[str, dict[str, Any]]:
        page_defaults: dict[str, Any] = {}
        axes_defaults: dict[str, Any] = {}
        figure_defaults: dict[str, Any] = {}
        if getattr(self._fig_spec, "page", None) is not None:
            for field in ("width_in", "height_in", "min_margin_in"):
                if hasattr(self._fig_spec.page, field):
                    page_defaults[field] = getattr(self._fig_spec.page, field)
        if getattr(self._fig_spec, "axes", None) is not None:
            for field in ("xlabel_fontsize", "ylabel_fontsize", "tick_label_fontsize", "event_label_fontsize"):
                if hasattr(self._fig_spec.axes, field):
                    axes_defaults[field] = getattr(self._fig_spec.axes, field)
        for field in ("legend_fontsize",):
            if hasattr(self._fig_spec, field):
                figure_defaults[field] = getattr(self._fig_spec, field)
        return {"page": page_defaults, "axes": axes_defaults, "figure": figure_defaults}

    def _ensure_size_metadata(self) -> None:
        """Backfill size metadata fields so template/preset logic is consistent."""
        page = self._fig_spec.page
        if getattr(self._fig_spec, "figure_width_in", None) is None:
            self._fig_spec.figure_width_in = page.width_in
        if getattr(self._fig_spec, "figure_height_in", None) is None:
            self._fig_spec.figure_height_in = page.height_in
        if getattr(self._fig_spec, "size_mode", None) is None:
            self._fig_spec.size_mode = "template"
        if getattr(self._fig_spec, "size_preset", None) is None and self._fig_spec.size_mode != "preset":
            self._fig_spec.size_preset = None
        # Keep page sizes in sync with figure-level overrides.
        try:
            page.width_in = float(self._fig_spec.figure_width_in)
            page.height_in = float(self._fig_spec.figure_height_in)
        except Exception:
            pass

    def _render_context(self, *, is_preview: bool) -> RenderContext:
        return RenderContext(
            is_preview=is_preview,
            trace_model=self.trace_model,
            series_map=self._series_map_override,
        )

    def _guess_initial_ranges(self) -> tuple[float, float, float, float]:
        """Derive basic axis limits from the trace model for manual ranges."""
        tm = self.trace_model
        if self._series_map_override:
            maybe = self._series_map_override.get(self._active_trace_key)
            if maybe is not None:
                time_arr, data_arr = maybe
                try:
                    x_min = float(np.nanmin(time_arr))
                    x_max = float(np.nanmax(time_arr))
                    y_min = float(np.nanmin(data_arr))
                    y_max = float(np.nanmax(data_arr))
                except Exception:
                    log.debug("Failed to derive ranges from series_map override", exc_info=True)
                if x_max <= x_min:
                    x_max = x_min + 1.0
                if y_max <= y_min:
                    y_max = y_min + 1.0
                return x_min, x_max, y_min, y_max
        x_min, x_max = 0.0, 10.0
        y_min, y_max = 0.0, 1.0
        if tm is None:
            return x_min, x_max, y_min, y_max

        time = getattr(tm, "time_full", None)
        if time is not None:
            try:
                x_min = float(np.nanmin(time))
                x_max = float(np.nanmax(time))
            except Exception:
                log.debug("Failed to derive time range from trace_model", exc_info=True)
        trace_key = self._active_trace_key or "inner"
        data = getattr(tm, f"{trace_key}_full", None)
        if data is not None:
            try:
                y_min = float(np.nanmin(data))
                y_max = float(np.nanmax(data))
            except Exception:
                log.debug("Failed to derive data range from trace_model", exc_info=True)

        if x_max <= x_min:
            x_max = x_min + 1.0
        if y_max <= y_min:
            y_max = y_min + 1.0
        return x_min, x_max, y_min, y_max

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        self.resize(max(1300, WINDOW_MIN_W), 850)
        self.setMinimumWidth(WINDOW_MIN_W)
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        # Left: preview
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(8)
        title = QLabel("Single Figure Studio")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        left_layout.addWidget(title)
        self._create_preview()
        if self._preview_viewport is not None:
            canvas_frame = QWidget()
            self._canvas_container = canvas_frame
            canvas_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            canvas_frame.setMinimumSize(max(MIN_PREVIEW_W, PREVIEW_MIN_W), MIN_PREVIEW_H)
            canvas_layout = QGridLayout(canvas_frame)
            canvas_layout.setContentsMargins(0, 0, 0, 0)
            canvas_layout.addWidget(self._preview_viewport, 0, 0)
            # Scale indicator overlay
            self._preview_scale_label = QLabel(canvas_frame)
            self._preview_scale_label.setStyleSheet(
                "color: #555; background: rgba(255, 255, 255, 180);"
                "border: 1px solid #ccc; border-radius: 3px; padding: 2px 6px;"
            )
            self._preview_scale_label.setVisible(False)
            self._preview_scale_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            canvas_layout.addWidget(self._preview_scale_label, 0, 0, Qt.AlignBottom | Qt.AlignRight)
            left_layout.addWidget(canvas_frame, stretch=1)

        # Export size info label
        self.label_export_size = QLabel("")
        text_color = CURRENT_THEME.get("text", "#6c757d")
        self.label_export_size.setStyleSheet(f"color: {text_color}; padding: 4px;")
        self.label_export_size.setWordWrap(True)
        left_layout.addWidget(self.label_export_size)
        # Right: controls (scrollable to avoid collapsing)
        right_content = QWidget()
        right_layout = QVBoxLayout(right_content)
        right_layout.setSpacing(10)
        right_layout.addWidget(self._build_actions_group())
        right_layout.addWidget(self._build_trace_group())
        right_layout.addWidget(self._build_axes_group())
        right_layout.addWidget(self._build_range_group())
        right_layout.addWidget(self._build_font_group())
        right_layout.addWidget(self._build_shape_group())
        right_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(right_content)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(CONTROL_MIN_W)
        right_content.setMinimumWidth(CONTROL_MIN_W)
        scroll.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(scroll)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet(
            "QSplitter::handle { background: palette(mid); }"
            "QSplitter::handle:horizontal { width: 8px; }"
        )
        self._main_splitter = splitter

        root.addWidget(splitter)
        self._right_panel = scroll

        restored = self._restore_window_state()

        # Force an initial splitter layout before the first paint.
        if not restored:
            init_w = max(self.width(), WINDOW_MIN_W)
            init_h = max(self.height(), 700)
            self.resize(init_w, init_h)
        if self._main_splitter and not self._splitter_initialized:
            total_w = max(self.width(), WINDOW_MIN_W)
            self._main_splitter.setSizes([max(PREVIEW_MIN_W, total_w - CONTROL_MIN_W), CONTROL_MIN_W])
            sizes = self._main_splitter.sizes()
            log.info("Composer splitter sizes initial: %s", sizes)
            if len(sizes) >= 2 and sizes[1] >= CONTROL_MIN_W and all(s > 0 for s in sizes):
                self._splitter_initialized = True
            self._main_splitter.update()
            self._main_splitter.repaint()

        if self.btn_export is not None:
            self.btn_export.clicked.connect(self._export_dialog)
        if self.cb_export_transparent is not None:
            self.cb_export_transparent.toggled.connect(self._on_export_background_toggled)
        if self.spin_dpi is not None:
            self.spin_dpi.valueChanged.connect(self._on_export_dpi_changed)
        if self.btn_save_project is not None:
            self.btn_save_project.clicked.connect(self._save_to_project)

    def _create_preview(self) -> None:
        ctx = self._render_context(is_preview=True)
        fig = build_figure(self._fig_spec, ctx, fig=None)
        self._figure = fig
        self._canvas = FigureCanvasQTAgg(fig)
        self._canvas.setParent(self)
        self._canvas.setAttribute(Qt.WA_DontShowOnScreen, True)
        self._canvas.setVisible(False)
        self._canvas.hide()
        self._sync_canvas_size_to_figure()
        self._canvas.setMinimumSize(1, 1)
        self._canvas.setFocusPolicy(Qt.NoFocus)
        self._preview_viewport = PreviewViewport()
        self._preview_viewport.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._preview_viewport.setMinimumSize(PREVIEW_MIN_W, MIN_PREVIEW_H)
        self._preview_viewport.set_event_target(self._canvas)
        self._preview_viewport.set_scale_callback(self._update_scale_label_from_viewport)
        self._preview_initialized = True

    # ------------------------------------------------------------------
    # Control builders
    # ------------------------------------------------------------------
    def _build_actions_group(self) -> QGroupBox:
        grp = QGroupBox("Actions")
        layout = QVBoxLayout(grp)
        layout.setSpacing(8)

        # Export settings row
        export_settings = QHBoxLayout()
        export_settings.addWidget(QLabel("DPI:"))
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 1200)
        self.spin_dpi.setSingleStep(25)
        self.spin_dpi.setValue(int(self._export_dpi))
        self.spin_dpi.setToolTip("Export resolution (dots per inch)")
        self.spin_dpi.setFixedWidth(80)
        export_settings.addWidget(self.spin_dpi)
        export_settings.addStretch()
        layout.addLayout(export_settings)

        self.cb_export_transparent = QCheckBox("Transparent background")
        self.cb_export_transparent.setChecked(False)
        layout.addWidget(self.cb_export_transparent)

        # Export button
        self.btn_export = QPushButton("Export Figure...")
        self.btn_export.setMinimumHeight(32)
        layout.addWidget(self.btn_export)

        # Save to project button
        self.btn_save_project = QPushButton("Save to Project")
        self.btn_save_project.setMinimumHeight(32)
        self.btn_save_project.setEnabled(self.dataset_id is not None and self.project is not None)
        layout.addWidget(self.btn_save_project)

        return grp

    def _build_trace_group(self) -> QGroupBox:
        grp = QGroupBox("Trace")
        layout = QVBoxLayout(grp)
        layout.setSpacing(6)
        self.trace_selector = QComboBox()
        for trace in self._fig_spec.traces:
            self.trace_selector.addItem(trace.key, trace.key)
        self.trace_selector.setMinimumContentsLength(14)
        self.trace_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.trace_selector.currentTextChanged.connect(self._on_trace_selected)
        layout.addWidget(QLabel("Visible trace (one at a time):"))
        layout.addWidget(self.trace_selector)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Color"))
        self.btn_trace_color = QPushButton()
        self.btn_trace_color.setFixedWidth(40)
        style_row.addWidget(self.btn_trace_color)
        style_row.addWidget(QLabel("Line width"))
        self.spin_trace_width = QDoubleSpinBox()
        self.spin_trace_width.setDecimals(2)
        self.spin_trace_width.setRange(0.10, 10.00)
        self.spin_trace_width.setSingleStep(0.05)
        style_row.addWidget(self.spin_trace_width)
        style_row.addStretch(1)
        layout.addLayout(style_row)

        if self.btn_trace_color:
            self.btn_trace_color.clicked.connect(self._on_trace_color_clicked)
        if self.spin_trace_width:
            self.spin_trace_width.valueChanged.connect(self._on_trace_width_changed)

        return grp

    def _build_axes_group(self) -> QGroupBox:
        grp = QGroupBox("Axes & markers")
        form = QFormLayout(grp)
        self.edit_xlabel = QLineEdit(self._fig_spec.axes.xlabel)
        self.edit_ylabel = QLineEdit(self._fig_spec.axes.ylabel)
        self.cb_grid = QCheckBox("Show grid")
        self.cb_grid.setChecked(self._fig_spec.axes.show_grid)
        self.cb_events = QCheckBox("Show event markers")
        self.cb_events.setChecked(any(ev.visible for ev in self._fig_spec.events) if self._fig_spec.events else False)
        self.cb_event_labels = QCheckBox("Show event labels")
        self.cb_event_labels.setChecked(self._fig_spec.axes.show_event_labels)
        self.cb_legend = QCheckBox("Show legend")
        self.cb_legend.setChecked(self._fig_spec.legend_visible)

        form.addRow("X label", self.edit_xlabel)
        form.addRow("Y label", self.edit_ylabel)
        form.addRow(self.cb_grid)
        form.addRow(self.cb_events)
        form.addRow(self.cb_event_labels)
        form.addRow(self.cb_legend)

        # Use editingFinished instead of textChanged so user can type full label before update
        self.edit_xlabel.editingFinished.connect(self._on_axis_labels_changed)
        self.edit_ylabel.editingFinished.connect(self._on_axis_labels_changed)
        self.cb_grid.toggled.connect(self._on_grid_toggled)
        self.cb_events.toggled.connect(self._on_events_toggled)
        self.cb_event_labels.toggled.connect(self._on_event_labels_toggled)
        self.cb_legend.toggled.connect(self._on_legend_toggled)
        return grp

    def _build_range_group(self) -> QGroupBox:
        grp = QGroupBox("Axis ranges")
        layout = QVBoxLayout(grp)

        # X range
        x_row = QHBoxLayout()
        x_row.setSpacing(6)
        self.cb_x_auto = QCheckBox("X auto")
        self.cb_x_auto.setChecked(True)
        x_min_val, x_max_val, y_min_val, y_max_val = self._initial_ranges
        self.spin_x_min = QDoubleSpinBox()
        self.spin_x_min.setRange(-1e6, 1e6)
        self.spin_x_min.setDecimals(2)
        self.spin_x_min.setSingleStep(0.05)
        self.spin_x_min.setValue(x_min_val)
        self.spin_x_max = QDoubleSpinBox()
        self.spin_x_max.setRange(-1e6, 1e6)
        self.spin_x_max.setDecimals(2)
        self.spin_x_max.setSingleStep(0.05)
        self.spin_x_max.setValue(x_max_val)
        for spin in [self.spin_x_min, self.spin_x_max]:
            spin.setEnabled(False)
        x_row.addWidget(self.cb_x_auto)
        x_row.addWidget(QLabel("Min"))
        x_row.addWidget(self.spin_x_min)
        x_row.addWidget(QLabel("Max"))
        x_row.addWidget(self.spin_x_max)
        layout.addLayout(x_row)

        # Y range
        y_row = QHBoxLayout()
        y_row.setSpacing(6)
        self.cb_y_auto = QCheckBox("Y auto")
        self.cb_y_auto.setChecked(True)
        self.spin_y_min = QDoubleSpinBox()
        self.spin_y_min.setRange(-1e6, 1e6)
        self.spin_y_min.setDecimals(2)
        self.spin_y_min.setSingleStep(0.05)
        self.spin_y_min.setValue(y_min_val)
        self.spin_y_max = QDoubleSpinBox()
        self.spin_y_max.setRange(-1e6, 1e6)
        self.spin_y_max.setDecimals(2)
        self.spin_y_max.setSingleStep(0.05)
        self.spin_y_max.setValue(y_max_val)
        for spin in [self.spin_y_min, self.spin_y_max]:
            spin.setEnabled(False)
        y_row.addWidget(self.cb_y_auto)
        y_row.addWidget(QLabel("Min"))
        y_row.addWidget(self.spin_y_min)
        y_row.addWidget(QLabel("Max"))
        y_row.addWidget(self.spin_y_max)
        layout.addLayout(y_row)

        reset_row = QHBoxLayout()
        self.btn_reset_view = QPushButton("Reset view")
        reset_row.addStretch(1)
        reset_row.addWidget(self.btn_reset_view)
        layout.addLayout(reset_row)

        self.btn_box_select = QPushButton("Box select range")
        self.btn_box_select.setCheckable(True)
        self.btn_box_select.toggled.connect(self._toggle_box_select)
        layout.addWidget(self.btn_box_select)

        self.cb_x_auto.toggled.connect(lambda checked: self._on_axis_range_mode_changed("x", checked))
        self.cb_y_auto.toggled.connect(lambda checked: self._on_axis_range_mode_changed("y", checked))
        # Use editingFinished instead of valueChanged so user can type full number before update
        self.spin_x_min.editingFinished.connect(lambda: self._apply_axis_ranges())
        self.spin_x_max.editingFinished.connect(lambda: self._apply_axis_ranges())
        self.spin_y_min.editingFinished.connect(lambda: self._apply_axis_ranges())
        self.spin_y_max.editingFinished.connect(lambda: self._apply_axis_ranges())
        self.btn_reset_view.clicked.connect(self._reset_view_ranges)
        return grp

    def _build_font_group(self) -> QGroupBox:
        grp = QGroupBox("Fonts")
        layout = QVBoxLayout(grp)
        layout.setSpacing(6)

        # Common font families
        fonts = ["sans-serif", "serif", "monospace", "Arial", "Times New Roman", "Courier New"]

        # --- Axis Titles Section ---
        axis_section = QGroupBox("Axis Titles")
        axis_form = QFormLayout(axis_section)

        self.spin_axis_fontsize = QDoubleSpinBox()
        self.spin_axis_fontsize.setDecimals(1)
        self.spin_axis_fontsize.setRange(6.0, 24.0)
        self.spin_axis_fontsize.setSingleStep(1.0)
        self.spin_axis_fontsize.setValue(self._fig_spec.axes.xlabel_fontsize or 12.0)

        self.combo_label_font = QComboBox()
        self.combo_label_font.addItems(fonts)
        self.combo_label_font.setCurrentText(self._fig_spec.axes.label_fontfamily)
        self.combo_label_font.setMinimumContentsLength(12)
        self.combo_label_font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

        axis_style_row = QHBoxLayout()
        self.cb_axis_bold = QCheckBox("Bold")
        self.cb_axis_bold.setChecked(self._fig_spec.axes.label_bold)
        self.cb_axis_italic = QCheckBox("Italic")
        self.cb_axis_italic.setChecked(self._fig_spec.axes.label_fontstyle == "italic")
        axis_style_row.addWidget(self.cb_axis_bold)
        axis_style_row.addWidget(self.cb_axis_italic)
        axis_style_row.addStretch()

        axis_form.addRow("Size (pt)", self.spin_axis_fontsize)
        axis_form.addRow("Font", self.combo_label_font)
        axis_form.addRow("Style", axis_style_row)

        # --- Tick Labels Section ---
        tick_section = QGroupBox("Tick Labels")
        tick_form = QFormLayout(tick_section)

        self.spin_tick_fontsize = QDoubleSpinBox()
        self.spin_tick_fontsize.setDecimals(1)
        self.spin_tick_fontsize.setRange(6.0, 20.0)
        self.spin_tick_fontsize.setSingleStep(1.0)
        self.spin_tick_fontsize.setValue(self._fig_spec.axes.tick_label_fontsize or 9.0)

        self.combo_tick_font = QComboBox()
        self.combo_tick_font.addItems(fonts)
        self.combo_tick_font.setCurrentText(self._fig_spec.axes.tick_fontfamily)
        self.combo_tick_font.setMinimumContentsLength(12)
        self.combo_tick_font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

        self.cb_tick_italic = QCheckBox("Italic")
        self.cb_tick_italic.setChecked(self._fig_spec.axes.tick_fontstyle == "italic")

        tick_form.addRow("Size (pt)", self.spin_tick_fontsize)
        tick_form.addRow("Font", self.combo_tick_font)
        tick_form.addRow("Style", self.cb_tick_italic)

        # --- Event Labels Section ---
        event_section = QGroupBox("Event Labels")
        event_form = QFormLayout(event_section)

        self.spin_event_label_fontsize = QDoubleSpinBox()
        self.spin_event_label_fontsize.setDecimals(1)
        self.spin_event_label_fontsize.setRange(6.0, 20.0)
        self.spin_event_label_fontsize.setSingleStep(1.0)
        self.spin_event_label_fontsize.setValue(self._fig_spec.axes.event_label_fontsize or 9.0)

        self.combo_event_label_font = QComboBox()
        self.combo_event_label_font.addItems(fonts)
        self.combo_event_label_font.setCurrentText(self._fig_spec.axes.event_label_fontfamily)
        self.combo_event_label_font.setMinimumContentsLength(12)
        self.combo_event_label_font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

        event_style_row = QHBoxLayout()
        self.cb_event_label_bold = QCheckBox("Bold")
        self.cb_event_label_bold.setChecked(self._fig_spec.axes.event_label_bold)
        self.cb_event_label_italic = QCheckBox("Italic")
        self.cb_event_label_italic.setChecked(self._fig_spec.axes.event_label_fontstyle == "italic")
        event_style_row.addWidget(self.cb_event_label_bold)
        event_style_row.addWidget(self.cb_event_label_italic)
        event_style_row.addStretch()

        event_form.addRow("Size (pt)", self.spin_event_label_fontsize)
        event_form.addRow("Font", self.combo_event_label_font)
        event_form.addRow("Style", event_style_row)

        # Add sections to main layout
        layout.addWidget(axis_section)
        layout.addWidget(tick_section)
        layout.addWidget(event_section)

        # Connect signals
        self.spin_axis_fontsize.valueChanged.connect(self._on_font_changed)
        self.combo_label_font.currentTextChanged.connect(self._on_font_changed)
        self.cb_axis_bold.toggled.connect(self._on_font_changed)
        self.cb_axis_italic.toggled.connect(self._on_font_changed)

        self.spin_tick_fontsize.valueChanged.connect(self._on_font_changed)
        self.combo_tick_font.currentTextChanged.connect(self._on_font_changed)
        self.cb_tick_italic.toggled.connect(self._on_font_changed)

        self.spin_event_label_fontsize.valueChanged.connect(self._on_font_changed)
        self.combo_event_label_font.currentTextChanged.connect(self._on_font_changed)
        self.cb_event_label_bold.toggled.connect(self._on_font_changed)
        self.cb_event_label_italic.toggled.connect(self._on_font_changed)

        return grp

    def _build_shape_group(self) -> QGroupBox:
        grp = QGroupBox("Axis shape")
        layout = QVBoxLayout(grp)
        self.combo_template = QComboBox()
        for label, template_id in self._template_choices:
            self.combo_template.addItem(label, template_id)
        self.combo_template.setMinimumContentsLength(14)
        self.combo_template.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_template.currentTextChanged.connect(self._on_template_changed)
        layout.addWidget(QLabel("Template"))
        layout.addWidget(self.combo_template)

        layout.addWidget(QLabel("Size mode"))
        self.combo_size_mode = QComboBox()
        self.combo_size_mode.addItem("Template", "template")
        self.combo_size_mode.addItem("Preset", "preset")
        self.combo_size_mode.addItem("Custom", "custom")
        self.combo_size_mode.setMinimumContentsLength(10)
        self.combo_size_mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_size_mode.currentIndexChanged.connect(self._on_size_mode_changed)
        layout.addWidget(self.combo_size_mode)

        layout.addWidget(QLabel("Preset"))
        self.combo_size_preset = QComboBox()
        self.combo_size_preset.addItem("Wide", "wide")
        self.combo_size_preset.addItem("Tall", "tall")
        self.combo_size_preset.addItem("Square", "square")
        self.combo_size_preset.setMinimumContentsLength(8)
        self.combo_size_preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_size_preset.currentIndexChanged.connect(self._on_size_preset_changed)
        layout.addWidget(self.combo_size_preset)

        dims_row = QHBoxLayout()
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(self.MIN_WIDTH_IN, self.MAX_WIDTH_IN)
        self.spin_width.setDecimals(2)
        self.spin_width.setSingleStep(0.05)
        self.spin_width.setValue(self._fig_spec.page.width_in)
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(self.MIN_HEIGHT_IN, self.MAX_HEIGHT_IN)
        self.spin_height.setDecimals(2)
        self.spin_height.setSingleStep(0.05)
        self.spin_height.setValue(self._fig_spec.page.height_in)
        dims_row.addWidget(QLabel("Figure width (in)"))
        dims_row.addWidget(self.spin_width)
        dims_row.addWidget(QLabel("Figure height (in)"))
        dims_row.addWidget(self.spin_height)

        layout.addLayout(dims_row)

        self.spin_width.valueChanged.connect(self._on_custom_size_changed)
        self.spin_height.valueChanged.connect(self._on_custom_size_changed)
        return grp

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------
    def _sync_controls_from_spec(self) -> None:
        """Populate controls from the current FigureSpec."""
        if self.trace_selector:
            with signals_blocked(self.trace_selector):
                self.trace_selector.setCurrentText(self._active_trace_key)
        # Trace style controls
        active_trace = self._get_trace_spec(self._active_trace_key)
        if active_trace and self.btn_trace_color:
            self.btn_trace_color.setStyleSheet(f"background-color: {active_trace.color};")
            self.btn_trace_color.setProperty("color", active_trace.color)
        if active_trace and self.spin_trace_width:
            with signals_blocked(self.spin_trace_width):
                self.spin_trace_width.setValue(active_trace.linewidth)

        axes = self._fig_spec.axes
        if self.cb_grid:
            self.cb_grid.setChecked(axes.show_grid)
        if self.cb_events:
            has_events = bool(self._fig_spec.events)
            self.cb_events.setEnabled(has_events)
            markers_on = bool(getattr(axes, "show_event_markers", True)) if has_events else False
            with signals_blocked(self.cb_events):
                self.cb_events.setChecked(markers_on)
        if self.cb_event_labels:
            labels_enabled = bool(self.cb_events.isChecked()) if self.cb_events else False
            self.cb_event_labels.setEnabled(labels_enabled)
            with signals_blocked(self.cb_event_labels):
                self.cb_event_labels.setChecked(axes.show_event_labels if labels_enabled else False)
        if self.cb_legend:
            self.cb_legend.setChecked(self._fig_spec.legend_visible)
        if self.edit_xlabel:
            self.edit_xlabel.setText(axes.xlabel)
        if self.edit_ylabel:
            self.edit_ylabel.setText(axes.ylabel)
        if self.spin_dpi:
            with signals_blocked(self.spin_dpi):
                self.spin_dpi.setValue(int(self._export_dpi))

        # Axis ranges
        x_auto = axes.x_range is None
        y_auto = axes.y_range is None
        if self.cb_x_auto:
            self.cb_x_auto.setChecked(x_auto)
        if self.cb_y_auto:
            self.cb_y_auto.setChecked(y_auto)
        if self.spin_x_min and self.spin_x_max and axes.x_range is not None:
            with signals_blocked(self.spin_x_min), signals_blocked(self.spin_x_max):
                self.spin_x_min.setValue(axes.x_range[0])
                self.spin_x_max.setValue(axes.x_range[1])
        if self.spin_y_min and self.spin_y_max and axes.y_range is not None:
            with signals_blocked(self.spin_y_min), signals_blocked(self.spin_y_max):
                self.spin_y_min.setValue(axes.y_range[0])
                self.spin_y_max.setValue(axes.y_range[1])
        for spin, auto in [
            (self.spin_x_min, x_auto),
            (self.spin_x_max, x_auto),
            (self.spin_y_min, y_auto),
            (self.spin_y_max, y_auto),
        ]:
            if spin is not None:
                spin.setEnabled(not auto)

        # Fonts - Axis titles
        if self.spin_axis_fontsize:
            self.spin_axis_fontsize.setValue(axes.xlabel_fontsize or 12.0)
        if self.combo_label_font:
            with signals_blocked(self.combo_label_font):
                self.combo_label_font.setCurrentText(axes.label_fontfamily)
        if self.cb_axis_bold:
            self.cb_axis_bold.setChecked(axes.label_bold)
        if self.cb_axis_italic:
            self.cb_axis_italic.setChecked(axes.label_fontstyle == "italic")

        # Fonts - Tick labels
        if self.spin_tick_fontsize:
            self.spin_tick_fontsize.setValue(axes.tick_label_fontsize or 9.0)
        if self.combo_tick_font:
            with signals_blocked(self.combo_tick_font):
                self.combo_tick_font.setCurrentText(axes.tick_fontfamily)
        if self.cb_tick_italic:
            self.cb_tick_italic.setChecked(axes.tick_fontstyle == "italic")

        # Fonts - Event labels
        if self.spin_event_label_fontsize:
            self.spin_event_label_fontsize.setValue(axes.event_label_fontsize or 9.0)
        if self.combo_event_label_font:
            with signals_blocked(self.combo_event_label_font):
                self.combo_event_label_font.setCurrentText(axes.event_label_fontfamily)
        if self.cb_event_label_bold:
            self.cb_event_label_bold.setChecked(axes.event_label_bold)
        if self.cb_event_label_italic:
            self.cb_event_label_italic.setChecked(axes.event_label_fontstyle == "italic")

        fig_w = getattr(self._fig_spec, "figure_width_in", self._fig_spec.page.width_in)
        fig_h = getattr(self._fig_spec, "figure_height_in", self._fig_spec.page.height_in)
        mode = getattr(self._fig_spec, "size_mode", "template")
        preset = getattr(self._fig_spec, "size_preset", None) or "wide"
        if self.combo_size_mode:
            idx = self.combo_size_mode.findData(mode)
            with signals_blocked(self.combo_size_mode):
                self.combo_size_mode.setCurrentIndex(idx if idx >= 0 else 0)
        if self.combo_size_preset:
            idx = self.combo_size_preset.findData(preset)
            with signals_blocked(self.combo_size_preset):
                self.combo_size_preset.setCurrentIndex(idx if idx >= 0 else 0)
            self.combo_size_preset.setEnabled(mode == "preset")
        if self.spin_width and self.spin_height:
            with signals_blocked(self.spin_width):
                self.spin_width.setValue(fig_w)
            with signals_blocked(self.spin_height):
                self.spin_height.setValue(fig_h)
            spins_enabled = mode == "custom"
            self.spin_width.setEnabled(spins_enabled)
            self.spin_height.setEnabled(spins_enabled)
        if self.combo_template:
            current_template = getattr(self._fig_spec, "template_id", DEFAULT_TEMPLATE_ID)
            for idx, (label, template_id) in enumerate(self._template_choices):
                if template_id == current_template:
                    with signals_blocked(self.combo_template):
                        self.combo_template.setCurrentIndex(idx)
                    break

        self._update_export_size_label()
        if self.cb_export_transparent is not None:
            with signals_blocked(self.cb_export_transparent):
                self.cb_export_transparent.setChecked(bool(self._export_transparent))

    def _enforce_page_bounds(self, update_controls: bool = True) -> None:
        """Clamp page size to min/max bounds to prevent label clipping or runaway sizes."""
        page = self._fig_spec.page
        clamped = False
        width = getattr(self._fig_spec, "figure_width_in", page.width_in)
        height = getattr(self._fig_spec, "figure_height_in", page.height_in)
        if width < self.MIN_WIDTH_IN:
            width = self.MIN_WIDTH_IN
            clamped = True
        if width > self.MAX_WIDTH_IN:
            width = self.MAX_WIDTH_IN
            clamped = True
        if height < self.MIN_HEIGHT_IN:
            height = self.MIN_HEIGHT_IN
            clamped = True
        if height > self.MAX_HEIGHT_IN:
            height = self.MAX_HEIGHT_IN
            clamped = True
        page.width_in = width
        page.height_in = height
        self._fig_spec.figure_width_in = width
        self._fig_spec.figure_height_in = height
        self._size_was_clamped = clamped
        if update_controls and self.spin_width and self.spin_height:
            with signals_blocked(self.spin_width):
                self.spin_width.setValue(width)
            with signals_blocked(self.spin_height):
                self.spin_height.setValue(height)

    def _template_base_size(self) -> tuple[float, float]:
        """Return the base template width/height in inches."""
        preset = get_template_preset(self._fig_spec.template_id)
        layout = getattr(preset, "layout_defaults", {}) or {}
        return (
            float(layout.get("width_in", self.DEFAULT_WIDTH_IN)),
            float(layout.get("height_in", self.DEFAULT_HEIGHT_IN)),
        )

    def _set_figure_size(self, width_in: float, height_in: float, *, update_controls: bool) -> None:
        """Update figure + page sizes together before enforcing bounds."""
        self._fig_spec.figure_width_in = float(width_in)
        self._fig_spec.figure_height_in = float(height_in)
        self._fig_spec.page.width_in = float(width_in)
        self._fig_spec.page.height_in = float(height_in)
        self._enforce_page_bounds(update_controls=update_controls)

    def _apply_size_policy_from_spec(
        self, *, force_recompute: bool = False, refresh: bool = False, update_controls: bool = True
    ) -> None:
        """
        Apply the stored size_mode/size_preset to derive the live figure size.

        Preset sizes are derived from template defaults when requested (force_recompute),
        while custom sizes honor the stored inches. Template mode always re-syncs to
        template defaults.
        """
        base_w, base_h = self._template_base_size()
        mode = getattr(self._fig_spec, "size_mode", "template")
        preset = getattr(self._fig_spec, "size_preset", None)
        width = getattr(self._fig_spec, "figure_width_in", None)
        height = getattr(self._fig_spec, "figure_height_in", None)

        if mode == "template":
            width, height = base_w, base_h
            self._fig_spec.size_preset = None
        elif mode == "preset":
            preset = preset or "wide"
            if force_recompute or width is None or height is None:
                width, height = preset_dimensions_from_base(base_w, base_h, preset)
            self._fig_spec.size_preset = preset
        else:  # custom
            if width is None or height is None:
                width, height = base_w, base_h
            self._fig_spec.size_preset = None

        self._set_figure_size(width, height, update_controls=update_controls)
        if refresh:
            self._refresh_preview(size_changed=True)

    def _format_default_view_note(self) -> str | None:
        if self._default_xlim is None and self._default_ylim is None:
            return None
        parts: list[str] = []
        if self._default_xlim is not None:
            parts.append(f"X={self._default_xlim[0]:.3g}–{self._default_xlim[1]:.3g}")
        if self._default_ylim is not None:
            parts.append(f"Y={self._default_ylim[0]:.3g}–{self._default_ylim[1]:.3g}")
        if not parts:
            return None
        return f"Initialized from main window view: {'; '.join(parts)}"

    def _apply_default_view_once(self) -> None:
        """Apply provided default axis limits a single time on first show."""
        if self._applied_default_view:
            return

        axes = self._fig_spec.axes
        applied = False

        if self._default_xlim is not None:
            x0, x1 = self._default_xlim
            axes.x_range = (float(x0), float(x1))
            applied = True
            if self.cb_x_auto:
                with signals_blocked(self.cb_x_auto):
                    self.cb_x_auto.setChecked(False)
            if self.spin_x_min and self.spin_x_max:
                with signals_blocked(self.spin_x_min):
                    self.spin_x_min.setValue(float(x0))
                with signals_blocked(self.spin_x_max):
                    self.spin_x_max.setValue(float(x1))
                self.spin_x_min.setEnabled(True)
                self.spin_x_max.setEnabled(True)

        if self._default_ylim is not None:
            y0, y1 = self._default_ylim
            axes.y_range = (float(y0), float(y1))
            applied = True
            if self.cb_y_auto:
                with signals_blocked(self.cb_y_auto):
                    self.cb_y_auto.setChecked(False)
            if self.spin_y_min and self.spin_y_max:
                with signals_blocked(self.spin_y_min):
                    self.spin_y_min.setValue(float(y0))
                with signals_blocked(self.spin_y_max):
                    self.spin_y_max.setValue(float(y1))
                self.spin_y_min.setEnabled(True)
                self.spin_y_max.setEnabled(True)

        if applied:
            self._applied_default_view = True
            self._default_view_note = self._format_default_view_note()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def showEvent(self, event: QShowEvent) -> None:
        """Ensure the first refresh happens after the dialog is visible and layout is sane."""
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_dynamic_minimum_size)
        needs_init = not self._splitter_initialized
        if self._main_splitter is not None:
            sizes = self._main_splitter.sizes()
            if len(sizes) >= 2 and sizes[0] > 0 and sizes[1] >= CONTROL_MIN_W:
                needs_init = False
        if needs_init:
            QTimer.singleShot(0, lambda: self._init_splitter_sizes_once(force=True))
        if not self._first_show_done:
            self._first_show_done = True
            self._apply_default_view_once()
            self._refresh_preview()

    def apply_theme(self) -> None:
        """Update theme-dependent colors when theme changes."""
        # Update grid color in axes spec
        if hasattr(self, '_fig_spec') and self._fig_spec.axes is not None:
            self._fig_spec.axes.grid_color = CURRENT_THEME.get("grid_color", "#c0c0c0")

        # Update export label color
        if hasattr(self, 'label_export_size') and self.label_export_size is not None:
            text_color = CURRENT_THEME.get("text", "#6c757d")
            self.label_export_size.setStyleSheet(f"color: {text_color};")

        # Update rectangle selector edge color if it exists
        if hasattr(self, '_box_selector') and self._box_selector is not None:
            try:
                ax = self._box_selector.ax
                self._box_selector.set_active(False)
                self._box_selector = RectangleSelector(
                    ax,
                    self._on_box_selected,
                    useblit=True,
                    button=[1],
                    interactive=False,
                    drag_from_anywhere=True,
                    props=dict(
                        edgecolor=CURRENT_THEME.get("text", "#000000"),
                        facecolor="none",
                        linewidth=1.0,
                        linestyle="--"
                    ),
                )
                self._box_selector.connect_event("motion_notify_event", self._on_box_drag)
            except Exception:
                pass

        # Refresh preview to show new colors
        if hasattr(self, '_refresh_preview'):
            self._refresh_preview()

    def _on_trace_selected(self, key: str) -> None:
        self._active_trace_key = key
        for trace in self._fig_spec.traces:
            trace.visible = trace.key == key
        self._sync_controls_from_spec()
        self._refresh_preview()

    def _on_trace_color_clicked(self) -> None:
        trace = self._get_trace_spec(self._active_trace_key)
        if trace is None or self.btn_trace_color is None:
            return
        color = QColorDialog.getColor()
        if not color.isValid():
            return
        trace.color = color.name()
        self.btn_trace_color.setStyleSheet(f"background-color: {trace.color};")
        self.btn_trace_color.setProperty("color", trace.color)
        self._refresh_preview()

    def _on_trace_width_changed(self, value: float) -> None:
        trace = self._get_trace_spec(self._active_trace_key)
        if trace is None:
            return
        trace.linewidth = float(value)
        self._refresh_preview()

    def _on_axis_labels_changed(self) -> None:
        axes = self._fig_spec.axes
        axes.xlabel = self.edit_xlabel.text() if self.edit_xlabel else axes.xlabel
        axes.ylabel = self.edit_ylabel.text() if self.edit_ylabel else axes.ylabel
        self._refresh_preview()

    def _reset_view_ranges(self) -> None:
        """Restore full-trace view by re-enabling autoscale on both axes."""
        axes = self._fig_spec.axes
        axes.x_range = None
        axes.y_range = None

        if self.cb_x_auto:
            with signals_blocked(self.cb_x_auto):
                self.cb_x_auto.setChecked(True)
        if self.cb_y_auto:
            with signals_blocked(self.cb_y_auto):
                self.cb_y_auto.setChecked(True)

        for spin in [self.spin_x_min, self.spin_x_max, self.spin_y_min, self.spin_y_max]:
            if spin is not None:
                spin.setEnabled(False)

        self._refresh_preview()

    def _on_grid_toggled(self, checked: bool) -> None:
        self._fig_spec.axes.show_grid = checked
        self._refresh_preview()

    def _on_export_background_toggled(self, checked: bool) -> None:
        self._export_transparent = bool(checked)
        if hasattr(self._fig_spec.page, "export_background"):
            self._fig_spec.page.export_background = "transparent" if checked else "white"
        self._update_export_size_label()

    def _on_export_dpi_changed(self, value: int) -> None:
        """Update export DPI without altering the live preview figure."""
        self._export_dpi = float(value)
        self._update_export_size_label()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_window_state()
        # Persist any pending changes
        self._persist_recipe_snapshot()
        # Immediately emit signal on close (don't wait for debounce timer)
        if self._pending_signal_emit and self.dataset_id:
            self._emit_tree_update_signal()
        super().closeEvent(event)

    def _on_events_toggled(self, checked: bool) -> None:
        self._set_events_visible(checked)

    def _on_event_labels_toggled(self, checked: bool) -> None:
        if not self.cb_event_labels:
            return
        axes = self._fig_spec.axes
        if self.cb_events and not self.cb_events.isChecked():
            with signals_blocked(self.cb_event_labels):
                self.cb_event_labels.setChecked(False)
            axes.show_event_labels = False
            return
        if not getattr(axes, "show_event_markers", True):
            with signals_blocked(self.cb_event_labels):
                self.cb_event_labels.setChecked(False)
            axes.show_event_labels = False
            return
        axes.show_event_labels = checked
        self._refresh_preview()

    def _on_legend_toggled(self, checked: bool) -> None:
        self._fig_spec.legend_visible = checked
        self._refresh_preview()

    def _on_axis_range_mode_changed(self, axis: str, auto: bool) -> None:
        spins = (
            (self.spin_x_min, self.spin_x_max)
            if axis == "x"
            else (self.spin_y_min, self.spin_y_max)
        )
        for spin in spins:
            if spin is not None:
                spin.setEnabled(not auto)
        self._apply_axis_ranges()

    def _on_font_changed(self) -> None:
        axes = self._fig_spec.axes

        # Axis titles
        if self.spin_axis_fontsize:
            axes.xlabel_fontsize = float(self.spin_axis_fontsize.value())
            axes.ylabel_fontsize = float(self.spin_axis_fontsize.value())
        if self.combo_label_font:
            axes.label_fontfamily = self.combo_label_font.currentText()
        if self.cb_axis_bold:
            axes.label_bold = self.cb_axis_bold.isChecked()
        if self.cb_axis_italic:
            axes.label_fontstyle = "italic" if self.cb_axis_italic.isChecked() else "normal"

        # Tick labels
        if self.spin_tick_fontsize:
            axes.tick_label_fontsize = float(self.spin_tick_fontsize.value())
        if self.combo_tick_font:
            axes.tick_fontfamily = self.combo_tick_font.currentText()
        if self.cb_tick_italic:
            axes.tick_fontstyle = "italic" if self.cb_tick_italic.isChecked() else "normal"

        # Event labels
        if self.spin_event_label_fontsize:
            axes.event_label_fontsize = float(self.spin_event_label_fontsize.value())
        if self.combo_event_label_font:
            axes.event_label_fontfamily = self.combo_event_label_font.currentText()
        if self.cb_event_label_bold:
            axes.event_label_bold = self.cb_event_label_bold.isChecked()
        if self.cb_event_label_italic:
            axes.event_label_fontstyle = "italic" if self.cb_event_label_italic.isChecked() else "normal"

        self._refresh_preview()  # Font changes don't affect canvas size

    def _on_size_mode_changed(self, _: int) -> None:
        if not self.combo_size_mode:
            return
        mode = self.combo_size_mode.currentData() or "template"
        self._fig_spec.size_mode = mode
        if mode != "preset":
            self._fig_spec.size_preset = None
        if mode == "preset" and self._fig_spec.size_preset is None:
            if self.combo_size_preset:
                self._fig_spec.size_preset = self.combo_size_preset.currentData()
            if not self._fig_spec.size_preset:
                self._fig_spec.size_preset = "wide"
        self._apply_size_policy_from_spec(
            force_recompute=mode in ("template", "preset"),
            refresh=True,
            update_controls=True,
        )
        self._sync_controls_from_spec()

    def _on_size_preset_changed(self, _: int) -> None:
        if not self.combo_size_preset:
            return
        preset = self.combo_size_preset.currentData() or "wide"
        self._fig_spec.size_mode = "preset"
        self._fig_spec.size_preset = preset
        self._apply_size_policy_from_spec(force_recompute=True, refresh=True, update_controls=True)
        self._sync_controls_from_spec()

    def _on_custom_size_changed(self) -> None:
        if not self.spin_width or not self.spin_height:
            return
        if getattr(self._fig_spec, "size_mode", "template") != "custom":
            return
        width = float(self.spin_width.value())
        height = float(self.spin_height.value())
        self._fig_spec.size_preset = None
        self._set_figure_size(width, height, update_controls=True)
        self._update_export_size_label()
        self._refresh_preview(size_changed=True)

    def _on_template_changed(self, _: str) -> None:
        """Switch template presets while respecting user overrides."""
        template_id = DEFAULT_TEMPLATE_ID
        if self.combo_template:
            template_id = self.combo_template.currentData() or DEFAULT_TEMPLATE_ID
        self._fig_spec.template_id = template_id
        self._template_defaults_cache = apply_template_preset(
            self._fig_spec,
            template_id,
            previous_defaults=self._template_defaults_cache,
            respect_overrides=True,
        )
        self._apply_size_policy_from_spec(
            force_recompute=getattr(self._fig_spec, "size_mode", "template") in ("template", "preset"),
            refresh=False,
            update_controls=False,
        )
        self._enforce_page_bounds(update_controls=False)
        self._update_export_size_label()
        self._sync_controls_from_spec()
        self._refresh_preview(size_changed=True)

    # ------------------------------------------------------------------
    # Preview helpers
    # ------------------------------------------------------------------
    def _settings(self) -> QSettings:
        return QSettings("TykockiLab", "VasoAnalyzer")

    def _restore_window_state(self) -> bool:
        """Restore saved window geometry and splitter sizes; return True if anything restored."""
        restored_any = False
        settings = self._settings()
        try:
            geom = settings.value("composer/windowGeometry")
            if geom is not None:
                self.restoreGeometry(geom)
                restored_any = True
        except Exception:
            log.debug("Failed to restore composer window geometry", exc_info=True)
        try:
            sizes = settings.value("composer/splitterSizes")
            if sizes:
                sizes_list = [int(s) for s in sizes]
                if (
                    len(sizes_list) >= 2
                    and sizes_list[1] >= CONTROL_MIN_W
                    and all(s > 0 for s in sizes_list)
                    and self._main_splitter is not None
                ):
                    self._main_splitter.setSizes(sizes_list)
                    self._splitter_initialized = True
                    restored_any = True
        except Exception:
            log.debug("Failed to restore composer splitter sizes", exc_info=True)
        return restored_any

    def _save_window_state(self) -> None:
        """Persist window geometry and splitter sizes."""
        settings = self._settings()
        try:
            settings.setValue("composer/windowGeometry", self.saveGeometry())
        except Exception:
            log.debug("Failed to persist composer geometry", exc_info=True)
        try:
            if self._main_splitter is not None:
                settings.setValue("composer/splitterSizes", self._main_splitter.sizes())
        except Exception:
            log.debug("Failed to persist composer splitter sizes", exc_info=True)

    def _log_layout_state_once(self) -> None:
        """Temporary diagnostic log for layout wiring."""
        try:
            main = self.centralWidget()
            child = main.layout().itemAt(0).widget() if main and main.layout() else None
            is_splitter = isinstance(child, QSplitter)
            sizes = child.sizes() if is_splitter else []
            log.info(
                "Composer layout: main=%s splitter=%s children=%s sizes=%s",
                type(main).__name__ if main else None,
                type(child).__name__ if child else None,
                child.count() if is_splitter else None,
                sizes,
            )
        except Exception:
            log.debug("Failed to log layout state", exc_info=True)

    def _set_manual_ranges(self, xmin: float, xmax: float, ymin: float, ymax: float, *, refresh: bool) -> None:
        """Update spec ranges and optionally rebuild; used by box select."""
        axes = self._fig_spec.axes
        axes.x_range = (xmin, xmax)
        axes.y_range = (ymin, ymax)
        if refresh:
            self._refresh_preview()
            return
        ax = self._current_axes()
        if ax is not None:
            ax.set_xlim(xmin, xmax)
            ax.set_ylim(ymin, ymax)
        if self._canvas:
            self._canvas.draw_idle()

    def _selector_extents(self) -> tuple[float, float, float, float] | None:
        """Safely read selector extents; return None on failure."""
        sel = self._box_selector
        if sel is None:
            return None
        try:
            ext = getattr(sel, "extents", None)
            if ext and len(ext) == 4:
                return tuple(ext)  # type: ignore[return-value]
        except Exception:
            log.debug("Failed to read selector extents", exc_info=True)
        self._disable_box_select_mode()
        return None

    def _disable_box_select_mode(self) -> None:
        """Turn off box select cleanly without errors."""
        if self.btn_box_select:
            with signals_blocked(self.btn_box_select):
                self.btn_box_select.setChecked(False)
        self._destroy_box_selector()

    def _sync_canvas_size_to_figure(self) -> None:
        """Ensure the offscreen canvas matches the figure pixel size."""
        if self._canvas is None or self._figure is None:
            return
        w_px = int(self._figure.get_figwidth() * self._figure.get_dpi())
        h_px = int(self._figure.get_figheight() * self._figure.get_dpi())
        w_px = max(1, w_px)
        h_px = max(1, h_px)
        if (self._last_figure_size == (w_px, h_px) and self._canvas.width() == w_px and self._canvas.height() == h_px):
            return
        self._last_figure_size = (w_px, h_px)
        self._canvas.setFixedSize(w_px, h_px)

    def _render_preview_image(self) -> None:
        """Render the current figure to a QImage and hand it to the viewport."""
        if self._canvas is None or self._preview_viewport is None:
            return
        if self._in_preview_capture:
            return
        renderer_ready = bool(getattr(self._canvas, "renderer", None))
        log.info(
            "Preview capture begin: canvas=%sx%s renderer_ready=%s dpi=%.2f",
            self._canvas.width(),
            self._canvas.height(),
            renderer_ready,
            self._figure.get_dpi() if self._figure else -1,
        )
        self._in_preview_capture = True
        try:
            self._canvas.draw()
            try:
                buf = self._canvas.buffer_rgba()
            except Exception:
                log.exception("Preview capture failed: canvas.buffer_rgba()")
                return

            try:
                h_px, w_px = buf.shape[:2]
            except Exception:
                w_px, h_px = map(int, self._figure.bbox.size)
            log.info("Preview buffer shape w=%s h=%s", w_px, h_px)

            if w_px <= 0 or h_px <= 0:
                log.warning("Preview capture produced invalid size: w=%s h=%s", w_px, h_px)
                return

            try:
                data = buf.tobytes()
                bytes_per_line = 4 * w_px
                qimg = QImage(data, w_px, h_px, bytes_per_line, QImage.Format_RGBA8888).copy()
            except Exception:
                log.exception("Preview capture failed: QImage construction w=%s h=%s", w_px, h_px)
                return

            if qimg.isNull():
                log.warning("Preview capture produced null QImage w=%s h=%s", w_px, h_px)
                return
            log.info(
                "Preview capture ready: qimg=%sx%s dpr=%.2f isNull=%s viewport=%sx%s",
                qimg.width(),
                qimg.height(),
                float(qimg.devicePixelRatio()),
                qimg.isNull(),
                self._preview_viewport.width(),
                self._preview_viewport.height(),
            )
            self._preview_viewport.set_image(qimg)
            self._preview_viewport.update()
        finally:
            self._in_preview_capture = False

    def _update_scale_label_from_viewport(self, scale: float) -> None:
        if self._preview_scale_label is None:
            return
        if scale < 0.999:
            pct = int(scale * 100)
            self._preview_scale_label.setText(f"Preview scaled to fit: {pct}%")
        else:
            self._preview_scale_label.setText("Preview at 100%")
        self._preview_scale_label.setVisible(True)

    def _toggle_box_select(self, checked: bool) -> None:
        if not checked:
            self._destroy_box_selector()
            return
        ax = self._current_axes()
        if ax is None:
            self._disable_box_select_mode()
            return
        self._create_box_selector(ax)

    def _create_box_selector(self, ax) -> None:
        self._destroy_box_selector()
        self._box_dragging = False
        self._box_selector = RectangleSelector(
            ax,
            self._on_box_selected,
            useblit=True,
            button=[1],
            interactive=False,
            drag_from_anywhere=True,
            props=dict(
                edgecolor=CURRENT_THEME.get("text", "#000000"),
                facecolor="none",
                linewidth=1.0,
                linestyle="--"
            ),
        )
        self._box_selector.connect_event("motion_notify_event", self._on_box_drag)

    def _on_box_drag(self, event) -> None:
        """Live-update ranges while dragging the selector."""
        extents = self._selector_extents()
        if extents is None:
            return
        x0, x1, y0, y1 = extents
        if any(val is None for val in [x0, x1, y0, y1]):
            return
        xmin, xmax = sorted([float(x0), float(x1)])
        ymin, ymax = sorted([float(y0), float(y1)])
        # Avoid updates for degenerate boxes
        if abs(xmax - xmin) < 1e-9 or abs(ymax - ymin) < 1e-9:
            return

        # Switch to manual once dragging starts
        if not self._box_dragging:
            self._box_dragging = True
            for cb in [self.cb_x_auto, self.cb_y_auto]:
                if cb:
                    with signals_blocked(cb):
                        cb.setChecked(False)
            for spin in [self.spin_x_min, self.spin_x_max, self.spin_y_min, self.spin_y_max]:
                if spin:
                    spin.setEnabled(True)

        # Update spin boxes without triggering handlers
        if self.spin_x_min and self.spin_x_max:
            with signals_blocked(self.spin_x_min):
                self.spin_x_min.setValue(xmin)
            with signals_blocked(self.spin_x_max):
                self.spin_x_max.setValue(xmax)
        if self.spin_y_min and self.spin_y_max:
            with signals_blocked(self.spin_y_min):
                self.spin_y_min.setValue(ymin)
            with signals_blocked(self.spin_y_max):
                self.spin_y_max.setValue(ymax)

        # Apply limits to the spec and live axes for immediate visual feedback
        self._set_manual_ranges(xmin, xmax, ymin, ymax, refresh=False)

    def _destroy_box_selector(self) -> None:
        if self._box_selector is not None:
            try:
                self._box_selector.disconnect_events()
                self._box_selector.set_visible(False)
            except Exception:
                log.debug("Error tearing down box selector", exc_info=True)
        self._box_selector = None
        self._box_dragging = False

    def _on_box_selected(self, eclick, erelease) -> None:
        """Apply box selection to axis ranges and exit select mode."""
        extents = self._selector_extents()
        if extents is None:
            return
        x0, x1, y0, y1 = extents
        xmin, xmax = sorted([float(x0), float(x1)])
        ymin, ymax = sorted([float(y0), float(y1)])
        # Ignore tiny selections
        if abs(xmax - xmin) < 1e-9 or abs(ymax - ymin) < 1e-9:
            return
        self._box_dragging = False
        # Force manual mode and apply ranges
        for cb in [self.cb_x_auto, self.cb_y_auto]:
            if cb:
                with signals_blocked(cb):
                    cb.setChecked(False)
        if self.spin_x_min and self.spin_x_max:
            with signals_blocked(self.spin_x_min):
                self.spin_x_min.setValue(xmin)
            with signals_blocked(self.spin_x_max):
                self.spin_x_max.setValue(xmax)
            self.spin_x_min.setEnabled(True)
            self.spin_x_max.setEnabled(True)
        if self.spin_y_min and self.spin_y_max:
            with signals_blocked(self.spin_y_min):
                self.spin_y_min.setValue(ymin)
            with signals_blocked(self.spin_y_max):
                self.spin_y_max.setValue(ymax)
            self.spin_y_min.setEnabled(True)
            self.spin_y_max.setEnabled(True)

        # Commit to spec and rebuild
        self._set_manual_ranges(xmin, xmax, ymin, ymax, refresh=True)

        if self.btn_box_select:
            with signals_blocked(self.btn_box_select):
                self.btn_box_select.setChecked(False)
        self._destroy_box_selector()

    def _current_axes(self):
        if self._figure is None:
            return None
        return self._figure.axes[0] if self._figure.axes else None

    def _set_events_visible(self, visible: bool) -> None:
        axes = self._fig_spec.axes
        has_events = bool(self._fig_spec.events)
        if not has_events:
            if self.cb_events:
                with signals_blocked(self.cb_events):
                    self.cb_events.setChecked(False)
            if self.cb_event_labels:
                with signals_blocked(self.cb_event_labels):
                    self.cb_event_labels.setChecked(False)
                self.cb_event_labels.setEnabled(False)
            axes.show_event_markers = False
            axes.show_event_labels = False
            return

        axes.show_event_markers = bool(visible)
        if not visible:
            axes.show_event_labels = False
            if self.cb_event_labels:
                with signals_blocked(self.cb_event_labels):
                    self.cb_event_labels.setChecked(False)
                self.cb_event_labels.setEnabled(False)
        else:
            if self.cb_event_labels:
                self.cb_event_labels.setEnabled(True)
                with signals_blocked(self.cb_event_labels):
                    self.cb_event_labels.setChecked(axes.show_event_labels)

        self._refresh_preview()

    def _apply_axis_ranges(self) -> None:
        axes = self._fig_spec.axes
        if self.cb_x_auto and self.cb_x_auto.isChecked():
            axes.x_range = None
        else:
            xmin = float(self.spin_x_min.value()) if self.spin_x_min else 0.0
            xmax = float(self.spin_x_max.value()) if self.spin_x_max else 1.0
            if xmax <= xmin:
                xmax = xmin + 1e-3
                if self.spin_x_max:
                    with signals_blocked(self.spin_x_max):
                        self.spin_x_max.setValue(xmax)
            axes.x_range = (xmin, xmax)

        if self.cb_y_auto and self.cb_y_auto.isChecked():
            axes.y_range = None
        else:
            ymin = float(self.spin_y_min.value()) if self.spin_y_min else 0.0
            ymax = float(self.spin_y_max.value()) if self.spin_y_max else 1.0
            if ymax <= ymin:
                ymax = ymin + 1e-3
                if self.spin_y_max:
                    with signals_blocked(self.spin_y_max):
                        self.spin_y_max.setValue(ymax)
            axes.y_range = (ymin, ymax)

        self._refresh_preview()

    def _refresh_preview(self, *, size_changed: bool = False) -> None:
        """
        Refresh the figure preview.

        Args:
            size_changed: Kept for compatibility with callers; the preview always
                         re-applies fit-to-pane scaling to avoid clipping.
        """
        if not self._preview_initialized or self._figure is None or self._canvas is None:
            return
        log.info(
            "Preview refresh start size_changed=%s fig_px=%s canvas=%sx%s renderer=%s",
            size_changed,
            self._last_figure_size,
            self._canvas.width(),
            self._canvas.height(),
            bool(getattr(self._canvas, "renderer", None)),
        )
        self._enforce_page_bounds(update_controls=True)
        ctx = self._render_context(is_preview=True)
        build_figure(self._fig_spec, ctx, fig=self._figure)
        # Force preview to look like a white page regardless of app theme
        self._figure.patch.set_facecolor("white")
        self._figure.patch.set_alpha(1.0)
        for ax in self._figure.get_axes():
            ax.set_facecolor("white")
        ax = self._current_axes()
        if self.btn_box_select and self.btn_box_select.isChecked():
            if ax is not None:
                self._create_box_selector(ax)
        else:
            self._destroy_box_selector()
        self._render_preview_image()
        self._update_export_size_label()
        self._mark_dirty_and_schedule_persist()
        log.info("Preview refresh done")

    def _apply_dynamic_minimum_size(self) -> None:
        """Derive a sane minimum window size from panel hints and preview needs."""
        rp = self._right_panel
        rp_w = 0
        if rp is not None:
            rp_w = rp.minimumSizeHint().width()
            if rp_w <= 0:
                rp_w = rp.sizeHint().width()
            if rp_w <= 0:
                rp_w = rp.width()
        rp_w = max(0, rp_w)

        central = self.centralWidget()
        layout = central.layout() if central is not None else None
        spacing = layout.spacing() if layout is not None else 0

        if layout is not None:
            margins = layout.contentsMargins()
            lm, tm, rm, bm = margins.left(), margins.top(), margins.right(), margins.bottom()
        else:
            lm = tm = rm = bm = 0

        min_w = max(
            WINDOW_MIN_W,
            int(rp_w + MIN_PREVIEW_W + spacing + lm + rm + EXTRA_W_PAD),
        )
        min_h = int(MIN_PREVIEW_H + tm + bm + EXTRA_H_PAD)
        self.setMinimumSize(min_w, min_h)

    def _init_splitter_sizes_once(self, *, retry: bool = False, force: bool = False) -> None:
        """Give the preview most space while keeping the right panel visible."""
        if self._splitter_initialized and not force:
            return
        if self._main_splitter is None or self._right_panel is None:
            return
        sizes_now = self._main_splitter.sizes()
        if (
            not force
            and len(sizes_now) >= 2
            and sizes_now[0] > 0
            and sizes_now[1] >= CONTROL_MIN_W
        ):
            self._splitter_initialized = True
            return
        panel_w = max(CONTROL_MIN_W, self._right_panel.minimumWidth())
        total_w = max(self.width(), WINDOW_MIN_W)
        self._main_splitter.setCollapsible(1, False)
        self._main_splitter.setHandleWidth(max(8, self._main_splitter.handleWidth()))
        self._main_splitter.setSizes([max(PREVIEW_MIN_W, total_w - panel_w), panel_w])
        sizes = self._main_splitter.sizes()
        log.info("Composer splitter sizes after init%s: %s", " (retry)" if retry else "", sizes)
        if len(sizes) >= 2 and sizes[1] >= CONTROL_MIN_W and all(s > 0 for s in sizes):
            self._splitter_initialized = True
            return
        if not self._splitter_retry_scheduled:
            self._splitter_retry_scheduled = True
            QTimer.singleShot(50, lambda: self._init_splitter_sizes_once(retry=True, force=True))

    def _update_export_size_label(self) -> None:
        if self.label_export_size is None:
            return
        page = self._fig_spec.page
        axes_w_in = page.width_in
        axes_h_in = page.height_in
        fig_w_in = page.effective_width_in or axes_w_in
        fig_h_in = page.effective_height_in or axes_h_in
        export_dpi = self._export_dpi or page.dpi
        w_px = int(fig_w_in * export_dpi)
        h_px = int(fig_h_in * export_dpi)
        clamp_note = ""
        if self._size_was_clamped:
            clamp_note = (
                f" (clamped to {self.MIN_WIDTH_IN:.1f}-{self.MAX_WIDTH_IN:.1f} in width "
                f"and {self.MIN_HEIGHT_IN:.1f}-{self.MAX_HEIGHT_IN:.1f} in height)"
            )
        text = (
            f"Axes: {axes_w_in:.2f} × {axes_h_in:.2f} in @ {export_dpi:.0f} dpi (export)\n"
            f"Resulting figure size: {fig_w_in:.2f} × {fig_h_in:.2f} in ({w_px} × {h_px} px){clamp_note}"
        )
        if self._default_view_note:
            text = f"{text}\n{self._default_view_note}"
        self.label_export_size.setText(text)

    @contextmanager
    def _project_repo(self):
        """Yield a short-lived SQLiteProjectRepository for persistence."""
        repo = None
        close_repo = False
        project_path = getattr(self.project, "path", None)
        try:
            if project_path:
                try:
                    from vasoanalyzer.services.project_service import open_project_repository

                    repo = open_project_repository(project_path)
                    close_repo = True
                except Exception:
                    log.debug("Failed to open fresh project repository", exc_info=True)
            if repo is None:
                store = getattr(self.project, "_store", None)
                if store is not None:
                    from vasoanalyzer.services.project_service import SQLiteProjectRepository

                    repo = SQLiteProjectRepository(store)
            yield repo
        finally:
            if close_repo and repo is not None:
                try:
                    repo.close()
                except Exception:
                    log.debug("Failed to close project repository", exc_info=True)

    def _persist_recipe_snapshot(self) -> None:
        """Persist the current FigureSpec back to the recipe record."""
        if not self._recipe_id:
            log.debug("No recipe_id set, skipping persistence")
            return
        self._pending_dirty = False

        print(f"\n[COMPOSER AUTOSAVE] Persisting recipe {self._recipe_id} for dataset {self.dataset_id}")

        with self._project_repo() as repo:
            if repo is None:
                print(f"[COMPOSER AUTOSAVE] ✗ No repository available")
                log.warning("Cannot persist recipe: no repository available")
                return

            try:
                spec_dict = figure_spec_to_dict(self._fig_spec)
                axes = self._fig_spec.axes
                x_range = axes.x_range
                y_range = axes.y_range
                trace_key = self._active_trace_key
                export_bg = getattr(self._fig_spec.page, "export_background", "white")

                repo.update_figure_recipe(
                    self._recipe_id,
                    spec_json=json.dumps(spec_dict),
                    trace_key=trace_key,
                    x_min=x_range[0] if x_range else None,
                    x_max=x_range[1] if x_range else None,
                    y_min=y_range[0] if y_range else None,
                    y_max=y_range[1] if y_range else None,
                    export_background=export_bg,
                )
                print(f"[COMPOSER AUTOSAVE] ✓ Recipe updated in database")
                log.debug(f"Persisted recipe {self._recipe_id} for dataset {self.dataset_id}")

                # Signal the tree to refresh immediately after persistence
                print(f"[COMPOSER AUTOSAVE] Scheduling tree signal emission...")
                self._schedule_signal_emission(immediate=True)

            except Exception as e:
                print(f"[COMPOSER AUTOSAVE] ✗ Failed to persist: {e}")
                log.error(f"Failed to persist recipe snapshot: {e}", exc_info=True)

    def _mark_dirty_and_schedule_persist(self) -> None:
        """Mark pending changes and debounce persistence to reduce DB churn."""
        if not self._recipe_id:
            return
        self._pending_dirty = True
        if self._persist_timer is None:
            self._persist_timer = QTimer(self)
            self._persist_timer.setSingleShot(True)
            self._persist_timer.timeout.connect(self._persist_recipe_snapshot)
        self._persist_timer.stop()
        # Longer debounce to coalesce edits; prevents rapid reopen/close of sqlite
        self._persist_timer.start(1500)

    def _schedule_signal_emission(self, *, immediate: bool = False) -> None:
        """Emit (or schedule) a tree update after persistence."""
        if not self.dataset_id:
            return
        self._pending_signal_emit = True
        if immediate:
            if self._signal_emit_timer is not None:
                self._signal_emit_timer.stop()
            self._emit_tree_update_signal()
            return
        if self._signal_emit_timer is None:
            self._signal_emit_timer = QTimer(self)
            self._signal_emit_timer.setSingleShot(True)
            self._signal_emit_timer.timeout.connect(self._emit_tree_update_signal)
        self._signal_emit_timer.stop()
        # Longer debounce (3 seconds) to avoid tree update spam during active editing
        self._signal_emit_timer.start(3000)

    def _emit_tree_update_signal(self) -> None:
        """Emit signal to parent window to update the project tree."""
        if not self._pending_signal_emit or not self.dataset_id:
            return
        self._pending_signal_emit = False

        parent = self.parent()
        signal = getattr(parent, "figure_recipes_changed", None)
        if signal is not None and hasattr(signal, "emit"):
            try:
                signal.emit(int(self.dataset_id))
                log.debug(f"Emitted debounced figure_recipes_changed signal for dataset {self.dataset_id}")
            except Exception as e:
                log.error(f"Failed to emit figure_recipes_changed signal: {e}", exc_info=True)
        # Fallback: call the tree updater directly if available (ensures immediate refresh)
        updater = getattr(parent, "_update_sample_tree_figures", None)
        if callable(updater):
            try:
                updater(int(self.dataset_id))
                log.debug(f"Called _update_sample_tree_figures for dataset {self.dataset_id}")
            except Exception as e:
                log.error(f"Failed to call _update_sample_tree_figures: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _export_dialog(self) -> None:
        # Generate a smart default filename
        default_name = "figure"
        if self._recipe_id:
            # Try to get recipe name
            with self._project_repo() as repo:
                if repo:
                    try:
                        recipe = repo.get_figure_recipe(self._recipe_id)
                        if recipe and recipe.get("name"):
                            # Clean the name for filesystem
                            default_name = recipe["name"].replace("/", "-").replace("\\", "-")
                    except Exception:
                        pass

        suggested = Path.cwd() / f"{default_name}.png"
        filter_defs = [
            {"label": "PNG Image (*.png)", "exts": [".png"], "kind": "png"},
            {"label": "TIFF Image (*.tiff *.tif)", "exts": [".tiff", ".tif"], "kind": "tiff"},
            {"label": "PDF Document (*.pdf)", "exts": [".pdf"], "kind": "pdf"},
            {"label": "SVG Vector (*.svg)", "exts": [".svg"], "kind": "svg"},
            {"label": "All Files (*)", "exts": [], "kind": "any"},
        ]
        filter_labels = ";;".join([f["label"] for f in filter_defs])
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Figure",
            str(suggested),
            filter_labels,
        )
        if not path:
            return

        meta_lookup = {f["label"]: f for f in filter_defs}
        meta = meta_lookup.get(selected_filter, {"exts": [], "kind": "any"})

        # Ensure the file has the correct extension based on selected filter
        exts = meta.get("exts", [])
        path_obj = Path(path)
        if exts:
            lower_suffix = path_obj.suffix.lower()
            if lower_suffix not in exts:
                path = str(path_obj.with_suffix(exts[0]))

        kind = meta.get("kind", "any")
        dpi_override: float | None = None
        if kind in ("png", "tiff"):
            dpi_override = float(self._export_dpi)

        self.export_figure(path, dpi_override=dpi_override)

    def export_figure(self, out_path: str, dpi_override: float | None = None) -> None:
        try:
            log.info("Exporting figure to %s", out_path)
            self._enforce_page_bounds(update_controls=True)
            bg = "transparent" if self._export_transparent else "white"
            if hasattr(self._fig_spec.page, "export_background"):
                self._fig_spec.page.export_background = bg
            self._persist_recipe_snapshot()
            ctx = self._render_context(is_preview=False)
            spec_for_export = (
                self._fig_spec if dpi_override is None else deepcopy(self._fig_spec)
            )
            if dpi_override is not None:
                spec_for_export.page.dpi = float(dpi_override)
            export_figure(
                spec_for_export,
                out_path,
                transparent=self._export_transparent,
                ctx=ctx,
                export_background=bg,
            )
            log.info("Export successful: %s", out_path)
        except Exception:
            log.exception("Export failed")

    # ------------------------------------------------------------------
    # Project save
    # ------------------------------------------------------------------
    def _figure_name_for_save(self) -> str:
        axes = getattr(self._fig_spec, "axes", None)
        trace_key = self._active_trace_key or "trace"
        if axes and axes.x_range:
            x0, x1 = axes.x_range
            return f"{trace_key} {x0:.1f}-{x1:.1f}s"
        return f"{trace_key} figure"

    def _save_to_project(self) -> None:
        """Create or update a recipe on demand, then enable autosave."""
        if self.project is None or self.dataset_id is None:
            QMessageBox.warning(
                self,
                "Save to Project",
                "No active project/dataset is available. Load a dataset and try again.",
            )
            return

        with self._project_repo() as repo:
            if repo is None:
                QMessageBox.warning(
                    self,
                    "Save to Project",
                    "Project repository is unavailable; cannot save figure.",
                )
                return
            try:
                spec_dict = figure_spec_to_dict(self._fig_spec)
                axes = self._fig_spec.axes
                x_range = axes.x_range
                y_range = axes.y_range
                trace_key = self._active_trace_key
                export_bg = getattr(self._fig_spec.page, "export_background", "white")
                if self._recipe_id:
                    repo.update_figure_recipe(
                        self._recipe_id,
                        spec_json=json.dumps(spec_dict),
                        trace_key=trace_key,
                        x_min=x_range[0] if x_range else None,
                        x_max=x_range[1] if x_range else None,
                        y_min=y_range[0] if y_range else None,
                        y_max=y_range[1] if y_range else None,
                        export_background=export_bg,
                    )
                else:
                    name = self._figure_name_for_save()
                    dsid = int(self.dataset_id)
                    self._recipe_id = repo.add_figure_recipe(
                        dsid,
                        name,
                        json.dumps(spec_dict),
                        source="composer_manual",
                        trace_key=trace_key,
                        x_min=x_range[0] if x_range else None,
                        x_max=x_range[1] if x_range else None,
                        y_min=y_range[0] if y_range else None,
                        y_max=y_range[1] if y_range else None,
                        export_background=export_bg,
                    )
                self._pending_dirty = False
                self._schedule_signal_emission(immediate=True)
                QMessageBox.information(
                    self,
                    "Save Complete",
                    "Figure saved to project. Future edits will auto-save.",
                )
            except Exception as e:
                log.error("Failed to save figure to project: %s", e, exc_info=True)
                QMessageBox.warning(
                    self,
                    "Save Failed",
                    f"Could not save figure to project:\n{e}",
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_trace_spec(self, key: str) -> TraceSpec | None:
        for trace in self._fig_spec.traces:
            if trace.key == key:
                return trace
        return None
