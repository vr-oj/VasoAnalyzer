# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Combined dialog for subplot layout, axis settings and style."""

import contextlib
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from matplotlib.colors import to_hex
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from utils import resource_path
from vasoanalyzer.ui.constants import DEFAULT_STYLE
from vasoanalyzer.ui.theme import CURRENT_THEME

log = logging.getLogger(__name__)


class UnifiedPlotSettingsDialog(QDialog):
    """Dialog merging layout, axis and style settings."""

    def __init__(self, parent, ax, canvas, ax2=None, event_text_objects=None, pinned_points=None):
        super().__init__(parent)
        self.ax = ax
        self.ax2 = ax2
        self.canvas = canvas
        self.fig = canvas.figure
        self._x_axis_target = None
        self.event_text_objects = event_text_objects or []
        self.pinned_points = pinned_points or []

        self._font_choices: Sequence[str] = ("Arial", "Helvetica", "Times New Roman", "Courier New")
        self._event_entries: list[dict[str, Any]] = []
        self._event_times: list[float] = []
        self._suppress_event_editor = False
        self._event_updates_fired = False
        self._event_update_callback = None

        # Debounce timer for layout preview updates
        self._preview_update_timer = QTimer()
        self._preview_update_timer.setSingleShot(True)
        self._preview_update_timer.setInterval(100)  # 100ms debounce
        self._preview_update_timer.timeout.connect(self._do_update_preview)

        # Debounce timer for event lane count changes
        self._event_lane_timer = QTimer()
        self._event_lane_timer.setSingleShot(True)
        self._event_lane_timer.setInterval(300)  # 300ms debounce for heavier operation
        self._event_lane_timer.timeout.connect(self._do_event_lane_update)
        self._pending_event_row = -1

        self.parent_window = parent
        self.style = DEFAULT_STYLE.copy()
        try:
            if hasattr(parent, "_snapshot_style"):
                self.style.update(parent._snapshot_style())
            elif hasattr(parent, "get_current_plot_style"):
                current = parent.get_current_plot_style() or {}
                if isinstance(current, dict):
                    self.style.update(current)
        except Exception:
            pass

        self._x_axis_target = self._resolve_shared_x_axis()
        current_xlabel = self._current_xlabel()
        if current_xlabel:
            self._set_shared_xlabel(current_xlabel)

        self._initialize_event_sources(parent)

        self.setWindowTitle("Plot Settings")
        self.setWindowIcon(QIcon(resource_path("icons", "Aa.svg")))
        self.setFont(QFont("Arial", 10))
        self.setMinimumWidth(720)
        self.setMinimumHeight(500)
        self.setSizeGripEnabled(True)

        # Make dialog responsive to screen size
        if parent:
            screen = parent.screen()
        else:
            from PyQt5.QtWidgets import QApplication

            screen = QApplication.primaryScreen()

        if screen:
            screen_geometry = screen.availableGeometry()
            # Set maximum height to 85% of available screen height
            max_height = int(screen_geometry.height() * 0.85)
            max_width = int(screen_geometry.width() * 0.90)
            self.setMaximumHeight(max_height)
            self.setMaximumWidth(max_width)

            # Set initial size to something reasonable
            initial_height = min(700, max_height)
            initial_width = min(900, max_width)
            self.resize(initial_width, initial_height)

        main = QVBoxLayout(self)
        main.setContentsMargins(14, 16, 14, 16)
        main.setSpacing(12)

        intro = QLabel(
            "Adjust frame layout, axis behaviour, and plot styling from a single place. "
            "Changes apply to the active sample and can be saved or reverted before closing."
        )
        intro.setWordWrap(True)
        intro.setObjectName("PlotSettingsIntro")
        main.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabBarAutoHide(False)
        main.addWidget(self.tabs, 1)

        # order of tabs loosely follows the more advanced GraphPad style
        self.tabs.addTab(self._make_canvas_layout_tab(), "Canvas & Layout")
        self.tabs.addTab(self._make_axis_tab(), "Axis")
        self.tabs.addTab(self._make_style_tab(), "Style")
        self.tabs.addTab(self._make_event_labels_tab(), "Event Labels")

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        qstyle = super().style()
        self.revert_btn = QPushButton("Revert to Snapshot")
        self.revert_btn.setIcon(qstyle.standardIcon(QStyle.SP_ArrowBack))
        self.revert_btn.clicked.connect(self._revert_snapshot)
        self.defaults_btn = QPushButton("Restore Style Defaults")
        self.defaults_btn.setIcon(qstyle.standardIcon(QStyle.SP_BrowserReload))
        self.defaults_btn.clicked.connect(self._restore_style_defaults)
        actions.addWidget(self.revert_btn)
        actions.addWidget(self.defaults_btn)
        main.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply_changes)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

        self.initial_style = self.style.copy()
        self.initial_layout = getattr(self, "initial_layout", self._get_initial_layout()).copy()
        self.initial_axis_state = self._capture_axis_state()

        self._populate_layout_controls(self.initial_layout)
        self._populate_axis_controls(self.initial_axis_state)
        self._populate_style_controls()

        self.update_preview()

    # ------------------------------------------------------------------
    # Helper: color picker ---------------------------------------------
    def _set_button_color(self, btn, color):
        btn.color = color
        btn.setStyleSheet(f"background-color: {color}")

    def _make_color_button(self, color):
        btn = QPushButton()
        btn.setFixedWidth(60)
        self._set_button_color(btn, color)

        def choose():
            # Ensure btn.color is a valid color string
            current_color = btn.color if isinstance(btn.color, str) else to_hex(btn.color)
            qcol = QColorDialog.getColor(QColor(current_color), self)
            if qcol.isValid():
                self._set_button_color(btn, qcol.name())

        btn.clicked.connect(choose)
        return btn

    def _normalize_color(self, color, fallback="#000000"):
        if not color:
            return fallback
        try:
            return to_hex(color)
        except (ValueError, TypeError):
            pass
        qcol = QColor(color)
        if qcol.isValid():
            return qcol.name()
        return fallback

    # ------------------------------------------------------------------
    # Frame & Origin tab ------------------------------------------------
    def _make_frame_tab_legacy(self):
        from vasoanalyzer.ui.dialogs.settings.frame_tab import (
            create_frame_tab_widgets,
            populate_frame_tab,
            wire_frame_tab,
        )

        refs = create_frame_tab_widgets(self, None)
        content = refs.tab
        self.origin_mode = refs.origin_mode
        self.origin_x = refs.origin_x
        self.origin_y = refs.origin_y
        self.canvas_preset = refs.canvas_preset
        self.canvas_w = refs.canvas_w
        self.canvas_h = refs.canvas_h
        self.fig_preset = refs.fig_preset
        self.fig_w = refs.fig_w
        self.fig_h = refs.fig_h

        populate_frame_tab(self)

        wire_frame_tab(self)
        self._toggle_origin_inputs()
        self._toggle_canvas_size_inputs()
        self._toggle_fig_size_inputs()

        return content

    def _make_frame_tab(self):
        return self._make_frame_tab_legacy()

    def _toggle_origin_inputs(self):
        manual = self.origin_mode.currentText() == "Manual"
        self.origin_x.setEnabled(manual)
        self.origin_y.setEnabled(manual)

    def _toggle_canvas_size_inputs(self):
        """Enable/disable canvas width/height based on preset selection."""
        custom = self.canvas_preset.currentText() == "Custom"
        self.canvas_w.setEnabled(custom)
        self.canvas_h.setEnabled(custom)

    def _toggle_fig_size_inputs(self):
        """Enable/disable figure width/height based on preset selection."""
        custom = self.fig_preset.currentText() == "Custom"
        self.fig_w.setEnabled(custom)
        self.fig_h.setEnabled(custom)

    # ------------------------------------------------------------------
    # Layout tab -------------------------------------------------------
    def _make_layout_tab_legacy(self, window=None):
        from vasoanalyzer.ui.dialogs.settings.layout_tab import (
            create_layout_tab_widgets,
            populate_layout_tab,
            wire_layout_tab,
        )

        refs = create_layout_tab_widgets(self, window)
        tab = refs.tab

        self.layout_controls = refs.layout_controls
        self._layout_sliders = refs.layout_sliders
        self.preview_fig = refs.preview_fig
        self.preview_canvas = refs.preview_canvas
        self.preview_ax = refs.preview_ax

        populate_layout_tab(self)
        wire_layout_tab(self)

        return tab

    def _make_layout_tab(self, window=None):
        return self._make_layout_tab_legacy(window)

    def _make_canvas_layout_tab(self):
        """Combine canvas/origin and layout controls into a single tab."""
        frame_tab = self._make_frame_tab()
        layout_scroll = self._make_layout_tab(self.parent_window)

        layout_content = None
        if isinstance(layout_scroll, QScrollArea):
            layout_content = layout_scroll.takeWidget()

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(16)
        container_layout.addWidget(frame_tab)

        if layout_content is not None:
            layout_content.setParent(container)
            container_layout.addWidget(layout_content)
        else:
            container_layout.addWidget(layout_scroll)

        container_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        return scroll

    def _get_initial_layout(self):
        sp = self.fig.subplotpars
        return {
            "left": sp.left,
            "right": sp.right,
            "top": sp.top,
            "bottom": sp.bottom,
            "wspace": sp.wspace,
            "hspace": sp.hspace,
        }

    # ------------------------------------------------------------------
    # Axis tab ---------------------------------------------------------
    def _toggle_range_inputs(self, widgets, enabled):
        for w in widgets:
            w.setEnabled(enabled)

    def _axis_section_title(self, axis, fallback):
        label = ""
        if axis is not None:
            label = (axis.get_ylabel() or "").strip()
        if label:
            return f"{fallback}: {label}"
        return fallback

    def _axis_units_suffix(self, axis):
        if axis is None:
            return ""
        label = axis.get_ylabel() or ""
        start = label.rfind("(")
        end = label.rfind(")")
        if 0 <= start < end:
            units = label[start + 1 : end].strip()
            if units:
                return f" {units}"
        return ""

    def _resolve_shared_x_axis(self):
        parent = getattr(self, "parent_window", None)
        candidates = []
        if parent is not None and hasattr(parent, "plot_host"):
            try:
                bottom_axis = parent.plot_host.bottom_axis()
                if bottom_axis is not None:
                    candidates.append(bottom_axis)
            except Exception:
                pass
        if self.ax is not None and self.ax not in candidates:
            candidates.append(self.ax)
        try:
            for axis in self.fig.axes:
                if axis not in candidates:
                    candidates.append(axis)
        except Exception:
            pass
        for axis in candidates:
            xlabel = (axis.get_xlabel() or "").strip()
            if xlabel:
                return axis
        return candidates[0] if candidates else self.ax

    def _current_xlabel(self):
        axis = getattr(self, "_x_axis_target", None) or self.ax
        if axis is not None:
            label = (axis.get_xlabel() or "").strip()
            if label:
                return label
        if self.ax2 is not None:
            alt = (self.ax2.get_xlabel() or "").strip()
            if alt:
                return alt
        return ""

    def _shared_x_axes(self):
        target = getattr(self, "_x_axis_target", None) or self.ax
        if target is None:
            return []
        axes = []
        try:
            fig_axes = list(self.fig.axes)
        except Exception:
            fig_axes = []
        for axis in fig_axes:
            if axis is None:
                continue
            if axis is target:
                axes.append(axis)
                continue
            try:
                shared = axis.get_shared_x_axes()
                if shared.joined(axis, target):
                    axes.append(axis)
                    continue
            except Exception:
                pass
            try:
                if target.get_shared_x_axes().joined(axis, target):
                    axes.append(axis)
                    continue
            except Exception:
                pass
        if target not in axes:
            axes.append(target)
        # preserve order but ensure uniqueness
        unique_axes = []
        for axis in axes:
            if axis not in unique_axes:
                unique_axes.append(axis)
        return unique_axes

    def _set_shared_xlabel(self, text):
        target = getattr(self, "_x_axis_target", None) or self.ax
        axes = self._shared_x_axes()
        for axis in axes:
            try:
                if axis is target:
                    axis.set_xlabel(text)
                else:
                    axis.set_xlabel("")
            except Exception:
                pass

    def _primary_trace_line(self):
        parent = getattr(self, "parent_window", None)
        if parent is not None:
            for attr in ("inner_line", "trace_line"):
                line = getattr(parent, attr, None)
                if isinstance(line, Line2D) and getattr(line, "axes", None) is self.ax:
                    return line
        if self.ax is None:
            return None
        visible_lines = [
            line for line in self.ax.lines if isinstance(line, Line2D) and line.get_visible()
        ]
        if visible_lines:
            return visible_lines[0]
        return self.ax.lines[0] if self.ax.lines else None

    def _secondary_trace_line(self):
        parent = getattr(self, "parent_window", None)
        if parent is not None:
            line = getattr(parent, "od_line", None)
            if isinstance(line, Line2D) and getattr(line, "axes", None) is self.ax2:
                return line
        if self.ax2 is None:
            return None
        visible_lines = [
            line for line in self.ax2.lines if isinstance(line, Line2D) and line.get_visible()
        ]
        if visible_lines:
            return visible_lines[0]
        return self.ax2.lines[0] if self.ax2.lines else None

    def _make_axis_tab_legacy(self):
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        # -- X Axis ---------------------------------------------------
        x_grp = QGroupBox("X Axis")
        x_form = QFormLayout(x_grp)
        x_form.setLabelAlignment(Qt.AlignRight)
        self.x_auto = QCheckBox("Auto range")
        self.x_auto.setChecked(self.ax.get_autoscalex_on())
        self.x_min = QDoubleSpinBox(suffix=" s")
        self.x_min.setRange(-1e6, 1e6)
        self.x_min.setValue(round(self.ax.get_xlim()[0], 2))
        self.x_max = QDoubleSpinBox(suffix=" s")
        self.x_max.setRange(-1e6, 1e6)
        self.x_max.setValue(round(self.ax.get_xlim()[1], 2))
        self.x_auto.toggled.connect(
            lambda b: self._toggle_range_inputs([self.x_min, self.x_max], not b)
        )
        self._toggle_range_inputs([self.x_min, self.x_max], not self.x_auto.isChecked())
        x_form.addRow(self.x_auto)
        x_form.addRow("Range:", self._pair(self.x_min, self.x_max))
        self.x_scale = QComboBox()
        self.x_scale.addItems(["Linear", "Log"])
        self.x_scale.setCurrentText("Log" if self.ax.get_xscale() == "log" else "Linear")
        x_form.addRow("Scale:", self.x_scale)
        self.x_ticks = QSpinBox()
        self.x_ticks.setRange(2, 20)
        self.x_ticks.setValue(len(self.ax.get_xticks()))
        x_form.addRow("Major ticks:", self.x_ticks)
        grid.addWidget(x_grp, 0, 0)

        # -- Top Plot (primary Y) -------------------------------------
        top_title = self._axis_section_title(self.ax, "Top Plot")
        top_units = self._axis_units_suffix(self.ax)
        y_grp = QGroupBox(top_title)
        y_form = QFormLayout(y_grp)
        y_form.setLabelAlignment(Qt.AlignRight)
        self.y_auto = QCheckBox("Auto range")
        self.y_auto.setChecked(self.ax.get_autoscaley_on())
        self.yi_min = QDoubleSpinBox(suffix=top_units)
        self.yi_min.setRange(-1e6, 1e6)
        self.yi_min.setValue(round(self.ax.get_ylim()[0], 2))
        self.yi_max = QDoubleSpinBox(suffix=top_units)
        self.yi_max.setRange(-1e6, 1e6)
        self.yi_max.setValue(round(self.ax.get_ylim()[1], 2))
        self.y_auto.toggled.connect(
            lambda b: self._toggle_range_inputs([self.yi_min, self.yi_max], not b)
        )
        self._toggle_range_inputs([self.yi_min, self.yi_max], not self.y_auto.isChecked())
        y_form.addRow(self.y_auto)
        y_form.addRow("Range:", self._pair(self.yi_min, self.yi_max))
        self.y_scale = QComboBox()
        self.y_scale.addItems(["Linear", "Log"])
        self.y_scale.setCurrentText("Log" if self.ax.get_yscale() == "log" else "Linear")
        y_form.addRow("Scale:", self.y_scale)
        self.y_ticks = QSpinBox()
        self.y_ticks.setRange(2, 20)
        self.y_ticks.setValue(len(self.ax.get_yticks()))
        y_form.addRow("Major ticks:", self.y_ticks)
        grid.addWidget(y_grp, 0, 1)

        # -- Bottom Plot (secondary Y) --------------------------------
        if self.ax2 is not None:
            bottom_title = self._axis_section_title(self.ax2, "Bottom Plot")
            bottom_units = self._axis_units_suffix(self.ax2)
            yo_grp = QGroupBox(bottom_title)
            yo_form = QFormLayout(yo_grp)
            yo_form.setLabelAlignment(Qt.AlignRight)
            self.yo_auto = QCheckBox("Auto range")
            self.yo_auto.setChecked(self.ax2.get_autoscaley_on())
            self.yo_min = QDoubleSpinBox(suffix=bottom_units)
            self.yo_min.setRange(-1e6, 1e6)
            self.yo_min.setValue(round(self.ax2.get_ylim()[0], 2))
            self.yo_max = QDoubleSpinBox(suffix=bottom_units)
            self.yo_max.setRange(-1e6, 1e6)
            self.yo_max.setValue(round(self.ax2.get_ylim()[1], 2))
            self.yo_auto.toggled.connect(
                lambda b: self._toggle_range_inputs([self.yo_min, self.yo_max], not b)
            )
            self._toggle_range_inputs([self.yo_min, self.yo_max], not self.yo_auto.isChecked())
            yo_form.addRow(self.yo_auto)
            yo_form.addRow("Range:", self._pair(self.yo_min, self.yo_max))
            self.yo_scale = QComboBox()
            self.yo_scale.addItems(["Linear", "Log"])
            self.yo_scale.setCurrentText("Log" if self.ax2.get_yscale() == "log" else "Linear")
            yo_form.addRow("Scale:", self.yo_scale)
            self.yo_ticks = QSpinBox()
            self.yo_ticks.setRange(2, 20)
            self.yo_ticks.setValue(len(self.ax2.get_yticks()))
            yo_form.addRow("Major ticks:", self.yo_ticks)
            grid.addWidget(yo_grp, 1, 0)

        # -- Grid & Ticks ---------------------------------------------
        tick_grp = QGroupBox("Grid && Ticks")
        tick_form = QFormLayout(tick_grp)
        self.show_grid = QCheckBox("Show grid")
        grid_state = getattr(self.parent_window, "grid_visible", None)
        if grid_state is None:
            grid_state = any(line.get_visible() for line in self.ax.get_xgridlines())
        self.show_grid.setChecked(bool(grid_state))
        self.tick_length = QDoubleSpinBox()
        self.tick_length.setRange(0.0, 20.0)
        self.tick_length.setValue(float(self.style.get("tick_length", 4.0)))
        self.tick_width = QDoubleSpinBox()
        self.tick_width.setRange(0.5, 5.0)
        self.tick_width.setValue(float(self.style.get("tick_width", 1.0)))
        tick_form.addRow(self.show_grid)
        tick_form.addRow("Tick length:", self.tick_length)
        tick_form.addRow("Tick width:", self.tick_width)
        grid.addWidget(tick_grp, 1, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)

        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        return scroll

    def _make_axis_tab(self):
        return self._make_axis_tab_legacy()

    def _make_event_labels_tab_legacy(self, window=None):
        from vasoanalyzer.ui.dialogs.settings.event_labels_tab import (
            create_event_labels_tab_widgets,
            populate_event_labels_tab,
            wire_event_labels_tab,
        )

        refs = create_event_labels_tab_widgets(self, window)
        container = refs.tab

        # Reattach attributes so downstream code still finds them on self
        self.event_font_family = refs.event_font_family
        self.event_font_size = refs.event_font_size
        self.event_bold = refs.event_bold
        self.event_italic = refs.event_italic
        self.event_color_btn = refs.event_color_btn
        self.event_labels_v3_toggle = refs.event_labels_v3_toggle
        self.event_label_mode = refs.event_label_mode
        self.event_cluster_style = refs.event_cluster_style
        self.event_max_per_cluster = refs.event_max_per_cluster
        self.event_label_lanes = refs.event_label_lanes
        self.event_belt_baseline = refs.event_belt_baseline
        self.event_span_siblings = refs.event_span_siblings
        self.event_auto_mode = refs.event_auto_mode
        self.event_density_compact = refs.event_density_compact
        self.event_density_belt = refs.event_density_belt
        self.event_outline_enabled = refs.event_outline_enabled
        self.event_outline_width = refs.event_outline_width
        self.event_outline_color_btn = refs.event_outline_color_btn
        self.event_tooltips_enabled = refs.event_tooltips_enabled
        self.event_tooltip_proximity = refs.event_tooltip_proximity
        self.event_legend_enabled = refs.event_legend_enabled
        self.event_legend_location = refs.event_legend_location
        self.event_list = refs.event_list
        self.event_editor = refs.event_editor
        self.event_overrides_box = refs.event_overrides_box
        self.event_empty_label = refs.event_empty_label

        populate_event_labels_tab(self)
        wire_event_labels_tab(self)

        self._refresh_event_list()

        return container

    def _make_event_labels_tab(self, window=None):
        return self._make_event_labels_tab_legacy(window)

    # ------------------------------------------------------------------
    # Event override helpers -------------------------------------------
    def _initialize_event_sources(self, parent: object | None) -> None:
        if parent is not None:
            callback = getattr(parent, "apply_event_label_overrides", None)
            if callable(callback):
                self._event_update_callback = callback
            labels = getattr(parent, "event_labels", None)
            times = getattr(parent, "event_times", None)
            meta = getattr(parent, "event_label_meta", None)
        else:
            labels = times = meta = None
        self._load_event_entries(labels, times, meta)

    def _load_event_entries(
        self,
        labels: Sequence[str] | None,
        times: Sequence[float] | None,
        meta: Sequence[Mapping[str, Any]] | None,
    ) -> None:
        self._event_entries.clear()
        self._event_times = []
        if not labels:
            return

        times_list: list[float] = []
        if times is not None:
            for value in times:
                try:
                    times_list.append(float(value))
                except (TypeError, ValueError):
                    times_list.append(0.0)
        meta_list: list[Mapping[str, Any]] = list(meta or [])
        if len(meta_list) < len(labels):
            meta_list.extend({} for _ in range(len(labels) - len(meta_list)))

        self._event_times = times_list[: len(labels)]

        for idx, raw_label in enumerate(labels):
            entry_meta = meta_list[idx] if idx < len(meta_list) else {}
            label_text = str(raw_label) if raw_label is not None else ""
            time_val = times_list[idx] if idx < len(times_list) else 0.0
            self._event_entries.append(
                {
                    "label": label_text,
                    "time": time_val,
                    "meta": dict(entry_meta) if isinstance(entry_meta, Mapping) else {},
                }
            )

    def set_event_update_callback(self, callback) -> None:
        if callable(callback):
            self._event_update_callback = callback

    def event_updates_emitted(self) -> bool:
        return bool(self._event_updates_fired)

    def get_event_overrides(self) -> tuple[list[str], list[dict[str, Any]]]:
        if not self._event_entries:
            return ([], [])
        labels = [entry.get("label", "") for entry in self._event_entries]
        metadata = [dict(entry.get("meta", {})) for entry in self._event_entries]
        return labels, metadata

    def _emit_event_updates(self) -> None:
        labels, meta = self.get_event_overrides()
        if labels is None or meta is None:
            return
        if callable(self._event_update_callback):
            self._event_update_callback(labels, meta)
        self._event_updates_fired = True

    def _format_event_list_item(self, entry: dict[str, Any]) -> str:
        label = entry.get("label") or "(Untitled)"
        try:
            time_val = float(entry.get("time", 0.0))
            return f"{label} — {time_val:.2f} s"
        except (TypeError, ValueError):
            return label

    def _refresh_event_list(self) -> None:
        if not hasattr(self, "event_list"):
            return
        self.event_list.blockSignals(True)
        self.event_list.clear()
        for entry in self._event_entries:
            self.event_list.addItem(QListWidgetItem(self._format_event_list_item(entry)))
        self.event_list.blockSignals(False)

        has_events = bool(self._event_entries)
        self.event_list.setEnabled(has_events)
        if hasattr(self, "event_overrides_box"):
            self.event_overrides_box.setVisible(has_events)
        if hasattr(self, "event_empty_label"):
            self.event_empty_label.setVisible(not has_events)

        if not has_events:
            if hasattr(self, "event_editor"):
                self.event_editor.clear()
            return

        prev_block = self.event_list.blockSignals(True)
        if self.event_list.currentRow() < 0:
            self.event_list.setCurrentRow(0)
        self.event_list.blockSignals(prev_block)
        self._on_event_row_changed(self.event_list.currentRow())

    def _on_event_row_changed(self, row: int) -> None:
        if self._suppress_event_editor:
            return
        if not (0 <= row < len(self._event_entries)):
            if hasattr(self, "event_editor"):
                self.event_editor.clear()
            return
        entry = self._event_entries[row]
        self._suppress_event_editor = True
        if hasattr(self, "event_editor"):
            self.event_editor.set_event(
                row,
                entry.get("label", ""),
                entry.get("time", 0.0),
                entry.get("meta", {}),
                max_lanes=(
                    int(self.event_label_lanes.value()) if hasattr(self, "event_label_lanes") else 2
                ),
            )
        self._suppress_event_editor = False

    def _on_event_style_changed(self, index: int, meta: dict[str, Any]) -> None:
        if self._suppress_event_editor or not (0 <= index < len(self._event_entries)):
            return
        self._event_entries[index]["meta"] = dict(meta or {})
        self._event_updates_fired = False

    def _on_event_label_changed(self, index: int, text: str) -> None:
        if self._suppress_event_editor or not (0 <= index < len(self._event_entries)):
            return
        normalized = text.strip()
        self._event_entries[index]["label"] = normalized
        self._update_event_list_item(index)
        self._event_updates_fired = False

    def _on_event_lane_count_changed(self, value: int) -> None:
        """Debounced event lane count change - stores row and restarts timer."""
        if self._suppress_event_editor:
            return
        if not hasattr(self, "event_list"):
            return
        current_row = self.event_list.currentRow()
        self._pending_event_row = current_row
        self._event_lane_timer.start()

    def _do_event_lane_update(self) -> None:
        """Actual event lane update implementation after debounce."""
        if self._pending_event_row >= 0:
            self._on_event_row_changed(self._pending_event_row)

    def _update_event_list_item(self, index: int) -> None:
        if not hasattr(self, "event_list"):
            return
        item = self.event_list.item(index)
        if item is None:
            return
        item.setText(self._format_event_list_item(self._event_entries[index]))

    def _pair(self, *widgets):
        row = QHBoxLayout()
        for w in widgets:
            row.addWidget(w)
        container = QGroupBox()
        rowbox = QHBoxLayout(container)
        rowbox.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            rowbox.addWidget(w)
        return container

    # ------------------------------------------------------------------
    # Style tab --------------------------------------------------------
    def _make_style_tab_legacy(self):
        from vasoanalyzer.ui.dialogs.settings.style_tab import build_style_tab

        return build_style_tab(self)

    def _make_style_tab(self):
        from vasoanalyzer.ui.dialogs.settings.style_tab import build_style_tab

        return build_style_tab(self)

    # ------------------------------------------------------------------
    def update_preview(self, *_):
        """Debounced preview update - restarts timer on each call."""
        self._preview_update_timer.start()

    def _do_update_preview(self):
        """Actual preview update implementation."""
        if not hasattr(self, "layout_controls"):
            return
        params = {name: ctrl.value() for name, ctrl in self.layout_controls.items()}
        self.preview_ax.clear()
        self.preview_ax.axis("off")
        self.preview_ax.add_patch(
            Rectangle(
                (params["left"], params["bottom"]),
                params["right"] - params["left"],
                params["top"] - params["bottom"],
                fill=False,
                edgecolor="#4a90e2",
                lw=2,
            )
        )
        self.preview_ax.set_xlim(0, 1)
        self.preview_ax.set_ylim(0, 1)
        self.preview_ax.invert_yaxis()
        self.preview_canvas.draw_idle()

    def _populate_layout_controls(self, params):
        if not hasattr(self, "layout_controls"):
            return
        for name, control in self.layout_controls.items():
            if name in params:
                control.blockSignals(True)
                control.setValue(float(params[name]))
                control.blockSignals(False)
        self.update_preview()

    def _populate_axis_controls(self, state):
        if not state:
            return
        # X axis
        self.x_auto.blockSignals(True)
        self.x_auto.setChecked(state.get("x_auto", True))
        self.x_auto.blockSignals(False)
        self.x_min.blockSignals(True)
        self.x_min.setValue(round(state.get("x_min", self.ax.get_xlim()[0]), 2))
        self.x_min.blockSignals(False)
        self.x_max.blockSignals(True)
        self.x_max.setValue(round(state.get("x_max", self.ax.get_xlim()[1]), 2))
        self.x_max.blockSignals(False)
        self._toggle_range_inputs([self.x_min, self.x_max], not self.x_auto.isChecked())
        x_scale = state.get("x_scale", self.ax.get_xscale())
        self.x_scale.setCurrentText("Log" if x_scale == "log" else "Linear")
        self.x_ticks.setValue(int(max(2, min(20, state.get("x_ticks", self.x_ticks.value())))))

        # Top plot axis
        self.y_auto.blockSignals(True)
        self.y_auto.setChecked(state.get("y_auto", True))
        self.y_auto.blockSignals(False)
        self.yi_min.blockSignals(True)
        self.yi_min.setValue(round(state.get("y_min", self.ax.get_ylim()[0]), 2))
        self.yi_min.blockSignals(False)
        self.yi_max.blockSignals(True)
        self.yi_max.setValue(round(state.get("y_max", self.ax.get_ylim()[1]), 2))
        self.yi_max.blockSignals(False)
        self._toggle_range_inputs([self.yi_min, self.yi_max], not self.y_auto.isChecked())
        y_scale = state.get("y_scale", self.ax.get_yscale())
        self.y_scale.setCurrentText("Log" if y_scale == "log" else "Linear")
        self.y_ticks.setValue(int(max(2, min(20, state.get("y_ticks", self.y_ticks.value())))))

        if self.ax2 is not None:
            bottom_auto = state.get(
                "bottom_auto",
                state.get("right_auto", self.ax2.get_autoscaley_on()),
            )
            self.yo_auto.blockSignals(True)
            self.yo_auto.setChecked(bool(bottom_auto))
            self.yo_auto.blockSignals(False)
            self.yo_min.blockSignals(True)
            self.yo_min.setValue(
                round(state.get("bottom_min", state.get("right_min", self.ax2.get_ylim()[0])), 2)
            )
            self.yo_min.blockSignals(False)
            self.yo_max.blockSignals(True)
            self.yo_max.setValue(
                round(state.get("bottom_max", state.get("right_max", self.ax2.get_ylim()[1])), 2)
            )
            self.yo_max.blockSignals(False)
            self._toggle_range_inputs([self.yo_min, self.yo_max], not self.yo_auto.isChecked())
            y2_scale = state.get("bottom_scale", state.get("right_scale", self.ax2.get_yscale()))
            self.yo_scale.setCurrentText("Log" if y2_scale == "log" else "Linear")
            bottom_ticks = state.get(
                "bottom_ticks", state.get("right_ticks", self.yo_ticks.value())
            )
            self.yo_ticks.setValue(int(max(2, min(20, bottom_ticks))))

        grid_on = state.get("grid_on")
        if grid_on is not None:
            self.show_grid.blockSignals(True)
            self.show_grid.setChecked(bool(grid_on))
            self.show_grid.blockSignals(False)

        title = state.get("title", self.ax.get_title())
        if hasattr(self, "title_edit"):
            self.title_edit.blockSignals(True)
            self.title_edit.setText(title)
            self.title_edit.blockSignals(False)

        xlabel = state.get("x_label", self._current_xlabel())
        if hasattr(self, "xlabel_edit"):
            self.xlabel_edit.blockSignals(True)
            self.xlabel_edit.setText(xlabel)
            self.xlabel_edit.blockSignals(False)

        ylabel = state.get("y_label", self.ax.get_ylabel())
        if hasattr(self, "yi_label_edit"):
            self.yi_label_edit.blockSignals(True)
            self.yi_label_edit.setText(ylabel)
            self.yi_label_edit.blockSignals(False)

        if hasattr(self, "yo_label_edit"):
            right_label = state.get(
                "bottom_label",
                state.get("right_label", self.ax2.get_ylabel() if self.ax2 else ""),
            )
            self.yo_label_edit.blockSignals(True)
            self.yo_label_edit.setText(right_label)
            self.yo_label_edit.blockSignals(False)

    def _set_combo_value(self, combo, value):
        if value is None:
            return
        if combo.findText(value) == -1:
            combo.addItem(value)
        combo.blockSignals(True)
        combo.setCurrentText(value)
        combo.blockSignals(False)

    def _populate_style_controls(self):
        style = self.style

        self._set_combo_value(
            self.axis_font_family,
            style.get("axis_font_family", DEFAULT_STYLE["axis_font_family"]),
        )
        self.axis_font_size.blockSignals(True)
        self.axis_font_size.setValue(
            int(style.get("axis_font_size", DEFAULT_STYLE["axis_font_size"]))
        )
        self.axis_font_size.blockSignals(False)
        self.axis_bold.blockSignals(True)
        self.axis_bold.setChecked(
            bool(style.get("axis_bold", DEFAULT_STYLE.get("axis_bold", True)))
        )
        self.axis_bold.blockSignals(False)
        self.axis_italic.blockSignals(True)
        self.axis_italic.setChecked(
            bool(style.get("axis_italic", DEFAULT_STYLE.get("axis_italic", False)))
        )
        self.axis_italic.blockSignals(False)

        self.tick_font_size.blockSignals(True)
        self.tick_font_size.setValue(
            int(style.get("tick_font_size", DEFAULT_STYLE["tick_font_size"]))
        )
        self.tick_font_size.blockSignals(False)

        x_color_source = self._x_axis_target or self.ax
        if x_color_source is not None:
            try:
                x_color = self._normalize_color(
                    x_color_source.xaxis.label.get_color(),
                    style.get("x_axis_color"),
                )
                self.style["x_axis_color"] = x_color
            except Exception:
                x_color = self._normalize_color(
                    style.get("x_axis_color", DEFAULT_STYLE.get("x_axis_color", "#000000")),
                    DEFAULT_STYLE.get("x_axis_color", "#000000"),
                )
        else:
            x_color = self._normalize_color(
                style.get("x_axis_color", DEFAULT_STYLE.get("x_axis_color", "#000000")),
                DEFAULT_STYLE.get("x_axis_color", "#000000"),
            )
        self._set_button_color(self.x_axis_color_btn, x_color)
        self._set_button_color(
            self.yi_axis_color_btn,
            style.get("y_axis_color", self.ax.yaxis.label.get_color()),
        )
        if hasattr(self, "yo_axis_color_btn"):
            self._set_button_color(
                self.yo_axis_color_btn,
                style.get("right_axis_color", self.ax2.yaxis.label.get_color()),
            )

        self._set_button_color(
            self.x_tick_color_btn,
            style.get("x_tick_color", self.ax.xaxis.label.get_color()),
        )
        self._set_button_color(
            self.yi_tick_color_btn,
            style.get("y_tick_color", self.ax.yaxis.label.get_color()),
        )
        if hasattr(self, "yo_tick_color_btn"):
            self._set_button_color(
                self.yo_tick_color_btn,
                style.get("right_tick_color", self.ax2.yaxis.label.get_color()),
            )

        self._set_combo_value(
            self.event_font_family,
            style.get("event_font_family", DEFAULT_STYLE["event_font_family"]),
        )
        self.event_font_size.blockSignals(True)
        self.event_font_size.setValue(
            int(style.get("event_font_size", DEFAULT_STYLE["event_font_size"]))
        )
        self.event_font_size.blockSignals(False)
        self.event_bold.blockSignals(True)
        self.event_bold.setChecked(
            bool(style.get("event_bold", DEFAULT_STYLE.get("event_bold", False)))
        )
        self.event_bold.blockSignals(False)
        self.event_italic.blockSignals(True)
        self.event_italic.setChecked(
            bool(style.get("event_italic", DEFAULT_STYLE.get("event_italic", False)))
        )
        self.event_italic.blockSignals(False)
        self._set_button_color(
            self.event_color_btn,
            style.get("event_color", DEFAULT_STYLE["event_color"]),
        )

        self._set_combo_value(
            self.pin_font_family,
            style.get("pin_font_family", DEFAULT_STYLE["pin_font_family"]),
        )
        self.pin_font_size.blockSignals(True)
        self.pin_font_size.setValue(int(style.get("pin_font_size", DEFAULT_STYLE["pin_font_size"])))
        self.pin_font_size.blockSignals(False)
        self.pin_bold.blockSignals(True)
        self.pin_bold.setChecked(bool(style.get("pin_bold", DEFAULT_STYLE.get("pin_bold", False))))
        self.pin_bold.blockSignals(False)
        self.pin_italic.blockSignals(True)
        self.pin_italic.setChecked(
            bool(style.get("pin_italic", DEFAULT_STYLE.get("pin_italic", False)))
        )
        self.pin_italic.blockSignals(False)
        self._set_button_color(
            self.pin_color_btn,
            style.get("pin_color", DEFAULT_STYLE["pin_color"]),
        )
        self.pin_marker_size.blockSignals(True)
        self.pin_marker_size.setValue(int(style.get("pin_size", DEFAULT_STYLE["pin_size"])))
        self.pin_marker_size.blockSignals(False)

        self.line_width.blockSignals(True)
        self.line_width.setValue(float(style.get("line_width", DEFAULT_STYLE["line_width"])))
        self.line_width.blockSignals(False)
        idx = self.line_style_combo.findData(
            style.get("line_style", DEFAULT_STYLE["line_style"]).lower()
        )
        if idx != -1:
            self.line_style_combo.blockSignals(True)
            self.line_style_combo.setCurrentIndex(idx)
            self.line_style_combo.blockSignals(False)
        primary_line = self._primary_trace_line()
        if primary_line is not None:
            primary_color = self._normalize_color(primary_line.get_color(), style.get("line_color"))
            self.style["line_color"] = primary_color
        else:
            primary_color = self._normalize_color(
                style.get("line_color", DEFAULT_STYLE["line_color"]),
                DEFAULT_STYLE["line_color"],
            )
        self._set_button_color(self.line_color_btn, primary_color)

        if hasattr(self, "od_line_width"):
            self.od_line_width.blockSignals(True)
            self.od_line_width.setValue(
                float(style.get("outer_line_width", DEFAULT_STYLE["outer_line_width"]))
            )
            self.od_line_width.blockSignals(False)
        if hasattr(self, "od_line_style_combo"):
            o_idx = self.od_line_style_combo.findData(
                style.get("outer_line_style", DEFAULT_STYLE["outer_line_style"]).lower()
            )
            if o_idx != -1:
                self.od_line_style_combo.blockSignals(True)
                self.od_line_style_combo.setCurrentIndex(o_idx)
                self.od_line_style_combo.blockSignals(False)
        if hasattr(self, "od_line_color_btn"):
            secondary_line = self._secondary_trace_line()
            if secondary_line is not None:
                secondary_color = self._normalize_color(
                    secondary_line.get_color(),
                    style.get("outer_line_color"),
                )
                self.style["outer_line_color"] = secondary_color
            else:
                secondary_color = self._normalize_color(
                    style.get("outer_line_color", DEFAULT_STYLE["outer_line_color"]),
                    DEFAULT_STYLE["outer_line_color"],
                )
            self._set_button_color(self.od_line_color_btn, secondary_color)

        self.tick_length.blockSignals(True)
        self.tick_length.setValue(float(style.get("tick_length", DEFAULT_STYLE["tick_length"])))
        self.tick_length.blockSignals(False)
        self.tick_width.blockSignals(True)
        self.tick_width.setValue(float(style.get("tick_width", DEFAULT_STYLE["tick_width"])))
        self.tick_width.blockSignals(False)

    def _restore_style_defaults(self):
        self.style = DEFAULT_STYLE.copy()
        self._populate_style_controls()

    def _revert_snapshot(self):
        self.style = self.initial_style.copy()
        self._populate_style_controls()
        self._populate_layout_controls(self.initial_layout)
        self._populate_axis_controls(self.initial_axis_state)

    def _capture_axis_state(self):
        state = {
            "x_auto": self.ax.get_autoscalex_on(),
            "x_min": self.ax.get_xlim()[0],
            "x_max": self.ax.get_xlim()[1],
            "x_scale": self.ax.get_xscale(),
            "x_ticks": len(self.ax.get_xticks()) or self.x_ticks.value(),
            "y_auto": self.ax.get_autoscaley_on(),
            "y_min": self.ax.get_ylim()[0],
            "y_max": self.ax.get_ylim()[1],
            "y_scale": self.ax.get_yscale(),
            "y_ticks": len(self.ax.get_yticks()) or self.y_ticks.value(),
            "grid_on": self.show_grid.isChecked(),
            "title": self.ax.get_title(),
            "x_label": self._current_xlabel(),
            "y_label": self.ax.get_ylabel(),
        }
        if self.ax2 is not None:
            state.update(
                {
                    "bottom_auto": self.ax2.get_autoscaley_on(),
                    "bottom_min": self.ax2.get_ylim()[0],
                    "bottom_max": self.ax2.get_ylim()[1],
                    "bottom_scale": self.ax2.get_yscale(),
                    "bottom_ticks": len(self.ax2.get_yticks()) or self.yo_ticks.value(),
                    "bottom_label": self.ax2.get_ylabel(),
                }
            )
        return state

    # ------------------------------------------------------------------
    def apply_changes(self):
        parent = getattr(self, "parent_window", None) or self.parent()

        if self.origin_mode.currentText() == "Manual":
            self.ax.spines["left"].set_position(("data", self.origin_x.value()))
            self.ax.spines["bottom"].set_position(("data", self.origin_y.value()))
        else:
            self.ax.spines["left"].set_position(("outward", 0))
            self.ax.spines["bottom"].set_position(("outward", 0))

        # Handle canvas and figure sizes independently
        # Always use forward=False to prevent matplotlib from auto-resizing widgets
        parent = getattr(self, "parent_window", None)
        canvas_changed = False
        figure_changed = False

        # ============================================================
        # CANVAS SIZE (white rectangle boundary in Figure Composer)
        # ============================================================
        canvas_preset = self.canvas_preset.currentText()
        if canvas_preset == "Custom":
            canvas_w = max(1.0, float(self.canvas_w.value()))
            canvas_h = max(1.0, float(self.canvas_h.value()))
        elif canvas_preset == "Square":
            # Square canvas: use min of default dimensions
            default_w = getattr(parent, "_default_frame_width_in", 10.0)
            default_h = getattr(parent, "_default_frame_height_in", 7.5)
            side = min(default_w, default_h)
            canvas_w = canvas_h = side
        else:  # Auto (Wide)
            canvas_w = getattr(parent, "_default_frame_width_in", 10.0)
            canvas_h = getattr(parent, "_default_frame_height_in", 7.5)

        # Update canvas size in parent (Figure Composer)
        if parent is not None:
            old_canvas_w = getattr(parent, "_canvas_width_in", canvas_w)
            old_canvas_h = getattr(parent, "_canvas_height_in", canvas_h)
            if abs(canvas_w - old_canvas_w) > 0.01 or abs(canvas_h - old_canvas_h) > 0.01:
                parent._canvas_width_in = canvas_w
                parent._canvas_height_in = canvas_h
                canvas_changed = True

        # Update canvas spinboxes
        self.canvas_w.setValue(round(canvas_w, 1))
        self.canvas_h.setValue(round(canvas_h, 1))

        # ============================================================
        # FIGURE SIZE (matplotlib plot inside canvas)
        # ============================================================
        fig_preset = self.fig_preset.currentText()
        if fig_preset == "Custom":
            fig_w = max(1.0, float(self.fig_w.value()))
            fig_h = max(1.0, float(self.fig_h.value()))
        elif fig_preset == "Square":
            # Square figure: largest square that fits in canvas
            side = min(canvas_w, canvas_h)
            fig_w = fig_h = side
        else:  # Fill Canvas
            fig_w = canvas_w
            fig_h = canvas_h

        # Validate: figure must fit inside canvas
        if fig_w > canvas_w + 0.01 or fig_h > canvas_h + 0.01:
            from PyQt5.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "Figure Exceeds Canvas",
                f"Figure size ({fig_w:.1f}×{fig_h:.1f} in) exceeds canvas ({canvas_w:.1f}×{canvas_h:.1f} in).\n\n"
                f"Resize canvas to fit figure?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                # Enlarge canvas to fit figure
                canvas_w = max(canvas_w, fig_w)
                canvas_h = max(canvas_h, fig_h)
                if parent is not None:
                    parent._canvas_width_in = canvas_w
                    parent._canvas_height_in = canvas_h
                self.canvas_w.setValue(round(canvas_w, 1))
                self.canvas_h.setValue(round(canvas_h, 1))
                self.canvas_preset.setCurrentText("Custom")
                canvas_changed = True
            else:
                # Shrink figure to fit canvas
                fig_w = min(fig_w, canvas_w)
                fig_h = min(fig_h, canvas_h)
                self.fig_preset.setCurrentText("Custom")

        # Update figure size in parent (Figure Composer)
        if parent is not None:
            old_fig_w = getattr(parent, "_figure_width_in", fig_w)
            old_fig_h = getattr(parent, "_figure_height_in", fig_h)
            if abs(fig_w - old_fig_w) > 0.01 or abs(fig_h - old_fig_h) > 0.01:
                parent._figure_width_in = fig_w
                parent._figure_height_in = fig_h
                figure_changed = True
        else:
            # Main window: apply figure size directly to matplotlib
            if (abs(fig_w - self.fig.get_figwidth()) > 0.01) or (
                abs(fig_h - self.fig.get_figheight()) > 0.01
            ):
                self.fig.set_size_inches(fig_w, fig_h, forward=False)
                figure_changed = True

        log.debug(
            "Plot settings applied (canvas_preset=%s, figure_preset=%s, canvas_changed=%s, figure_changed=%s)",
            canvas_preset,
            fig_preset,
            canvas_changed,
            figure_changed,
        )

        # Apply canvas and figure sizes if anything changed
        if canvas_changed or figure_changed:
            if parent is not None and hasattr(parent, "_apply_canvas_size"):
                # Figure Composer: apply canvas and figure sizes from state variables
                # This will call set_size_inches() with the correct values
                parent._apply_canvas_size()
            else:
                # Main window: just redraw
                with contextlib.suppress(Exception):
                    self.fig.canvas.draw_idle()

        # Update spinboxes with calculated values (don't read from matplotlib after DPI changes)
        self.fig_w.setValue(round(fig_w, 1))
        self.fig_h.setValue(round(fig_h, 1))

        layout_values = {n: c.value() for n, c in self.layout_controls.items()}
        layout_values["left"] = max(0.0, min(layout_values["left"], 1.0))
        layout_values["right"] = max(layout_values["left"] + 0.05, min(layout_values["right"], 1.0))
        layout_values["bottom"] = max(0.0, min(layout_values["bottom"], 1.0))
        layout_values["top"] = max(layout_values["bottom"] + 0.05, min(layout_values["top"], 1.0))
        layout_values["wspace"] = max(0.0, layout_values["wspace"])
        layout_values["hspace"] = max(0.0, layout_values["hspace"])
        self.fig.subplots_adjust(**layout_values)

        x_auto = self.x_auto.isChecked()
        self.ax.set_autoscalex_on(x_auto)
        if x_auto:
            self.ax.autoscale(enable=True, axis="x")
        else:
            with contextlib.suppress(Exception):
                self.ax.set_xlim(self.x_min.value(), self.x_max.value())

        y_auto = self.y_auto.isChecked()
        self.ax.set_autoscaley_on(y_auto)
        if y_auto:
            self.ax.autoscale(enable=True, axis="y")
        else:
            with contextlib.suppress(Exception):
                self.ax.set_ylim(self.yi_min.value(), self.yi_max.value())

        self.ax.set_xscale(self.x_scale.currentText().lower())
        self.ax.set_yscale(self.y_scale.currentText().lower())
        self.ax.xaxis.set_major_locator(MaxNLocator(self.x_ticks.value()))
        self.ax.yaxis.set_major_locator(MaxNLocator(self.y_ticks.value()))

        if self.ax2 is not None:
            y2_auto = self.yo_auto.isChecked()
            self.ax2.set_autoscaley_on(y2_auto)
            if y2_auto:
                self.ax2.autoscale(enable=True, axis="y")
            else:
                with contextlib.suppress(Exception):
                    self.ax2.set_ylim(self.yo_min.value(), self.yo_max.value())
            self.ax2.set_yscale(self.yo_scale.currentText().lower())
            self.ax2.yaxis.set_major_locator(MaxNLocator(self.yo_ticks.value()))

        grid_on = self.show_grid.isChecked()
        if grid_on:
            self.ax.grid(True, color=CURRENT_THEME.get("grid_color", "#e0e0e0"))
        else:
            self.ax.grid(False)
        if parent is not None and hasattr(parent, "grid_visible"):
            parent.grid_visible = bool(grid_on)

        self.ax.set_title(self.title_edit.text())
        new_xlabel = self.xlabel_edit.text()
        self._set_shared_xlabel(new_xlabel)
        if parent is not None:
            shared_setter = getattr(parent, "_set_shared_xlabel", None)
            if callable(shared_setter):
                shared_setter(new_xlabel)
        self.ax.set_ylabel(self.yi_label_edit.text())
        if self.ax2 is not None:
            self.ax2.set_ylabel(self.yo_label_edit.text())

        self.style["axis_font_family"] = self.axis_font_family.currentText()
        self.style["axis_font_size"] = int(self.axis_font_size.value())
        self.style["axis_bold"] = self.axis_bold.isChecked()
        self.style["axis_italic"] = self.axis_italic.isChecked()
        self.style["tick_font_size"] = int(self.tick_font_size.value())
        self.style["axis_color"] = self.x_axis_color_btn.color
        self.style["x_axis_color"] = self.x_axis_color_btn.color
        self.style["y_axis_color"] = self.yi_axis_color_btn.color
        self.style["x_tick_color"] = self.x_tick_color_btn.color
        self.style["y_tick_color"] = self.yi_tick_color_btn.color
        self.style["tick_color"] = self.x_tick_color_btn.color
        self.style["tick_length"] = float(self.tick_length.value())
        self.style["tick_width"] = float(self.tick_width.value())
        self.style["line_width"] = float(self.line_width.value())
        self.style["line_style"] = (
            self.line_style_combo.currentData() or DEFAULT_STYLE["line_style"]
        ).lower()
        self.style["line_color"] = self.line_color_btn.color
        self.style["event_font_family"] = self.event_font_family.currentText()
        self.style["event_font_size"] = int(self.event_font_size.value())
        self.style["event_bold"] = self.event_bold.isChecked()
        self.style["event_italic"] = self.event_italic.isChecked()
        self.style["event_color"] = self.event_color_btn.color
        self.style["event_labels_v3_enabled"] = self.event_labels_v3_toggle.isChecked()
        self.style["event_label_mode"] = self.event_label_mode.currentData() or "vertical"
        self.style["event_label_style_policy"] = self.event_cluster_style.currentData() or "first"
        self.style["event_label_max_per_cluster"] = int(self.event_max_per_cluster.value())
        self.style["event_label_lanes"] = int(self.event_label_lanes.value())
        self.style["event_label_belt_baseline"] = self.event_belt_baseline.isChecked()
        self.style["event_label_span_siblings"] = self.event_span_siblings.isChecked()
        self.style["pin_font_family"] = self.pin_font_family.currentText()
        self.style["pin_font_size"] = int(self.pin_font_size.value())
        self.style["pin_bold"] = self.pin_bold.isChecked()
        self.style["pin_italic"] = self.pin_italic.isChecked()
        self.style["pin_color"] = self.pin_color_btn.color
        self.style["pin_size"] = int(self.pin_marker_size.value())
        self.style["event_label_auto_mode"] = self.event_auto_mode.isChecked()
        self.style["event_label_density_compact"] = float(self.event_density_compact.value())
        self.style["event_label_density_belt"] = float(self.event_density_belt.value())
        self.style["event_label_outline_enabled"] = self.event_outline_enabled.isChecked()
        self.style["event_label_outline_width"] = float(self.event_outline_width.value())
        self.style["event_label_outline_color"] = self.event_outline_color_btn.color
        self.style["event_label_tooltips_enabled"] = self.event_tooltips_enabled.isChecked()
        self.style["event_label_tooltip_proximity"] = int(self.event_tooltip_proximity.value())
        self.style["event_label_legend_enabled"] = self.event_legend_enabled.isChecked()
        self.style["event_label_legend_location"] = self.event_legend_location.currentText()

        # Event highlights
        if hasattr(self, "event_highlight_color_btn"):
            self.style["event_highlight_color"] = self.event_highlight_color_btn.color
        if hasattr(self, "event_highlight_alpha"):
            self.style["event_highlight_alpha"] = float(self.event_highlight_alpha.value())
        if hasattr(self, "event_highlight_duration"):
            self.style["event_highlight_duration_ms"] = int(self.event_highlight_duration.value())

        if self.ax2 is not None:
            if hasattr(self, "yo_axis_color_btn"):
                self.style["right_axis_color"] = self.yo_axis_color_btn.color
            if hasattr(self, "yo_tick_color_btn"):
                self.style["right_tick_color"] = self.yo_tick_color_btn.color
            if hasattr(self, "od_line_width"):
                self.style["outer_line_width"] = float(self.od_line_width.value())
            if hasattr(self, "od_line_style_combo"):
                self.style["outer_line_style"] = (
                    self.od_line_style_combo.currentData() or DEFAULT_STYLE["outer_line_style"]
                ).lower()
            if hasattr(self, "od_line_color_btn"):
                self.style["outer_line_color"] = self.od_line_color_btn.color

        self._emit_event_updates()

        if parent is not None and hasattr(parent, "apply_plot_style"):
            parent.apply_plot_style(self.style, persist=True)
        else:
            self.canvas.draw_idle()

    # ------------------------------------------------------------------
    def get_style(self):
        return self.style.copy()

    # ------------------------------------------------------------------
    def _on_ok(self):
        self.apply_changes()
        self.accept()
