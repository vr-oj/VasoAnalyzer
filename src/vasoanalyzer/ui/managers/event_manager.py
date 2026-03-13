# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""EventManager -- event management logic extracted from VasoAnalyzerApp."""

from __future__ import annotations

import contextlib
import copy
import html
import logging
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
    QTableWidgetItem,
)

from vasoanalyzer.export.profiles import (
    EVENT_TABLE_ROW_PER_EVENT_ID,
    EVENT_VALUES_SINGLE_COLUMN_ID,
    PRESSURE_CURVE_STANDARD_ID,
)
from vasoanalyzer.services.project_service import (
    events_dataframe_from_rows,
    normalize_event_table_rows,
)
from vasoanalyzer.ui.commands import AddEventCommand, DeleteEventsCommand, ReplaceEventCommand
from vasoanalyzer.ui.controllers.selection_sync import event_time_for_row, pick_event_row
from vasoanalyzer.ui.dialogs.event_review_wizard import EventReviewWizard
from vasoanalyzer.ui.event_table import build_event_table_column_contract
from vasoanalyzer.ui.plots.overlays import AnnotationSpec
from vasoanalyzer.ui.theme import CURRENT_THEME, css_rgba_to_mpl

if TYPE_CHECKING:
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)

_TIME_SYNC_DEBUG = os.environ.get("VA_TIME_SYNC_DEBUG", "").strip().lower() in ("1", "true", "yes")


def _log_time_sync(label: str, **fields) -> None:
    """Conditional debug logger for time/frame sync flows."""
    if not (_TIME_SYNC_DEBUG or log.isEnabledFor(logging.DEBUG)):
        return
    clean = {k: v for k, v in fields.items() if v is not None}
    payload = ", ".join(f"{k}={v}" for k, v in clean.items())
    if _TIME_SYNC_DEBUG:
        log.info("[SYNC] %s %s", label, payload)
    else:
        log.debug("[SYNC] %s %s", label, payload)


# Review state constants (mirrored from main_window / review_mode_controller)
REVIEW_UNREVIEWED = "UNREVIEWED"
REVIEW_CONFIRMED = "CONFIRMED"
REVIEW_EDITED = "EDITED"
REVIEW_NEEDS_FOLLOWUP = "NEEDS_FOLLOWUP"


class EventManager(QObject):
    """Manages event lifecycle: add, edit, delete, review, display, and export."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

    def quick_add_event_at_trace_point(self, x: float, y: float, trace_type: str = "inner") -> None:
        h = self._host
        """Quick-add an event marker at the clicked trace position."""
        if h.trace_data is None or "Time (s)" not in h.trace_data.columns:
            QMessageBox.warning(h, "No Trace", "Load a trace before adding event markers.")
            return

        try:
            click_time = float(x)
        except (TypeError, ValueError):
            return

        times = h.trace_data["Time (s)"].to_numpy(dtype=float)
        if times.size == 0:
            QMessageBox.warning(h, "No Trace", "Trace timebase is empty.")
            return

        nearest_idx = int(np.argmin(np.abs(times - click_time)))
        event_time = float(times[nearest_idx])

        default_label = f"Event {len(h.event_table_data) + 1}"
        label_text, label_ok = QInputDialog.getText(
            h,
            "Add Event Marker",
            "Event label:",
            text=default_label,
        )
        if not label_ok:
            return

        label_value = str(label_text or "").strip()
        if not label_value:
            return

        def _round_optional(value: float | None) -> float | None:
            if value is None:
                return None
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            if not np.isfinite(numeric):
                return None
            return round(numeric, 2)

        # Always use the actual trace values at the snapped time point
        # rather than the raw click y-coordinate, for data consistency.
        id_val, od_val, avg_p_val, set_p_val = h._sample_values_at_time(event_time)

        # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
        new_entry = (
            label_value,
            round(event_time, 2),
            _round_optional(id_val),
            _round_optional(od_val),
            _round_optional(avg_p_val),
            _round_optional(set_p_val),
            int(nearest_idx),
        )

        insert_idx = len(h.event_table_data)
        for idx, row in enumerate(h.event_table_data):
            row_time = event_time_for_row(row)
            if row_time is None:
                continue
            with contextlib.suppress(Exception):
                if float(event_time) < float(row_time):
                    insert_idx = idx
                    break

        cmd = AddEventCommand(h, insert_idx, new_entry)
        h.undo_stack.push(cmd)
        h._focus_event_row(insert_idx, source="manual")
        log.info("Quick-added event marker: %s", new_entry)

    def prompt_add_event(self, x, y, trace_type="inner"):
        h = self._host
        if not h.event_table_data:
            QMessageBox.warning(h, "No Events", "You must load events before adding new ones.")
            return

        # Build label options and insertion points
        insert_labels = [f"{label} at {t:.2f}s" for label, t, *_ in h.event_table_data]
        insert_labels.append("↘️ Add to end")  # final option

        selected, ok = QInputDialog.getItem(
            h,
            "Insert Event",
            "Insert new event before which existing event?",
            insert_labels,
            0,
            False,
        )

        if not ok or not selected:
            return

        # Choose label for new event
        new_label, label_ok = QInputDialog.getText(
            h, "New Event Label", "Enter label for the new event:"
        )

        if not label_ok or not new_label.strip():
            return

        insert_idx = insert_labels.index(selected)

        has_od = h.trace_data is not None and "Outer Diameter" in h.trace_data.columns
        avg_label = h._trace_label_for("p_avg")
        set_label = h._trace_label_for("p2")
        has_avg_p = h.trace_data is not None and avg_label in h.trace_data.columns
        has_set_p = h.trace_data is not None and set_label in h.trace_data.columns

        arr_t = h.trace_data["Time (s)"].values
        idx = int(np.argmin(np.abs(arr_t - x)))
        event_time = float(arr_t[idx])

        # Always use actual trace values at the snapped time point
        id_val, od_val, avg_p_val, set_p_val = h._sample_values_at_time(event_time)

        frame_number = idx  # store nearest trace index as frame hint

        def _ro(v: float | None) -> float | None:
            if v is None:
                return None
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return round(f, 2) if np.isfinite(f) else None

        # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
        new_entry = (
            new_label.strip(),
            round(event_time, 2),
            _ro(id_val),
            _ro(od_val),
            _ro(avg_p_val),
            _ro(set_p_val),
            frame_number,
        )

        cmd = AddEventCommand(h, insert_idx, new_entry)
        h.undo_stack.push(cmd)
        log.info("Inserted new event: %s", new_entry)

    def manual_add_event(self):
        h = self._host
        if not h.trace_data:
            QMessageBox.warning(h, "No Trace", "Load a trace before adding events.")
            return

        has_od = "Outer Diameter" in h.trace_data.columns
        insert_labels = [f"{lbl} at {t:.2f}s" for lbl, t, *_ in h.event_table_data]
        insert_labels.append("↘️ Add to end")
        selected, ok = QInputDialog.getItem(
            h,
            "Insert Event",
            "Insert new event before which existing event?",
            insert_labels,
            0,
            False,
        )
        if not ok or not selected:
            return

        label, l_ok = QInputDialog.getText(
            h, "New Event Label", "Enter label for the new event:"
        )
        if not l_ok or not label.strip():
            return

        t_val, t_ok = QInputDialog.getDouble(h, "Event Time", "Time (s):", 0.0, 0, 1e6, 2)
        if not t_ok:
            return

        id_val, id_ok = QInputDialog.getDouble(h, "Inner Diameter", "ID (µm):", 0.0, 0, 1e6, 2)
        if not id_ok:
            return

        insert_idx = insert_labels.index(selected)
        arr_t = h.trace_data["Time (s)"].values
        frame_number = int(np.argmin(np.abs(arr_t - t_val)))
        od_val = None
        if has_od:
            od_val, ok = QInputDialog.getDouble(h, "Outer Diameter", "OD (µm):", 0.0, 0, 1e6, 2)
            if not ok:
                return

        # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
        # Pressure values set to None for manually entered events
        new_entry = (
            label.strip(),
            round(t_val, 2),
            round(id_val, 2),
            round(od_val, 2) if od_val is not None else None,
            None,  # avg_p - not available for manual entry
            None,  # set_p - not available for manual entry
            frame_number,
        )

        cmd = AddEventCommand(h, insert_idx, new_entry)
        h.undo_stack.push(cmd)
        log.info("Manually inserted event: %s", new_entry)

    def handle_event_replacement(self, x, y):
        h = self._host
        if not h.event_labels or not h.event_times:
            log.info("No events available to replace.")
            return

        options = [
            f"{label} at {time:.2f}s"
            for label, time in zip(h.event_labels, h.event_times, strict=False)
        ]
        selected, ok = QInputDialog.getItem(
            h,
            "Select Event to Replace",
            "Choose the event whose value you want to replace:",
            options,
            0,
            False,
        )

        if ok and selected:
            index = options.index(selected)
            event_label = h.event_labels[index]
            event_time = h.event_times[index]

            confirm = QMessageBox.question(
                h,
                "Confirm Replacement",
                f"Replace ID for '{event_label}' at {event_time:.2f}s with {y:.1f} µm?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if confirm == QMessageBox.StandardButton.Yes:
                has_od = h.trace_data is not None and "Outer Diameter" in h.trace_data.columns
                old_value = h.event_table_data[index][2]
                h.last_replaced_event = (index, old_value)
                if has_od:
                    frame_num = h.event_table_data[index][4]
                    h.event_table_data[index] = (
                        event_label,
                        round(event_time, 2),
                        round(y, 2),
                        h.event_table_data[index][3],
                        frame_num,
                    )
                else:
                    frame_num = h.event_table_data[index][3]
                    h.event_table_data[index] = (
                        event_label,
                        round(event_time, 2),
                        round(y, 2),
                        frame_num,
                    )
                h.event_table_controller.update_row(index, h.event_table_data[index])
                h._mark_row_edited(index)
                h.auto_export_table()
                h.mark_session_dirty()

    def delete_selected_events(self, checked: bool = False, *, indices: list[int] | None = None):
        h = self._host
        """Delete selected events."""
        if indices is None:
            selection = h.event_table.selectionModel()
            if selection is None:
                return
            indices = sorted({index.row() for index in selection.selectedRows()})
        if not indices:
            return

        events_desc = [
            h.event_table_data[idx][0]
            for idx in indices
            if 0 <= idx < len(h.event_table_data)
        ]
        if len(indices) == 1 and events_desc:
            prompt = f"Delete event: {events_desc[0]}?"
        else:
            prompt = f"Delete {len(indices)} selected events?"

        confirm = QMessageBox.question(
            h,
            "Delete Event" if len(indices) == 1 else "Delete Events",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._delete_events_by_indices(indices)

    def _delete_events_by_indices(self, indices: list[int]) -> None:
        h = self._host
        if not indices:
            return
        valid = sorted(
            set(idx for idx in indices if 0 <= idx < len(h.event_table_data)),
        )
        if not valid:
            return

        # Capture rows + meta before removal for undo
        removed: list[tuple[int, tuple, dict[str, Any]]] = []
        meta_list = getattr(h, "event_label_meta", []) or []
        for idx in valid:
            row = h.event_table_data[idx]
            meta = dict(meta_list[idx]) if idx < len(meta_list) else {}
            removed.append((idx, row, meta))

        cmd = DeleteEventsCommand(h, removed)
        h.undo_stack.push(cmd)
        h._update_excel_controls()

    # ------------------------------------------------------------------
    # Atomic insert / remove used by undo commands
    # ------------------------------------------------------------------

    def _insert_event_at(
        self, index: int, row: tuple, meta: dict[str, Any] | None = None
    ) -> None:
        """Insert *row* at *index* into all event arrays and refresh the UI."""
        h = self._host
        label = row[0] if row else ""
        time_val = float(row[1]) if len(row) > 1 else 0.0
        frame_val = int(row[-1]) if (row and row[-1] is not None) else 0

        for attr in ("event_labels", "event_times", "event_frames", "event_label_meta"):
            if not isinstance(getattr(h, attr, None), list):
                setattr(h, attr, [])

        if index >= len(h.event_table_data):
            h.event_table_data.append(row)
            h.event_labels.append(label)
            h.event_times.append(time_val)
            h.event_frames.append(frame_val)
            h.event_label_meta.append(h._with_default_review_state(meta))
        else:
            h.event_table_data.insert(index, row)
            h.event_labels.insert(index, label)
            h.event_times.insert(index, time_val)
            h.event_frames.insert(index, frame_val)
            h._insert_event_meta(index, meta)

        h._ensure_event_meta_length(len(h.event_table_data))
        h.populate_table()
        h.update_plot()
        h.auto_export_table()
        h.mark_session_dirty()

    def _remove_event_at(self, index: int) -> tuple | None:
        """Remove the event at *index* from all event arrays and refresh the UI.

        Returns the removed ``EventRow`` or ``None`` if *index* is out of range.
        """
        h = self._host
        if index < 0 or index >= len(h.event_table_data):
            return None

        removed = h.event_table_data.pop(index)
        if index < len(h.event_labels):
            del h.event_labels[index]
        if index < len(h.event_times):
            del h.event_times[index]
        if index < len(h.event_frames):
            del h.event_frames[index]
        h._delete_event_meta(index)
        h.event_table_controller.remove_row(index)

        h.update_plot()
        h.auto_export_table()
        h.mark_session_dirty()
        return removed

    def _sync_event_data_from_table(self) -> None:
        h = self._host
        """Recompute cached event arrays, metadata, and annotation entries."""

        rows = list(getattr(h, "event_table_data", []) or [])
        h._normalize_event_label_meta(len(rows))
        if not getattr(h, "_suppress_event_table_sync", False):
            h._apply_event_rows_to_current_sample(rows)
        if not rows:
            h.event_labels = []
            h.event_times = []
            h.event_frames = []
            h.event_annotations = []
            h.event_metadata = []
            h.event_label_meta = []
            plot_host = getattr(h, "plot_host", None)
            if plot_host is not None:
                plot_host.set_annotation_entries([])
                plot_host.set_events([], labels=[], label_meta=[])
                h._refresh_event_annotation_artists()
        else:
            h.event_text_objects = []
            h._apply_current_style()
        h._refresh_overview_events()
        return

    def _apply_event_rows_to_current_sample(self, rows: list[tuple]) -> None:
        h = self._host
        """Update the current sample's UI state and DataFrame to mirror ``rows``."""

        sample = getattr(h, "current_sample", None)
        if sample is None:
            return
        normalized = normalize_event_table_rows(rows)
        if normalized:
            df = events_dataframe_from_rows(normalized)
            sample.events_data = df
        else:
            sample.events_data = None
        state = getattr(sample, "ui_state", None)
        if not isinstance(state, dict):
            state = {}
            sample.ui_state = state
        state["event_table_data"] = list(normalized or [])
        h.project_state[id(sample)] = state

    def handle_table_edit(self, row: int, new_val: float, old_val: float):
        h = self._host
        if row >= len(h.event_table_data):
            return

        rounded_val = round(float(new_val), 2)
        row_data = list(h.event_table_data[row])
        time = row_data[1]

        if len(row_data) == 5:
            od_val = row_data[3]
            frame = row_data[4]
            h.event_table_data[row] = (
                row_data[0],
                time,
                rounded_val,
                od_val,
                frame,
            )
        else:
            frame = row_data[3] if len(row_data) > 3 else 0
            h.event_table_data[row] = (
                row_data[0],
                time,
                rounded_val,
                frame,
            )

        h.last_replaced_event = (row, old_val)

        cmd = ReplaceEventCommand(h, row, old_val, rounded_val)
        h.undo_stack.push(cmd)
        log.info("ID updated at %.2fs → %.2f µm", time, rounded_val)
        event_label = row_data[0] if row_data else ""
        h._change_log.record_event_value_edit(row, old_val, rounded_val, event_label)
        h._mark_row_edited(row)
        h.mark_session_dirty()
        h._sync_event_data_from_table()

    def handle_event_label_edit(self, row: int, new_label: str, old_label: str) -> None:
        h = self._host
        if not (0 <= row < len(h.event_table_data)):
            return

        label_text = "" if new_label is None else str(new_label)
        row_data = list(h.event_table_data[row])
        if not row_data or row_data[0] == label_text:
            return

        row_data[0] = label_text
        h.event_table_data[row] = tuple(row_data)
        h._change_log.record_event_label_edit(row, old_label, label_text)

        if not hasattr(h, "event_labels") or h.event_labels is None:
            h.event_labels = []
        if len(h.event_labels) < len(h.event_table_data):
            h.event_labels.extend(
                "" for _ in range(len(h.event_table_data) - len(h.event_labels))
            )
        if row < len(h.event_labels):
            h.event_labels[row] = label_text
        else:
            h.event_labels.append(label_text)

        h._ensure_event_meta_length(len(h.event_table_data))
        h._mark_row_edited(row)
        h.apply_event_label_overrides(h.event_labels, h.event_label_meta)

    def populate_event_table_from_df(self, df):
        h = self._host
        rows = []
        has_od = any(col.lower().startswith("od") or "outer" in col.lower() for col in df.columns)
        has_avg_p = any("avg" in col.lower() and "pressure" in col.lower() for col in df.columns)
        has_set_p = any("set" in col.lower() and "pressure" in col.lower() for col in df.columns)

        for _, item in df.iterrows():
            label = item.get("EventLabel", item.get("Event", ""))
            time_val = item.get("Time (s)", item.get("Time", 0.0))
            id_val = item.get("ID (µm)", item.get("Inner Diameter", 0.0))
            frame_val = item.get("Frame", 0)

            try:
                time_val = float(time_val)
            except (TypeError, ValueError):
                time_val = 0.0

            try:
                id_val = float(id_val)
            except (TypeError, ValueError):
                id_val = 0.0

            od_val = None
            if has_od:
                od_val = item.get("OD (µm)", item.get("Outer Diameter", None))
                try:
                    od_val = float(od_val) if od_val is not None else None
                except (TypeError, ValueError):
                    od_val = None

            avg_p_val = None
            if has_avg_p:
                avg_p_val = item.get("Avg P (mmHg)", item.get("Avg Pressure (mmHg)", None))
                try:
                    avg_p_val = float(avg_p_val) if avg_p_val is not None else None
                except (TypeError, ValueError):
                    avg_p_val = None

            set_p_val = None
            if has_set_p:
                set_p_val = item.get("Set P (mmHg)", item.get("Set Pressure (mmHg)", None))
                try:
                    set_p_val = float(set_p_val) if set_p_val is not None else None
                except (TypeError, ValueError):
                    set_p_val = None

            try:
                frame_val = int(frame_val)
            except (TypeError, ValueError):
                frame_val = 0

            # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
            rows.append((str(label), time_val, id_val, od_val, avg_p_val, set_p_val, frame_val))

        h.event_table_data = rows
        h.event_label_meta = [h._with_default_review_state(None) for _ in rows]
        h.event_table_controller.set_events(
            rows,
            has_outer_diameter=has_od,
            has_avg_pressure=has_avg_p,
            has_set_pressure=has_set_p,
            review_states=h._current_review_states(),
        )
        h._apply_event_table_column_contract()
        h._update_excel_controls()

    def update_event_label_positions(self, event=None):
        h = self._host
        """Legacy hook; annotation lane handles positioning automatically."""
        return

    def _selected_event_rows(self) -> list[int]:
        h = self._host
        event_table = getattr(h, "event_table", None)
        if event_table is None:
            return []
        selection = event_table.selectionModel()
        if selection is None:
            return []
        return sorted({index.row() for index in selection.selectedIndexes() if index.isValid()})

    def _on_event_table_selection_changed(self, *_args) -> None:
        h = self._host
        if h._event_table_updating or h._event_selection_syncing:
            return
        event_table = getattr(h, "event_table", None)
        if event_table is None or not event_table.isEnabled():
            return
        rows = h._selected_event_rows()
        if not rows:
            plot_host = getattr(h, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "set_selected_event_index"):
                with contextlib.suppress(Exception):
                    plot_host.set_selected_event_index(None)
            return
        target_row = pick_event_row(rows, h.event_table_data)
        if target_row is None:
            return
        h._focus_event_row(target_row, source="selection")

    def _focus_event_row(self, row: int, *, source: str) -> None:
        h = self._host
        if not h.event_table_data or not (0 <= row < len(h.event_table_data)):
            return
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_selected_event_index"):
            with contextlib.suppress(Exception):
                plot_host.set_selected_event_index(int(row))

        # Sync review panel if active (unless source is already review_controller)
        if hasattr(h, "review_controller") and source != "review_controller":
            if h.review_controller.is_active():
                h.review_controller.sync_to_event(row)

        event_time = event_time_for_row(h.event_table_data[row])
        if event_time is None:
            h._warn_event_sync("Event time missing for selected row; selection ignored.")
            return
        if h.trace_time is None or len(h.trace_time) == 0:
            h._warn_event_sync("Trace timebase unavailable; selection ignored.")
            return
        if not h._event_time_in_range(event_time):
            h._warn_event_sync(
                f"Event time {event_time:.3f}s outside trace range; selection ignored."
            )
            return
        label_value = ""
        with contextlib.suppress(Exception):
            label_value = str(h.event_table_data[row][0] or "").strip()
        status_text = (
            f"Event {row + 1}: {label_value} @ {event_time:.3f}s"
            if label_value
            else f"Event {row + 1} @ {event_time:.3f}s"
        )
        with contextlib.suppress(Exception):
            h.statusBar().showMessage(status_text, 4000)

        if source not in {"table", "selection"}:
            model = h.event_table.model()
            if model is not None:
                index = model.index(row, 0)
                selection = h.event_table.selectionModel()
                h._event_selection_syncing = True
                try:
                    if selection is not None:
                        selection.blockSignals(True)
                    h.event_table.selectRow(row)
                finally:
                    if selection is not None:
                        selection.blockSignals(False)
                    h._event_selection_syncing = False
                h.event_table.scrollTo(index)

        frame_idx_raw = h._frame_index_from_event_row(row)
        frame_idx = frame_idx_raw
        frame_idx_from_time = None
        if frame_idx is None and event_time is not None:
            frame_idx_from_time = h._frame_index_for_time_canonical(event_time)
            frame_idx = frame_idx_from_time

        _log_time_sync(
            "EVENT_FOCUS",
            source=source,
            row=row,
            event_time=event_time,
            frame_from_row=frame_idx_raw,
            frame_from_time=frame_idx_from_time,
            target_frame=frame_idx,
        )

        h.jump_to_time(event_time, from_event=True, source="event")
        h._on_view_state_changed(reason="event focus")

    def _highlight_selected_event(self, event_time: float) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None:
            return

        h._time_cursor_time = float(event_time)
        plot_host.set_time_cursor(
            h._time_cursor_time,
            visible=h._time_cursor_visible,
        )
        plot_host.set_event_highlight_style(
            color=h._event_highlight_color,
            alpha=h._event_highlight_base_alpha,
        )
        plot_host.highlight_event(h._time_cursor_time, visible=True)

        h._event_highlight_timer.stop()
        h._event_highlight_elapsed_ms = 0
        if h._event_highlight_duration_ms > 0:
            interval = max(16, min(100, h._event_highlight_duration_ms // 30 or 16))
            h._event_highlight_timer.setInterval(interval)
            h._event_highlight_timer.start()
        h._on_view_state_changed(reason="event highlight")

    def _clear_event_highlight(self) -> None:
        h = self._host
        timer = getattr(h, "_event_highlight_timer", None)
        if timer is not None:
            timer.stop()
        h._event_highlight_elapsed_ms = 0
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None:
            plot_host.highlight_event(None, visible=False)
            plot_host.set_event_highlight_alpha(h._event_highlight_base_alpha)

    def _on_event_highlight_tick(self) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None:
            h._event_highlight_timer.stop()
            return
        if h._event_highlight_duration_ms <= 0:
            h._event_highlight_timer.stop()
            return
        interval = h._event_highlight_timer.interval()
        h._event_highlight_elapsed_ms += interval
        progress = h._event_highlight_elapsed_ms / float(h._event_highlight_duration_ms)
        if progress >= 1.0:
            h._event_highlight_timer.stop()
            plot_host.highlight_event(None, visible=False)
            plot_host.set_event_highlight_alpha(h._event_highlight_base_alpha)
            return
        remaining = max(0.0, 1.0 - progress)
        plot_host.set_event_highlight_alpha(h._event_highlight_base_alpha * remaining)

    def _frame_index_from_event_row(self, row: int) -> int | None:
        h = self._host
        """
        Return the legacy trace/frame hint from the event table, if present.

        This value comes from imported event tables and is not the canonical
        video frame. Event sync is driven by event time.
        """

        if not (0 <= row < len(h.event_table_data)):
            return None

        data = h.event_table_data[row]
        frame_val = None
        if len(data) >= 5:
            frame_val = data[4]
        elif len(data) >= 4:
            frame_val = data[3]

        try:
            frame_idx = int(frame_val)
        except (TypeError, ValueError):
            return None
        if frame_idx < 0:
            return None
        return frame_idx

    def _nearest_event_index(self, time_value: float) -> int | None:
        h = self._host
        if not h.event_times:
            return None
        try:
            times = np.asarray(h.event_times, dtype=float)
        except (TypeError, ValueError):
            return None
        if times.size == 0:
            return None
        idx = int(np.argmin(np.abs(times - time_value)))
        return idx

    def _warn_event_sync(self, message: str) -> None:
        h = self._host
        log.warning("Event sync: %s", message)
        status = getattr(h, "statusBar", None)
        if callable(status):
            status().showMessage(message, 4000)

    def _event_time_in_range(self, event_time: float) -> bool:
        h = self._host
        if h.trace_time is None or len(h.trace_time) == 0:
            return False
        t_min = float(np.nanmin(h.trace_time))
        t_max = float(np.nanmax(h.trace_time))
        if not (np.isfinite(t_min) and np.isfinite(t_max)):
            return False
        eps = 1e-6
        return (t_min - eps) <= event_time <= (t_max + eps)

    def _ensure_event_meta_length(self, length: int | None = None) -> None:
        h = self._host
        if length is None:
            length = len(h.event_labels)
        length = max(int(length), 0)
        h._normalize_event_label_meta(length)

    def _normalize_event_label_meta(self, length: int | None = None) -> None:
        h = self._host
        target_len = len(h.event_table_data) if length is None else length
        current = list(getattr(h, "event_label_meta", []) or [])
        if len(current) < target_len:
            current.extend({} for _ in range(target_len - len(current)))
        elif len(current) > target_len:
            current = current[:target_len]
        normalized: list[dict[str, Any]] = []
        for meta in current:
            normalized.append(h._with_default_review_state(meta))
        h.event_label_meta = normalized

    def _insert_event_meta(self, index: int, meta: dict[str, Any] | None = None) -> None:
        h = self._host
        payload = h._with_default_review_state(meta)
        if not hasattr(h, "event_label_meta"):
            h.event_label_meta = [payload]
            # CRITICAL FIX (Bug #2): Mark sample state dirty when event metadata changes
            h._sample_state_dirty = True
            return
        index = max(0, min(int(index), len(h.event_label_meta)))
        h.event_label_meta.insert(index, payload)
        # CRITICAL FIX (Bug #2): Mark sample state dirty when event metadata changes
        h._sample_state_dirty = True

    def _delete_event_meta(self, index: int) -> None:
        h = self._host
        if not hasattr(h, "event_label_meta"):
            return
        if 0 <= index < len(h.event_label_meta):
            del h.event_label_meta[index]
            # CRITICAL FIX (Bug #2): Mark sample state dirty when event metadata changes
            h._sample_state_dirty = True

    def _with_default_review_state(meta: Mapping[str, Any] | None) -> dict[str, Any]:
        h = self._host
        payload = dict(meta or {})
        state = payload.get("review_state")
        if isinstance(state, str) and state.strip():
            payload["review_state"] = state.strip().upper().replace(" ", "_").replace("-", "_")
        else:
            payload["review_state"] = REVIEW_UNREVIEWED
        return payload

    def _current_review_states(self) -> list[str]:
        h = self._host
        h._normalize_event_label_meta(len(h.event_table_data))
        return [meta.get("review_state", REVIEW_UNREVIEWED) for meta in h.event_label_meta]

    def _fallback_restore_review_states(self, event_count: int) -> None:
        h = self._host
        """
        CRITICAL FIX (Bug #3): Fallback method to restore review states when deserialization fails.

        Tries multiple strategies:
        1. Load review states from current sample's events DataFrame (if Bug #1 fix is in place)
        2. Preserve existing event_label_meta if available
        3. Default to UNREVIEWED as last resort

        Args:
            event_count: Number of events to create metadata for
        """
        review_states_restored = False

        # Strategy 1: Try to load from current sample's events DataFrame
        try:
            if (
                hasattr(h, "current_sample")
                and h.current_sample is not None
                and hasattr(h.current_sample, "events_data")
                and h.current_sample.events_data is not None
            ):
                events_df = h.current_sample.events_data
                if "review_state" in events_df.columns:
                    states = events_df["review_state"].tolist()
                    if len(states) == event_count:
                        h.event_label_meta = [{"review_state": str(state)} for state in states]
                        review_states_restored = True
                        log.info(f"Restored {len(states)} review states from events DataFrame")
        except Exception as e:
            log.debug(f"Could not restore review states from DataFrame: {e}")

        # Strategy 2: Preserve existing event_label_meta if it exists and has the right length
        if not review_states_restored and hasattr(h, "event_label_meta"):
            existing = getattr(h, "event_label_meta", [])
            if isinstance(existing, list) and len(existing) == event_count:
                # Keep existing - already has review states
                log.info(f"Preserved {len(existing)} existing review states from event_label_meta")
                review_states_restored = True

        # Strategy 3: Default to UNREVIEWED as last resort
        if not review_states_restored:
            h.event_label_meta = [
                h._with_default_review_state(None) for _ in range(event_count)
            ]
            log.warning(
                f"Could not restore review states - defaulted {event_count} events to UNREVIEWED"
            )

    def _set_review_state_for_row(self, index: int, state: str) -> None:
        h = self._host
        if not hasattr(h, "event_label_meta"):
            h.event_label_meta = []
        h._normalize_event_label_meta(len(h.event_table_data))
        if 0 <= index < len(h.event_label_meta):
            old_state = h.event_label_meta[index].get("review_state", "UNREVIEWED")
            h.event_label_meta[index]["review_state"] = state
            if old_state != state:
                event_label = ""
                if hasattr(h, "event_table_data") and index < len(h.event_table_data):
                    event_label = h.event_table_data[index][0] if h.event_table_data[index] else ""
                h._change_log.record_review_status_change(index, old_state, state, event_label)
            # CRITICAL FIX (Bug #2): Mark sample state dirty when review state changes
            h._sample_state_dirty = True
            h._update_review_notice_visibility()

    def _refresh_event_annotation_artists(self) -> None:
        h = self._host
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None:
            h.event_text_objects = []
            h._apply_current_style()
            return
        getter = getattr(plot_host, "annotation_text_objects", None)
        if callable(getter):
            h.event_text_objects = list(getter())
        else:
            h.event_text_objects = []
        h._apply_current_style()

    def apply_event_label_overrides(
        h,
        labels: Sequence[str],
        metadata: Sequence[Mapping[str, Any]],
    ) -> None:
        h = self._host
        """Apply per-event label overrides coming from the style editor."""

        if labels is None or metadata is None:
            return
        new_labels = list(labels)
        existing_states = h._current_review_states()
        new_meta = [h._with_default_review_state(entry) for entry in metadata]
        if not new_labels:
            # No events – clear helpers and bail.
            h.event_labels = []
            h.event_label_meta = []
            plot_host = getattr(h, "plot_host", None)
            if plot_host is not None:
                plot_host.set_events([], labels=[], label_meta=[])
                plot_host.set_annotation_entries([])
                h._refresh_event_annotation_artists()
            return

        if len(new_labels) != len(h.event_labels):
            log.warning(
                "Event label override count mismatch (%s vs %s); ignoring update.",
                len(new_labels),
                len(h.event_labels),
            )
            return

        h.event_labels = new_labels
        if len(new_meta) < len(new_labels):
            new_meta.extend(
                h._with_default_review_state(None)
                for _ in range(len(new_labels) - len(new_meta))
            )
        elif len(new_meta) > len(new_labels):
            new_meta = new_meta[: len(new_labels)]
        for idx, state in enumerate(existing_states):
            if idx < len(new_meta):
                new_meta[idx]["review_state"] = state
        h.event_label_meta = [h._with_default_review_state(entry) for entry in new_meta]
        h._normalize_event_label_meta(len(h.event_label_meta))

        # Update table rows in-place so the UI reflects any text edits.
        for idx, label in enumerate(new_labels):
            if idx >= len(h.event_table_data):
                continue
            row = list(h.event_table_data[idx])
            if not row:
                continue
            row[0] = label
            h.event_table_data[idx] = tuple(row)
            controller = getattr(h, "event_table_controller", None)
            if controller is not None:
                controller.update_row(idx, h.event_table_data[idx])
        controller = getattr(h, "event_table_controller", None)
        if controller is not None:
            controller.set_review_states(h._current_review_states())

        # Rebuild annotations and tooltips to reflect the new text.
        annotations: list[AnnotationSpec] = []
        metadata_entries: list[dict[str, Any]] = []
        has_outer = h.trace_data is not None and "Outer Diameter" in h.trace_data.columns
        for idx, label in enumerate(new_labels):
            time_val = float(h.event_times[idx]) if idx < len(h.event_times) else 0.0
            annotations.append(AnnotationSpec(time_s=time_val, label=label))

            tooltip_parts = [label, f"{time_val:.2f} s"]
            if idx < len(h.event_table_data):
                row = h.event_table_data[idx]
                try:
                    id_val = float(row[2])
                    if np.isfinite(id_val):
                        tooltip_parts.append(f"ID {id_val:.2f} µm")
                except Exception:
                    log.debug("Failed to parse inner diameter value", exc_info=True)
                od_idx = 3 if has_outer and len(row) >= 5 else None
                if od_idx is not None:
                    try:
                        od_val = float(row[od_idx])
                        if np.isfinite(od_val):
                            tooltip_parts.append(f"OD {od_val:.2f} µm")
                    except Exception:
                        log.debug("Failed to parse outer diameter value", exc_info=True)
            metadata_entries.append(
                {
                    "time": time_val,
                    "label": label,
                    "tooltip": " · ".join(part for part in tooltip_parts if part),
                }
            )

        h.event_annotations = annotations
        h.event_metadata = metadata_entries

        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None:
            plot_host.set_events(
                h.event_times,
                labels=h.event_labels,
                label_meta=h.event_label_meta,
            )
            visible_entries = h.event_annotations if h._annotation_lane_visible else []
            plot_host.set_annotation_entries(visible_entries)
            h._refresh_event_annotation_artists()
        h.mark_session_dirty()

    def _ensure_event_label_actions(self) -> None:
        h = self._host
        if getattr(h, "_event_label_action_group", None) is not None:
            return

        h._event_label_action_group = QActionGroup(h)
        h._event_label_action_group.setExclusive(True)

        def make_action(text: str, mode: str) -> QAction:
            action = QAction(text, h)
            action.setCheckable(True)
            h._event_label_action_group.addAction(action)

            def _on_toggled(checked: bool, *, value: str = mode) -> None:
                if checked:
                    h._set_event_label_mode(value)

            action.toggled.connect(_on_toggled)
            return action

        h.actEventLabelsOff = make_action("Off", "off")
        h.actEventLabelsVertical = make_action("Indices", "indices")
        h.actEventLabelsHorizontal = make_action("Names on Hover", "names_on_hover")
        h.actEventLabelsOutside = make_action("Names Always", "names_always")

        h._sync_event_controls()

    def _on_event_lines_toggled(self, checked: bool) -> None:
        h = self._host
        h._event_lines_visible = bool(checked)
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None:
            plot_host.set_event_lines_visible(h._event_lines_visible)
        else:
            h._toggle_event_lines_legacy(h._event_lines_visible)
        h._sync_event_controls()
        h._on_view_state_changed(reason="event lines toggled")

    def _on_event_label_mode_auto(self, checked: bool) -> None:
        h = self._host
        if checked:
            h._set_event_label_mode("indices")

    def _on_event_label_mode_all(self, checked: bool) -> None:
        h = self._host
        if checked:
            h._set_event_label_mode("names_always")

    def _set_event_label_mode(self, mode: str) -> None:
        h = self._host
        normalized = mode.lower()
        alias = {
            "auto": "indices",
            "all": "names_always",
            "vertical": "indices",
            "horizontal_outside": "indices",
            "horizontal": "names_always",
            "none": "off",
        }
        normalized = alias.get(normalized, normalized)
        if normalized not in {"off", "indices", "names_on_hover", "names_always"}:
            normalized = "indices"
        if normalized == h._event_label_mode:
            return
        h._apply_event_label_mode(normalized)

    def _apply_event_label_mode(self, mode: str | None = None) -> None:
        h = self._host
        """Central switch for event labels.

        Ensures legacy lane is disabled when helper is active.
        """
        incoming = mode if mode is not None else h._event_label_mode
        mapped = {
            "auto": "indices",
            "all": "names_always",
            "vertical": "indices",
            "horizontal_outside": "indices",
            "horizontal": "names_always",
        }.get(incoming, incoming)
        h._event_label_mode = mapped
        with contextlib.suppress(Exception):
            h.settings.setValue("plot/eventLabelMode", h._event_label_mode)

        # Always tear down the legacy annotation lane FIRST
        h._annotation_lane_visible = False
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None:
            plot_host.set_annotation_entries([])
        else:
            h._refresh_event_annotation_artists()

        if plot_host is None:
            h.canvas.draw_idle()
            h._sync_event_controls()
            h._on_view_state_changed(reason="event label mode")
            return

        set_display_mode = getattr(plot_host, "set_event_display_mode", None)
        if callable(set_display_mode):
            set_display_mode(h._event_label_mode)
        else:
            plot_host.set_event_label_mode(h._event_label_mode)  # fallback
        h._refresh_event_annotation_artists()
        h.canvas.draw_idle()
        h._sync_event_controls()
        h._on_view_state_changed(reason="event label mode")

    def _sync_event_controls(self) -> None:
        h = self._host
        if (
            h.actEventLines is not None
            and h.actEventLines.isChecked() != h._event_lines_visible
        ):
            h.actEventLines.blockSignals(True)
            h.actEventLines.setChecked(h._event_lines_visible)
            h.actEventLines.blockSignals(False)

        if (
            h.menu_event_lines_action is not None
            and h.menu_event_lines_action.isChecked() != h._event_lines_visible
        ):
            h.menu_event_lines_action.blockSignals(True)
            h.menu_event_lines_action.setChecked(h._event_lines_visible)
            h.menu_event_lines_action.blockSignals(False)

        mode = h._event_label_mode
        mapping = {
            "off": h.actEventLabelsOff,
            "indices": h.actEventLabelsVertical,
            "names_on_hover": h.actEventLabelsHorizontal,
            "names_always": h.actEventLabelsOutside,
        }
        for key, action in mapping.items():
            if action is None:
                continue
            should_check = mode == key
            if action.isChecked() != should_check:
                action.blockSignals(True)
                action.setChecked(should_check)
                action.blockSignals(False)

        if h.event_label_button is not None:
            labels = {
                "off": "Labels: Off",
                "indices": "Labels: Indices",
                "names_on_hover": "Labels: Hover",
                "names_always": "Labels: Always",
            }
            h.event_label_button.setText(labels.get(mode, "Labels"))

    def toggle_channel_event_labels(self, checked: bool) -> None:
        h = self._host
        """Show or hide vertical event text labels inside channel tracks."""
        h._channel_event_labels_visible = bool(checked)
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_channel_event_labels_visible"):
            plot_host.set_channel_event_labels_visible(h._channel_event_labels_visible)

    def set_channel_event_label_font_size(self, size_pt: float) -> None:
        h = self._host
        """Set the event label font size and update checked state in the size menu."""
        h._channel_event_label_font_size = float(size_pt)
        # Sync checkmarks in the font-size submenu.
        size_group = getattr(h, "_event_label_font_size_group", None)
        if size_group is not None:
            for action in size_group.actions():
                with contextlib.suppress(Exception):
                    action.setChecked(float(action.data()) == h._channel_event_label_font_size)
        plot_host = getattr(h, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_channel_event_label_font_size"):
            plot_host.set_channel_event_label_font_size(h._channel_event_label_font_size)

    def _overview_event_times(self) -> list[float]:
        h = self._host
        rows = list(getattr(h, "event_table_data", []) or [])
        times: list[float] = []
        if rows:
            for row in rows:
                if len(row) < 2:
                    continue
                try:
                    t_val = float(row[1])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(t_val):
                    times.append(t_val)
            return times
        times = [float(t) for t in getattr(h, "event_times", []) or [] if t is not None]
        return [t for t in times if math.isfinite(t)]

    def _refresh_overview_events(self) -> None:
        h = self._host
        overview = getattr(h, "overview_strip", None)
        if overview is None:
            return
        overview.set_events(h._overview_event_times())

    def _reset_event_table_for_loading(self) -> None:
        h = self._host
        """Clear event table state to avoid stale selections during dataset switches."""
        h._event_table_updating = True
        h._suppress_event_table_sync = True
        try:
            h._set_event_table_enabled(False)
            event_table = getattr(h, "event_table", None)
            selection = event_table.selectionModel() if event_table is not None else None
            if selection is not None:
                selection.blockSignals(True)
                selection.clearSelection()
                selection.blockSignals(False)

            controller = getattr(h, "event_table_controller", None)
            if controller is not None:
                controller.clear()
            else:
                h.event_table_data = []
                h._sync_event_data_from_table()
                h._update_event_table_presence_state(False)
            plot_host = getattr(h, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "set_selected_event_index"):
                with contextlib.suppress(Exception):
                    plot_host.set_selected_event_index(None)
            h._clear_event_highlight()
        finally:
            h._event_table_updating = False
            h._suppress_event_table_sync = False

    def _set_event_table_enabled(self, enabled: bool) -> None:
        h = self._host
        event_table = getattr(h, "event_table", None)
        if event_table is not None:
            event_table.setEnabled(bool(enabled))

    def _set_event_table_visible(self, visible: bool, *, source: str = "user") -> None:
        h = self._host
        event_table = getattr(h, "event_table", None)
        event_table_action = getattr(h, "event_table_action", None)
        if event_table is None:
            return
        action = getattr(h, "event_table_action", None)
        if event_table.isVisible() != visible:
            event_table.setVisible(visible)
        if action is not None and action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        log.debug("UI: Event table visibility updated to %s (source=%s)", visible, source)
        if source == "user":
            h._on_view_state_changed(reason="event table visibility")

    def toggle_event_table(self, checked: bool):
        h = self._host
        h._set_event_table_visible(bool(checked), source="user")

    def _on_event_rows_changed(self) -> None:
        h = self._host
        """Sync cached event state after the table model mutates."""

        controller = getattr(h, "event_table_controller", None)
        if controller is None:
            return
        try:
            rows = controller.rows
        except Exception:
            rows = []
        h.event_table_data = [tuple(row) for row in rows]
        h._sync_event_data_from_table()
        h._update_event_table_presence_state(bool(h.event_table_data))
        if controller is not None:
            controller.set_review_states(h._current_review_states())
        h._update_excel_controls()

    def _update_event_table_presence_state(self, has_events: bool) -> None:
        h = self._host
        h._event_panel_has_data = bool(has_events)
        if has_events:
            h._set_event_table_visible(True, source="data")
        h._update_review_notice_visibility()

    def _event_table_signal_availability(self) -> tuple[bool, bool, bool]:
        h = self._host
        trace = h.trace_data
        has_od = trace is not None and "Outer Diameter" in trace.columns
        avg_label = h._trace_label_for("p_avg")
        set_label = h._trace_label_for("p2")
        has_avg_p = trace is not None and avg_label in trace.columns
        has_set_p = trace is not None and set_label in trace.columns
        return has_od, has_avg_p, has_set_p

    def _event_table_review_mode_active(self) -> bool:
        h = self._host
        controller = getattr(h, "review_controller", None)
        if controller is not None and controller.is_active():
            return True
        wizard = getattr(h, "_event_review_wizard", None)
        return bool(wizard is not None and wizard.isVisible())

    def _apply_event_table_column_contract(self) -> None:
        h = self._host
        controller = getattr(h, "event_table_controller", None)
        if controller is None:
            return
        has_od, has_avg_p, has_set_p = h._event_table_signal_availability()
        show_id = True if h.id_toggle_act is None else h.id_toggle_act.isChecked()
        show_od = bool(h.od_toggle_act.isChecked()) if h.od_toggle_act is not None else False
        show_avg_p = (
            bool(h.avg_pressure_toggle_act.isChecked())
            if h.avg_pressure_toggle_act is not None
            else False
        )
        show_set_p = (
            bool(h.set_pressure_toggle_act.isChecked())
            if h.set_pressure_toggle_act is not None
            else False
        )
        column_keys = build_event_table_column_contract(
            review_mode=h._event_table_review_mode_active(),
            show_id=show_id,
            show_od=show_od,
            show_avg_p=show_avg_p,
            show_set_p=show_set_p,
            has_id=True,
            has_od=has_od,
            has_avg_p=has_avg_p,
            has_set_p=has_set_p,
        )
        controller.apply_column_contract(column_keys)

    def show_event_table_context_menu(self, position):
        h = self._host
        index = h.event_table.indexAt(position)
        if index.isValid():
            selection = h.event_table.selectionModel()
            if selection is not None and not selection.isSelected(index):
                h.event_table.selectRow(index.row())
        row = index.row() if index.isValid() else len(h.event_table_data)
        menu = QMenu()
        has_events = bool(getattr(h, "event_table_data", None))

        # --- Determine multi-selection ---
        selected_rows: list[int] = []
        sel_model = h.event_table.selectionModel()
        if sel_model is not None:
            selected_rows = sorted({idx.row() for idx in sel_model.selectedRows()})
        multi = len(selected_rows) > 1

        # === Row-specific actions ===
        if index.isValid():
            if multi:
                delete_action = menu.addAction(f"🗑️ Delete {len(selected_rows)} Events")
                edit_action = edit_label_action = edit_time_action = None
                edit_od_action = jump_action = pin_action = None
                replace_with_pin_action = duplicate_action = None
                insert_before_action = insert_after_action = None
            else:
                # --- Edit submenu ---
                edit_menu = menu.addMenu("✏️ Edit")
                edit_label_action = edit_menu.addAction("Label…")
                edit_time_action = edit_menu.addAction("Time (s)…")
                edit_action = edit_menu.addAction("ID (µm)…")
                has_od_col = h.trace_data is not None and "Outer Diameter" in h.trace_data.columns
                edit_od_action = edit_menu.addAction("OD (µm)…") if has_od_col else None

                delete_action = menu.addAction("🗑️ Delete Event")
                duplicate_action = menu.addAction("📋 Duplicate Event…")
                menu.addSeparator()

                # --- Insert ---
                insert_before_action = menu.addAction("⬆️ Insert Event Before…")
                insert_after_action = menu.addAction("⬇️ Insert Event After…")
                menu.addSeparator()

                jump_action = menu.addAction("🔍 Jump to Event on Plot")
                pin_action = menu.addAction("📌 Pin to Plot")
                menu.addSeparator()
                replace_with_pin_action = menu.addAction("🔄 Replace ID with Pinned Value")
        else:
            edit_action = delete_action = jump_action = pin_action = None
            replace_with_pin_action = duplicate_action = None
            edit_label_action = edit_time_action = edit_od_action = None
            insert_before_action = insert_after_action = None

        # === Copy submenu ===
        copy_menu = menu.addMenu("Copy")
        copy_row_action = copy_menu.addAction("Row-per-Event (Excel)")
        copy_values_action = copy_menu.addAction("Values Only (Column Paste)")
        copy_profile_menu = copy_menu.addMenu("Profile")
        copy_pressure_action = copy_profile_menu.addAction("Pressure Curve (Standard)")
        for act in (copy_row_action, copy_values_action, copy_pressure_action):
            act.setEnabled(has_events)

        menu.addSeparator()

        # === Undo / Redo ===
        undo_action = menu.addAction("↩️ Undo")
        undo_action.setEnabled(h.undo_stack.canUndo())
        if h.undo_stack.canUndo():
            undo_action.setText(f"↩️ Undo: {h.undo_stack.undoText()}")
        redo_action = menu.addAction("↪️ Redo")
        redo_action.setEnabled(h.undo_stack.canRedo())
        if h.undo_stack.canRedo():
            redo_action.setText(f"↪️ Redo: {h.undo_stack.redoText()}")

        menu.addSeparator()
        clear_pins_action = menu.addAction("❌ Clear All Pins")
        menu.addSeparator()
        add_event_action = menu.addAction("➕ Add Event…")

        # === Renumber ===
        renumber_action = menu.addAction("🔢 Renumber Events")
        renumber_action.setEnabled(has_events)

        action = menu.exec(h.event_table.viewport().mapToGlobal(position))
        if action is None:
            return

        # --- Handle copy actions ---
        if action == copy_row_action:
            h._copy_event_profile_to_clipboard(EVENT_TABLE_ROW_PER_EVENT_ID, include_header=True)
            return
        if action == copy_values_action:
            h._copy_event_profile_to_clipboard(
                EVENT_VALUES_SINGLE_COLUMN_ID, include_header=False
            )
            return
        if action == copy_pressure_action:
            h._copy_event_profile_to_clipboard(PRESSURE_CURVE_STANDARD_ID, include_header=True)
            return

        # --- Handle undo/redo ---
        if action == undo_action:
            h.undo_stack.undo()
            return
        if action == redo_action:
            h.undo_stack.redo()
            return

        # --- Handle renumber ---
        if action == renumber_action:
            self._renumber_events()
            return

        # --- Multi-delete ---
        if multi and action == delete_action:
            h.delete_selected_events(indices=selected_rows)
            return

        if not index.isValid():
            if action == add_event_action:
                h.manual_add_event()
            elif action == clear_pins_action:
                self._clear_all_pins()
            return

        # --- Single-row actions ---
        if action == edit_action:
            if row >= len(h.event_table_data):
                return
            old_val = h.event_table_data[row][2]
            new_val, ok = QInputDialog.getDouble(
                h,
                "Edit ID",
                "Enter new ID (µm):",
                float(old_val) if old_val is not None else 0.0,
                0,
                10000,
                2,
            )
            if ok:
                cmd = ReplaceEventCommand(h, row, old_val, new_val)
                h.undo_stack.push(cmd)

        elif action == edit_label_action:
            self._edit_event_label(row)

        elif action == edit_time_action:
            self._edit_event_time(row)

        elif edit_od_action is not None and action == edit_od_action:
            self._edit_event_od(row)

        elif action == delete_action:
            h.delete_selected_events(indices=[row])

        elif action == duplicate_action:
            self._duplicate_event(row)

        elif action == insert_before_action:
            self._insert_event_relative(row, before=True)

        elif action == insert_after_action:
            self._insert_event_relative(row, before=False)

        elif action == jump_action:
            h._focus_event_row(row, source="context")

        elif action == pin_action:
            plot_host = getattr(h, "plot_host", None)
            is_pyqtgraph = plot_host is not None and plot_host.get_render_backend() == "pyqtgraph"
            if is_pyqtgraph:
                return
            t = h.event_table_data[row][1]
            id_val = h.event_table_data[row][2]
            marker = h.ax.plot(t, id_val, "ro", markersize=6)[0]
            label = h.ax.annotate(
                f"{t:.2f} s\n{round(id_val, 1)} µm",
                xy=(t, id_val),
                xytext=(6, 6),
                textcoords="offset points",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    fc=css_rgba_to_mpl(CURRENT_THEME["hover_label_bg"]),
                    ec=CURRENT_THEME["hover_label_border"],
                    lw=1,
                ),
                fontsize=8,
            )
            h.pinned_points.append((marker, label))
            h.canvas.draw_idle()

        elif index.isValid() and action == replace_with_pin_action:
            t_event = h.event_table_data[row][1]
            if not h.pinned_points:
                QMessageBox.information(h, "No Pins", "There are no pinned points to use.")
                return

            def _pin_time(pin) -> float:
                coords = h._pin_coords(pin[0])
                return coords[0] if coords is not None else float("inf")

            closest_pin = min(h.pinned_points, key=lambda p: abs(_pin_time(p) - t_event))
            coords = h._pin_coords(closest_pin[0])
            if coords is None:
                return
            pin_id = coords[1]
            confirm = QMessageBox.question(
                h,
                "Confirm Replacement",
                f"Replace ID at {t_event:.2f}s with pinned value: {pin_id:.2f} µm?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm == QMessageBox.StandardButton.Yes:
                h.last_replaced_event = (row, h.event_table_data[row][2])
                has_od = h.trace_data is not None and "Outer Diameter" in h.trace_data.columns
                if has_od:
                    h.event_table_data[row] = (
                        h.event_table_data[row][0],
                        t_event,
                        round(pin_id, 2),
                        h.event_table_data[row][3],
                        h.event_table_data[row][4],
                    )
                else:
                    h.event_table_data[row] = (
                        h.event_table_data[row][0],
                        t_event,
                        round(pin_id, 2),
                        h.event_table_data[row][3],
                    )
                h.event_table_controller.update_row(row, h.event_table_data[row])
                h._mark_row_edited(row)
                h.auto_export_table()
                log.info(
                    "Replaced ID at %.2fs with pinned value %.2f µm.",
                    t_event,
                    pin_id,
                )
                h.mark_session_dirty()

        elif action == clear_pins_action:
            self._clear_all_pins()

        elif action == add_event_action:
            h.manual_add_event()

    # ------------------------------------------------------------------
    # Context-menu helper actions
    # ------------------------------------------------------------------

    def _clear_all_pins(self) -> None:
        h = self._host
        if not h.pinned_points:
            QMessageBox.information(h, "No Pins", "There are no pins to clear.")
            return
        for marker, label in h.pinned_points:
            h._safe_remove_artist(marker)
            h._safe_remove_artist(label)
        h.pinned_points.clear()
        h.canvas.draw_idle()
        log.info("Cleared all pins.")
        h.mark_session_dirty()

    def _edit_event_label(self, row: int) -> None:
        h = self._host
        if row < 0 or row >= len(h.event_table_data):
            return
        old_label = h.event_table_data[row][0]
        new_label, ok = QInputDialog.getText(
            h, "Edit Label", "Event label:", text=str(old_label)
        )
        if not ok or not new_label.strip():
            return
        entry = list(h.event_table_data[row])
        entry[0] = new_label.strip()
        h.event_table_data[row] = tuple(entry)
        if row < len(h.event_labels):
            h.event_labels[row] = new_label.strip()
        h.event_table_controller.update_row(row, h.event_table_data[row])
        h._mark_row_edited(row)
        h.update_plot()
        h.auto_export_table()
        h.mark_session_dirty()

    def _edit_event_time(self, row: int) -> None:
        h = self._host
        if row < 0 or row >= len(h.event_table_data):
            return
        old_time = float(h.event_table_data[row][1])
        new_time, ok = QInputDialog.getDouble(
            h, "Edit Time", "Time (s):", old_time, 0, 1e6, 2
        )
        if not ok:
            return
        entry = list(h.event_table_data[row])
        entry[1] = round(new_time, 2)
        h.event_table_data[row] = tuple(entry)
        if row < len(h.event_times):
            h.event_times[row] = round(new_time, 2)
        h.event_table_controller.update_row(row, h.event_table_data[row])
        h._mark_row_edited(row)
        h.update_plot()
        h.auto_export_table()
        h.mark_session_dirty()

    def _edit_event_od(self, row: int) -> None:
        h = self._host
        if row < 0 or row >= len(h.event_table_data):
            return
        entry = list(h.event_table_data[row])
        # OD is at index 3 in the EventRow tuple
        old_od = float(entry[3]) if entry[3] is not None else 0.0
        new_od, ok = QInputDialog.getDouble(
            h, "Edit OD", "OD (µm):", old_od, 0, 1e6, 2
        )
        if not ok:
            return
        entry[3] = round(new_od, 2)
        h.event_table_data[row] = tuple(entry)
        h.event_table_controller.update_row(row, h.event_table_data[row])
        h._mark_row_edited(row)
        h.auto_export_table()
        h.mark_session_dirty()

    def _duplicate_event(self, row: int) -> None:
        h = self._host
        if row < 0 or row >= len(h.event_table_data):
            return
        src = h.event_table_data[row]
        label = f"{src[0]} (copy)"
        new_label, ok = QInputDialog.getText(
            h, "Duplicate Event", "Label for duplicate:", text=label
        )
        if not ok or not new_label.strip():
            return
        new_entry = (new_label.strip(),) + src[1:]
        insert_idx = row + 1
        cmd = AddEventCommand(h, insert_idx, new_entry)
        h.undo_stack.push(cmd)
        h._focus_event_row(insert_idx, source="manual")

    def _insert_event_relative(self, row: int, *, before: bool = True) -> None:
        """Insert a new event before or after *row* using a dialog."""
        h = self._host
        if h.trace_data is None or "Time (s)" not in h.trace_data.columns:
            QMessageBox.warning(h, "No Trace", "Load a trace before adding events.")
            return

        insert_idx = row if before else row + 1
        default_label = f"Event {len(h.event_table_data) + 1}"
        label, ok = QInputDialog.getText(
            h, "New Event", "Event label:", text=default_label
        )
        if not ok or not label.strip():
            return

        # Default time: midpoint between neighbors, or neighbor time
        if insert_idx > 0 and insert_idx < len(h.event_table_data):
            t_before = float(h.event_table_data[insert_idx - 1][1])
            t_after = float(h.event_table_data[insert_idx][1])
            default_time = round((t_before + t_after) / 2, 2)
        elif insert_idx > 0:
            default_time = float(h.event_table_data[insert_idx - 1][1])
        elif h.event_table_data:
            default_time = float(h.event_table_data[0][1])
        else:
            default_time = 0.0

        t_val, ok = QInputDialog.getDouble(
            h, "Event Time", "Time (s):", default_time, 0, 1e6, 2
        )
        if not ok:
            return

        id_val, od_val, avg_p, set_p = h._sample_values_at_time(t_val)
        times = h.trace_data["Time (s)"].to_numpy(dtype=float)
        frame = int(np.argmin(np.abs(times - t_val))) if times.size > 0 else 0

        def _ro(v: float | None) -> float | None:
            if v is None:
                return None
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return round(f, 2) if np.isfinite(f) else None

        new_entry = (
            label.strip(),
            round(t_val, 2),
            _ro(id_val),
            _ro(od_val),
            _ro(avg_p),
            _ro(set_p),
            frame,
        )
        cmd = AddEventCommand(h, insert_idx, new_entry)
        h.undo_stack.push(cmd)
        h._focus_event_row(insert_idx, source="manual")

    def _renumber_events(self) -> None:
        """Renumber all event labels sequentially (Event 1, Event 2, …)."""
        h = self._host
        if not h.event_table_data:
            return
        prefix, ok = QInputDialog.getText(
            h, "Renumber Events", "Label prefix:", text="Event"
        )
        if not ok or not prefix.strip():
            return
        prefix = prefix.strip()
        for i in range(len(h.event_table_data)):
            entry = list(h.event_table_data[i])
            entry[0] = f"{prefix} {i + 1}"
            h.event_table_data[i] = tuple(entry)
            if i < len(h.event_labels):
                h.event_labels[i] = entry[0]
        h.populate_table()
        h.update_plot()
        h.auto_export_table()
        h.mark_session_dirty()

    def load_events(self, labels, diam_before, od_before=None):
        h = self._host
        h.event_labels = list(labels)
        h.event_label_meta = [h._with_default_review_state(None) for _ in h.event_labels]
        h.event_table_data = []
        has_od = od_before is not None
        # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
        for lbl, diam, od in zip(
            labels,
            diam_before,
            od_before if has_od else [None] * len(labels),
            strict=False,
        ):
            h.event_table_data.append((lbl, 0.0, diam, od, None, None, 0))
        h.populate_table()

    def _load_events_from_path(self, file_path: str) -> bool:
        h = self._host
        try:
            labels, times, frames = load_events(file_path)
        except Exception as exc:
            QMessageBox.critical(
                h,
                "Events Load Error",
                f"Could not load events:\n{exc}",
            )
            return False

        if not labels:
            QMessageBox.information(
                h, "No Events Found", "The selected file contained no events."
            )
            return False

        if frames is None:
            frames = [0] * len(labels)

        h.load_project_events(labels, times, frames, None, None, auto_export=True)
        h._last_event_import = h._sanitize_import_metadata(
            {
                "events_original_filename": os.path.basename(file_path),
                "manual": True,
                "import_timestamp": h._utc_iso_timestamp(),
                "import_source": "file_dialog",
            }
        )
        if h.current_sample is not None:
            meta = dict(h.current_sample.import_metadata or {})
            meta.update(h._last_event_import)
            h.current_sample.import_metadata = h._sanitize_import_metadata(meta)
        h._event_table_path = str(file_path)
        h.statusBar().showMessage(f"{len(labels)} events loaded", 3000)
        h.mark_session_dirty()
        return True

    def _handle_load_events(self):
        h = self._host
        if h.trace_data is None:
            QMessageBox.warning(
                h,
                "No Trace Loaded",
                "Load a trace before importing events so they can be aligned.",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            h,
            "Select Events File",
            "",
            "Table Files (*.csv *.tsv *.txt);;All Files (*)",
        )
        if not file_path:
            return
        h._load_events_from_path(file_path)

    def _review_notice_key(self) -> tuple:
        h = self._host
        sample = getattr(h, "current_sample", None)
        if sample is None:
            return ("session",)
        dataset_id = getattr(sample, "dataset_id", None)
        sample_id = getattr(sample, "id", None)
        if sample_id is None:
            sample_id = id(sample)
        sample_name = getattr(sample, "name", None)
        return (dataset_id, sample_id, sample_name)

    def _configure_review_notice_banner(self) -> None:
        h = self._host
        if not hasattr(h, "review_notice_review_button"):
            return
        tooltip = None
        if hasattr(h, "review_events_action") and h.review_events_action is not None:
            tooltip = h.review_events_action.toolTip() or None
        h.review_notice_review_button.setToolTip(
            tooltip or "Open the review panel to confirm or edit event values"
        )
        h.review_notice_dismiss_button.setToolTip("Hide this notice for the current dataset")

    def _dismiss_review_notice(self) -> None:
        h = self._host
        h._review_notice_dismissed_key = h._review_notice_key()
        h._update_review_notice_visibility()

    def _update_review_notice_visibility(self) -> None:
        h = self._host
        """Update the non-blocking review notice based on review state."""
        if getattr(h, "_suppress_review_prompt", False):
            return

        banner = getattr(h, "review_notice_banner", None)
        if banner is None:
            return

        if not getattr(h, "event_table_data", None):
            banner.setVisible(False)
            return

        review_states = (
            h._current_review_states() if hasattr(h, "_current_review_states") else []
        )
        if not review_states:
            banner.setVisible(False)
            return

        has_unreviewed = any(state == REVIEW_UNREVIEWED for state in review_states)
        if not has_unreviewed:
            banner.setVisible(False)
            return

        dismissed = h._review_notice_dismissed_key == h._review_notice_key()
        banner.setVisible(not dismissed)

    def _launch_event_review_wizard(self) -> None:
        h = self._host
        if h._event_review_wizard is not None and h._event_review_wizard.isVisible():
            with contextlib.suppress(Exception):
                h._event_review_wizard.raise_()
                h._event_review_wizard.activateWindow()
            return

        if not h.event_table_data:
            QMessageBox.information(h, "No Events", "Load events before starting a review.")
            return

        events = [tuple(row) for row in h.event_table_data]
        review_states = h._current_review_states()

        def _focus(idx: int, event_data: tuple | None = None) -> None:
            h._current_review_event_index = idx
            try:
                h._focus_event_row(int(idx), source="wizard")
            except Exception:
                log.debug("Unable to focus event row %s from wizard", idx, exc_info=True)

        dialog = EventReviewWizard(
            h,
            events=events,
            review_states=review_states,
            focus_event_callback=_focus,
            sample_values_callback=h._sample_values_at_time,
        )
        h._event_review_wizard = dialog
        flags = dialog.windowFlags()
        dialog.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.accepted.connect(h._apply_event_review_changes)
        dialog.rejected.connect(h._cleanup_event_review_wizard)
        dialog.finished.connect(h._cleanup_event_review_wizard)
        dialog.show()
        with contextlib.suppress(Exception):
            dialog.raise_()
            dialog.activateWindow()
        h._apply_event_table_column_contract()

    def _apply_event_review_changes(self) -> None:
        h = self._host
        wizard = getattr(h, "_event_review_wizard", None)
        if wizard is None:
            return

        updated_events = wizard.updated_events()
        updated_states = wizard.updated_review_states()
        if updated_events:
            h.event_table_data = [tuple(row) for row in updated_events]
        if updated_states:
            h._normalize_event_label_meta(len(h.event_table_data))
            for idx, state in enumerate(updated_states):
                h._set_review_state_for_row(idx, state)

        # CRITICAL FIX (Bug #2): Mark sample state dirty after review changes applied
        # (Note: _set_review_state_for_row also sets this, but setting here ensures it's set
        # even if only event data changed without state changes)
        h._sample_state_dirty = True

        h.populate_table()
        h._sync_event_data_from_table()
        h.mark_session_dirty()
        h._prompt_export_event_table_after_review()

    def _cleanup_event_review_wizard(self, *args) -> None:
        h = self._host
        h._event_review_wizard = None
        h._current_review_event_index = None
        h._apply_event_table_column_contract()

    def _prompt_export_event_table_after_review(self) -> None:
        h = self._host
        """
        Offer to export the updated event table after a review session completes.
        """
        if not getattr(h, "event_table_data", None):
            return

        path = h._event_table_path

        if path:
            msg = QMessageBox(h)
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setWindowTitle("Export updated event table?")
            msg.setText(
                "You reviewed and updated the event table.\n\n"
                f"Do you want to save these changes to:\n{path}"
            )
            overwrite_btn = msg.addButton("Export", QMessageBox.ButtonRole.AcceptRole)
            choose_btn = msg.addButton("Choose different path…", QMessageBox.ButtonRole.ActionRole)
            later_btn = msg.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(overwrite_btn)
            msg.exec()
            clicked = msg.clickedButton()

            if clicked is overwrite_btn:
                if not h._export_event_table_to_path(path):
                    h._export_event_table_via_dialog()
            elif clicked is choose_btn:
                h._export_event_table_via_dialog()
        else:
            msg = QMessageBox(h)
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setWindowTitle("Export updated event table?")
            msg.setText(
                "You reviewed and updated the event table.\n\n"
                "Do you want to export these values to a file?"
            )
            export_btn = msg.addButton("Export…", QMessageBox.ButtonRole.AcceptRole)
            later_btn = msg.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(export_btn)
            msg.exec()

            if msg.clickedButton() is export_btn:
                h._export_event_table_via_dialog()

    def _sync_sample_events_dataframe(self, sample_state: dict) -> None:
        h = self._host
        """Ensure the current sample's events_data mirrors the table rows in sample_state."""
        sample = getattr(h, "current_sample", None)
        if sample is None:
            return
        rows = list(sample_state.get("event_table_data") or [])
        normalized_rows = normalize_event_table_rows(rows)
        if normalized_rows:
            df = events_dataframe_from_rows(normalized_rows)
            sample.events_data = df
        else:
            sample.events_data = None
