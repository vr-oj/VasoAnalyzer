# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtGui import QUndoCommand

if TYPE_CHECKING:
    from vasoanalyzer.ui.event_table import EventRow


class AddEventCommand(QUndoCommand):
    """Undoable command for inserting one event into the event table."""

    def __init__(self, app, index: int, row: EventRow, meta: dict[str, Any] | None = None):
        label_text = row[0] if row else "event"
        super().__init__(f"Add Event '{label_text}'")
        self.app = app
        self._index = index
        self._row = row
        self._meta = dict(meta or {})

    def redo(self) -> None:
        self.app._insert_event_at(self._index, self._row, self._meta)

    def undo(self) -> None:
        self.app._remove_event_at(self._index)


class DeleteEventsCommand(QUndoCommand):
    """Undoable command for deleting one or more events from the event table."""

    def __init__(self, app, removed: list[tuple[int, EventRow, dict[str, Any]]]):
        count = len(removed)
        if count == 1:
            super().__init__(f"Delete Event '{removed[0][1][0]}'")
        else:
            super().__init__(f"Delete {count} Events")
        self.app = app
        # Store as (index, row, meta) sorted by index ascending for re-insertion
        self._removed = sorted(removed, key=lambda r: r[0])

    def redo(self) -> None:
        # Remove in reverse order so indices stay valid
        for idx, _row, _meta in reversed(self._removed):
            self.app._remove_event_at(idx)

    def undo(self) -> None:
        # Re-insert in ascending order
        for idx, row, meta in self._removed:
            self.app._insert_event_at(idx, row, meta)


class ReplaceEventCommand(QUndoCommand):
    def __init__(self, app, index, old_val, new_val):
        super().__init__(f"Replace Event #{index}")
        self.app = app
        self.i = index
        self.old = old_val
        self.new = new_val

    def redo(self):
        self._apply_new_value(self.new)

    def undo(self):
        self._apply_new_value(self.old)

    def _apply_new_value(self, value):
        row = list(self.app.event_table_data[self.i])
        if len(row) < 3:
            return
        row[2] = round(float(value), 2)
        updated = tuple(row)
        self.app.event_table_data[self.i] = updated
        if hasattr(self.app, "event_table_controller"):
            self.app.event_table_controller.update_row(self.i, updated)
        self.app.auto_export_table()
        if hasattr(self.app, "_sync_event_data_from_table"):
            self.app._sync_event_data_from_table()


class PointEditCommand(QUndoCommand):
    """Undoable command that applies manual point edits."""

    def __init__(self, app, actions, summary):
        label = f"Edit {summary.point_count} points ({summary.channel})"
        super().__init__(label)
        self.app = app
        self._actions = tuple(actions)
        self._summary = summary

    def redo(self):
        self.app._apply_point_editor_actions(self._actions, self._summary)

    def undo(self):
        self.app._revert_point_editor_actions(len(self._actions))


class PointEditBatchCommand(QUndoCommand):
    """Groups multiple point edit actions into a single undoable unit.

    When a user performs many edits in a point editor session, they are
    collected into this batch so that Ctrl+Z undoes them all at once
    rather than one at a time.
    """

    def __init__(self, app, action_groups, summaries):
        total = sum(s.point_count for s in summaries)
        channels = sorted({s.channel for s in summaries})
        label = f"Batch edit {total} points ({', '.join(channels)})"
        super().__init__(label)
        self.app = app
        self._action_groups = [tuple(ag) for ag in action_groups]
        self._summaries = list(summaries)
        self._total_actions = sum(len(ag) for ag in self._action_groups)

    def redo(self):
        for actions, summary in zip(self._action_groups, self._summaries):
            self.app._apply_point_editor_actions(actions, summary)

    def undo(self):
        self.app._revert_point_editor_actions(self._total_actions)
