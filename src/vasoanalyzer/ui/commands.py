from PyQt5.QtWidgets import QUndoCommand


class ReplaceEventCommand(QUndoCommand):
    def __init__(self, app, index, old_val, new_val):
        super().__init__(f"Replace Event #{index}")
        self.app = app
        self.i = index
        self.old = old_val
        self.new = new_val

    def redo(self):
        lbl, t, _, frame = self.app.event_table_data[self.i]
        self.app.event_table_data[self.i] = (lbl, t, self.new, frame)
        self.app.populate_table()
        self.app.auto_export_table()

    def undo(self):
        lbl, t, _, frame = self.app.event_table_data[self.i]
        self.app.event_table_data[self.i] = (lbl, t, self.old, frame)
        self.app.populate_table()
        self.app.auto_export_table()
