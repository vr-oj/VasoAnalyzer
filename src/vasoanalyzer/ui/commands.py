# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from PyQt6.QtGui import QUndoCommand


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
