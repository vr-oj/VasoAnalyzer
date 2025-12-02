# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# mypy: ignore-errors

"""Event handling mixin for VasoAnalyzer main window.

This mixin contains all event-related functionality including:
- Event table population and management
- Event label positioning and styling
- Event highlighting and navigation
- Event addition, deletion, and editing
- Context menu operations
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QInputDialog,
    QMenu,
    QMessageBox,
)

from vasoanalyzer.ui.commands import ReplaceEventCommand
from vasoanalyzer.ui.plots.overlays import AnnotationSpec
from vasoanalyzer.ui.theme import CURRENT_THEME, css_rgba_to_mpl

log = logging.getLogger(__name__)


class EventMixin:
    """Mixin providing event handling functionality."""

    def _refresh_event_annotation_artists(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            self.event_text_objects = []
            self._apply_current_style()
            return
        getter = getattr(plot_host, "annotation_text_objects", None)
        if callable(getter):
            self.event_text_objects = list(getter())
        else:
            self.event_text_objects = []
        self._apply_current_style()

    def _on_event_rows_changed(self) -> None:
        """Sync cached event state after the table model mutates."""

        controller = getattr(self, "event_table_controller", None)
        if controller is None:
            return
        try:
            rows = controller.rows
        except Exception:
            rows = []
        self.event_table_data = [tuple(row) for row in rows]
        self._sync_event_data_from_table()

    def _ensure_event_meta_length(self, length: int | None = None) -> None:
        if length is None:
            length = len(self.event_labels)
        length = max(int(length), 0)
        current = list(getattr(self, "event_label_meta", []))
        if len(current) < length:
            current.extend({} for _ in range(length - len(current)))
        elif len(current) > length:
            current = current[:length]
        self.event_label_meta = current

    def _insert_event_meta(self, index: int, meta: dict[str, Any] | None = None) -> None:
        payload = dict(meta or {})
        if not hasattr(self, "event_label_meta"):
            self.event_label_meta = [payload]
            return
        index = max(0, min(int(index), len(self.event_label_meta)))
        self.event_label_meta.insert(index, payload)

    def _delete_event_meta(self, index: int) -> None:
        if not hasattr(self, "event_label_meta"):
            return
        if 0 <= index < len(self.event_label_meta):
            del self.event_label_meta[index]

    def _sync_event_data_from_table(self) -> None:
        """Recompute cached event arrays, metadata, and annotation entries."""

        rows = list(getattr(self, "event_table_data", []) or [])
        if not rows:
            self.event_labels = []
            self.event_times = []
            self.event_frames = []
            self.event_annotations = []
            self.event_metadata = []
            self.event_label_meta = []
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                plot_host.set_annotation_entries([])
                plot_host.set_events([], labels=[], label_meta=[])
                self._refresh_event_annotation_artists()
        else:
            self.event_text_objects = []
            self._apply_current_style()
        return

    def apply_event_label_overrides(
        self,
        labels: Sequence[str],
        metadata: Sequence[Mapping[str, Any]],
    ) -> None:
        """Apply per-event label overrides coming from the style editor."""

        if labels is None or metadata is None:
            return
        new_labels = list(labels)
        new_meta = [dict(entry or {}) for entry in metadata]
        if not new_labels:
            # No events – clear helpers and bail.
            self.event_labels = []
            self.event_label_meta = []
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                plot_host.set_events([], labels=[], label_meta=[])
                plot_host.set_annotation_entries([])
                self._refresh_event_annotation_artists()
            return

        if len(new_labels) != len(self.event_labels):
            log.warning(
                "Event label override count mismatch (%s vs %s); ignoring update.",
                len(new_labels),
                len(self.event_labels),
            )
            return

        self.event_labels = new_labels
        if len(new_meta) < len(new_labels):
            new_meta.extend({} for _ in range(len(new_labels) - len(new_meta)))
        elif len(new_meta) > len(new_labels):
            new_meta = new_meta[: len(new_labels)]
        self.event_label_meta = new_meta

        # Update table rows in-place so the UI reflects any text edits.
        for idx, label in enumerate(new_labels):
            if idx >= len(self.event_table_data):
                continue
            row = list(self.event_table_data[idx])
            if not row:
                continue
            row[0] = label
            self.event_table_data[idx] = tuple(row)
            controller = getattr(self, "event_table_controller", None)
            if controller is not None:
                controller.update_row(idx, self.event_table_data[idx])

        # Rebuild annotations and tooltips to reflect the new text.
        annotations: list[AnnotationSpec] = []
        metadata_entries: list[dict[str, Any]] = []
        has_outer = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
        for idx, label in enumerate(new_labels):
            time_val = float(self.event_times[idx]) if idx < len(self.event_times) else 0.0
            annotations.append(AnnotationSpec(time_s=time_val, label=label))

            tooltip_parts = [label, f"{time_val:.2f} s"]
            if idx < len(self.event_table_data):
                row = self.event_table_data[idx]
                try:
                    id_val = float(row[2])
                    if np.isfinite(id_val):
                        tooltip_parts.append(f"ID {id_val:.2f} µm")
                except Exception:
                    pass
                od_idx = 3 if has_outer and len(row) >= 5 else None
                if od_idx is not None:
                    try:
                        od_val = float(row[od_idx])
                        if np.isfinite(od_val):
                            tooltip_parts.append(f"OD {od_val:.2f} µm")
                    except Exception:
                        pass
            metadata_entries.append(
                {
                    "time": time_val,
                    "label": label,
                    "tooltip": " · ".join(part for part in tooltip_parts if part),
                }
            )

        self.event_annotations = annotations
        self.event_metadata = metadata_entries

        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.set_events(
                self.event_times,
                labels=self.event_labels,
                label_meta=self.event_label_meta,
            )
            visible_entries = self.event_annotations if self._annotation_lane_visible else []
            plot_host.set_annotation_entries(visible_entries)
            self._refresh_event_annotation_artists()
        self.mark_session_dirty()

    def toggle_event_table(self, checked: bool):
        setter = getattr(self, "_set_event_table_visible", None)
        if callable(setter):
            setter(bool(checked), source="user")
        elif hasattr(self, "event_table"):
            self.event_table.setVisible(checked)

    def _ensure_event_label_actions(self) -> None:
        if getattr(self, "_event_label_action_group", None) is not None:
            return

        self._event_label_action_group = QActionGroup(self)
        self._event_label_action_group.setExclusive(True)

        def make_action(text: str, mode: str) -> QAction:
            action = QAction(text, self)
            action.setCheckable(True)
            self._event_label_action_group.addAction(action)

            def _on_toggled(checked: bool, *, value: str = mode) -> None:
                if checked:
                    self._set_event_label_mode(value)

            action.toggled.connect(_on_toggled)
            return action

        self.actEventLabelsVertical = make_action("Vertical", "vertical")
        self.actEventLabelsHorizontal = make_action("Horizontal", "horizontal")
        self.actEventLabelsOutside = make_action("Outside Belt", "horizontal_outside")

        self._sync_event_controls()

    def _on_event_lines_toggled(self, checked: bool) -> None:
        self._event_lines_visible = bool(checked)
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.set_event_lines_visible(self._event_lines_visible)
        else:
            self._toggle_event_lines_legacy(self._event_lines_visible)
        self._sync_event_controls()

    def _on_event_label_mode_auto(self, checked: bool) -> None:
        if checked:
            self._set_event_label_mode("vertical")

    def _on_event_label_mode_all(self, checked: bool) -> None:
        if checked:
            self._set_event_label_mode("horizontal_outside")

    def _set_event_label_mode(self, mode: str) -> None:
        normalized = mode.lower()
        alias = {
            "auto": "vertical",
            "all": "horizontal_outside",
        }
        normalized = alias.get(normalized, normalized)
        if normalized not in {"vertical", "horizontal", "horizontal_outside"}:
            normalized = "vertical"
        if normalized == self._event_label_mode:
            return
        self._apply_event_label_mode(normalized)

    def _apply_event_label_mode(self, mode: str | None = None) -> None:
        """Central switch for event labels.

        Ensures legacy lane is disabled when helper is active.
        """
        incoming = mode if mode is not None else self._event_label_mode
        mapped = {"auto": "vertical", "all": "horizontal_outside"}.get(incoming, incoming)
        self._event_label_mode = mapped

        # Always tear down the legacy annotation lane FIRST
        self._annotation_lane_visible = False
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.set_annotation_entries([])
        else:
            self._refresh_event_annotation_artists()

        if plot_host is None:
            self.canvas.draw_idle()
            self._sync_event_controls()
            return

        # Using the new helper: ensure per-track lines are *disabled* (helper draws its own)
        plot_host.use_track_event_lines(False)
        plot_host.set_event_label_mode(self._event_label_mode)  # rebuilds helper & xlim callbacks
        self._refresh_event_annotation_artists()
        self.canvas.draw_idle()
        self._sync_event_controls()

    def _sync_event_controls(self) -> None:
        if (
            self.actEventLines is not None
            and self.actEventLines.isChecked() != self._event_lines_visible
        ):
            self.actEventLines.blockSignals(True)
            self.actEventLines.setChecked(self._event_lines_visible)
            self.actEventLines.blockSignals(False)

        if (
            self.menu_event_lines_action is not None
            and self.menu_event_lines_action.isChecked() != self._event_lines_visible
        ):
            self.menu_event_lines_action.blockSignals(True)
            self.menu_event_lines_action.setChecked(self._event_lines_visible)
            self.menu_event_lines_action.blockSignals(False)

        mode = self._event_label_mode
        mapping = {
            "vertical": self.actEventLabelsVertical,
            "horizontal": self.actEventLabelsHorizontal,
            "horizontal_outside": self.actEventLabelsOutside,
        }
        for key, action in mapping.items():
            if action is None:
                continue
            should_check = mode == key
            if action.isChecked() != should_check:
                action.blockSignals(True)
                action.setChecked(should_check)
                action.blockSignals(False)

        if self.event_label_button is not None:
            labels = {
                "vertical": "Labels: Vertical",
                "horizontal": "Labels: Horizontal",
                "horizontal_outside": "Labels: Belt",
            }
            self.event_label_button.setText(labels.get(mode, "Labels"))

    def populate_table(self):
        has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
        self.event_table_controller.set_events(self.event_table_data, has_outer_diameter=has_od)
        self._update_excel_controls()

    def populate_event_table_from_df(self, df):
        rows = []
        has_od = any(col.lower().startswith("od") or "outer" in col.lower() for col in df.columns)

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

            if has_od:
                od_val = item.get("OD (µm)", item.get("Outer Diameter", None))
                try:
                    od_val = float(od_val) if od_val is not None else None
                except (TypeError, ValueError):
                    od_val = None
                try:
                    frame_val = int(frame_val)
                except (TypeError, ValueError):
                    frame_val = 0
                rows.append((str(label), time_val, id_val, od_val, frame_val))
            else:
                try:
                    frame_val = int(frame_val)
                except (TypeError, ValueError):
                    frame_val = 0
                rows.append((str(label), time_val, id_val, frame_val))

        self.event_table_data = rows
        self.event_table_controller.set_events(rows, has_outer_diameter=has_od)
        self._update_excel_controls()

    def update_event_label_positions(self, event=None):
        """Legacy hook; annotation lane handles positioning automatically."""
        return

    def handle_table_edit(self, row: int, new_val: float, old_val: float):
        if row >= len(self.event_table_data):
            return

        rounded_val = round(float(new_val), 2)
        row_data = list(self.event_table_data[row])
        time = row_data[1]

        if len(row_data) == 5:
            od_val = row_data[3]
            frame = row_data[4]
            self.event_table_data[row] = (
                row_data[0],
                time,
                rounded_val,
                od_val,
                frame,
            )
        else:
            frame = row_data[3] if len(row_data) > 3 else 0
            self.event_table_data[row] = (
                row_data[0],
                time,
                rounded_val,
                frame,
            )

        self.last_replaced_event = (row, old_val)

        cmd = ReplaceEventCommand(self, row, old_val, rounded_val)
        self.undo_stack.push(cmd)
        log.info("ID updated at %.2fs → %.2f µm", time, rounded_val)
        self.mark_session_dirty()
        self._sync_event_data_from_table()

    def table_row_clicked(self, row, col):
        self._focus_event_row(row, source="table")

    def _focus_event_row(self, row: int, *, source: str) -> None:
        if not self.event_table_data or not (0 <= row < len(self.event_table_data)):
            return

        try:
            event_time = float(self.event_table_data[row][1])
        except (TypeError, ValueError):
            event_time = None

        if source != "table":
            model = self.event_table.model()
            if model is not None:
                index = model.index(row, 0)
                self.event_table.selectRow(row)
                self.event_table.scrollTo(index)

        if event_time is not None:
            self._highlight_selected_event(event_time)
        else:
            self._clear_event_highlight()

        frame_idx = self._frame_index_from_event_row(row)
        if frame_idx is None and event_time is not None:
            frame_idx = self._frame_index_for_time(event_time)

        if frame_idx is not None and self.snapshot_frames:
            self.set_current_frame(frame_idx)
        elif event_time is not None:
            self.update_slider_marker()

    def _highlight_selected_event(self, event_time: float) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            return

        self._time_cursor_time = float(event_time)
        plot_host.set_time_cursor(
            self._time_cursor_time,
            visible=self._time_cursor_visible,
        )
        plot_host.set_event_highlight_style(
            color=self._event_highlight_color,
            alpha=self._event_highlight_base_alpha,
        )
        plot_host.highlight_event(self._time_cursor_time, visible=True)

        self._event_highlight_timer.stop()
        self._event_highlight_elapsed_ms = 0
        if self._event_highlight_duration_ms > 0:
            interval = max(16, min(100, self._event_highlight_duration_ms // 30 or 16))
            self._event_highlight_timer.setInterval(interval)
            self._event_highlight_timer.start()

    def _clear_event_highlight(self) -> None:
        timer = getattr(self, "_event_highlight_timer", None)
        if timer is not None:
            timer.stop()
        self._event_highlight_elapsed_ms = 0
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.highlight_event(None, visible=False)
            plot_host.set_event_highlight_alpha(self._event_highlight_base_alpha)

    def _on_event_highlight_tick(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            self._event_highlight_timer.stop()
            return
        if self._event_highlight_duration_ms <= 0:
            self._event_highlight_timer.stop()
            return
        interval = self._event_highlight_timer.interval()
        self._event_highlight_elapsed_ms += interval
        progress = self._event_highlight_elapsed_ms / float(self._event_highlight_duration_ms)
        if progress >= 1.0:
            self._event_highlight_timer.stop()
            plot_host.highlight_event(None, visible=False)
            plot_host.set_event_highlight_alpha(self._event_highlight_base_alpha)
            return
        remaining = max(0.0, 1.0 - progress)
        plot_host.set_event_highlight_alpha(self._event_highlight_base_alpha * remaining)

    def _frame_index_from_event_row(self, row: int) -> int | None:
        if not (0 <= row < len(self.event_table_data)):
            return None

        data = self.event_table_data[row]
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
        if not self.event_times:
            return None
        try:
            times = np.asarray(self.event_times, dtype=float)
        except (TypeError, ValueError):
            return None
        if times.size == 0:
            return None
        idx = int(np.argmin(np.abs(times - time_value)))
        return idx

    def handle_event_replacement(self, x, y):
        if not self.event_labels or not self.event_times:
            log.info("No events available to replace.")
            return

        options = [
            f"{label} at {time:.2f}s"
            for label, time in zip(self.event_labels, self.event_times, strict=False)
        ]
        selected, ok = QInputDialog.getItem(
            self,
            "Select Event to Replace",
            "Choose the event whose value you want to replace:",
            options,
            0,
            False,
        )

        if ok and selected:
            index = options.index(selected)
            event_label = self.event_labels[index]
            event_time = self.event_times[index]

            confirm = QMessageBox.question(
                self,
                "Confirm Replacement",
                f"Replace ID for '{event_label}' at {event_time:.2f}s with {y:.1f} µm?",
                QMessageBox.Yes | QMessageBox.No,
            )

            if confirm == QMessageBox.Yes:
                has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
                old_value = self.event_table_data[index][2]
                self.last_replaced_event = (index, old_value)
                if has_od:
                    frame_num = self.event_table_data[index][4]
                    self.event_table_data[index] = (
                        event_label,
                        round(event_time, 2),
                        round(y, 2),
                        self.event_table_data[index][3],
                        frame_num,
                    )
                else:
                    frame_num = self.event_table_data[index][3]
                    self.event_table_data[index] = (
                        event_label,
                        round(event_time, 2),
                        round(y, 2),
                        frame_num,
                    )
                self.event_table_controller.update_row(index, self.event_table_data[index])
                self.auto_export_table()
                self.mark_session_dirty()

    def prompt_add_event(self, x, y, trace_type="inner"):
        if not self.event_table_data:
            QMessageBox.warning(self, "No Events", "You must load events before adding new ones.")
            return

        # Build label options and insertion points
        insert_labels = [f"{label} at {t:.2f}s" for label, t, *_ in self.event_table_data]
        insert_labels.append("↘️ Add to end")  # final option

        selected, ok = QInputDialog.getItem(
            self,
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
            self, "New Event Label", "Enter label for the new event:"
        )

        if not label_ok or not new_label.strip():
            return

        insert_idx = insert_labels.index(selected)

        # Calculate frame number based on time
        frame_number = int(x / self.recording_interval)

        has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns

        arr_t = self.trace_data["Time (s)"].values
        idx = int(np.argmin(np.abs(arr_t - x)))
        id_val = self.trace_data["Inner Diameter"].values[idx]
        od_val = self.trace_data["Outer Diameter"].values[idx] if has_od else None

        if trace_type == "outer" and has_od:
            od_val = y
        else:
            id_val = y

        if has_od:
            new_entry = (
                new_label.strip(),
                round(x, 2),
                round(id_val, 2),
                round(od_val, 2),
                frame_number,
            )
        else:
            new_entry = (
                new_label.strip(),
                round(x, 2),
                round(id_val, 2),
                frame_number,
            )

        # Insert into data
        if insert_idx == len(self.event_table_data):  # Add to end
            self.event_labels.append(new_label.strip())
            self.event_times.append(x)
            self.event_table_data.append(new_entry)
            self.event_frames.append(frame_number)
            self.event_label_meta.append({})
        else:
            self.event_labels.insert(insert_idx, new_label.strip())
            self.event_times.insert(insert_idx, x)
            self.event_table_data.insert(insert_idx, new_entry)
            self.event_frames.insert(insert_idx, frame_number)
            self._insert_event_meta(insert_idx)

        self.populate_table()
        self.auto_export_table()
        self.update_plot()
        log.info("Inserted new event: %s", new_entry)
        self.mark_session_dirty()

    def manual_add_event(self):
        if not self.trace_data:
            QMessageBox.warning(self, "No Trace", "Load a trace before adding events.")
            return

        has_od = "Outer Diameter" in self.trace_data.columns
        insert_labels = [f"{lbl} at {t:.2f}s" for lbl, t, *_ in self.event_table_data]
        insert_labels.append("↘️ Add to end")
        selected, ok = QInputDialog.getItem(
            self,
            "Insert Event",
            "Insert new event before which existing event?",
            insert_labels,
            0,
            False,
        )
        if not ok or not selected:
            return

        label, l_ok = QInputDialog.getText(
            self, "New Event Label", "Enter label for the new event:"
        )
        if not l_ok or not label.strip():
            return

        t_val, t_ok = QInputDialog.getDouble(self, "Event Time", "Time (s):", 0.0, 0, 1e6, 2)
        if not t_ok:
            return

        id_val, id_ok = QInputDialog.getDouble(self, "Inner Diameter", "ID (µm):", 0.0, 0, 1e6, 2)
        if not id_ok:
            return

        insert_idx = insert_labels.index(selected)
        frame_number = int(t_val / self.recording_interval)
        if has_od:
            od_val, ok = QInputDialog.getDouble(self, "Outer Diameter", "OD (µm):", 0.0, 0, 1e6, 2)
            if not ok:
                return
            new_entry = (
                label.strip(),
                round(t_val, 2),
                round(id_val, 2),
                round(od_val, 2),
                frame_number,
            )
        else:
            new_entry = (label.strip(), round(t_val, 2), round(id_val, 2), frame_number)

        if insert_idx == len(self.event_table_data):
            self.event_labels.append(label.strip())
            self.event_times.append(t_val)
            self.event_table_data.append(new_entry)
            self.event_frames.append(frame_number)
            self.event_label_meta.append({})
        else:
            self.event_labels.insert(insert_idx, label.strip())
            self.event_times.insert(insert_idx, t_val)
            self.event_table_data.insert(insert_idx, new_entry)
            self.event_frames.insert(insert_idx, frame_number)
            self._insert_event_meta(insert_idx)

        self.populate_table()
        self.update_plot()
        self.auto_export_table()
        log.info("Manually inserted event: %s", new_entry)
        self.mark_session_dirty()

    # [H] ========================= HOVER LABEL AND CURSOR SYNC ===========================

    def show_event_table_context_menu(self, position):
        index = self.event_table.indexAt(position)
        row = index.row() if index.isValid() else len(self.event_table_data)
        menu = QMenu()

        # Group 1: Edit & Delete
        if index.isValid():
            edit_action = menu.addAction("✏️ Edit ID (µm)…")
            delete_action = menu.addAction("🗑️ Delete Event")
        menu.addSeparator()

        # Group 2: Plot Navigation
        if index.isValid():
            jump_action = menu.addAction("🔍 Jump to Event on Plot")
            pin_action = menu.addAction("📌 Pin to Plot")
        menu.addSeparator()

        # Group 3: Pin Utilities
        if index.isValid():
            replace_with_pin_action = menu.addAction("🔄 Replace ID with Pinned Value")
        clear_pins_action = menu.addAction("❌ Clear All Pins")
        menu.addSeparator()

        add_event_action = menu.addAction("➕ Add Event…")

        # Show menu
        action = menu.exec_(self.event_table.viewport().mapToGlobal(position))

        # Group 1 actions
        if index.isValid() and action == edit_action:
            if row >= len(self.event_table_data):
                return
            old_val = self.event_table_data[row][2]
            new_val, ok = QInputDialog.getDouble(
                self,
                "Edit ID",
                "Enter new ID (µm):",
                float(old_val) if old_val is not None else 0.0,
                0,
                10000,
                2,
            )
            if ok:
                has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
                rounded = round(new_val, 2)
                if has_od:
                    lbl, t, _, od_val, frame_val = self.event_table_data[row]
                    self.event_table_data[row] = (lbl, t, rounded, od_val, frame_val)
                else:
                    lbl, t, _, frame_val = self.event_table_data[row]
                    self.event_table_data[row] = (lbl, t, rounded, frame_val)
                self.event_table_controller.update_row(row, self.event_table_data[row])
                self.auto_export_table()

        elif index.isValid() and action == delete_action:
            confirm = QMessageBox.question(
                self,
                "Delete Event",
                f"Delete event: {self.event_table_data[row][0]}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                del self.event_labels[row]
                del self.event_times[row]
                if len(self.event_frames) > row:
                    del self.event_frames[row]
                self._delete_event_meta(row)
                self.event_table_data.pop(row)
                self.event_table_controller.remove_row(row)
                self.update_plot()
                self._update_excel_controls()

        # Group 2 actions
        elif index.isValid() and action == jump_action:
            self._focus_event_row(row, source="context")

        elif index.isValid() and action == pin_action:
            t = self.event_table_data[row][1]
            id_val = self.event_table_data[row][2]
            marker = self.ax.plot(t, id_val, "ro", markersize=6)[0]
            label = self.ax.annotate(
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
            self.pinned_points.append((marker, label))
            self.canvas.draw_idle()

        # Group 3 actions
        elif index.isValid() and action == replace_with_pin_action:
            t_event = self.event_table_data[row][1]
            if not self.pinned_points:
                QMessageBox.information(self, "No Pins", "There are no pinned points to use.")
                return
            closest_pin = min(self.pinned_points, key=lambda p: abs(p[0].get_xdata()[0] - t_event))
            pin_id = closest_pin[0].get_ydata()[0]
            confirm = QMessageBox.question(
                self,
                "Confirm Replacement",
                f"Replace ID at {t_event:.2f}s with pinned value: {pin_id:.2f} µm?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                self.last_replaced_event = (row, self.event_table_data[row][2])
                has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
                if has_od:
                    self.event_table_data[row] = (
                        self.event_table_data[row][0],
                        t_event,
                        round(pin_id, 2),
                        self.event_table_data[row][3],
                        self.event_table_data[row][4],
                    )
                else:
                    self.event_table_data[row] = (
                        self.event_table_data[row][0],
                        t_event,
                        round(pin_id, 2),
                        self.event_table_data[row][3],
                    )
                self.event_table_controller.update_row(row, self.event_table_data[row])
                self.auto_export_table()
                log.info(
                    "Replaced ID at %.2fs with pinned value %.2f µm.",
                    t_event,
                    pin_id,
                )
                self.mark_session_dirty()

        elif action == clear_pins_action:
            if not self.pinned_points:
                QMessageBox.information(self, "No Pins", "There are no pins to clear.")
                return
            for marker, label in self.pinned_points:
                marker.remove()
                label.remove()
            self.pinned_points.clear()
            self.canvas.draw_idle()
            log.info("Cleared all pins.")
            self.mark_session_dirty()

        elif action == add_event_action:
            self.manual_add_event()
