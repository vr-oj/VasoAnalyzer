"""Minimal Matplotlib-based composer window for quick figure exports.

Phase 1 scope:
- Single Axes
- Basic X/Y limit controls with autoscale toggles
- Simple export using FigureConfig size/dpi
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import logging
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QSpinBox,
)

from vasoanalyzer.core.trace_model import TraceModel

log = logging.getLogger(__name__)


@dataclass
class AxesConfig:
    xlim: Optional[Tuple[float, float]] = None
    ylim: Optional[Tuple[float, float]] = None
    autoscale_x: bool = True
    autoscale_y: bool = True
    xscale: str = "linear"
    yscale: str = "linear"
    show_grid: bool = True
    show_minor_grid: bool = False
    grid_linestyle: str = "-"
    grid_alpha: float = 0.4
    show_spines: bool = True
    xlabel: str = "Time (s)"
    ylabel: str = "Inner diameter (um)"
    title: str = ""
    label_style: "TextStyleConfig" = field(default_factory=lambda: TextStyleConfig(size=10.0))
    tick_style: "TextStyleConfig" = field(default_factory=lambda: TextStyleConfig(size=9.0))
    title_style: "TextStyleConfig" = field(
        default_factory=lambda: TextStyleConfig(size=11.0, weight="bold")
    )

    def to_dict(self) -> dict:
        return {
            "xlim": list(self.xlim) if self.xlim is not None else None,
            "ylim": list(self.ylim) if self.ylim is not None else None,
            "autoscale_x": self.autoscale_x,
            "autoscale_y": self.autoscale_y,
            "xscale": self.xscale,
            "yscale": self.yscale,
            "show_grid": self.show_grid,
            "show_minor_grid": self.show_minor_grid,
            "grid_linestyle": self.grid_linestyle,
            "grid_alpha": self.grid_alpha,
            "show_spines": self.show_spines,
            "xlabel": self.xlabel,
            "ylabel": self.ylabel,
            "title": self.title,
            "label_style": self.label_style.to_dict(),
            "tick_style": self.tick_style.to_dict(),
            "title_style": self.title_style.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AxesConfig":
        data = data or {}
        xlim = data.get("xlim")
        ylim = data.get("ylim")
        xlim_tuple = tuple(xlim) if isinstance(xlim, (list, tuple)) and len(xlim) == 2 else None
        ylim_tuple = tuple(ylim) if isinstance(ylim, (list, tuple)) and len(ylim) == 2 else None
        # Support legacy size-only fields
        label_style_data = data.get("label_style")
        tick_style_data = data.get("tick_style")
        title_style_data = data.get("title_style")
        if label_style_data is None and "label_fontsize" in data:
            label_style_data = {"size": data.get("label_fontsize")}
        if tick_style_data is None and "tick_fontsize" in data:
            tick_style_data = {"size": data.get("tick_fontsize")}
        if title_style_data is None and "title_fontsize" in data:
            title_style_data = {"size": data.get("title_fontsize")}
        return cls(
            xlim=xlim_tuple,
            ylim=ylim_tuple,
            autoscale_x=bool(data.get("autoscale_x", True)),
            autoscale_y=bool(data.get("autoscale_y", True)),
            xscale=str(data.get("xscale", "linear")),
            yscale=str(data.get("yscale", "linear")),
            show_grid=bool(data.get("show_grid", True)),
            show_minor_grid=bool(data.get("show_minor_grid", False)),
            grid_linestyle=str(data.get("grid_linestyle", "-")),
            grid_alpha=float(data.get("grid_alpha", 0.4)),
            show_spines=bool(data.get("show_spines", True)),
            xlabel=str(data.get("xlabel", "Time (s)")),
            ylabel=str(data.get("ylabel", "Inner diameter (um)")),
            title=str(data.get("title", "")),
            label_style=TextStyleConfig.from_dict(label_style_data),
            tick_style=TextStyleConfig.from_dict(tick_style_data),
            title_style=TextStyleConfig.from_dict(title_style_data),
        )


@dataclass
class TraceStyleConfig:
    key: str
    label: str
    visible: bool = True
    color: str = ""
    linewidth: float = 1.5
    linestyle: str = "-"
    marker: str = ""
    markersize: float = 0.0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "visible": self.visible,
            "color": self.color,
            "linewidth": self.linewidth,
            "linestyle": self.linestyle,
            "marker": self.marker,
            "markersize": self.markersize,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TraceStyleConfig":
        data = data or {}
        return cls(
            key=str(data.get("key", "")),
            label=str(data.get("label", "")),
            visible=bool(data.get("visible", True)),
            color=str(data.get("color", "")),
            linewidth=float(data.get("linewidth", 1.5)),
            linestyle=str(data.get("linestyle", "-")),
            marker=str(data.get("marker", "")),
            markersize=float(data.get("markersize", 0.0)),
        )


@dataclass
class FigureConfig:
    width_mm: float = 180.0
    height_mm: float = 120.0
    dpi: int = 300
    facecolor: str = "white"
    tight_layout: bool = True
    axes: List[AxesConfig] = field(default_factory=lambda: [AxesConfig()])
    traces: List[TraceStyleConfig] = field(default_factory=list)
    show_legend: bool = True
    legend_loc: str = "best"
    nrows: int = 1
    ncols: int = 1

    def __post_init__(self) -> None:
        if not self.traces:
            self.traces = [
                TraceStyleConfig("inner", "Inner diameter", True, "", 1.5),
                TraceStyleConfig("outer", "Outer diameter", False, "", 1.2),
                TraceStyleConfig("avg_pressure", "Avg pressure", False, "", 1.2),
                TraceStyleConfig("set_pressure", "Set pressure", False, "", 1.2),
            ]

    def to_dict(self) -> dict:
        return {
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "dpi": self.dpi,
            "facecolor": self.facecolor,
            "tight_layout": self.tight_layout,
            "axes": [ax.to_dict() for ax in self.axes],
            "traces": [t.to_dict() for t in self.traces],
            "show_legend": self.show_legend,
            "legend_loc": self.legend_loc,
            "nrows": self.nrows,
            "ncols": self.ncols,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FigureConfig":
        data = data or {}
        axes_data = data.get("axes")
        axes_cfgs = (
            [AxesConfig.from_dict(item) for item in axes_data]
            if isinstance(axes_data, list) and axes_data
            else [AxesConfig()]
        )
        trace_data = data.get("traces")
        trace_cfgs = (
            [TraceStyleConfig.from_dict(item) for item in trace_data]
            if isinstance(trace_data, list) and trace_data
            else []
        )
        return cls(
            width_mm=float(data.get("width_mm", 180.0)),
            height_mm=float(data.get("height_mm", 120.0)),
            dpi=int(data.get("dpi", 300)),
            facecolor=str(data.get("facecolor", "white")),
            tight_layout=bool(data.get("tight_layout", True)),
            axes=axes_cfgs,
            traces=trace_cfgs,
            show_legend=bool(data.get("show_legend", True)),
            legend_loc=str(data.get("legend_loc", "best")),
            nrows=int(data.get("nrows", 1) or 1),
            ncols=int(data.get("ncols", 1) or 1),
        )


class MatplotlibComposerWindow(QMainWindow):
    """A lightweight Matplotlib-native composer with a single Axes."""

    def __init__(
        self,
        trace_model: Optional[TraceModel],
        event_times,
        event_labels,
        event_colors,
        event_frames=None,
        initial_x_range: Optional[Tuple[float, float]] = None,
        initial_y_range: Optional[Tuple[float, float]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.trace_model = trace_model
        self._event_times = list(event_times or [])
        self._event_labels = list(event_labels or [])
        self._event_colors = list(event_colors or []) if event_colors else None
        self._event_frames = list(event_frames or [])
        self._initial_x_range = (
            (float(initial_x_range[0]), float(initial_x_range[1]))
            if initial_x_range is not None
            else None
        )
        self._initial_y_range = (
            (float(initial_y_range[0]), float(initial_y_range[1]))
            if initial_y_range is not None
            else None
        )
        self._trace_controls: Dict[str, Dict[str, object]] = {}
        self._text_controls: Dict[str, Dict[str, object]] = {}

        self.setWindowTitle("Matplotlib Composer")

        self.fig_cfg = FigureConfig()

        self.figure = Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self.setCentralWidget(central)

        self._build_controls()
        self._apply_initial_view_ranges()
        self._render_from_config()

    # ------------------------------------------------------------------ UI setup
    def _build_controls(self) -> None:
        dock = QDockWidget("Figure Controls", self)
        dock.setObjectName("MatplotlibComposerControls")
        dock_widget = QWidget(dock)
        form = QFormLayout(dock_widget)
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(6)

        # Axis controls
        self._add_section_label(form, "Axis")
        self.check_auto_x = QCheckBox("Auto X")
        self.check_auto_x.setChecked(False)
        self.check_auto_x.toggled.connect(self._on_auto_x_toggled)
        form.addRow(self.check_auto_x)

        self.spin_xmin = QDoubleSpinBox()
        self.spin_xmin.setRange(-1e9, 1e9)
        self.spin_xmin.setDecimals(6)
        self.spin_xmin.setEnabled(True)
        self.spin_xmin.valueChanged.connect(self._on_xmin_changed)
        self.spin_xmax = QDoubleSpinBox()
        self.spin_xmax.setRange(-1e9, 1e9)
        self.spin_xmax.setDecimals(6)
        self.spin_xmax.setEnabled(True)
        self.spin_xmax.valueChanged.connect(self._on_xmax_changed)
        form.addRow("X min:", self.spin_xmin)
        form.addRow("X max:", self.spin_xmax)

        self.check_auto_y = QCheckBox("Auto Y")
        self.check_auto_y.setChecked(False)
        self.check_auto_y.toggled.connect(self._on_auto_y_toggled)
        form.addRow(self.check_auto_y)

        self.spin_ymin = QDoubleSpinBox()
        self.spin_ymin.setRange(-1e9, 1e9)
        self.spin_ymin.setDecimals(6)
        self.spin_ymin.setEnabled(True)
        self.spin_ymin.valueChanged.connect(self._on_ymin_changed)
        self.spin_ymax = QDoubleSpinBox()
        self.spin_ymax.setRange(-1e9, 1e9)
        self.spin_ymax.setDecimals(6)
        self.spin_ymax.setEnabled(True)
        self.spin_ymax.valueChanged.connect(self._on_ymax_changed)
        form.addRow("Y min:", self.spin_ymin)
        form.addRow("Y max:", self.spin_ymax)

        # Grid and spines
        ax_cfg = self._axes_cfg()
        self.check_grid_major = QCheckBox("Show major grid")
        self.check_grid_major.setChecked(ax_cfg.show_grid)
        self.check_grid_major.toggled.connect(self._on_grid_major_toggled)
        form.addRow(self.check_grid_major)

        self.check_grid_minor = QCheckBox("Show minor grid")
        self.check_grid_minor.setChecked(ax_cfg.show_minor_grid)
        self.check_grid_minor.toggled.connect(self._on_grid_minor_toggled)
        form.addRow(self.check_grid_minor)

        linestyle_options = [
            ("Solid", "-"),
            ("Dashed", "--"),
            ("Dotted", ":"),
            ("Dash-dot", "-."),
        ]
        self.combo_grid_style = QComboBox()
        for label, value in linestyle_options:
            self.combo_grid_style.addItem(label, value)
        self._select_combobox_value(self.combo_grid_style, ax_cfg.grid_linestyle, default_value="-")
        self.combo_grid_style.currentIndexChanged.connect(self._on_grid_style_changed)
        form.addRow("Grid style:", self.combo_grid_style)

        self.spin_grid_alpha = QDoubleSpinBox()
        self.spin_grid_alpha.setRange(0.0, 1.0)
        self.spin_grid_alpha.setSingleStep(0.05)
        self.spin_grid_alpha.setValue(ax_cfg.grid_alpha)
        self.spin_grid_alpha.valueChanged.connect(self._on_grid_alpha_changed)
        form.addRow("Grid alpha:", self.spin_grid_alpha)

        self.check_spines = QCheckBox("Show axis frame/spines")
        self.check_spines.setChecked(ax_cfg.show_spines)
        self.check_spines.toggled.connect(self._on_spines_toggled)
        form.addRow(self.check_spines)

        # Layout (subplots)
        self._add_section_label(form, "Layout")
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 3)
        self.spin_rows.setValue(self.fig_cfg.nrows)
        self.spin_rows.valueChanged.connect(self._on_rows_changed)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 3)
        self.spin_cols.setValue(self.fig_cfg.ncols)
        self.spin_cols.valueChanged.connect(self._on_cols_changed)
        layout_row = QWidget()
        layout_layout = QHBoxLayout(layout_row)
        layout_layout.setContentsMargins(0, 0, 0, 0)
        layout_layout.setSpacing(6)
        layout_layout.addWidget(QLabel("Rows:"))
        layout_layout.addWidget(self.spin_rows)
        layout_layout.addWidget(QLabel("Cols:"))
        layout_layout.addWidget(self.spin_cols)
        layout_layout.addStretch(1)
        form.addRow(layout_row)

        # Trace styling
        self._add_section_label(form, "Trace Display")
        marker_options = [
            ("None", ""),
            ("Circle", "o"),
            ("Square", "s"),
            ("Triangle up", "^"),
            ("Triangle down", "v"),
        ]
        for trace_cfg in self.fig_cfg.traces:
            row = QWidget(dock_widget)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            visible_chk = QCheckBox(trace_cfg.label)
            visible_chk.setChecked(trace_cfg.visible)
            visible_chk.toggled.connect(
                lambda checked, key=trace_cfg.key: self._on_trace_visibility_changed(
                    key, checked
                )
            )
            color_btn = QPushButton("Color")
            color_btn.setAutoDefault(False)
            color_btn.clicked.connect(
                lambda _=False, key=trace_cfg.key: self._on_trace_color_clicked(key)
            )
            self._apply_color_to_button(color_btn, trace_cfg.color)
            lw_spin = QDoubleSpinBox()
            lw_spin.setRange(0.1, 10.0)
            lw_spin.setSingleStep(0.1)
            lw_spin.setValue(trace_cfg.linewidth)
            lw_spin.valueChanged.connect(
                lambda value, key=trace_cfg.key: self._on_trace_linewidth_changed(
                    key, value
                )
            )
            ls_combo = QComboBox()
            for label, value in linestyle_options:
                ls_combo.addItem(label, value)
            self._select_combobox_value(ls_combo, trace_cfg.linestyle, default_value="-")
            ls_combo.currentIndexChanged.connect(
                lambda _=0, key=trace_cfg.key: self._on_trace_linestyle_changed(
                    key
                )
            )
            marker_combo = QComboBox()
            for label, value in marker_options:
                marker_combo.addItem(label, value)
            self._select_combobox_value(marker_combo, trace_cfg.marker, default_value="")
            marker_combo.currentIndexChanged.connect(
                lambda _=0, key=trace_cfg.key: self._on_trace_marker_changed(key)
            )
            marker_size_spin = QDoubleSpinBox()
            marker_size_spin.setRange(0.0, 20.0)
            marker_size_spin.setSingleStep(0.5)
            marker_size_spin.setValue(trace_cfg.markersize)
            marker_size_spin.valueChanged.connect(
                lambda value, key=trace_cfg.key: self._on_trace_markersize_changed(
                    key, value
                )
            )
            row_layout.addWidget(visible_chk)
            row_layout.addWidget(color_btn)
            row_layout.addWidget(QLabel("LW:"))
            row_layout.addWidget(lw_spin)
            row_layout.addWidget(QLabel("LS:"))
            row_layout.addWidget(ls_combo)
            row_layout.addWidget(QLabel("Marker:"))
            row_layout.addWidget(marker_combo)
            row_layout.addWidget(QLabel("Size:"))
            row_layout.addWidget(marker_size_spin)
            row_layout.addStretch(1)
            form.addRow("", row)
            self._trace_controls[trace_cfg.key] = {
                "visible": visible_chk,
                "color_btn": color_btn,
                "linewidth": lw_spin,
                "linestyle": ls_combo,
                "marker": marker_combo,
                "markersize": marker_size_spin,
            }

        # Fonts
        self._add_section_label(form, "Fonts")
        self.title_edit = QLineEdit(ax_cfg.title)
        self.title_edit.editingFinished.connect(self._on_title_changed)
        form.addRow("Title:", self.title_edit)

        self._add_text_style_controls(
            form, "title", "Title style", ax_cfg.title_style, allow_family=True
        )
        self._add_text_style_controls(
            form, "label", "Axis label style", ax_cfg.label_style, allow_family=True
        )
        self._add_text_style_controls(
            form, "tick", "Tick label style", ax_cfg.tick_style, allow_family=True
        )

        # Legend
        self._add_section_label(form, "Legend")
        self.check_legend = QCheckBox("Show legend")
        self.check_legend.setChecked(self.fig_cfg.show_legend)
        self.check_legend.toggled.connect(self._on_legend_toggled)
        form.addRow(self.check_legend)

        self.combo_legend_loc = QComboBox()
        legend_options = [
            ("Best", "best"),
            ("Upper right", "upper right"),
            ("Upper left", "upper left"),
            ("Lower right", "lower right"),
            ("Lower left", "lower left"),
            ("Right", "right"),
            ("Center left", "center left"),
            ("Center right", "center right"),
            ("Lower center", "lower center"),
            ("Upper center", "upper center"),
            ("Center", "center"),
        ]
        for label, value in legend_options:
            self.combo_legend_loc.addItem(label, value)
        self._select_combobox_value(self.combo_legend_loc, self.fig_cfg.legend_loc, default_value="best")
        self.combo_legend_loc.currentIndexChanged.connect(self._on_legend_loc_changed)
        form.addRow("Legend location:", self.combo_legend_loc)

        self.btn_export = QPushButton("Export figure…")
        self.btn_export.clicked.connect(self._on_export_clicked)
        form.addRow(self.btn_export)

        dock_widget.setLayout(form)
        dock.setWidget(dock_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    # ------------------------------------------------------------------ helpers
    def _add_section_label(self, form: QFormLayout, text: str) -> None:
        label = QLabel(f"<b>{text}</b>")
        form.addRow(label)

    def _axes_cfg(self) -> AxesConfig:
        return self.fig_cfg.axes[0]

    def _apply_initial_view_ranges(self) -> None:
        ax_cfg = self._axes_cfg()
        if self._initial_x_range is not None:
            ax_cfg.autoscale_x = False
            ax_cfg.xlim = self._initial_x_range
            self._set_auto_checkbox(self.check_auto_x, False)
            self._set_spinpair_enabled(self.spin_xmin, self.spin_xmax, True)
            self._update_spinpair(self.spin_xmin, self.spin_xmax, ax_cfg.xlim)
        else:
            ax_cfg.autoscale_x = False
            self._set_auto_checkbox(self.check_auto_x, False)
            self._set_spinpair_enabled(self.spin_xmin, self.spin_xmax, True)
            self._init_x_limits_from_data()

        if self._initial_y_range is not None:
            ax_cfg.autoscale_y = False
            ax_cfg.ylim = self._initial_y_range
            self._set_auto_checkbox(self.check_auto_y, False)
            self._set_spinpair_enabled(self.spin_ymin, self.spin_ymax, True)
            self._update_spinpair(self.spin_ymin, self.spin_ymax, ax_cfg.ylim)
        else:
            ax_cfg.autoscale_y = False
            self._set_auto_checkbox(self.check_auto_y, False)
            self._set_spinpair_enabled(self.spin_ymin, self.spin_ymax, True)
            self._init_y_limits_from_data()

    def _init_limits_from_data(self) -> None:
        self._init_x_limits_from_data()
        self._init_y_limits_from_data()

    def _init_x_limits_from_data(self) -> None:
        if self.trace_model is None:
            return
        times = getattr(self.trace_model, "time_full", None)
        if times is None or getattr(times, "size", 0) == 0:
            return
        ax_cfg = self._axes_cfg()
        if not ax_cfg.autoscale_x and ax_cfg.xlim is not None:
            return
        ax_cfg.xlim = (float(times[0]), float(times[-1]))
        self._update_spinpair(self.spin_xmin, self.spin_xmax, ax_cfg.xlim)

    def _init_y_limits_from_data(self) -> None:
        if self.trace_model is None:
            return
        inner = getattr(self.trace_model, "inner_full", None)
        if inner is None or getattr(inner, "size", 0) == 0:
            return
        ax_cfg = self._axes_cfg()
        if not ax_cfg.autoscale_y and ax_cfg.ylim is not None:
            return
        ymin = float(inner.min())
        ymax = float(inner.max())
        if ymin == ymax:
            ymin -= 1.0
            ymax += 1.0
        ax_cfg.ylim = (ymin, ymax)
        self._update_spinpair(self.spin_ymin, self.spin_ymax, ax_cfg.ylim)

    def _update_spinpair(self, spin_min: QDoubleSpinBox, spin_max: QDoubleSpinBox, values) -> None:
        if values is None or len(values) != 2:
            return
        spin_min.blockSignals(True)
        spin_max.blockSignals(True)
        spin_min.setValue(float(values[0]))
        spin_max.setValue(float(values[1]))
        spin_min.blockSignals(False)
        spin_max.blockSignals(False)

    def _set_auto_checkbox(self, checkbox: QCheckBox, checked: bool) -> None:
        checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.blockSignals(False)

    def _set_spinpair_enabled(
        self, spin_min: QDoubleSpinBox, spin_max: QDoubleSpinBox, enabled: bool
    ) -> None:
        spin_min.setEnabled(enabled)
        spin_max.setEnabled(enabled)

    def _resolve_trace_series(self, key: str):
        if self.trace_model is None:
            return None
        mapping = {
            "inner": "inner_full",
            "outer": "outer_full",
            "avg_pressure": "avg_pressure_full",
            "set_pressure": "set_pressure_full",
        }
        attr = mapping.get(key)
        if attr is None:
            return None
        return getattr(self.trace_model, attr, None)

    def _get_trace_cfg(self, key: str) -> Optional[TraceStyleConfig]:
        for cfg in self.fig_cfg.traces:
            if cfg.key == key:
                return cfg
        return None

    def _resolve_event_x_positions(self) -> list[float]:
        """Match PlotHost behavior: events use event_times (seconds)."""
        if self._event_times:
            return [float(t) for t in self._event_times]
        # Fallback: derive from frames if provided and within trace length
        if self._event_frames and self.trace_model is not None:
            times = getattr(self.trace_model, "time_full", None)
            if times is not None and getattr(times, "size", 0) > 0:
                total = times.size
                positions: list[float] = []
                for frame in self._event_frames:
                    try:
                        idx = int(frame)
                    except Exception:
                        continue
                    idx = max(0, min(idx, total - 1))
                    positions.append(float(times[idx]))
                return positions
        return []

    def _text_cfg(self, key: str) -> Optional["TextStyleConfig"]:
        ax_cfg = self._axes_cfg()
        if key == "title":
            return ax_cfg.title_style
        if key == "label":
            return ax_cfg.label_style
        if key == "tick":
            return ax_cfg.tick_style
        return None

    def _select_combobox_value(
        self, combo: QComboBox, value: str, *, default_value: str
    ) -> None:
        found_index = combo.findData(value)
        if found_index < 0:
            found_index = combo.findData(default_value)
        if found_index < 0:
            found_index = 0
        combo.blockSignals(True)
        combo.setCurrentIndex(found_index)
        combo.blockSignals(False)

    def _apply_color_to_button(self, button: QPushButton, color: str) -> None:
        if color:
            button.setStyleSheet(f"background-color: {color};")
        else:
            button.setStyleSheet("")

    def _add_text_style_controls(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        cfg: "TextStyleConfig",
        *,
        allow_family: bool = False,
    ) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        size_spin = QDoubleSpinBox()
        size_spin.setRange(6.0, 96.0)
        size_spin.setValue(cfg.size)
        size_spin.valueChanged.connect(lambda v, k=key: self._on_text_size_changed(k, v))

        bold_chk = QCheckBox("Bold")
        bold_chk.setChecked(str(cfg.weight).lower() == "bold")
        bold_chk.toggled.connect(lambda c, k=key: self._on_text_bold_toggled(k, c))

        italic_chk = QCheckBox("Italic")
        italic_chk.setChecked(str(cfg.style).lower() == "italic")
        italic_chk.toggled.connect(lambda c, k=key: self._on_text_italic_toggled(k, c))

        color_btn = QPushButton("Color")
        color_btn.setAutoDefault(False)
        self._apply_color_to_button(color_btn, cfg.color)
        color_btn.clicked.connect(lambda _=False, k=key: self._on_text_color_clicked(k))

        layout.addWidget(QLabel(label))
        layout.addWidget(color_btn)
        layout.addWidget(QLabel("Size:"))
        layout.addWidget(size_spin)
        layout.addWidget(bold_chk)
        layout.addWidget(italic_chk)

        family_edit = None
        if allow_family:
            family_edit = QLineEdit(cfg.family)
            family_edit.setPlaceholderText("Font family")
            family_edit.editingFinished.connect(
                lambda k=key, w=family_edit: self._on_text_family_changed(k, w.text())
            )
            layout.addWidget(family_edit)

        layout.addStretch(1)
        form.addRow(row)
        self._text_controls[key] = {
            "size": size_spin,
            "bold": bold_chk,
            "italic": italic_chk,
            "color": color_btn,
            "family": family_edit,
        }

    # ------------------------------------------------------------------ rendering
    def _render_from_config(self) -> None:
        fig = self.figure
        fig.clf()

        inches_w = self.fig_cfg.width_mm / 25.4
        inches_h = self.fig_cfg.height_mm / 25.4
        fig.set_size_inches(inches_w, inches_h, forward=True)
        fig.set_dpi(self.fig_cfg.dpi)
        fig.set_facecolor(self.fig_cfg.facecolor)

        ax_cfg = self._axes_cfg()
        nrows = max(1, int(self.fig_cfg.nrows))
        ncols = max(1, int(self.fig_cfg.ncols))
        axes_grid = fig.subplots(nrows, ncols, squeeze=False)
        axes_list = [ax for row in axes_grid for ax in row]

        for ax in axes_list:
            ax.set_xscale(ax_cfg.xscale)
            ax.set_yscale(ax_cfg.yscale)
            ax.set_xlabel(ax_cfg.xlabel)
            ax.set_ylabel(ax_cfg.ylabel)

            for spine in ax.spines.values():
                spine.set_visible(ax_cfg.show_spines)

            ax.grid(
                ax_cfg.show_grid,
                which="major",
                linestyle=ax_cfg.grid_linestyle,
                alpha=ax_cfg.grid_alpha,
            )
            if ax_cfg.show_minor_grid:
                ax.minorticks_on()
                ax.grid(
                    True,
                    which="minor",
                    linestyle=ax_cfg.grid_linestyle,
                    alpha=max(0.1, ax_cfg.grid_alpha * 0.7),
                )
            else:
                ax.minorticks_off()

            if not ax_cfg.autoscale_x and ax_cfg.xlim is not None:
                ax.set_xlim(*ax_cfg.xlim)
            if not ax_cfg.autoscale_y and ax_cfg.ylim is not None:
                ax.set_ylim(*ax_cfg.ylim)

            visible_labels = []
            if self.trace_model is not None:
                time_arr = getattr(self.trace_model, "time_full", None)
                if time_arr is not None and getattr(time_arr, "size", 0) > 0:
                    for trace_cfg in self.fig_cfg.traces:
                        if not trace_cfg.visible:
                            continue
                        y = self._resolve_trace_series(trace_cfg.key)
                        if y is None or getattr(y, "size", 0) != getattr(time_arr, "size", -1):
                            continue
                        kwargs = {}
                        if trace_cfg.color:
                            kwargs["color"] = trace_cfg.color
                        if trace_cfg.linewidth:
                            kwargs["linewidth"] = trace_cfg.linewidth
                        if trace_cfg.linestyle:
                            kwargs["linestyle"] = trace_cfg.linestyle
                        if trace_cfg.marker:
                            kwargs["marker"] = trace_cfg.marker
                        if trace_cfg.markersize > 0:
                            kwargs["markersize"] = trace_cfg.markersize
                        ax.plot(time_arr, y, label=trace_cfg.label, **kwargs)
                        if trace_cfg.label:
                            visible_labels.append(trace_cfg.label)

            color = "gray"
            if self._event_colors and len(self._event_colors) > 0:
                color = self._event_colors[0]
            x_events = self._resolve_event_x_positions()
            if x_events:
                try:
                    log.debug(
                        "MatplotlibComposer events sample=%s trace_xlim=%s",
                        x_events[:3],
                        ax.get_xlim(),
                    )
                except Exception:
                    pass
            for x_ev in x_events:
                try:
                    ax.axvline(float(x_ev), color=color, alpha=0.5, linewidth=0.8)
                except Exception:
                    continue

            self._apply_text_styles(ax, ax_cfg)

            have_labeled_traces = any(
                t.visible and t.label for t in self.fig_cfg.traces
            )
            if self.fig_cfg.show_legend and have_labeled_traces:
                ax.legend(loc=self.fig_cfg.legend_loc or "best")

        if self.fig_cfg.tight_layout:
            fig.tight_layout()

        self.canvas.draw_idle()

    def _apply_text_styles(self, ax, ax_cfg: AxesConfig) -> None:
        label_style = ax_cfg.label_style
        tick_style = ax_cfg.tick_style
        title_style = ax_cfg.title_style

        # Axis labels
        for axis_label in (ax.xaxis.label, ax.yaxis.label):
            if label_style.size:
                axis_label.set_size(label_style.size)
            if label_style.weight:
                axis_label.set_weight(label_style.weight)
            if label_style.style:
                axis_label.set_style(label_style.style)
            if label_style.color:
                axis_label.set_color(label_style.color)
            if label_style.family:
                axis_label.set_family(label_style.family)

        # Tick labels
        for tick_label in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
            if tick_style.size:
                tick_label.set_fontsize(tick_style.size)
            if tick_style.weight:
                tick_label.set_weight(tick_style.weight)
            if tick_style.style:
                tick_label.set_style(tick_style.style)
            if tick_style.color:
                tick_label.set_color(tick_style.color)
            if tick_style.family:
                tick_label.set_family(tick_style.family)

        # Title
        if ax_cfg.title:
            title_text = ax.set_title(ax_cfg.title)
            if title_style.size:
                title_text.set_size(title_style.size)
            if title_style.weight:
                title_text.set_weight(title_style.weight)
            if title_style.style:
                title_text.set_style(title_style.style)
            if title_style.color:
                title_text.set_color(title_style.color)
            if title_style.family:
                title_text.set_family(title_style.family)
        else:
            ax.set_title("")

    # ------------------------------------------------------------------ slots
    def _on_auto_x_toggled(self, checked: bool) -> None:
        ax_cfg = self._axes_cfg()
        ax_cfg.autoscale_x = bool(checked)
        self._set_spinpair_enabled(self.spin_xmin, self.spin_xmax, not checked)
        if checked:
            ax_cfg.xlim = None
        else:
            self._init_x_limits_from_data()
        self._render_from_config()

    def _on_auto_y_toggled(self, checked: bool) -> None:
        ax_cfg = self._axes_cfg()
        ax_cfg.autoscale_y = bool(checked)
        self._set_spinpair_enabled(self.spin_ymin, self.spin_ymax, not checked)
        if checked:
            ax_cfg.ylim = None
        else:
            self._init_y_limits_from_data()
        self._render_from_config()

    def _on_grid_major_toggled(self, checked: bool) -> None:
        ax_cfg = self._axes_cfg()
        ax_cfg.show_grid = bool(checked)
        self._render_from_config()

    def _on_grid_minor_toggled(self, checked: bool) -> None:
        ax_cfg = self._axes_cfg()
        ax_cfg.show_minor_grid = bool(checked)
        self._render_from_config()

    def _on_grid_style_changed(self) -> None:
        ax_cfg = self._axes_cfg()
        ax_cfg.grid_linestyle = str(self.combo_grid_style.currentData())
        self._render_from_config()

    def _on_grid_alpha_changed(self, value: float) -> None:
        ax_cfg = self._axes_cfg()
        ax_cfg.grid_alpha = float(value)
        self._render_from_config()

    def _on_spines_toggled(self, checked: bool) -> None:
        ax_cfg = self._axes_cfg()
        ax_cfg.show_spines = bool(checked)
        self._render_from_config()

    def _on_rows_changed(self, value: int) -> None:
        rows = max(1, int(value))
        if rows != self.fig_cfg.nrows:
            self.fig_cfg.nrows = rows
            self._render_from_config()

    def _on_cols_changed(self, value: int) -> None:
        cols = max(1, int(value))
        if cols != self.fig_cfg.ncols:
            self.fig_cfg.ncols = cols
            self._render_from_config()

    def _on_xmin_changed(self, value: float) -> None:
        self._update_xlim(value, self.spin_xmax.value())

    def _on_xmax_changed(self, value: float) -> None:
        self._update_xlim(self.spin_xmin.value(), value)

    def _on_ymin_changed(self, value: float) -> None:
        self._update_ylim(value, self.spin_ymax.value())

    def _on_ymax_changed(self, value: float) -> None:
        self._update_ylim(self.spin_ymin.value(), value)

    def _update_xlim(self, xmin: float, xmax: float) -> None:
        ax_cfg = self._axes_cfg()
        if ax_cfg.autoscale_x:
            return
        if xmin >= xmax:
            xmax = xmin + 1e-6
            self._update_spinpair(self.spin_xmin, self.spin_xmax, (xmin, xmax))
        ax_cfg.xlim = (float(xmin), float(xmax))
        self._render_from_config()

    def _update_ylim(self, ymin: float, ymax: float) -> None:
        ax_cfg = self._axes_cfg()
        if ax_cfg.autoscale_y:
            return
        if ymin >= ymax:
            ymax = ymin + 1e-6
            self._update_spinpair(self.spin_ymin, self.spin_ymax, (ymin, ymax))
        ax_cfg.ylim = (float(ymin), float(ymax))
        self._render_from_config()

    def _on_trace_visibility_changed(self, key: str, checked: bool) -> None:
        cfg = self._get_trace_cfg(key)
        if cfg is None:
            return
        cfg.visible = bool(checked)
        self._render_from_config()

    def _on_trace_linewidth_changed(self, key: str, value: float) -> None:
        cfg = self._get_trace_cfg(key)
        if cfg is None:
            return
        cfg.linewidth = float(value)
        self._render_from_config()

    def _on_trace_linestyle_changed(self, key: str) -> None:
        cfg = self._get_trace_cfg(key)
        if cfg is None:
            return
        combo = self._trace_controls.get(key, {}).get("linestyle")
        if isinstance(combo, QComboBox):
            cfg.linestyle = str(combo.currentData())
        self._render_from_config()

    def _on_trace_marker_changed(self, key: str) -> None:
        cfg = self._get_trace_cfg(key)
        if cfg is None:
            return
        combo = self._trace_controls.get(key, {}).get("marker")
        if isinstance(combo, QComboBox):
            cfg.marker = str(combo.currentData())
        self._render_from_config()

    def _on_trace_markersize_changed(self, key: str, value: float) -> None:
        cfg = self._get_trace_cfg(key)
        if cfg is None:
            return
        cfg.markersize = float(value)
        self._render_from_config()

    def _on_trace_color_clicked(self, key: str) -> None:
        cfg = self._get_trace_cfg(key)
        if cfg is None:
            return
        current_color = cfg.color if cfg.color else "#000000"
        color = QColorDialog.getColor()
        if not color.isValid():
            return
        hex_color = color.name()
        cfg.color = hex_color
        control = self._trace_controls.get(key, {}).get("color_btn")
        if isinstance(control, QPushButton):
            self._apply_color_to_button(control, hex_color)
        self._render_from_config()

    def _on_title_changed(self) -> None:
        ax_cfg = self._axes_cfg()
        ax_cfg.title = self.title_edit.text()
        self._render_from_config()

    def _on_text_size_changed(self, key: str, value: float) -> None:
        cfg = self._text_cfg(key)
        if cfg is None:
            return
        cfg.size = float(value)
        self._render_from_config()

    def _on_text_bold_toggled(self, key: str, checked: bool) -> None:
        cfg = self._text_cfg(key)
        if cfg is None:
            return
        cfg.weight = "bold" if checked else "normal"
        self._render_from_config()

    def _on_text_italic_toggled(self, key: str, checked: bool) -> None:
        cfg = self._text_cfg(key)
        if cfg is None:
            return
        cfg.style = "italic" if checked else "normal"
        self._render_from_config()

    def _on_text_color_clicked(self, key: str) -> None:
        cfg = self._text_cfg(key)
        if cfg is None:
            return
        color = QColorDialog.getColor()
        if not color.isValid():
            return
        cfg.color = color.name()
        controls = self._text_controls.get(key, {})
        btn = controls.get("color")
        if isinstance(btn, QPushButton):
            self._apply_color_to_button(btn, cfg.color)
        self._render_from_config()

    def _on_text_family_changed(self, key: str, family: str) -> None:
        cfg = self._text_cfg(key)
        if cfg is None:
            return
        cfg.family = family.strip()
        self._render_from_config()

    def _on_legend_toggled(self, checked: bool) -> None:
        self.fig_cfg.show_legend = bool(checked)
        self._render_from_config()

    def _on_legend_loc_changed(self) -> None:
        self.fig_cfg.legend_loc = str(self.combo_legend_loc.currentData())
        self._render_from_config()

    def _on_export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export figure",
            "",
            "PNG Image (*.png);;PDF (*.pdf);;SVG (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            self.figure.savefig(
                path,
                dpi=self.fig_cfg.dpi,
                facecolor=self.fig_cfg.facecolor,
                bbox_inches="tight" if self.fig_cfg.tight_layout else None,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Export complete", f"Saved figure to:\n{path}")


# Local import guard for Qt enums
from PyQt5.QtCore import Qt  # noqa: E402  (imported late to avoid circular refs)
@dataclass
class TextStyleConfig:
    family: str = ""
    size: float = 10.0
    weight: str = "normal"
    style: str = "normal"
    color: str = ""

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "size": self.size,
            "weight": self.weight,
            "style": self.style,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TextStyleConfig":
        data = data or {}
        return cls(
            family=str(data.get("family", "")),
            size=float(data.get("size", 10.0)),
            weight=str(data.get("weight", "normal")),
            style=str(data.get("style", "normal")),
            color=str(data.get("color", "")),
        )
