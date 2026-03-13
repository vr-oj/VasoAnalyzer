# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""PlotManager -- plot rendering and channel management extracted from VasoAnalyzerApp."""

from __future__ import annotations

import contextlib
import logging
import math
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, QSignalBlocker, QTimer, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

import vasoanalyzer.core.project as project_module
from vasoanalyzer.core.audit import serialize_edit_log
from vasoanalyzer.core.timebase import derive_tiff_page_times, page_for_time
from vasoanalyzer.ui.constants import DEFAULT_STYLE
from vasoanalyzer.ui.dialogs.legend_settings_dialog import LegendSettingsDialog
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.theme import CURRENT_THEME, css_rgba_to_mpl
from vasoanalyzer.ui.time_scrollbar import (
    TIME_SCROLLBAR_SCALE,
    compute_scrollbar_state,
    window_from_scroll_value,
)
from vasoanalyzer.ui.style_manager import PlotStyleManager

if TYPE_CHECKING:
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)


class PlotManager(QObject):
    """Manages plot rendering, channels, hover, scroll, and view state."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

    def sync_slider_with_plot(self, event=None):
        h = self._host
        h.update_scroll_slider()

    def _apply_current_style(self, *, redraw: bool = False) -> None:
        """Reapply the current plot style to reflect updated artists."""
        h = self._host

        if not hasattr(h, "ax") or h.ax is None:
            return
        manager = h._ensure_style_manager()
        main_line = h.trace_line
        if main_line is None and h.ax.lines:
            main_line = h.ax.lines[0]
        x_axis = h._x_axis_for_style()
        manager.apply(
            ax=h.ax,
            ax_secondary=h.ax2,
            x_axis=x_axis,
            event_text_objects=h.event_text_objects,
            pinned_points=h.pinned_points,
            main_line=main_line,
            od_line=h.od_line,
        )
        style_snapshot = manager.style()
        h._event_highlight_color = style_snapshot.get(
            "event_highlight_color",
            DEFAULT_STYLE.get("event_highlight_color", h._event_highlight_color),
        )
        h._event_highlight_base_alpha = max(
            0.0,
            min(
                float(
                    style_snapshot.get(
                        "event_highlight_alpha",
                        DEFAULT_STYLE.get(
                            "event_highlight_alpha", h._event_highlight_base_alpha
                        ),
                    )
                ),
                1.0,
            ),
        )
        h._event_highlight_duration_ms = max(
            0,
            int(
                style_snapshot.get(
                    "event_highlight_duration_ms",
                    DEFAULT_STYLE.get(
                        "event_highlight_duration_ms",
                        h._event_highlight_duration_ms,
                    ),
                )
            ),
        )
        h._event_highlight_elapsed_ms = 0
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None:
            plot_host.set_event_highlight_style(
                color=h._event_highlight_color,
                alpha=h._event_highlight_base_alpha,
            )
        if redraw:
            h.canvas.draw_idle()

    def _outer_channel_available(self) -> bool:
        h = self._host
        if h.trace_data is None:
            return False
        if "Outer Diameter" not in h.trace_data.columns:
            return False
        series = h.trace_data["Outer Diameter"]
        try:
            return not series.isna().all()
        except Exception:
            return True

    def _avg_pressure_channel_available(self) -> bool:
        h = self._host
        if h.trace_data is None:
            return False
        label = h._trace_label_for("p_avg")
        if label not in h.trace_data.columns:
            return False
        series = h.trace_data[label]
        try:
            return not series.isna().all()
        except Exception:
            return True

    def _set_pressure_channel_available(self) -> bool:
        h = self._host
        if h.trace_data is None:
            return False
        label = h._trace_label_for("p2")
        sample = getattr(h, "current_sample", None)
        columns = list(h.trace_data.columns)
        in_columns = label in columns
        log.info(
            "UI: set-pressure availability check for %s -> label=%r in_columns=%s",
            getattr(sample, "name", "<unknown>") if sample is not None else "<none>",
            label,
            in_columns,
        )
        effective_label = label
        canonical_label = getattr(project_module, "P2_CANONICAL_LABEL", "Set Pressure (mmHg)")
        if not in_columns and canonical_label in h.trace_data.columns:
            log.info(
                "UI: set-pressure fallback -> using canonical %r even though label=%r",
                canonical_label,
                label,
            )
            effective_label = canonical_label
            in_columns = True

        if not in_columns:
            log.debug(
                "SET PRESSURE UNAVAILABLE: expected '%s' in %s",
                label,
                list(h.trace_data.columns),
            )
            return False
        series = h.trace_data[effective_label]
        try:
            return not series.isna().all()
        except Exception:
            return True

    def _current_channel_presence(self) -> tuple[bool, bool]:
        h = self._host
        if not hasattr(h, "plot_host"):
            return (False, False)
        specs = h.plot_host.channel_specs()
        ids = {spec.track_id for spec in specs} if specs else set()
        return ("inner" in ids, "outer" in ids)

    def _ensure_valid_channel_selection(
        self,
        inner_on: bool,
        outer_on: bool,
        *,
        toggled: str,
        outer_supported: bool,
    ) -> tuple[bool, bool]:
        h = self._host
        inner_on = bool(inner_on)
        outer_on = bool(outer_on and outer_supported)
        if not inner_on and not outer_on:
            if toggled == "inner" and outer_supported:
                outer_on = True
            else:
                inner_on = True
        return inner_on, outer_on

    def _reset_channel_view_defaults(self) -> None:
        """Ensure freshly loaded traces start with ID and OD visible when available."""
        h = self._host

        has_outer = h._outer_channel_available()
        has_avg = h._avg_pressure_channel_available()
        has_set = h._set_pressure_channel_available()
        h._apply_toggle_state(
            True,
            True,
            outer_supported=has_outer,
            avg_pressure_supported=has_avg,
            set_pressure_supported=has_set,
        )
        if h.avg_pressure_toggle_act is not None:
            h.avg_pressure_toggle_act.blockSignals(True)
            h.avg_pressure_toggle_act.setChecked(has_avg)
            h.avg_pressure_toggle_act.blockSignals(False)
        if h.set_pressure_toggle_act is not None:
            h.set_pressure_toggle_act.blockSignals(True)
            h.set_pressure_toggle_act.setChecked(False)
            h.set_pressure_toggle_act.blockSignals(False)

    def _rebuild_channel_layout(
        self, inner_on: bool, outer_on: bool, *, redraw: bool = True
    ) -> None:
        h = self._host
        # PyQtGraph: always build tracks for available data; show/hide via visibility flags
        render_backend = None
        if hasattr(h, "plot_host") and h.plot_host is not None:
            with contextlib.suppress(Exception):
                render_backend = h.plot_host.get_render_backend()

        if render_backend == "pyqtgraph":
            specs: list[ChannelTrackSpec] = []
            has_outer = h._outer_channel_available()
            has_avg = h._avg_pressure_channel_available()
            has_set = h._set_pressure_channel_available()

            specs.append(
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            )

            if has_outer:
                specs.append(
                    ChannelTrackSpec(
                        track_id="outer",
                        component="outer",
                        label="Outer Diameter (µm)",
                        height_ratio=1.0,
                    )
                )

            if has_avg:
                specs.append(
                    ChannelTrackSpec(
                        track_id="avg_pressure",
                        component="avg_pressure",
                        label=h._trace_label_for("p_avg"),
                        height_ratio=1.0,
                    )
                )

            if has_set:
                specs.append(
                    ChannelTrackSpec(
                        track_id="set_pressure",
                        component="set_pressure",
                        label=h._trace_label_for("p2"),
                        height_ratio=1.0,
                    )
                )

            if not specs:
                specs.append(
                    ChannelTrackSpec(
                        track_id="inner",
                        component="inner",
                        label="Inner Diameter (µm)",
                        height_ratio=1.0,
                    )
                )

            host = h.plot_host
            # Align host visibility flags with requested toggle states (or defaults)
            host.set_channel_visible("inner", bool(inner_on))
            host.set_channel_visible("outer", bool(outer_on and has_outer))
            if has_avg:
                desired_avg = (
                    h.avg_pressure_toggle_act.isChecked()
                    if hasattr(h, "avg_pressure_toggle_act") and h.avg_pressure_toggle_act
                    else True
                )
                host.set_channel_visible("avg_pressure", bool(desired_avg))
            else:
                host.set_channel_visible("avg_pressure", False)
            if has_set:
                desired_set = (
                    h.set_pressure_toggle_act.isChecked()
                    if hasattr(h, "set_pressure_toggle_act") and h.set_pressure_toggle_act
                    else False  # Default: hide Set Pressure track
                )
                host.set_channel_visible("set_pressure", bool(desired_set))
            else:
                host.set_channel_visible("set_pressure", False)

            sample = getattr(h, "current_sample", None)
            avg_track_added = has_avg
            set_track_added = has_set
            layout_ready = bool(getattr(h, "_layout_log_ready", False))
            if (
                sample is not None
                and layout_ready
                and getattr(h, "_last_track_layout_sample_id", None) != id(sample)
            ):
                sample_name = getattr(sample, "name", getattr(sample, "label", "N/A"))
                log.info(
                    "UI: Track layout for sample %s -> inner=%s outer=%s avg_pressure=%s set_pressure=%s",
                    sample_name,
                    True,
                    has_outer,
                    avg_track_added,
                    set_track_added,
                )
                h._last_track_layout_sample_id = id(sample)

            h._unbind_primary_axis_callbacks()
            host.ensure_channels(specs)

            inner_track = host.track("inner")
            outer_track = host.track("outer") if has_outer else None
            avg_track = host.track("avg_pressure") if has_avg else None
            set_track = host.track("set_pressure") if has_set else None

            ordered_tracks = [t for t in (inner_track, outer_track, avg_track, set_track) if t]
            primary_track = next((t for t in ordered_tracks if t.is_visible()), None) or (
                ordered_tracks[0] if ordered_tracks else None
            )

            h.ax = primary_track.ax if primary_track else None
            h.ax2 = outer_track.ax if inner_track and outer_track else None
            h._bind_primary_axis_callbacks()
            h._init_hover_artists()

            h.trace_line = inner_track.primary_line if inner_track else None
            h.inner_line = h.trace_line
            h.od_line = outer_track.primary_line if outer_track else None
            h.outer_line = h.od_line

            for axis in h.plot_host.axes():
                if h.grid_visible:
                    axis.grid(True, color=CURRENT_THEME["grid_color"])
                else:
                    axis.grid(False)

            stored_xlabel = getattr(h, "_shared_xlabel", None)
            if stored_xlabel is not None:
                h._set_shared_xlabel(stored_xlabel)

            h._apply_current_style(redraw=False)
            h._refresh_plot_legend()
            h._sync_track_visibility_from_host()
            if redraw and hasattr(h, "canvas"):
                h.canvas.draw_idle()
            return

        specs: list[ChannelTrackSpec] = []
        if inner_on:
            specs.append(
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            )
        if outer_on:
            specs.append(
                ChannelTrackSpec(
                    track_id="outer",
                    component="outer",
                    label="Outer Diameter (µm)",
                    height_ratio=1.0,
                )
            )

        # Add pressure tracks if available and toggled on
        avg_pressure_on = (
            h.avg_pressure_toggle_act.isChecked()
            if hasattr(h, "avg_pressure_toggle_act") and h.avg_pressure_toggle_act is not None
            else True
        )
        set_pressure_on = (
            h.set_pressure_toggle_act.isChecked()
            if hasattr(h, "set_pressure_toggle_act") and h.set_pressure_toggle_act is not None
            else False
        )

        if h._avg_pressure_channel_available() and avg_pressure_on:
            log.debug("Track layout: adding avg_pressure track spec")
            specs.append(
                ChannelTrackSpec(
                    track_id="avg_pressure",
                    component="avg_pressure",
                    label=h._trace_label_for("p_avg"),
                    height_ratio=1.0,
                )
            )
        if h._set_pressure_channel_available() and set_pressure_on:
            log.debug("Track layout: adding set_pressure track spec")
            specs.append(
                ChannelTrackSpec(
                    track_id="set_pressure",
                    component="set_pressure",
                    label=h._trace_label_for("p2"),
                    height_ratio=1.0,
                )
            )

        if not specs:
            specs.append(
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            )

        sample = getattr(h, "current_sample", None)
        avg_track_added = any(spec.track_id == "avg_pressure" for spec in specs)
        set_track_added = any(spec.track_id == "set_pressure" for spec in specs)
        layout_ready = bool(getattr(h, "_layout_log_ready", False))
        if (
            sample is not None
            and layout_ready
            and getattr(h, "_last_track_layout_sample_id", None) != id(sample)
        ):
            sample_name = getattr(sample, "name", getattr(sample, "label", "N/A"))
            log.info(
                "UI: Track layout for sample %s -> inner=%s outer=%s avg_pressure=%s set_pressure=%s",
                sample_name,
                inner_on,
                outer_on,
                avg_track_added,
                set_track_added,
            )
            h._last_track_layout_sample_id = id(sample)

        h._unbind_primary_axis_callbacks()
        h.plot_host.ensure_channels(specs)

        inner_track = h.plot_host.track("inner") if inner_on else None
        outer_track = h.plot_host.track("outer") if outer_on else None

        primary_track = inner_track or outer_track
        h.ax = primary_track.ax if primary_track else None
        h.ax2 = outer_track.ax if inner_track and outer_track else None
        h._bind_primary_axis_callbacks()
        h._init_hover_artists()

        h.trace_line = (
            inner_track.primary_line
            if inner_track
            else (outer_track.primary_line if outer_track else None)
        )
        h.inner_line = inner_track.primary_line if inner_track else None
        h.od_line = outer_track.primary_line if outer_track else None
        h.outer_line = h.od_line

        for axis in h.plot_host.axes():
            if h.grid_visible:
                axis.grid(True, color=CURRENT_THEME["grid_color"])
            else:
                axis.grid(False)

        stored_xlabel = getattr(h, "_shared_xlabel", None)
        if stored_xlabel is not None:
            h._set_shared_xlabel(stored_xlabel)

        h._apply_current_style(redraw=False)
        h._refresh_plot_legend()
        if redraw:
            h.canvas.draw_idle()

    def _apply_channel_toggle(self, channel: str, checked: bool) -> None:
        h = self._host
        # PyQtGraph: drive host visibility without rebuilding tracks
        render_backend = None
        if hasattr(h, "plot_host") and h.plot_host is not None:
            with contextlib.suppress(Exception):
                render_backend = h.plot_host.get_render_backend()
        if render_backend == "pyqtgraph":
            h._apply_channel_toggle_pyqtgraph(channel, checked)
            return

        # For pressure channels, simply rebuild the layout
        if channel in ("avg_pressure", "set_pressure"):
            # Get current inner/outer state
            previous_inner, previous_outer = h._current_channel_presence()
            inner_on = (
                h.id_toggle_act.isChecked() if h.id_toggle_act is not None else previous_inner
            )
            outer_on = (
                h.od_toggle_act.isChecked() if h.od_toggle_act is not None else previous_outer
            )

            h._rebuild_channel_layout(inner_on, outer_on)
            h._refresh_zoom_window()
            h._invalidate_sample_state_cache()
            h._apply_event_table_column_contract()
            return

        # Original logic for inner/outer channels
        outer_supported = h._outer_channel_available()
        previous_inner, previous_outer = h._current_channel_presence()
        inner_on = (
            h.id_toggle_act.isChecked() if h.id_toggle_act is not None else previous_inner
        )
        outer_on = (
            h.od_toggle_act.isChecked() if h.od_toggle_act is not None else previous_outer
        )

        if channel == "inner":
            inner_on = bool(checked)
        else:
            if checked and not outer_supported:
                h._apply_toggle_state(inner_on, False, outer_supported=False)
                h._update_trace_controls_state()
                h._apply_event_table_column_contract()
                return
            outer_on = bool(checked)

        inner_on, outer_on = h._ensure_valid_channel_selection(
            inner_on,
            outer_on,
            toggled=channel,
            outer_supported=outer_supported,
        )

        current_inner, current_outer = h._current_channel_presence()
        h._apply_toggle_state(inner_on, outer_on, outer_supported=outer_supported)
        h._update_trace_controls_state()
        h._apply_event_table_column_contract()

        if inner_on == current_inner and outer_on == current_outer:
            return

        h._rebuild_channel_layout(inner_on, outer_on)
        h._refresh_zoom_window()
        h._on_view_state_changed(reason="channel toggle")

    def _apply_channel_toggle_pyqtgraph(self, channel: str, checked: bool) -> None:
        h = self._host
        host = getattr(h, "plot_host", None)
        if host is None:
            return

        if channel in ("avg_pressure", "set_pressure"):
            host.set_channel_visible(channel, bool(checked))
        else:
            has_outer = h._outer_channel_available()
            inner_visible = host.is_channel_visible("inner")
            outer_visible = host.is_channel_visible("outer") if has_outer else False

            if channel == "inner":
                inner_visible = bool(checked)
            else:
                if checked and not has_outer:
                    h._apply_toggle_state(inner_visible, False, outer_supported=False)
                    h._update_trace_controls_state()
                    return
                outer_visible = bool(checked)

            inner_visible, outer_visible = h._ensure_valid_channel_selection(
                inner_visible,
                outer_visible,
                toggled=channel,
                outer_supported=has_outer,
            )

            h._apply_toggle_state(inner_visible, outer_visible, outer_supported=has_outer)
            host.set_channel_visible("inner", inner_visible)
            host.set_channel_visible("outer", outer_visible)

        h._sync_track_visibility_from_host()
        h._update_trace_controls_state()
        h._refresh_plot_legend()
        if hasattr(h, "canvas"):
            with contextlib.suppress(Exception):
                h.canvas.draw_idle()
        h._on_view_state_changed(reason="channel toggle")
        h._apply_event_table_column_contract()

    def _plot_toolbar_signal_buttons(self) -> list[QToolButton]:
        h = self._host
        toolbar = getattr(h, "toolbar", None)
        if toolbar is None:
            return []
        buttons: list[QToolButton] = []
        for action in (
            getattr(h, "id_toggle_act", None),
            getattr(h, "od_toggle_act", None),
            getattr(h, "avg_pressure_toggle_act", None),
            getattr(h, "set_pressure_toggle_act", None),
        ):
            if action is None:
                continue
            widget = toolbar.widgetForAction(action)
            if isinstance(widget, QToolButton):
                widget.setProperty("isSignalToggle", True)
                buttons.append(widget)
        return buttons

    def _plot_toolbar_row2_buttons(self) -> list[QToolButton]:
        h = self._host
        toolbar = getattr(h, "toolbar", None)
        if toolbar is None:
            return []
        buttons: list[QToolButton] = []
        seen: set[int] = set()

        def add_button(button: QToolButton | None) -> None:
            if not isinstance(button, QToolButton):
                return
            if id(button) in seen:
                return
            buttons.append(button)
            seen.add(id(button))

        for action in (
            getattr(h, "actPgPan", None),
            getattr(h, "actBoxZoom", None),
            getattr(h, "actPan", None),
            getattr(h, "actZoom", None),
        ):
            if action is None:
                continue
            widget = toolbar.widgetForAction(action)
            add_button(widget)

        for action in (
            getattr(toolbar, "_quick_zoom_all_action", None),
            getattr(toolbar, "_quick_zoom_back_action", None),
            getattr(toolbar, "_quick_zoom_in_action", None),
            getattr(toolbar, "_quick_zoom_out_action", None),
            getattr(toolbar, "_quick_autoscale_action", None),
        ):
            if action is None:
                continue
            widget = toolbar.widgetForAction(action)
            add_button(widget)

        for button in self._plot_toolbar_view_buttons():
            add_button(button)

        for button in h._plot_toolbar_signal_buttons():
            add_button(button)

        add_button(getattr(h, "project_toggle_btn", None))
        add_button(getattr(h, "metadata_toggle_btn", None))

        return buttons

    def _plot_toolbar_nav_buttons(self) -> list[QToolButton]:
        """Return Navigation group buttons (Pan, Select, Fit View, Autoscale Y, Zoom In/Out, Undo Zoom)."""
        h = self._host
        toolbar = getattr(h, "toolbar", None)
        if toolbar is None:
            return []
        buttons: list[QToolButton] = []
        seen: set[int] = set()

        def add(widget: QToolButton | None) -> None:
            if isinstance(widget, QToolButton) and id(widget) not in seen:
                buttons.append(widget)
                seen.add(id(widget))

        for action in (
            getattr(h, "actPgPan", None),
            getattr(h, "actBoxZoom", None),
            getattr(h, "actPan", None),
            getattr(h, "actZoom", None),
        ):
            if action is not None:
                add(toolbar.widgetForAction(action))

        for attr in (
            "_quick_zoom_all_action",
            "_quick_autoscale_action",
            "_quick_zoom_in_action",
            "_quick_zoom_out_action",
            "_quick_zoom_back_action",
        ):
            action = getattr(toolbar, attr, None)
            if action is not None:
                add(toolbar.widgetForAction(action))

        return buttons

    def _plot_toolbar_view_buttons(self) -> list[QToolButton]:
        """Return View group buttons (Grid, Event Labels, Style)."""
        h = self._host
        toolbar = getattr(h, "toolbar", None)
        if toolbar is None:
            return []
        buttons: list[QToolButton] = []
        seen: set[int] = set()

        def add(widget: QToolButton | None) -> None:
            if isinstance(widget, QToolButton) and id(widget) not in seen:
                buttons.append(widget)
                seen.add(id(widget))

        for action in (getattr(h, "actGrid", None), getattr(h, "actStyle", None)):
            if action is not None:
                add(toolbar.widgetForAction(action))

        # Event Labels may be a split QToolButton added via addWidget — find by object name
        event_labels_btn = toolbar.findChild(QToolButton, "PlotToolbarEventLabels")
        if event_labels_btn is not None:
            add(event_labels_btn)
        else:
            action = getattr(h, "actChannelEventLabels", None)
            if action is not None:
                add(toolbar.widgetForAction(action))

        return buttons

    def _normalize_plot_toolbar_group_widths(self, compact: bool) -> None:
        """Normalize button widths within each toolbar group independently."""
        groups = [
            (self._plot_toolbar_nav_buttons(), 100),
            (self._plot_toolbar_view_buttons(), 80),
            (self._plot_toolbar_signal_buttons(), 140),
        ]
        for buttons, max_width in groups:
            if not buttons:
                continue
            for btn in buttons:
                btn.setMinimumWidth(0)
                btn.setMaximumWidth(16777215)
                btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            if compact:
                continue
            widths = [btn.sizeHint().width() for btn in buttons if btn.sizeHint().isValid()]
            if not widths:
                continue
            target = min(max(widths), max_width)
            for btn in buttons:
                btn.setMinimumWidth(target)
                btn.setMaximumWidth(target)
                btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
                btn.updateGeometry()

    def _normalize_plot_toolbar_button_geometry(self) -> None:
        h = self._host
        buttons = h._plot_toolbar_row2_buttons()
        if not buttons:
            return
        for button in buttons:
            button.setMinimumHeight(0)
            button.setMaximumHeight(16777215)

        heights = []
        for button in buttons:
            hint = button.sizeHint()
            if hint.isValid():
                heights.append(hint.height())
        if not heights:
            return

        target_height = max(heights)
        for button in buttons:
            button.setMinimumHeight(target_height)
            button.setMaximumHeight(target_height)
            button.updateGeometry()

    def _lock_plot_toolbar_row2_order(self) -> None:
        h = self._host
        toolbar = getattr(h, "toolbar", None)
        if toolbar is None:
            return

        nav_pan = getattr(h, "actPgPan", None) or getattr(h, "actPan", None)
        nav_select = getattr(h, "actBoxZoom", None) or getattr(h, "actZoom", None)

        # Navigation group: Fit View, Autoscale Y, Zoom In, Zoom Out, Undo Zoom
        quick_actions = [
            getattr(toolbar, "_quick_zoom_all_action", None),
            getattr(toolbar, "_quick_autoscale_action", None),
            getattr(toolbar, "_quick_zoom_in_action", None),
            getattr(toolbar, "_quick_zoom_out_action", None),
            getattr(toolbar, "_quick_zoom_back_action", None),
        ]

        # View group: Grid, Event Labels (optional), Style
        # Event Labels may be a widget action (split button) — prefer that over raw QAction
        event_labels_action = (
            getattr(toolbar, "_event_labels_widget_action", None)
            or getattr(h, "actChannelEventLabels", None)
        )
        view_actions = [a for a in [
            getattr(h, "actGrid", None),
            event_labels_action,
            getattr(h, "actStyle", None),
        ] if a is not None]

        signal_actions = [
            getattr(h, "id_toggle_act", None),
            getattr(h, "od_toggle_act", None),
            getattr(h, "avg_pressure_toggle_act", None),
            getattr(h, "set_pressure_toggle_act", None),
        ]

        panel_actions = [
            getattr(h, "project_toggle_action", None),
            getattr(h, "metadata_toggle_action", None),
        ]

        separators = [action for action in toolbar.actions() if action.isSeparator()]
        sep_nav_view = separators[0] if len(separators) > 0 else toolbar.addSeparator()
        sep_view_signals = separators[1] if len(separators) > 1 else toolbar.addSeparator()
        sep_signals_panels = separators[2] if len(separators) > 2 else toolbar.addSeparator()

        # Row 2 canonical order:
        # Project, Details
        # | Pan, Select, Fit View, Autoscale Y, Zoom In, Zoom Out, Undo Zoom
        # | Grid, Event Labels, Style
        # | Inner, Outer, Pressure, Set Pressure
        ordered_actions = [
            *panel_actions,
            sep_signals_panels,
            nav_pan,
            nav_select,
            *quick_actions,
            sep_nav_view,
            *view_actions,
            sep_view_signals,
            *signal_actions,
        ]

        before_action = None
        for action in reversed([act for act in ordered_actions if act is not None]):
            toolbar.insertAction(before_action, action)
            before_action = action

    def _update_plot_toolbar_signal_button_widths(self, compact: bool) -> None:
        h = self._host
        buttons = h._plot_toolbar_signal_buttons()
        if not buttons:
            return
        for button in buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        if compact:
            return

        widths = []
        for button in buttons:
            hint = button.sizeHint()
            if hint.isValid():
                widths.append(hint.width())
        if not widths:
            return

        target_width = min(max(widths), 140)
        for button in buttons:
            button.setMinimumWidth(target_width)
            button.setMaximumWidth(target_width)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            button.updateGeometry()

    def _refresh_zoom_window(self) -> None:
        h = self._host
        if not h.zoom_dock:
            return
        current_window = None
        if hasattr(h, "plot_host"):
            current_window = h.plot_host.current_window()
        if current_window is None:
            h.zoom_dock.clear_span()
            return
        start, end = current_window
        h.zoom_dock.show_span(start, end)

    def _serialize_plot_layout(self) -> dict | None:
        h = self._host
        if not hasattr(h, "plot_host"):
            return None
        layout = h.plot_host.layout_state()
        specs = h.plot_host.channel_specs()
        return {
            "order": list(layout.order),
            "height_ratios": {k: float(v) for k, v in layout.height_ratios.items()},
            "visibility": {k: bool(v) for k, v in layout.visibility.items()},
            "channels": [
                {
                    "track_id": spec.track_id,
                    "component": spec.component,
                    "label": spec.label,
                    "height_ratio": float(spec.height_ratio),
                }
                for spec in specs
            ],
        }

    def _apply_pending_plot_layout(self) -> None:
        h = self._host
        layout = getattr(h, "_pending_plot_layout", None)
        if not layout:
            return
        if not hasattr(h, "plot_host"):
            return
        # Fast path: if the pending layout matches the current layout, skip work.
        try:
            current = h._serialize_plot_layout()
            if (
                isinstance(layout, dict)
                and isinstance(current, dict)
                and layout.get("order") == current.get("order")
                and dict(layout.get("height_ratios", {})) == dict(current.get("height_ratios", {}))
                and dict(layout.get("visibility", {})) == dict(current.get("visibility", {}))
            ):
                h._pending_plot_layout = None
                return
        except Exception:
            log.debug("Plot layout update check failed", exc_info=True)
        specs_map = {spec.track_id: spec for spec in h.plot_host.channel_specs()}
        order = None
        height_ratios = None
        visibility = None
        if isinstance(layout, dict):
            order = layout.get("order")
            height_ratios = layout.get("height_ratios", {}) or {}
            visibility = layout.get("visibility")
        else:
            order = getattr(layout, "order", None)
            height_ratios = getattr(layout, "height_ratios", {}) or {}
            visibility = getattr(layout, "visibility", None)
        if not order:
            order = list(specs_map.keys())
        if height_ratios is None:
            height_ratios = {}
        new_specs: list[ChannelTrackSpec] = []
        added_ids: set[str] = set()
        for track_id in order:
            spec = specs_map.get(track_id)
            if not spec:
                continue
            ratio = float(height_ratios.get(track_id, spec.height_ratio))
            new_specs.append(
                ChannelTrackSpec(
                    track_id=spec.track_id,
                    component=spec.component,
                    label=spec.label,
                    height_ratio=ratio,
                )
            )
            added_ids.add(track_id)
        for track_id, spec in specs_map.items():
            if track_id in added_ids:
                continue
            new_specs.append(
                ChannelTrackSpec(
                    track_id=spec.track_id,
                    component=spec.component,
                    label=spec.label,
                    height_ratio=spec.height_ratio,
                )
            )
        if new_specs:
            h.plot_host.ensure_channels(new_specs)
        if visibility and isinstance(visibility, Mapping):
            for track_id, visible in visibility.items():
                applied = False
                with contextlib.suppress(Exception):
                    h.plot_host.set_channel_visible(track_id, bool(visible))
                    applied = True
                if applied:
                    continue
                if hasattr(h.plot_host, "track"):
                    track = None
                    with contextlib.suppress(Exception):
                        track = h.plot_host.track(track_id)
                    if track is not None:
                        with contextlib.suppress(Exception):
                            track.set_visible(bool(visible))
            h._sync_track_visibility_from_host()
        h._pending_plot_layout = None

    def _apply_button_style(button: QPushButton) -> None:
        h = self._host
        button.style().unpolish(button)
        button.style().polish(button)

    def _prepare_trace_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        h = self._host
        trace = df.copy()
        if "Time (s)" in trace.columns:
            trace["Time (s)"] = pd.to_numeric(trace["Time (s)"], errors="coerce")

        if "Inner Diameter" in trace.columns:
            trace["Inner Diameter"] = pd.to_numeric(trace["Inner Diameter"], errors="coerce")
            inner_raw_name = "Inner Diameter (raw)"
            inner_clean_name = "Inner Diameter (clean)"
            inner_values = trace["Inner Diameter"].to_numpy(dtype=float, copy=True)

            if inner_raw_name in trace.columns:
                trace[inner_raw_name] = pd.to_numeric(trace[inner_raw_name], errors="coerce")
            else:
                insert_at = trace.columns.get_loc("Inner Diameter") + 1
                trace.insert(insert_at, inner_raw_name, inner_values.copy())

            if inner_clean_name in trace.columns:
                trace[inner_clean_name] = pd.to_numeric(trace[inner_clean_name], errors="coerce")
            else:
                insert_at = (
                    trace.columns.get_loc(inner_raw_name) + 1
                    if inner_raw_name in trace.columns
                    else trace.columns.get_loc("Inner Diameter") + 1
                )
                trace.insert(insert_at, inner_clean_name, inner_values.copy())
        if "Outer Diameter" in trace.columns:
            trace["Outer Diameter"] = pd.to_numeric(trace["Outer Diameter"], errors="coerce")
            outer_raw_name = "Outer Diameter (raw)"
            outer_clean_name = "Outer Diameter (clean)"
            outer_values = trace["Outer Diameter"].to_numpy(dtype=float, copy=True)

            if outer_raw_name in trace.columns:
                trace[outer_raw_name] = pd.to_numeric(trace[outer_raw_name], errors="coerce")
            else:
                insert_at = trace.columns.get_loc("Outer Diameter") + 1
                trace.insert(insert_at, outer_raw_name, outer_values.copy())

            if outer_clean_name in trace.columns:
                trace[outer_clean_name] = pd.to_numeric(trace[outer_clean_name], errors="coerce")
            else:
                insert_at = (
                    trace.columns.get_loc(outer_raw_name) + 1
                    if outer_raw_name in trace.columns
                    else trace.columns.get_loc("Outer Diameter") + 1
                )
                trace.insert(insert_at, outer_clean_name, outer_values.copy())

        trace.attrs.setdefault("edit_log", [])
        return trace

    def _update_trace_sync_state(self) -> None:
        """Cache canonical trace time + frame mappings for sync."""
        h = self._host

        h.trace_time = None
        h.frame_numbers = None
        h.frame_number_to_trace_idx = {}
        h.tiff_page_to_trace_idx = {}
        h.tiff_page_times = []
        h.tiff_page_times_valid = False
        h.snapshot_interval_median = None
        h.frame_trace_time = None
        h.frame_trace_index = None
        h.trace_time_exact = None
        h.frame_times = []

        if h.trace_data is None:
            return

        if "Time (s)" in h.trace_data.columns:
            with contextlib.suppress(Exception):
                h.trace_time = h.trace_data["Time (s)"].to_numpy(dtype=float)
        if "Time_s_exact" in h.trace_data.columns:
            with contextlib.suppress(Exception):
                h.trace_time_exact = h.trace_data["Time_s_exact"].to_numpy(dtype=float)

        if "FrameNumber" in h.trace_data.columns:
            try:
                series = pd.to_numeric(h.trace_data["FrameNumber"], errors="coerce")
                h.frame_numbers = series.to_numpy()
                h.frame_number_to_trace_idx = {
                    int(fn): int(i) for i, fn in enumerate(h.frame_numbers) if pd.notna(fn)
                }
            except Exception:
                log.debug("Unable to build frame→trace mapping", exc_info=True)
        if "TiffPage" in h.trace_data.columns:
            try:
                tiff_series = pd.to_numeric(h.trace_data["TiffPage"], errors="coerce")
                if "Saved" in h.trace_data.columns:
                    saved_mask = (
                        pd.to_numeric(h.trace_data["Saved"], errors="coerce")
                        .fillna(0)
                        .to_numpy()
                        > 0
                    )
                    tiff_series = tiff_series.where(saved_mask)
                h.tiff_page_to_trace_idx = {
                    int(tp): int(i) for i, tp in enumerate(tiff_series.to_numpy()) if pd.notna(tp)
                }
            except Exception:
                log.debug("Unable to build TIFF page→trace mapping", exc_info=True)

        h._refresh_tiff_page_times()

    def _refresh_tiff_page_times(self, *, expected_page_count: int | None = None) -> None:
        """Derive canonical TIFF page times from trace data when available."""
        h = self._host

        h.tiff_page_times = []
        h.tiff_page_times_valid = False
        h.snapshot_interval_median = None

        if h.trace_data is None:
            return

        sample = getattr(h, "current_sample", None)
        page_count_hint = expected_page_count
        if page_count_hint is None and h.snapshot_total_frames:
            page_count_hint = int(h.snapshot_total_frames)
        result = derive_tiff_page_times(h.trace_data, expected_page_count=page_count_hint)
        h.tiff_page_times = result.tiff_page_times
        h.tiff_page_times_valid = bool(result.valid)
        h.snapshot_interval_median = result.median_interval_s

        if not result.tiff_page_times and sample is not None:
            meta = dict(sample.import_metadata or {})
            timebase_block = dict(meta.get("timebase") or {})
            tiff_block = dict(timebase_block.get("tiff") or {})
            stored_times = tiff_block.get("tiff_page_times")
            if isinstance(stored_times, list) and stored_times:
                h.tiff_page_times = stored_times
                h.tiff_page_times_valid = bool(tiff_block.get("tiff_page_times_valid", False))
                stored_median = tiff_block.get("snapshot_interval_median_s")
                if stored_median is not None:
                    h.snapshot_interval_median = float(stored_median)

        warning_key = None
        if page_count_hint is not None and result.warnings:
            warning_key = (
                tuple(result.warnings),
                result.page_count,
                result.time_column,
            )
        if warning_key and warning_key != h._last_tiff_page_time_warning_key:
            for warning in result.warnings:
                log.warning("TIFF page time mapping: %s", warning)
            h._last_tiff_page_time_warning_key = warning_key
        elif page_count_hint is not None and not result.warnings:
            h._last_tiff_page_time_warning_key = None

        h._update_snapshot_sync_toggle()

        if sample is None:
            return

        meta = dict(sample.import_metadata or {})
        timebase_block = dict(meta.get("timebase") or {})
        tiff_block = dict(timebase_block.get("tiff") or {})
        if result.tiff_page_times:
            tiff_block["tiff_page_times"] = result.tiff_page_times
            tiff_block["tiff_page_times_valid"] = bool(result.valid)
            tiff_block["tiff_page_time_warnings"] = list(result.warnings)
            tiff_block["snapshot_interval_median_s"] = (
                float(result.median_interval_s) if result.median_interval_s is not None else None
            )
            tiff_block["tiff_page_time_column"] = result.time_column
        elif "tiff_page_times" not in tiff_block:
            tiff_block["tiff_page_times"] = None
        timebase_block["tiff"] = tiff_block
        meta["timebase"] = timebase_block
        sample.import_metadata = meta

    def _sync_trace_dataframe_from_model(self) -> None:
        h = self._host
        if h.trace_data is None or h.trace_model is None:
            return

        inner_clean = h.trace_model.inner_full.copy()
        inner_raw = h.trace_model.inner_raw.copy()
        h.trace_data.loc[:, "Inner Diameter"] = inner_clean
        if "Inner Diameter (clean)" in h.trace_data.columns:
            h.trace_data.loc[:, "Inner Diameter (clean)"] = inner_clean
        if "Inner Diameter (raw)" in h.trace_data.columns:
            h.trace_data.loc[:, "Inner Diameter (raw)"] = inner_raw
        else:
            h.trace_data["Inner Diameter (raw)"] = inner_raw

        if h.trace_model.outer_full is not None and "Outer Diameter" in h.trace_data.columns:
            outer_clean = h.trace_model.outer_full.copy()
            h.trace_data.loc[:, "Outer Diameter"] = outer_clean
            if "Outer Diameter (clean)" in h.trace_data.columns:
                h.trace_data.loc[:, "Outer Diameter (clean)"] = outer_clean
            if h.trace_model.outer_raw is not None:
                if "Outer Diameter (raw)" in h.trace_data.columns:
                    h.trace_data.loc[:, "Outer Diameter (raw)"] = (
                        h.trace_model.outer_raw.copy()
                    )
                else:
                    h.trace_data["Outer Diameter (raw)"] = h.trace_model.outer_raw.copy()

        serialized_log = serialize_edit_log(h.trace_model.edit_log)
        h.trace_data.attrs["edit_log"] = serialized_log

        if h.current_sample is not None:
            h.current_sample.edit_history = serialized_log
            h.current_sample.change_log = h._change_log.serialize()
            synchronized = h.trace_data.copy()
            synchronized.attrs = dict(h.trace_data.attrs)
            h.current_sample.trace_data = synchronized

    def _refresh_views_after_edit(self) -> None:
        h = self._host
        if h.trace_model is None:
            return
        current_window: tuple[float, float] | None = None
        if hasattr(h, "plot_host") and h.plot_host is not None:
            current_window = h.plot_host.current_window()
        if current_window is None:
            current_window = h.trace_model.full_range

        h.trace_model.clear_cache()
        if h.plot_host is not None:
            h.plot_host.set_trace_model(h.trace_model)
            if current_window is not None:
                h.plot_host.set_time_window(*current_window)
        if h.zoom_dock:
            h.zoom_dock.set_trace_model(h.trace_model)
        if h.scope_dock:
            h.scope_dock.set_trace_model(h.trace_model)
        if hasattr(h, "_refresh_zoom_window"):
            with contextlib.suppress(Exception):
                h._refresh_zoom_window()
        h._update_trace_controls_state()
        if hasattr(h, "canvas"):
            with contextlib.suppress(Exception):
                h.canvas.draw_idle()

    def _channel_has_data_in_window(self, channel: str, window: tuple[float, float]) -> bool:
        """Return True if the channel has any samples inside the window."""
        h = self._host
        if h.trace_model is None:
            return False
        time_full = getattr(h.trace_model, "time_full", None)
        if time_full is None:
            return False

        series = None
        channel_key = str(channel).strip().lower()
        if channel_key == "inner":
            series = getattr(h.trace_model, "inner_full", None)
        elif channel_key == "outer":
            series = getattr(h.trace_model, "outer_full", None)
        if series is None:
            return False

        x0, x1 = float(window[0]), float(window[1])
        xmin, xmax = (x0, x1) if x0 <= x1 else (x1, x0)
        mask = (time_full >= xmin) & (time_full <= xmax)
        if not np.any(mask):
            return False

        window_values = series[mask]
        return bool(np.any(np.isfinite(window_values)))

    def _set_plot_cursor_for_mode(self, mode: str) -> None:
        h = self._host
        target = None
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "widget"):
            with contextlib.suppress(Exception):
                target = plot_host.widget()
        if target is None:
            target = getattr(h, "canvas", None)
        if target is None:
            return
        cursor = Qt.CursorShape.OpenHandCursor if mode == "pan" else Qt.CursorShape.CrossCursor
        with contextlib.suppress(Exception):
            target.setCursor(QCursor(cursor))

    def _sync_autoscale_y_action_from_host(self) -> None:
        """Align the Y-autoscale toggle with the current renderer state."""
        h = self._host
        act = getattr(h, "actAutoscaleY", None)
        if act is None:
            return
        plot_host = getattr(h, "plot_host", None)
        enabled = False
        if plot_host is not None and hasattr(plot_host, "is_autoscale_y_enabled"):
            with contextlib.suppress(Exception):
                enabled = bool(plot_host.is_autoscale_y_enabled())
        act.blockSignals(True)
        act.setChecked(enabled)
        act.blockSignals(False)

    def _sync_grid_action(self) -> None:
        h = self._host
        if h.actGrid is None:
            return
        desired = bool(h.grid_visible)
        if h.actGrid.isChecked() != desired:
            h.actGrid.blockSignals(True)
            h.actGrid.setChecked(desired)
            h.actGrid.blockSignals(False)

    def _update_trace_controls_state(self) -> None:
        h = self._host
        has_trace = (
            h.trace_data is not None and getattr(h.trace_data, "empty", False) is False
        )
        if h.id_toggle_act is not None:
            h.id_toggle_act.setEnabled(has_trace)
        has_outer = bool(
            has_trace
            and h.trace_data is not None
            and "Outer Diameter" in h.trace_data.columns
        )
        if h.od_toggle_act is not None:
            h.od_toggle_act.setEnabled(has_outer)
            if not has_outer and h.od_toggle_act.isChecked():
                h.od_toggle_act.blockSignals(True)
                h.od_toggle_act.setChecked(False)
                h.od_toggle_act.blockSignals(False)
        has_avg = has_trace and self._avg_pressure_channel_available()
        if h.avg_pressure_toggle_act is not None:
            h.avg_pressure_toggle_act.setEnabled(has_avg)
            if not has_avg and h.avg_pressure_toggle_act.isChecked():
                h.avg_pressure_toggle_act.blockSignals(True)
                h.avg_pressure_toggle_act.setChecked(False)
                h.avg_pressure_toggle_act.blockSignals(False)
        has_set = has_trace and self._set_pressure_channel_available()
        if h.set_pressure_toggle_act is not None:
            h.set_pressure_toggle_act.setEnabled(has_set)
            if not has_set and h.set_pressure_toggle_act.isChecked():
                h.set_pressure_toggle_act.blockSignals(True)
                h.set_pressure_toggle_act.setChecked(False)
                h.set_pressure_toggle_act.blockSignals(False)
        if getattr(h, "actEditPoints", None) is not None:
            h.actEditPoints.setEnabled(has_trace)

    def _sync_track_visibility_from_host(self) -> None:
        """Align toolbar actions with PyQtGraph host visibility state."""
        h = self._host

        host = getattr(h, "plot_host", None)
        if host is None:
            return
        with contextlib.suppress(Exception):
            backend = host.get_render_backend()
        if host is None or backend != "pyqtgraph":
            return

        mapping = {
            "inner": getattr(h, "id_toggle_act", None),
            "outer": getattr(h, "od_toggle_act", None),
            "avg_pressure": getattr(h, "avg_pressure_toggle_act", None),
            "set_pressure": getattr(h, "set_pressure_toggle_act", None),
        }

        for key, action in mapping.items():
            if action is None:
                continue
            desired = host.is_channel_visible(key)
            if action.isChecked() != desired:
                action.blockSignals(True)
                action.setChecked(desired)
                action.blockSignals(False)

        h._update_trace_controls_state()

    def update_slider_marker(self):
        h = self._host
        # Make sure we have a trace and some TIFF frames
        if h.trace_data is None or not h.snapshot_frames:
            return
        if h.slider is None:
            return

        # 1) Get the current slider index
        idx = h.slider.value()

        # 2) Lookup the timestamp for this frame
        t_current = None
        if h.frame_trace_index is not None and idx < len(h.frame_trace_index):
            trace_idx = int(h.frame_trace_index[idx])
            if h.trace_time is not None and trace_idx < len(h.trace_time):
                t_current = float(h.trace_time[trace_idx])
            elif h.trace_data is not None:
                with contextlib.suppress(Exception):
                    t_current = float(h.trace_data["Time (s)"].iat[trace_idx])
        elif h.frame_trace_time is not None and idx < len(h.frame_trace_time):
            t_current = float(h.frame_trace_time[idx])
        elif idx < len(h.frame_times):
            t_current = float(h.frame_times[idx])
        elif h.recording_interval:
            t_current = idx * h.recording_interval

        if t_current is None:
            return

        # 3) Drive the shared time cursor overlay (fallback on legacy per-axis markers)
        h._time_cursor_time = float(t_current)
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None:
            try:
                plot_host.set_time_cursor(
                    h._time_cursor_time,
                    visible=h._time_cursor_visible,
                )
                h._on_view_state_changed(reason="time cursor moved")
                return
            except Exception:
                log.debug(
                    "PlotHost time cursor update failed; falling back to legacy markers",
                    exc_info=True,
                )

        axes = [h.ax] if getattr(h, "ax", None) is not None else []
        if not axes:
            return
        for ax in axes:
            line = h.slider_markers.get(ax)
            if line is None or line.axes is None:
                line = ax.axvline(
                    x=t_current,
                    color="red",
                    linestyle="--",
                    linewidth=1.5,
                    label="TIFF Frame",
                    zorder=5,
                )
                h.slider_markers[ax] = line
            else:
                line.set_xdata([t_current, t_current])
        h.canvas.draw_idle()
        h._on_view_state_changed(reason="time cursor moved")

    def _init_hover_artists(self) -> None:
        """Create per-axis hover annotations and crosshair lines."""
        h = self._host

        for line in getattr(h, "_hover_vlines", []) or []:
            if line is None:
                continue
            with contextlib.suppress(Exception):
                line.remove()
        h._hover_vlines = []
        h._hover_vline_inner = None
        h._hover_vline_outer = None

        for annot in (
            getattr(h, "hover_annotation_id", None),
            getattr(h, "hover_annotation_od", None),
        ):
            if annot is None:
                continue
            with contextlib.suppress(Exception):
                annot.remove()

        # Check if we're using PyQtGraph renderer
        plot_host = getattr(h, "plot_host", None)
        is_pyqtgraph = plot_host is not None and plot_host.get_render_backend() == "pyqtgraph"

        # PyQtGraph doesn't support matplotlib-style annotations
        # For now, disable hover annotations when using PyQtGraph
        # TODO: Implement PyQtGraph-specific hover feedback using TextItem
        # NOTE: This hover/pin path is Matplotlib-only; Phase 3 should replace
        # it with a PyQtGraph-native implementation or remove the legacy branch.
        if is_pyqtgraph:
            h.hover_annotation_id = None
            h.hover_annotation_od = None
            return

        # Matplotlib-specific hover annotations
        line_color = CURRENT_THEME.get("cursor_line", CURRENT_THEME.get("grid_color", "#6e7687"))

        def _make_annotation(target_ax):
            return target_ax.annotate(
                text="",
                xy=(0.0, 0.0),
                xytext=(10, 10),
                textcoords="offset points",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    fc=css_rgba_to_mpl(CURRENT_THEME["hover_label_bg"]),
                    ec=CURRENT_THEME["hover_label_border"],
                    lw=1,
                ),
                arrowprops=dict(arrowstyle="->"),
                fontsize=9,
                color=CURRENT_THEME["text"],
            )

        h.hover_annotation_id = None
        h.hover_annotation_od = None

        if h.ax is not None:
            h.hover_annotation_id = _make_annotation(h.ax)
            h.hover_annotation_id.set_visible(False)
            vline = h.ax.axvline(np.nan, color=line_color, linewidth=0.9, alpha=0.7)
            vline.set_visible(False)
            vline.set_zorder(55)
            h._hover_vline_inner = vline
            h._hover_vlines.append(vline)

        if h.ax2 is not None:
            h.hover_annotation_od = _make_annotation(h.ax2)
            h.hover_annotation_od.set_visible(False)
            vline = h.ax2.axvline(np.nan, color=line_color, linewidth=0.9, alpha=0.7)
            vline.set_visible(False)
            vline.set_zorder(55)
            h._hover_vline_outer = vline
            h._hover_vlines.append(vline)
        else:
            h.hover_annotation_od = None

    def _hide_hover_feedback(self) -> None:
        """Hide hover annotations and crosshair lines."""
        h = self._host

        changed = False
        for annot in (
            getattr(h, "hover_annotation_id", None),
            getattr(h, "hover_annotation_od", None),
        ):
            if annot is not None and annot.get_visible():
                annot.set_visible(False)
                changed = True
        for line in getattr(h, "_hover_vlines", []) or []:
            if line is not None and line.get_visible():
                line.set_visible(False)
                changed = True
        if changed:
            h.canvas.draw_idle()

    def _reset_time_scrollbar_to_start(self) -> None:
        h = self._host
        slider = h.scroll_slider
        if slider is None:
            return
        h.update_scroll_slider()
        h._updating_time_scrollbar = True
        blocker = QSignalBlocker(slider)
        try:
            slider.setValue(slider.minimum())
        finally:
            h._updating_time_scrollbar = False
            del blocker

    def _force_trace_start_view(self, window: tuple[float, float]) -> None:
        h = self._host
        if window is None:
            return
        t0, t1 = float(window[0]), float(window[1])
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_time_window"):
            h._set_xrange_source("load.start", (t0, t1))
            plot_host.set_time_window(t0, t1)
            if hasattr(plot_host, "force_primary_xrange"):
                plot_host.force_primary_xrange()
        elif plot_host is not None and hasattr(plot_host, "force_primary_xrange"):
            h._set_xrange_source("load.start", (t0, t1))
            try:
                plot_host.force_primary_xrange()
            except TypeError:
                plot_host.force_primary_xrange(t0, t1)
        elif h.ax is not None:
            h.ax.set_xlim(t0, t1)
            h.canvas.draw_idle()
        h._last_x_window_width_s = float(t1 - t0)
        h._reset_time_scrollbar_to_start()

    def update_plot(self, track_limits: bool = True):
        h = self._host
        t0 = time.perf_counter()
        try:
            if h.trace_data is None:
                return

            has_outer = (
                "Outer Diameter" in h.trace_data.columns
                and not h.trace_data["Outer Diameter"].isna().all()
            )

            inner_requested = (
                h.id_toggle_act.isChecked() if h.id_toggle_act is not None else True
            )
            outer_requested = (
                h.od_toggle_act.isChecked() if h.od_toggle_act is not None else False
            )
            inner_visible, outer_visible = h._ensure_valid_channel_selection(
                inner_requested,
                outer_requested,
                toggled="inner",
                outer_supported=has_outer,
            )

            h._apply_toggle_state(inner_visible, outer_visible, outer_supported=has_outer)
            h._update_trace_controls_state()
            h._rebuild_channel_layout(inner_visible, outer_visible, redraw=False)
            h._apply_pending_plot_layout()

            inner_track = h.plot_host.track("inner") if inner_visible else None
            outer_track = h.plot_host.track("outer") if outer_visible else None
            primary_track = inner_track or outer_track
            if primary_track is None:
                log.error("No channels available after layout rebuild")
                return

            h.ax = primary_track.ax
            h.ax2 = outer_track.ax if inner_track and outer_track else None
            h._bind_primary_axis_callbacks()
            h._init_hover_artists()

            h.event_text_objects = []
            sample = getattr(h, "current_sample", None)
            dataset_id = getattr(sample, "dataset_id", None)
            cached_window = None
            if dataset_id is not None:
                cached_window = h._window_cache.get(dataset_id)
            prev_window = cached_window or h.plot_host.current_window()
            try:
                h.trace_model = h._get_trace_model_for_sample(h.current_sample)
            except Exception:
                log.exception("Failed to build trace model from dataframe")
                return

            h.plot_host.set_trace_model(h.trace_model)
            if h.zoom_dock:
                h.zoom_dock.set_trace_model(h.trace_model)
            if h.scope_dock:
                h.scope_dock.set_trace_model(h.trace_model)
            initial_window = None
            if track_limits or prev_window is None:
                # Default initial view: first slice of the recording (start-aligned).
                initial_window = h._initial_time_window()
                if initial_window is not None:
                    target_window = initial_window
                    full_range = h.trace_model.full_range
                    from vasoanalyzer.ui.main_window import DEFAULT_INITIAL_VIEW_SECONDS
                    if full_range[1] - full_range[0] > DEFAULT_INITIAL_VIEW_SECONDS:
                        log.info(
                            "Initial load: showing first %.0f seconds of %.0f second trace",
                            DEFAULT_INITIAL_VIEW_SECONDS,
                            full_range[1] - full_range[0],
                        )
                else:
                    target_window = h.trace_model.full_range
            else:
                target_window = prev_window
            h.plot_host.set_time_window(*target_window)
            h._last_x_window_width_s = float(target_window[1] - target_window[0])
            # NOTE: Removed redundant autoscale_all() call here - set_time_window() already
            # performs autoscaling internally via _apply_window(). Calling autoscale_all()
            # again causes double rendering of all tracks, which is especially slow for
            # datasets with multiple pressure channels (4 tracks × 2 = 8 expensive updates).
            # This was causing 9+ second load times for multi-track datasets.
            # if track_limits and prev_window is None:
            #     h.plot_host.autoscale_all()
            h.trace_line = None
            h.inner_line = None
            if inner_track is not None:
                h.trace_line = inner_track.primary_line
                h.inner_line = h.trace_line
                if h.trace_line is not None:
                    h.trace_line.set_visible(inner_visible)

            if outer_track is not None:
                h.od_line = outer_track.primary_line
                h.outer_line = h.od_line
                if h.od_line is not None:
                    h.od_line.set_visible(outer_visible)
                if h.trace_line is None:
                    h.trace_line = h.od_line
            else:
                h.od_line = None
                h.outer_line = None

            for axis in h.plot_host.axes():
                if h.grid_visible:
                    axis.grid(True, color=CURRENT_THEME["grid_color"])
                else:
                    axis.grid(False)

            time_full = h.trace_model.time_full
            if time_full.size:
                h.xlim_full = (float(time_full[0]), float(time_full[-1]))
            inner_full = h.trace_model.inner_full
            if inner_full.size:
                inner_min = float(np.nanmin(inner_full))
                inner_max = float(np.nanmax(inner_full))
                h.ylim_full = (inner_min, inner_max)

            # Plot events if available
            if h.event_labels and h.event_times:
                h._ensure_event_meta_length(len(h.event_labels))
                h.plot_host.set_events(
                    h.event_times,
                    labels=h.event_labels,
                    label_meta=h.event_label_meta,
                )
                # Enable event label rendering for matplotlib; PyQtGraph defaults to off.
                if not h._plot_host_is_pyqtgraph():
                    h.plot_host.set_event_labels_visible(True)
                annotations = h.event_annotations or []
                h._annotation_lane_visible = True
                h.plot_host.set_annotation_entries(annotations)
                h._refresh_event_annotation_artists()
            else:
                h.plot_host.set_events([], labels=[], label_meta=[])
                # Disable event label rendering when no events
                h.plot_host.set_event_labels_visible(False)
                h.event_table_data = []
                h.event_metadata = []
                h.event_text_objects = []
                h.event_annotations = []
                h.event_label_meta = []
                h._annotation_lane_visible = True
                h.plot_host.set_annotation_entries([])
                h._refresh_event_annotation_artists()

            h._update_trace_controls_state()
            h._refresh_plot_legend()
            h.canvas.setToolTip("")

            # Apply plot style (defaults on first load) - defer draw to avoid redundant redraws
            h.apply_plot_style(h.get_current_plot_style(), persist=False, draw=False)
            h._apply_pending_pyqtgraph_track_state()
            h._refresh_trace_navigation_data()
            h.canvas.draw_idle()

            if initial_window is not None:
                h._force_trace_start_view(initial_window)
            h._refresh_zoom_window()

            # Cache the current window for this dataset to avoid re-autoscaling on next load
            sample = getattr(h, "current_sample", None)
            dsid = getattr(sample, "dataset_id", None)
            if dsid is not None:
                window = h.plot_host.current_window() if hasattr(h, "plot_host") else None
                if window is not None:
                    h._window_cache[dsid] = window

            # Force the shared X-axis to be visible even on initial load (pyqtgraph)
            plot_host = getattr(h, "plot_host", None)
            if plot_host is not None:
                try:
                    updater = getattr(plot_host, "_update_bottom_axis_assignments", None)
                    if callable(updater):
                        updater()
                    bottom_axis = getattr(plot_host, "bottom_axis", lambda: None)()
                    if bottom_axis is not None:
                        with contextlib.suppress(Exception):
                            bottom_axis.setVisible(True)
                            bottom_axis.setStyle(showValues=True, tickLength=5)
                            bottom_axis.setLabel(h._shared_xlabel or "Time (s)")
                            bottom_axis.showLabel(True)
                except Exception:
                    log.debug("Failed to force bottom axis visibility", exc_info=True)

        finally:
            log.debug("update_plot completed in %.3f s", time.perf_counter() - t0)

    def _refresh_plot_legend(self):
        h = self._host
        if not hasattr(h, "ax"):
            return

        legend = getattr(h, "plot_legend", None)
        if legend is not None:
            with contextlib.suppress(Exception):
                legend.remove()
        h.plot_legend = None

    def apply_legend_settings(self, settings=None, *, mark_dirty: bool = False) -> None:
        """Merge ``settings`` into the current legend options and refresh."""
        h = self._host

        from vasoanalyzer.ui.main_window import DEFAULT_LEGEND_SETTINGS, LEGEND_LABEL_DEFAULTS, _copy_legend_settings
        merged = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)

        if isinstance(h.legend_settings, dict):
            existing = _copy_legend_settings(h.legend_settings)
            labels = existing.pop("labels", {}) or {}
            merged.update(existing)
            merged["labels"] = labels

        if isinstance(settings, dict):
            incoming = settings.copy()
            labels_incoming = incoming.pop("labels", {}) or {}
            merged.update(incoming)
            merged.setdefault("labels", {})
            merged["labels"].update(labels_incoming)

        h.legend_settings = merged
        h._refresh_plot_legend()
        if mark_dirty:
            h.mark_session_dirty()

    def open_legend_settings_dialog(self):
        """Display the legend settings dialog and apply changes on accept."""
        h = self._host

        current_settings = copy.deepcopy(h.legend_settings)
        labels_defaults = {}
        if getattr(h, "trace_line", None) is not None:
            labels_defaults["inner"] = LEGEND_LABEL_DEFAULTS.get("inner", "Inner")
        if getattr(h, "od_line", None) is not None:
            labels_defaults["outer"] = LEGEND_LABEL_DEFAULTS.get("outer", "Outer")

        labels_current = {}
        stored_labels = (current_settings.get("labels") or {}) if current_settings else {}
        for key, default_value in labels_defaults.items():
            value = stored_labels.get(key, default_value)
            labels_current[key] = value

        dialog = LegendSettingsDialog(
            h,
            settings=current_settings,
            labels=labels_current,
            defaults=labels_defaults,
        )

        if dialog.exec():
            h.apply_legend_settings(dialog.get_settings(), mark_dirty=True)

    def _on_trace_nav_window_requested(self, x0: float, x1: float) -> None:
        h = self._host
        h._apply_time_window((x0, x1))
        h.mark_session_dirty(reason="view range changed")

    def _trace_full_range(self) -> tuple[float, float] | None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "full_range"):
            with contextlib.suppress(Exception):
                full = plot_host.full_range()
                if full is not None:
                    return float(full[0]), float(full[1])
        if h.trace_model is not None:
            try:
                return h.trace_model.full_range
            except Exception:
                log.debug("Failed to get trace model full range", exc_info=True)
        if h.trace_data is not None and "Time (s)" in h.trace_data.columns:
            series = h.trace_data["Time (s)"]
            with contextlib.suppress(Exception):
                return float(series.min()), float(series.max())
        return None

    def _set_trace_navigation_visible(self, visible: bool) -> None:
        h = self._host
        h._trace_navigation_available = bool(visible)
        h._apply_overview_strip_visibility()
        nav_bar = getattr(h, "trace_nav_bar", None)
        if nav_bar is not None:
            nav_bar.setVisible(bool(visible))
            nav_bar.setEnabled(bool(visible))

    def _apply_overview_strip_visibility(self) -> None:
        h = self._host
        overview = getattr(h, "overview_strip", None)
        if overview is None:
            return
        is_available = bool(getattr(h, "_trace_navigation_available", False))
        overview_visible = is_available and bool(h._overview_strip_enabled)
        overview.setVisible(overview_visible)
        overview.setEnabled(overview_visible)

    def toggle_overview_strip(self, checked: bool) -> None:
        h = self._host
        h._overview_strip_enabled = bool(checked)
        h._apply_overview_strip_visibility()

    def _refresh_trace_navigation_data(self) -> None:
        h = self._host
        overview = getattr(h, "overview_strip", None)
        if overview is None:
            return

        full_range = h._trace_full_range()
        if h.trace_model is None or full_range is None:
            overview.clear()
            h._set_trace_navigation_visible(False)
            return

        overview.set_trace_model(h.trace_model)
        overview.set_full_range(*full_range)
        plot_host = getattr(h, "plot_host", None)
        window = plot_host.current_window() if plot_host is not None else None
        if window is not None:
            overview.set_time_window(window[0], window[1])
        h._refresh_overview_events()
        h._set_trace_navigation_visible(True)

    def _plot_host_is_pyqtgraph(self) -> bool:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        is_pg = bool(plot_host is not None and plot_host.get_render_backend() == "pyqtgraph")
        if (
            not is_pg
            and hasattr(h, "action_select_range")
            and h.action_select_range is not None
        ):
            with contextlib.suppress(Exception):
                h.action_select_range.blockSignals(True)
                h.action_select_range.setChecked(False)
                h.action_select_range.blockSignals(False)
        return is_pg

    def _attach_plot_host_window_listener(self) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "add_time_window_listener"):
            return
        listener = getattr(h, "_plot_host_window_listener", None)
        if listener is not None and hasattr(plot_host, "remove_time_window_listener"):
            plot_host.remove_time_window_listener(listener)
        h._plot_host_window_listener = h._on_plot_host_time_window_changed
        plot_host.add_time_window_listener(h._plot_host_window_listener)
        if (
            os.getenv("VASO_DEBUG_XRANGE") == "1"
            and hasattr(plot_host, "attach_xrange_debug")
            and not getattr(h, "_xrange_debug_attached", False)
        ):
            attached = plot_host.attach_xrange_debug(
                lambda: (
                    h._xrange_source,
                    h._xrange_expected,
                    bool(getattr(h, "_scrolling_from_scrollbar", False)),
                ),
                set_source_callable=h._set_xrange_source,
            )
            if attached:
                h._xrange_debug_attached = True

    def _on_plot_host_time_window_changed(self, x0: float, x1: float) -> None:
        h = self._host
        if getattr(h, "_syncing_time_window", False):
            return
        if os.getenv("VASO_DEBUG_XRANGE") == "1" and not getattr(
            self, "_xrange_debug_attached", False
        ):
            plot_host = getattr(h, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "attach_xrange_debug"):
                attached = plot_host.attach_xrange_debug(
                    lambda: (
                        h._xrange_source,
                        h._xrange_expected,
                        bool(getattr(h, "_scrolling_from_scrollbar", False)),
                    ),
                    set_source_callable=h._set_xrange_source,
                )
                if attached:
                    h._xrange_debug_attached = True
        h._update_last_x_window_width(x0, x1)
        try:
            h.update_scroll_slider()
        except Exception:
            log.exception("Failed to synchronize time scrollbar with plot window")
        overview = getattr(h, "overview_strip", None)
        if overview is not None:
            overview.set_time_window(x0, x1)
        h._invalidate_sample_state_cache()
        plot_host = getattr(h, "plot_host", None)
        is_user_range = bool(
            plot_host
            and hasattr(plot_host, "is_user_range_change_active")
            and plot_host.is_user_range_change_active()
        )
        if is_user_range:
            h.mark_session_dirty(reason="view range changed")

    def _collect_plot_view_state(self) -> dict[str, Any]:
        h = self._host
        state: dict[str, Any] = {}
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and plot_host.get_render_backend() == "pyqtgraph":
            window = plot_host.current_window()
            if window is not None:
                state["axis_xlim"] = [float(window[0]), float(window[1])]
            track_state: dict[str, Any] = {}
            tracks = []
            with contextlib.suppress(Exception):
                tracks = plot_host.tracks()
            for track in tracks or []:
                view = getattr(track, "view", None)
                if view is None:
                    continue
                try:
                    ymin, ymax = view.get_ylim()
                except Exception:
                    continue
                track_state[track.id] = {
                    "ylim": [float(ymin), float(ymax)],
                    "autoscale": view.is_autoscale_enabled(),
                }
            if track_state:
                state["pyqtgraph_track_state"] = track_state
            state["event_text_labels_on_trace"] = bool(plot_host.event_labels_visible())
            return state

        if h.ax is not None:
            state["axis_xlim"] = list(h.ax.get_xlim())
            state["axis_ylim"] = list(h.ax.get_ylim())
        if h.ax2 is not None:
            state["axis_outer_ylim"] = list(h.ax2.get_ylim())
        return state

    def _apply_pyqtgraph_track_state(self, track_state: dict | None) -> None:
        h = self._host
        if not track_state:
            h._pending_pyqtgraph_track_state = None
            return
        plot_host = getattr(h, "plot_host", None)
        if (
            plot_host is None
            or plot_host.get_render_backend() != "pyqtgraph"
            or not hasattr(plot_host, "track")
        ):
            h._pending_pyqtgraph_track_state = track_state
            return

        for track_id, payload in track_state.items():
            track = plot_host.track(track_id)
            if track is None:
                continue
            autoscale = bool(payload.get("autoscale"))
            if autoscale:
                track.view.set_autoscale_y(True)
                with contextlib.suppress(Exception):
                    track.autoscale()
                continue
            ylim = payload.get("ylim")
            if isinstance(ylim, list | tuple) and len(ylim) == 2:
                try:
                    y0 = float(ylim[0])
                    y1 = float(ylim[1])
                except (TypeError, ValueError):
                    continue
                track.set_ylim(y0, y1)
        h._pending_pyqtgraph_track_state = None
        h._sync_autoscale_y_action_from_host()

    def _apply_pending_pyqtgraph_track_state(self) -> None:
        h = self._host
        if h._pending_pyqtgraph_track_state:
            h._apply_pyqtgraph_track_state(h._pending_pyqtgraph_track_state)

    def _sync_time_window_from_axes(self) -> None:
        """Pull the current Matplotlib limits back into PlotHost."""
        h = self._host

        if getattr(h, "_syncing_time_window", False):
            return

        primary_ax = h.plot_host.primary_axis() if hasattr(h, "plot_host") else None
        if primary_ax is None and h.ax is not None:
            primary_ax = h.ax
        if primary_ax is None:
            return

        x0, x1 = primary_ax.get_xlim()
        if hasattr(h, "plot_host"):
            current = h.plot_host.current_window()
            if current is not None:
                tol = max(abs(x1 - x0), 1.0) * 1e-6
                if abs(current[0] - x0) <= tol and abs(current[1] - x1) <= tol:
                    return
        h._apply_time_window((x0, x1))

    def _unbind_primary_axis_callbacks(self) -> None:
        """Detach x-limit callbacks from the current primary axis."""
        h = self._host

        if getattr(h, "_axis_source_axis", None) is None:
            h._axis_xlim_cid = None
            return
        if h._axis_xlim_cid is not None:
            with contextlib.suppress(Exception):
                h._axis_source_axis.callbacks.disconnect(h._axis_xlim_cid)
        h._axis_source_axis = None
        h._axis_xlim_cid = None

    def _bind_primary_axis_callbacks(self) -> None:
        """Attach x-limit callbacks to the current primary axis."""
        h = self._host

        h._unbind_primary_axis_callbacks()
        h._axis_source_axis = h.ax
        if h.ax is None:
            return
        try:
            h._axis_xlim_cid = h.ax.callbacks.connect(
                "xlim_changed", h._handle_axis_xlim_changed
            )
        except Exception:
            h._axis_source_axis = None
            h._axis_xlim_cid = None

    def _handle_axis_xlim_changed(self, ax) -> None:
        h = self._host
        if getattr(h, "_syncing_time_window", False):
            return
        if ax is None:
            return
        xlim = ax.get_xlim()
        h._set_xrange_source("axis_xlim_changed", (float(xlim[0]), float(xlim[1])))
        h._update_last_x_window_width(xlim[0], xlim[1])
        h._apply_time_window(xlim)
        h.update_scroll_slider()
        h._invalidate_sample_state_cache()

    def scroll_plot(self) -> None:
        h = self._host
        if h.scroll_slider is None:
            return
        h.scroll_plot_user(h.scroll_slider.value(), source="valueChanged")

    def scroll_plot_user(self, value: int, *, source: str | None = None) -> None:
        h = self._host
        if h.trace_data is None or h.scroll_slider is None:
            return
        if getattr(h, "_updating_time_scrollbar", False):
            return

        full_range = h._trace_full_range()
        if full_range is None:
            return
        window = h._current_time_window()
        full_t_min, full_t_max = full_range

        width = h._scrollbar_drag_width_s
        if width is None or width <= 0:
            width = h._last_x_window_width_s
        if width is None or width <= 0:
            if window is not None:
                width = window[1] - window[0]
            else:
                width = full_t_max - full_t_min
        if width <= 0:
            return

        max_scroll = max(1, h.scroll_slider.maximum())
        new_left, new_right = window_from_scroll_value(
            value,
            t0=full_t_min,
            t1=full_t_max,
            current_width=width,
            max_value=max_scroll,
        )

        source_label = source or "scrollbar"
        h._set_xrange_source(f"scrollbar.{source_label}", (new_left, new_right))
        h._apply_time_window((new_left, new_right))
        h.mark_session_dirty(reason="view range changed")

    def update_hover_label(self, event):
        h = self._host
        valid_axes = [ax for ax in (h.ax, h.ax2) if ax is not None]
        if event.inaxes not in valid_axes or h.trace_data is None or event.xdata is None:
            h._last_hover_time = None
            h.canvas.setToolTip("")
            h._hide_hover_feedback()
            return

        times = h.trace_data["Time (s)"].to_numpy()
        if times.size == 0:
            h._hide_hover_feedback()
            return

        xdata = float(event.xdata)
        idx = int(np.clip(np.searchsorted(times, xdata), 0, len(times) - 1))
        time_val = float(times[idx])
        h._last_hover_time = time_val

        tooltip_shown = False
        if getattr(h, "event_metadata", None):
            x_low, x_high = h.ax.get_xlim() if h.ax is not None else (0.0, 0.0)
            tolerance = max((x_high - x_low) * 0.004, 0.05)
            for meta in h.event_metadata:
                if abs(time_val - meta["time"]) <= tolerance:
                    h.canvas.setToolTip(meta["tooltip"])
                    tooltip_shown = True
                    break
        if not tooltip_shown:
            h.canvas.setToolTip("")

        column = "Inner Diameter"
        label = "ID"
        annot = h.hover_annotation_id
        if event.inaxes is h.ax2 and "Outer Diameter" in h.trace_data.columns:
            column = "Outer Diameter"
            label = "OD"
            annot = h.hover_annotation_od or h.hover_annotation_id

        values = h.trace_data.get(column)
        value = float(values.to_numpy()[idx]) if values is not None else float("nan")
        value_text = f"{value:.2f} µm" if np.isfinite(value) else "—"

        if annot is not None:
            y_coord = value if np.isfinite(value) else (event.ydata or 0.0)
            annot.xy = (time_val, y_coord)
            annot.set_text(f"t={time_val:.2f} s\n{label}={value_text}")
            annot.set_visible(True)

        other = (
            h.hover_annotation_od
            if annot is h.hover_annotation_id
            else h.hover_annotation_id
        )
        if other is not None and other.get_visible():
            other.set_visible(False)

        for line in getattr(h, "_hover_vlines", []) or []:
            if line is not None:
                line.set_xdata([time_val, time_val])
                line.set_visible(True)

        h.canvas.draw_idle()

    def update_scroll_slider(self):
        h = self._host
        if h.scroll_slider is None:
            return
        if getattr(h, "trace_nav_bar", None) is not None and h._plot_host_is_pyqtgraph():
            h.scroll_slider.hide()
            return
        if getattr(h, "_scrolling_from_scrollbar", False):
            return
        has_trace = (
            h.trace_data is not None and getattr(h.trace_data, "empty", False) is False
        )
        if not has_trace:
            h.scroll_slider.hide()
            return

        full_range = h._trace_full_range()
        window = h._current_time_window()
        if full_range is None or window is None:
            h.scroll_slider.hide()
            return
        full_t_min, full_t_max = full_range
        win_start, win_end = window
        h.window_width = win_end - win_start
        value, page_step = compute_scrollbar_state(
            full_t_min,
            full_t_max,
            win_start,
            win_end,
            scale=TIME_SCROLLBAR_SCALE,
        )

        if os.getenv("VASO_DEBUG_SCROLLBAR") == "1":
            log.debug(
                "[SCROLLBAR SYNC] window=(%s, %s) value=%s page_step=%s",
                win_start,
                win_end,
                value,
                page_step,
            )
        h._updating_time_scrollbar = True
        blocker = QSignalBlocker(h.scroll_slider)
        try:
            h.scroll_slider.setRange(0, TIME_SCROLLBAR_SCALE)
            h.scroll_slider.setPageStep(page_step)
            h.scroll_slider.setSingleStep(max(1, page_step // 10))
            h.scroll_slider.setValue(value)
        finally:
            h._updating_time_scrollbar = False
            del blocker

        h.scroll_slider.setEnabled(full_t_max > full_t_min)
        h.scroll_slider.show()

    def _on_scrollbar_pressed(self) -> None:
        h = self._host
        h._scrolling_from_scrollbar = True
        window = h._current_time_window()
        width = None
        if window is not None:
            width = float(window[1]) - float(window[0])
        if width is None or width <= 0:
            full = h._trace_full_range()
            if full is not None:
                width = float(full[1]) - float(full[0])
        if width is not None and width > 0:
            h._scrollbar_drag_width_s = width
            log.debug("[SCROLLBAR DRAG] drag_width_s=%.6f source=sliderPressed", width)

    def _on_scrollbar_released(self) -> None:
        h = self._host
        h._scrolling_from_scrollbar = False
        if h.scroll_slider is None:
            return
        h.scroll_plot_user(h.scroll_slider.value(), source="sliderReleased")
        h._scrollbar_drag_width_s = None

    def _on_scrollbar_value_changed(self, value: int) -> None:
        h = self._host
        if getattr(h, "_updating_time_scrollbar", False):
            return
        if getattr(h, "_scrolling_from_scrollbar", False):
            return
        h.scroll_plot_user(value, source="valueChanged")

    def _on_scrollbar_moved(self, value: int) -> None:
        h = self._host
        h.scroll_plot_user(value, source="sliderMoved")

    def _get_selected_range_from_plot_host(self) -> tuple[float, float] | None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if (
            plot_host is None
            or not hasattr(plot_host, "get_render_backend")
            or plot_host.get_render_backend() != "pyqtgraph"
        ):
            return None
        if hasattr(plot_host, "selected_range"):
            rng = plot_host.selected_range()
            if rng is not None:
                return rng
        if hasattr(plot_host, "current_window"):
            return plot_host.current_window()
        return None

    def _visible_channels_from_toggles(self) -> dict[str, bool]:
        h = self._host
        visible_channels = {
            "inner": bool(getattr(h, "id_toggle_act", None) and h.id_toggle_act.isChecked()),
            "outer": bool(getattr(h, "od_toggle_act", None) and h.od_toggle_act.isChecked()),
            "avg_pressure": bool(
                getattr(h, "avg_pressure_toggle_act", None)
                and h.avg_pressure_toggle_act.isChecked()
            ),
            "set_pressure": bool(
                getattr(h, "set_pressure_toggle_act", None)
                and h.set_pressure_toggle_act.isChecked()
            ),
        }
        if not any(visible_channels.values()):
            visible_channels["inner"] = True
        return visible_channels

    def apply_plot_style(self, style, persist: bool = False, draw: bool = True):
        h = self._host
        manager = h._ensure_style_manager()
        effective_style = manager.update(style or {})
        x_axis = h._x_axis_for_style()

        # Don't pass v3 event text objects to StyleManager - v3 handles its own styling
        plot_host = getattr(h, "plot_host", None)
        v3_enabled = False
        if plot_host is not None:
            with contextlib.suppress(Exception):
                v3_enabled = effective_style.get("event_labels_v3_enabled", False)
        event_texts = [] if v3_enabled else h.event_text_objects

        manager.apply(
            ax=h.ax,
            ax_secondary=h.ax2,
            x_axis=x_axis,
            event_text_objects=event_texts,
            pinned_points=h.pinned_points,
            main_line=h.ax.lines[0] if h.ax.lines else None,
            od_line=h.od_line,
        )

        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None:
            defaults = DEFAULT_STYLE
            try:
                # Batch all setter calls to avoid cascading redraws
                plot_host.suspend_updates()
                # Always use v3 - force upgrade from old saved settings
                plot_host.set_event_labels_v3_enabled(True)
                plot_host.set_event_label_mode(
                    effective_style.get(
                        "event_label_mode",
                        defaults.get("event_label_mode", "vertical"),
                    )
                )
                plot_host.set_max_labels_per_cluster(
                    effective_style.get(
                        "event_label_max_per_cluster",
                        defaults.get("event_label_max_per_cluster", 1),
                    )
                )
                plot_host.set_cluster_style_policy(
                    effective_style.get(
                        "event_label_style_policy",
                        defaults.get("event_label_style_policy", "first"),
                    )
                )
                plot_host.set_label_lanes(
                    effective_style.get(
                        "event_label_lanes",
                        defaults.get("event_label_lanes", 3),
                    )
                )
                plot_host.set_belt_baseline(
                    effective_style.get(
                        "event_label_belt_baseline",
                        defaults.get("event_label_belt_baseline", True),
                    )
                )
                plot_host.set_event_label_span_siblings(
                    effective_style.get(
                        "event_label_span_siblings",
                        defaults.get("event_label_span_siblings", True),
                    )
                )
                plot_host.set_auto_event_label_mode(
                    effective_style.get(
                        "event_label_auto_mode",
                        defaults.get("event_label_auto_mode", True),
                    )
                )
                plot_host.set_label_density_thresholds(
                    compact=effective_style.get(
                        "event_label_density_compact",
                        defaults.get("event_label_density_compact", 0.8),
                    ),
                    belt=effective_style.get(
                        "event_label_density_belt",
                        defaults.get("event_label_density_belt", 0.25),
                    ),
                )
                plot_host.set_label_outline_enabled(
                    effective_style.get(
                        "event_label_outline_enabled",
                        defaults.get("event_label_outline_enabled", True),
                    )
                )
                plot_host.set_label_outline(
                    effective_style.get(
                        "event_label_outline_width",
                        defaults.get("event_label_outline_width", 2.0),
                    ),
                    effective_style.get(
                        "event_label_outline_color",
                        defaults.get("event_label_outline_color", (1.0, 1.0, 1.0, 0.9)),
                    ),
                )
                plot_host.set_label_tooltips_enabled(
                    effective_style.get(
                        "event_label_tooltips_enabled",
                        defaults.get("event_label_tooltips_enabled", True),
                    )
                )
                plot_host.set_tooltip_proximity(
                    effective_style.get(
                        "event_label_tooltip_proximity",
                        defaults.get("event_label_tooltip_proximity", 10),
                    )
                )
                plot_host.set_compact_legend_enabled(
                    effective_style.get(
                        "event_label_legend_enabled",
                        defaults.get("event_label_legend_enabled", True),
                    )
                )
                plot_host.set_compact_legend_location(
                    effective_style.get(
                        "event_label_legend_loc",
                        defaults.get("event_label_legend_loc", "upper right"),
                    )
                )
                if hasattr(plot_host, "set_axis_font"):
                    plot_host.set_axis_font(
                        family=effective_style.get(
                            "axis_font_family",
                            defaults.get("axis_font_family", "Arial"),
                        ),
                        size=effective_style.get(
                            "axis_font_size",
                            defaults.get("axis_font_size", 12),
                        ),
                    )
                    plot_host.set_tick_font_size(
                        effective_style.get(
                            "tick_font_size",
                            defaults.get("tick_font_size", 12),
                        )
                    )
                    plot_host.set_default_line_width(
                        effective_style.get(
                            "line_width",
                            defaults.get("line_width", 2.0),
                        )
                    )
                plot_host.set_event_base_style(
                    font_family=effective_style.get(
                        "event_font_family",
                        defaults.get("event_font_family", "Arial"),
                    ),
                    font_size=effective_style.get(
                        "event_font_size",
                        defaults.get("event_font_size", 15),
                    ),
                    bold=effective_style.get(
                        "event_bold",
                        defaults.get("event_bold", False),
                    ),
                    italic=effective_style.get(
                        "event_italic",
                        defaults.get("event_italic", False),
                    ),
                    color=effective_style.get(
                        "event_color",
                        defaults.get("event_color", "#000000"),
                    ),
                )
            except Exception:
                log.exception("Failed to apply event label style to PlotHost")
            finally:
                # Always resume updates, even if there was an error
                plot_host.resume_updates()

        if draw:
            h.canvas.draw_idle()
        if hasattr(h, "plot_style_dialog") and h.plot_style_dialog:
            with contextlib.suppress(AttributeError):
                h.plot_style_dialog.set_style(effective_style)

        if h._style_holder is None:
            h._style_holder = _StyleHolder(effective_style.copy())
        else:
            h._style_holder.set_style(effective_style.copy())

        if persist and h.current_sample:
            if not isinstance(h.current_sample.ui_state, dict):
                h.current_sample.ui_state = {}
            h.current_sample.ui_state["style_settings"] = effective_style
            h.mark_session_dirty()
            h.request_deferred_autosave(delay_ms=2000, reason="style")

    def _x_axis_for_style(self):
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None:
            axis = plot_host.bottom_axis()
            if axis is not None:
                return axis
        return h.ax

    def _ensure_style_manager(self) -> PlotStyleManager:
        h = self._host
        if getattr(h, "_style_manager", None) is None:
            base_style = (
                h._style_holder.get_style()
                if h._style_holder is not None
                else DEFAULT_STYLE.copy()
            )
            h._style_manager = PlotStyleManager(base_style)
        return h._style_manager

    def _clear_canvas_and_table(self):
        """Wipe the current plot and event table."""
        h = self._host
        h._clear_slider_markers()
        h.trace_data = None
        h.event_label_meta = []
        if hasattr(h, "plot_host"):
            h.plot_host.clear()
            initial_specs = [
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            ]
            h.plot_host.ensure_channels(initial_specs)
            inner_track = h.plot_host.track("inner")
            h.ax = inner_track.ax if inner_track else None
            h._bind_primary_axis_callbacks()
        h.ax2 = None
        h.outer_line = None
        h.trace_model = None
        h._refresh_trace_navigation_data()
        if h.zoom_dock:
            h.zoom_dock.set_trace_model(None)
        if h.scope_dock:
            h.scope_dock.set_trace_model(None)
        h.canvas.draw_idle()
        if hasattr(h, "event_table_controller"):
            h.event_table_controller.clear()
        if hasattr(h, "load_events_action") and h.load_events_action is not None:
            h.load_events_action.setEnabled(False)
        if hasattr(h, "action_import_events") and h.action_import_events is not None:
            h.action_import_events.setEnabled(False)
        h._event_lines_visible = True
        h._event_label_mode = "indices"
        h._sync_event_controls()
        h._apply_toggle_state(True, False, outer_supported=False)
        h._update_trace_controls_state()
        h._update_event_table_presence_state(False)
        h._update_plot_empty_state()

    def get_current_plot_style(self):
        h = self._host
        manager = h._ensure_style_manager()
        if hasattr(h, "plot_style_dialog") and h.plot_style_dialog:
            try:
                style = h.plot_style_dialog.get_style()
                if style:
                    manager.update(style)
                return manager.style()
            except AttributeError:
                pass

        if h._style_holder is not None:
            return h._style_holder.get_style()

        return manager.style()

    def _configure_plot_empty_state_actions(self) -> None:
        h = self._host
        panel = getattr(h, "plot_empty_state", None)
        if panel is None:
            return

        primary_action = getattr(h, "load_trace_action", None) or getattr(
            self, "action_open_trace", None
        )
        primary_tooltip = None
        if primary_action is not None:
            primary_tooltip = primary_action.toolTip() or None
        panel.primary_button.setText("Open Data\u2026")
        panel.set_primary_action(
            primary_action,
            tooltip=primary_tooltip or "Open a trace CSV file and auto-detect matching events",
        )

        secondary_action = getattr(h, "action_import_folder", None)
        secondary_tooltip = None
        if secondary_action is not None:
            secondary_tooltip = secondary_action.toolTip() or None
        panel.set_secondary_action(
            secondary_action,
            text="Import Folder\u2026",
            tooltip=secondary_tooltip or "Import a folder of datasets into the current project",
        )

    def _update_plot_empty_state(self) -> None:
        h = self._host
        stack = getattr(h, "plot_stack_layout", None)
        empty_page = getattr(h, "plot_empty_state_page", None)
        content_page = getattr(h, "plot_content_page", None)
        if stack is None or empty_page is None or content_page is None:
            return
        show_empty = h.trace_data is None and h.current_sample is None
        target = empty_page if show_empty else content_page
        if stack.currentWidget() is not target:
            stack.setCurrentWidget(target)
