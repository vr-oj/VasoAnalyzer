from PyQt5.QtWidgets import QDockWidget, QTreeWidget


class ProjectExplorerWidget(QDockWidget):
    """Simple dock with a tree widget for project exploration."""

    def __init__(self, parent=None):
        super().__init__("Project", parent)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.setWidget(self.tree)
