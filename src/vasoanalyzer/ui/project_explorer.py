# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.theme import CURRENT_THEME


class ProjectExplorerWidget(QDockWidget):
    """Simple dock with a tree widget for project exploration."""

    def __init__(self, parent=None):
        super().__init__("Project", parent)
        # ``objectName`` must be set for QMainWindow.saveState() to work
        self.setObjectName("ProjectDock")
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)
        empty_title = QWidget(self)
        empty_title.setMaximumHeight(0)
        self.setTitleBarWidget(empty_title)
        self.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.setMinimumWidth(220)

        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        card = QFrame(container)
        card.setObjectName("ProjectCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        title_label = QLabel("Project", card)
        title_label.setObjectName("ProjectHeaderLabel")
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)

        separator = QFrame(card)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)

        self.tree = QTreeWidget()
        self.tree.setObjectName("ProjectTree")
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)

        card_layout.addLayout(header_layout)
        card_layout.addWidget(separator)
        card_layout.addWidget(self.tree)

        container_layout.addWidget(card)
        self.setWidget(container)
        self.apply_theme()

    def set_open(self, open_: bool):
        """Show or hide the dock; keep API consistent with toolbar toggle."""
        if open_:
            self.show()
        else:
            self.hide()
        if open_:
            self.raise_()

    def apply_theme(self) -> None:
        """Apply palette-derived colors to the dock contents."""

        border = CURRENT_THEME.get("grid_color", "#d0d0d0")
        bg = CURRENT_THEME.get("table_bg", "#ffffff")
        text = CURRENT_THEME.get("text", "#000000")

        self.setStyleSheet(
            f"""
            QDockWidget#ProjectDock {{
                background: {bg};
                border: none;
            }}
            QDockWidget#ProjectDock QWidget {{
                background: {bg};
                color: {text};
            }}
            QFrame#ProjectCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 9px;
                padding: 3px 3px 6px 3px;
            }}
            QTreeWidget#ProjectTree {{
                background: {bg};
                border: none;
            }}
        """
        )
