#!/usr/bin/env python3
"""Replace method bodies in main_window.py with forwarding stubs for ALL managers.

Also extracts SampleManager methods into a new file.

Run from project root:
    python scripts/wire_all_managers.py
"""
import ast
import re
import textwrap
from pathlib import Path

MW = Path("src/vasoanalyzer/ui/main_window.py")
SAMPLE_OUT = Path("src/vasoanalyzer/ui/managers/sample_manager.py")
PLOT_OUT = Path("src/vasoanalyzer/ui/managers/plot_manager.py")

# Method -> manager attribute name mapping
# Methods listed here will be replaced with forwarding stubs
MANAGER_MAP = {}

def mgr(manager_attr, methods):
    for m in methods:
        MANAGER_MAP[m] = manager_attr

# Navigation manager
mgr("_navigation_mgr", [
    "reset_to_full_view", "_register_trace_nav_shortcuts", "show_goto_time_dialog",
    "_jump_to_start", "_jump_to_end", "_pan_window_fraction", "_jump_to_event",
    "_zoom_all_x", "reset_view", "fit_to_data", "zoom_to_selection", "zoom_out",
    "fit_x_full", "fit_y_in_current_x", "_value_range",
])

# Export manager
mgr("_export_mgr", [
    "auto_export_table", "_export_event_table_to_path", "_export_event_table_via_dialog",
    "_event_rows_for_export", "_build_export_table_for_profile", "_show_export_warnings",
    "_copy_event_profile_to_clipboard", "_default_event_export_filename",
    "_export_event_profile_csv_via_dialog", "open_excel_template_export_dialog",
    "_update_gif_animator_state", "show_gif_animator", "open_sync_clip_exporter",
    "export_project_bundle_action", "export_shareable_project",
    "export_dataset_package_action",
])

# Project manager
mgr("_project_mgr", [
    "new_project", "_create_project_from_inputs", "_open_project_file_legacy",
    "open_project_file", "_prepare_project_for_save", "_project_snapshot_for_save",
    "_set_save_actions_enabled", "_start_background_save", "_on_save_progress_changed",
    "_on_save_error", "_on_save_finished", "save_project_file", "save_project_file_as",
    "_run_deferred_autosave", "request_deferred_autosave", "auto_save_project",
    "_autosave_tick", "_bump_project_state_rev", "_replace_current_project",
])

# Snapshot manager
mgr("_snapshot_mgr", [
    "_apply_snapshot_view_mode", "_snapshot_has_image", "_update_snapshot_panel_layout",
    "_update_snapshot_rotation_controls", "toggle_snapshot_viewer",
    "_reset_snapshot_loading_info", "_format_stride_label", "_probe_tiff_frame_count",
    "_prompt_tiff_load_strategy", "_derive_frame_trace_time", "_load_snapshot_from_path",
    "load_snapshot", "save_analysis", "open_analysis", "_trace_time_for_frame_number",
    "_set_snapshot_data_source", "load_snapshots", "compute_frame_trace_indices",
    "_time_for_frame", "_frame_index_for_time_canonical", "jump_to_time",
    "set_current_frame", "update_snapshot_size", "_update_snapshot_sampling_badge",
    "_tiff_page_for_frame", "_trace_time_exact_for_page", "_apply_frame_change",
    "_update_snapshot_status", "_update_metadata_display", "_snapshot_view_visible",
    "_update_metadata_button_state", "on_snapshot_speed_changed",
    "on_snapshot_sync_toggled", "on_snapshot_loop_toggled", "_reset_snapshot_speed",
    "_resolve_snapshot_pps_default", "_sync_time_cursor_to_snapshot",
    "_update_playback_button_state", "_set_playback_state",
    "_on_snapshot_page_changed_v2", "_on_snapshot_playback_time_changed",
    "_on_snapshot_playing_changed", "toggle_snapshot_playback",
    "_mapped_trace_time_for_page", "_sync_trace_cursor_to_time",
    "step_previous_frame", "step_next_frame", "rotate_snapshot_ccw",
    "rotate_snapshot_cw", "reset_snapshot_rotation", "set_snapshot_metadata_visible",
    "_clear_slider_markers", "_set_snapshot_sync_time", "_refresh_snapshot_sync_label",
    "_update_snapshot_viewer_state", "_ensure_sample_snapshots_loaded",
    "_on_snapshot_load_finished",
])

# Theme manager
mgr("_theme_mgr", [
    "_update_theme_action_checks", "_update_action_icons",
    "apply_theme", "set_color_scheme",
    "_apply_event_table_card_theme", "_apply_snapshot_theme",
    "_apply_primary_toolbar_theme",
    # Note: _apply_status_bar_theme stays inline (called during __init__)
])

# Event manager
mgr("_event_mgr", [
    "quick_add_event_at_trace_point", "prompt_add_event", "manual_add_event",
    "handle_event_replacement", "delete_selected_events", "_delete_events_by_indices",
    "_sync_event_data_from_table", "_apply_event_rows_to_current_sample",
    "handle_table_edit", "handle_event_label_edit", "populate_event_table_from_df",
    "update_event_label_positions", "_selected_event_rows",
    "_on_event_table_selection_changed", "_focus_event_row",
    "_highlight_selected_event", "_clear_event_highlight", "_on_event_highlight_tick",
    "_frame_index_from_event_row", "_nearest_event_index", "_warn_event_sync",
    "_event_time_in_range", "_ensure_event_meta_length", "_normalize_event_label_meta",
    "_insert_event_meta", "_delete_event_meta",
    "_current_review_states", "_fallback_restore_review_states",
    "_set_review_state_for_row", "_refresh_event_annotation_artists",
    "apply_event_label_overrides", "_ensure_event_label_actions",
    "_on_event_lines_toggled", "_on_event_label_mode_auto", "_on_event_label_mode_all",
    "_set_event_label_mode", "_apply_event_label_mode", "_sync_event_controls",
    "toggle_channel_event_labels", "set_channel_event_label_font_size",
    "_overview_event_times", "_refresh_overview_events",
    "_reset_event_table_for_loading", "_set_event_table_enabled",
    "_set_event_table_visible", "toggle_event_table", "_on_event_rows_changed",
    "_update_event_table_presence_state", "_event_table_signal_availability",
    "_event_table_review_mode_active", "_apply_event_table_column_contract",
    "show_event_table_context_menu", "load_events", "_load_events_from_path",
    "_handle_load_events", "_review_notice_key", "_configure_review_notice_banner",
    "_dismiss_review_notice", "_update_review_notice_visibility",
    "_launch_event_review_wizard", "_apply_event_review_changes",
    "_cleanup_event_review_wizard", "_prompt_export_event_table_after_review",
    "_sync_sample_events_dataframe",
    # Note: _with_default_review_state is @staticmethod, stays inline
])

# Sample manager (NEW)
mgr("_sample_mgr", [
    "_ensure_data_cache", "_update_sample_link_metadata", "_resolve_sample_link",
    "import_dataset_from_project_action", "import_dataset_package_action",
    "_gather_selected_samples_for_copy", "copy_selected_datasets", "paste_datasets",
    "_persist_sample_ui_state", "_get_sample_data_quality",
    "_update_tree_icons_for_samples", "_set_samples_data_quality",
    "_select_dataset_ids", "_select_tree_item_for_sample",
    "_selected_samples_from_tree", "_experiment_name_for_sample",
    "_open_first_sample_if_none_active", "_activate_sample",
    "on_sample_notes_changed", "on_sample_add_attachment",
    "on_sample_remove_attachment", "on_sample_open_attachment",
    "_queue_sample_load_until_context", "_flush_pending_sample_loads",
    "_log_sample_data_summary", "load_sample_into_view",
    "_prepare_sample_view", "_begin_sample_load_job",
    "_on_sample_load_finished", "_on_sample_load_error", "_render_sample",
    "add_sample", "add_sample_to_current_experiment", "load_data_into_sample",
    "_sample_values_at_time",
    "_start_sample_load_progress", "_update_sample_load_progress",
    "_finish_sample_load_progress", "_get_trace_model_for_sample",
    "sample_inner_diameter", "gather_ui_state", "_invalidate_sample_state_cache",
    "gather_sample_state", "apply_ui_state", "_sample_is_embedded",
    "apply_sample_state",
])

# Plot manager (NEW)
mgr("_plot_mgr", [
    # Channel / track
    "_rebuild_channel_layout", "_apply_channel_toggle", "_apply_channel_toggle_pyqtgraph",
    "_outer_channel_available", "_avg_pressure_channel_available",
    "_set_pressure_channel_available", "_current_channel_presence",
    "_ensure_valid_channel_selection", "_reset_channel_view_defaults",
    "_sync_track_visibility_from_host", "_channel_has_data_in_window",
    # Hover / cursor
    "_init_hover_artists", "update_hover_label", "_hide_hover_feedback",
    "_set_plot_cursor_for_mode", "_get_selected_range_from_plot_host",
    # Legend / style
    "apply_legend_settings", "_refresh_plot_legend", "open_legend_settings_dialog",
    "get_current_plot_style", "apply_plot_style", "_apply_current_style",
    "_ensure_style_manager", "_x_axis_for_style",
    # Scroll / slider
    "update_scroll_slider", "scroll_plot", "scroll_plot_user",
    "sync_slider_with_plot", "update_slider_marker",
    "_reset_time_scrollbar_to_start",
    "_on_scrollbar_value_changed", "_on_scrollbar_moved",
    "_on_scrollbar_pressed", "_on_scrollbar_released",
    # View state
    "_collect_plot_view_state", "_apply_pyqtgraph_track_state",
    "_apply_pending_pyqtgraph_track_state", "_serialize_plot_layout",
    "_apply_pending_plot_layout", "_sync_time_window_from_axes",
    "_on_plot_host_time_window_changed",
    # PyQtGraph infra
    "_plot_host_is_pyqtgraph", "_attach_plot_host_window_listener",
    "_bind_primary_axis_callbacks", "_unbind_primary_axis_callbacks",
    "_handle_axis_xlim_changed", "_sync_autoscale_y_action_from_host",
    "_sync_grid_action", "_refresh_zoom_window",
    # Overview / trace nav
    "_apply_overview_strip_visibility", "toggle_overview_strip",
    "_set_trace_navigation_visible", "_on_trace_nav_window_requested",
    "_refresh_trace_navigation_data", "_trace_full_range",
    # Update / refresh
    "update_plot", "_update_plot_empty_state", "_configure_plot_empty_state_actions",
    "_update_trace_controls_state", "_force_trace_start_view",
    "_refresh_views_after_edit",
    # Plot toolbar
    "_plot_toolbar_signal_buttons", "_plot_toolbar_row2_buttons",
    "_lock_plot_toolbar_row2_order", "_normalize_plot_toolbar_button_geometry",
    "_update_plot_toolbar_signal_button_widths", "_apply_button_style",
    # Trace data utils
    "_sync_trace_dataframe_from_model", "_update_trace_sync_state",
    "_prepare_trace_dataframe", "_visible_channels_from_toggles",
    # Canvas
    "_clear_canvas_and_table", "_refresh_tiff_page_times",
])

# Methods that must stay inline (called during __init__ before managers exist)
KEEP_INLINE = {
    "_apply_status_bar_theme",
    "_status_bar_theme_colors",
    "_resolve_snapshot_pps_default",  # Also in snapshot_mgr but called at line 775
    "_with_default_review_state",     # @staticmethod
}


def main():
    source = MW.read_text()
    lines = source.splitlines()
    tree = ast.parse(source)

    cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "VasoAnalyzerApp":
            cls = node
            break
    assert cls is not None

    # Collect all method info
    method_info = {}  # name -> (start, end, is_static, text)
    for item in cls.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name in MANAGER_MAP and item.name not in KEEP_INLINE:
                start = item.lineno
                end = item.end_lineno
                is_static = any(
                    isinstance(d, ast.Name) and d.id == "staticmethod"
                    for d in item.decorator_list
                )
                text = "\n".join(lines[start - 1 : end])
                method_info[item.name] = (start, end, is_static, text)

    print(f"Found {len(method_info)} methods to stub out of {len(MANAGER_MAP)} mapped")
    missing = set(MANAGER_MAP.keys()) - set(method_info.keys()) - KEEP_INLINE
    if missing:
        print(f"  Not found (may be fine if already stubbed or inline): {sorted(missing)}")

    # --- Extract SampleManager methods ---
    sample_methods = {
        name: info for name, info in method_info.items()
        if MANAGER_MAP.get(name) == "_sample_mgr"
    }
    extract_sample_manager(sample_methods, lines)

    # --- Extract PlotManager methods ---
    plot_methods = {
        name: info for name, info in method_info.items()
        if MANAGER_MAP.get(name) == "_plot_mgr"
    }
    extract_plot_manager(plot_methods, lines)
    patch_plot_manager()
    patch_sample_manager()

    # --- Replace methods with forwarding stubs (bottom-to-top) ---
    sorted_items = sorted(method_info.items(), key=lambda x: x[1][0], reverse=True)
    new_lines = list(lines)

    for name, (start, end, is_static, text) in sorted_items:
        mgr_attr = MANAGER_MAP[name]
        stub = generate_stub(name, text, mgr_attr, is_static)
        new_lines[start - 1 : end] = stub.splitlines()

    # --- Add manager instantiation to __init__ ---
    result_text = "\n".join(new_lines)
    result_text = add_manager_init(result_text)

    MW.write_text(result_text + "\n")
    final_lines = result_text.splitlines()
    print(f"Updated {MW} ({len(final_lines)} lines)")


def generate_stub(name, text, mgr_attr, is_static):
    """Generate a forwarding stub for the method."""
    mlines = text.splitlines()

    # Collect decorators and def line(s)
    header_lines = []
    def_line_idx = 0
    for i, line in enumerate(mlines):
        if line.strip().startswith("@"):
            header_lines.append(line)
        elif line.strip().startswith("def ") or line.strip().startswith("async def "):
            header_lines.append(line)
            def_line_idx = i
            break

    # Handle multi-line def
    if not mlines[def_line_idx].rstrip().endswith(":"):
        for j in range(def_line_idx + 1, len(mlines)):
            header_lines.append(mlines[j])
            if mlines[j].rstrip().endswith(":"):
                def_line_idx = j
                break

    # Parse to get args
    def_text = "\n".join(header_lines)
    parse_text = def_text + "\n        pass"
    try:
        parsed = ast.parse(textwrap.dedent(parse_text))
        func = parsed.body[0]
        args = func.args

        fwd_args = []
        for a in args.args[1:]:  # skip self
            fwd_args.append(a.arg)
        if args.vararg:
            fwd_args.append(f"*{args.vararg.arg}")
        for a in args.kwonlyargs:
            fwd_args.append(f"{a.arg}={a.arg}")
        if args.kwarg:
            fwd_args.append(f"**{args.kwarg.arg}")

        args_str = ", ".join(fwd_args)
    except Exception as e:
        print(f"  WARNING: Could not parse args for {name}: {e}")
        args_str = ""

    # Check for return value
    has_return = False
    for line in mlines[def_line_idx + 1:]:
        stripped = line.strip()
        if stripped.startswith("return ") and stripped != "return None" and stripped != "return":
            has_return = True
            break

    indent = "        "
    prefix = "return " if has_return else ""

    if is_static:
        # Static methods can't use self._mgr, keep body
        return text

    call = f"{prefix}self.{mgr_attr}.{name}({args_str})"
    stub_lines = header_lines + [f"{indent}{call}"]
    return "\n".join(stub_lines)


def add_manager_init(source_text):
    """Insert manager imports and instantiation before create_menubar() call."""
    # Find the line with QTimer.singleShot(0, self._maybe_run_onboarding)
    # and insert manager init before it
    marker = "self.create_menubar()"
    if marker not in source_text:
        print("WARNING: Could not find create_menubar marker, trying alternate")
        marker = "QTimer.singleShot(0, self._maybe_run_onboarding)"

    init_block = """
        # ===== Instantiate Manager Delegates =====
        from vasoanalyzer.ui.managers.export_manager import ExportManager
        from vasoanalyzer.ui.managers.navigation_manager import NavigationManager
        from vasoanalyzer.ui.managers.project_manager import ProjectManager
        from vasoanalyzer.ui.managers.snapshot_manager import SnapshotManager
        from vasoanalyzer.ui.managers.theme_manager import ThemeManager
        from vasoanalyzer.ui.managers.event_manager import EventManager
        from vasoanalyzer.ui.managers.sample_manager import SampleManager
        from vasoanalyzer.ui.managers.plot_manager import PlotManager

        self._export_mgr = ExportManager(self, parent=self)
        self._project_mgr = ProjectManager(self, parent=self)
        self._snapshot_mgr = SnapshotManager(self, parent=self)
        self._navigation_mgr = NavigationManager(self, parent=self)
        self._theme_mgr = ThemeManager(self, parent=self)
        self._event_mgr = EventManager(self, parent=self)
        self._sample_mgr = SampleManager(self, parent=self)
        self._plot_mgr = PlotManager(self, parent=self)

"""

    # Insert before the marker line
    lines = source_text.splitlines()
    for i, line in enumerate(lines):
        if marker in line:
            # Find the right insertion point (before this line)
            lines.insert(i, init_block.rstrip())
            break
    else:
        print("ERROR: Could not find insertion point for manager init!")

    return "\n".join(lines)


def extract_sample_manager(sample_methods, all_lines):
    """Extract sample methods and create SampleManager file."""
    header = '''# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""SampleManager -- sample lifecycle logic extracted from VasoAnalyzerApp."""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from PyQt5.QtCore import QByteArray, QMimeData, QObject, QRunnable, QSettings, QTimer, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QTreeWidgetItem,
)

from collections.abc import Mapping
from vasoanalyzer.core.project import Attachment, Experiment, SampleN
from vasoanalyzer.core.project_context import ProjectContext
from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.io.events import find_matching_event_file, load_events
from vasoanalyzer.io.traces import load_trace
from vasoanalyzer.services.cache_service import DataCache, cache_dir_for_project
from vasoanalyzer.storage.dataset_package import (
    DatasetPackageValidationError,
    export_dataset_package,
    import_dataset_package,
)
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:
    from vasoanalyzer.services.types import ProjectRepository
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)


class SampleManager(QObject):
    """Manages sample lifecycle: loading, activation, state gather/apply."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

'''

    # Sort by original order
    sorted_methods = sorted(sample_methods.items(), key=lambda x: x[1][0])

    transformed = []
    for name, (start, end, is_static, text) in sorted_methods:
        transformed.append(transform_method(text))

    body = "\n\n".join(transformed)
    full = header + body + "\n"
    SAMPLE_OUT.write_text(full)
    print(f"Wrote {SAMPLE_OUT} ({len(full.splitlines())} lines)")


def transform_method(text):
    """Transform a method's self references to h = self._host."""
    mlines = text.splitlines()

    # Find def line
    def_idx = 0
    for i, line in enumerate(mlines):
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            def_idx = i
            break

    # Find end of def signature (handle multi-line)
    sig_end = def_idx
    if not mlines[def_idx].rstrip().endswith(":"):
        for j in range(def_idx + 1, len(mlines)):
            if mlines[j].rstrip().endswith(":"):
                sig_end = j
                break

    # Find where body starts (after docstring)
    body_start = sig_end + 1
    if body_start < len(mlines):
        stripped = mlines[body_start].strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            if stripped.count(quote) >= 2:
                body_start += 1
            else:
                for j in range(body_start + 1, len(mlines)):
                    if quote in mlines[j]:
                        body_start = j + 1
                        break

    # Insert h = self._host
    indent = "        "
    h_line = f"{indent}h = self._host"
    result = mlines[:body_start] + [h_line] + mlines[body_start:]

    # Do self -> h replacements
    # Strategy: lines before body_start (def signature + docstring) are kept verbatim.
    # Lines at/after body_start get self.xxx -> h.xxx.
    # The inserted h_line is at position body_start, so body_start+1 onward gets replaced.
    final_lines = result[:body_start + 1]  # def sig + docstring + h_line (verbatim)
    for line in result[body_start + 1:]:
        line = replace_self_in_line(line)
        final_lines.append(line)

    return "\n".join(final_lines)


def replace_self_in_line(line):
    """Replace self references with h references."""
    line = line.replace("getattr(self,", "getattr(h,")
    line = line.replace("getattr(self)", "getattr(h)")
    line = line.replace("hasattr(self,", "hasattr(h,")
    line = line.replace("setattr(self,", "setattr(h,")
    line = line.replace("id(self)", "id(h)")

    line = re.sub(r"QMessageBox\.(\w+)\(self,", r"QMessageBox.\1(h,", line)
    line = re.sub(r"QInputDialog\.(\w+)\(self,", r"QInputDialog.\1(h,", line)
    line = re.sub(r"QFileDialog\.(\w+)\(self,", r"QFileDialog.\1(h,", line)

    stripped = line.strip()
    if stripped == "self," or stripped == "self":
        line = line.replace("self", "h")

    # self.xxx -> h.xxx (but not self._host)
    line = re.sub(r"(?<!\w)self\.(?!_host\b)", "h.", line)

    return line


def patch_plot_manager():
    """Inject lazy imports into PlotManager for main_window-internal symbols."""
    text = PLOT_OUT.read_text()
    patches = [
        (
            "                    if full_range[1] - full_range[0] > DEFAULT_INITIAL_VIEW_SECONDS:",
            "                    from vasoanalyzer.ui.main_window import DEFAULT_INITIAL_VIEW_SECONDS\n"
            "                    if full_range[1] - full_range[0] > DEFAULT_INITIAL_VIEW_SECONDS:",
        ),
        (
            "        merged = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)",
            "        from vasoanalyzer.ui.main_window import DEFAULT_LEGEND_SETTINGS, LEGEND_LABEL_DEFAULTS, _copy_legend_settings\n"
            "        merged = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)",
        ),
    ]
    for old, new in patches:
        if old in text and new not in text:
            text = text.replace(old, new)
    PLOT_OUT.write_text(text)


def patch_sample_manager():
    """Inject lazy imports into SampleManager for main_window-internal symbols."""
    text = SAMPLE_OUT.read_text()
    patches = [
        (
            "        dialog = SourceProjectBrowserDialog(",
            "        from vasoanalyzer.ui.dialogs.source_project_browser import SourceProjectBrowserDialog, build_import_plan\n        dialog = SourceProjectBrowserDialog(",
        ),
        (
            "        job = _SampleLoadJob(",
            "        from vasoanalyzer.ui.main_window import _SampleLoadJob\n        job = _SampleLoadJob(",
        ),
        (
            "            merged_style = {**DEFAULT_STYLE, **style} if style else DEFAULT_STYLE.copy()\n            h._style_holder = _StyleHolder(merged_style.copy())",
            "            from vasoanalyzer.ui.main_window import _StyleHolder\n            from vasoanalyzer.ui.constants import DEFAULT_STYLE\n            merged_style = {**DEFAULT_STYLE, **style} if style else DEFAULT_STYLE.copy()\n            h._style_holder = _StyleHolder(merged_style.copy())",
        ),
        (
            "                h.legend_settings = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)",
            "                from vasoanalyzer.ui.main_window import DEFAULT_LEGEND_SETTINGS, _copy_legend_settings\n                h.legend_settings = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)",
        ),
    ]
    for old, new in patches:
        if old in text and new not in text:
            text = text.replace(old, new)
    SAMPLE_OUT.write_text(text)


def extract_plot_manager(plot_methods, all_lines):
    """Extract plot methods and create PlotManager file."""
    header = '''# VasoAnalyzer
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
from PyQt5.QtCore import QObject, QSignalBlocker, QTimer, Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
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

'''

    sorted_methods = sorted(plot_methods.items(), key=lambda x: x[1][0])

    transformed = []
    for name, (start, end, is_static, text) in sorted_methods:
        transformed.append(transform_method(text))

    body = "\n\n".join(transformed)
    full = header + body + "\n"
    PLOT_OUT.write_text(full)
    print(f"Wrote {PLOT_OUT} ({len(full.splitlines())} lines)")


if __name__ == "__main__":
    main()
