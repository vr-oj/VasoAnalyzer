# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAbstractItemView, QDockWidget, QTreeWidget


class ProjectExplorerWidget(QDockWidget):
    """Simple dock with a tree widget for project exploration."""

    def __init__(self, parent=None):
        super().__init__("Project", parent)
        # ``objectName`` must be set for QMainWindow.saveState() to work
        self.setObjectName("ProjectDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.setMinimumWidth(220)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setWidget(self.tree)

    def set_open(self, open_: bool):
        """Show or hide the dock; keep API consistent with toolbar toggle."""
        if open_:
            self.show()
        else:
            self.hide()
        if open_:
            self.raise_()
