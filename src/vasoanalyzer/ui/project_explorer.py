# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from PyQt5.QtWidgets import QAbstractItemView, QDockWidget, QTreeWidget


class ProjectExplorerWidget(QDockWidget):
    """Simple dock with a tree widget for project exploration."""

    def __init__(self, parent=None):
        super().__init__("Project", parent)
        # ``objectName`` must be set for QMainWindow.saveState() to work
        self.setObjectName("ProjectDock")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setWidget(self.tree)
