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
        self.setMinimumWidth(240)

        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        card = QFrame(container)
        card.setObjectName("ProjectCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
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
        self.tree.setIndentation(14)

        self.empty_state_label = QLabel("No datasets yet. Open Data… or Import Folder…", card)
        self.empty_state_label.setObjectName("ProjectEmptyState")
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setVisible(False)

        card_layout.addLayout(header_layout)
        card_layout.addWidget(separator)
        card_layout.addWidget(self.tree, 1)
        card_layout.addWidget(self.empty_state_label, 0)

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
        panel_bg = CURRENT_THEME.get("panel_bg", bg)
        panel_border = CURRENT_THEME.get("panel_border", border)
        panel_radius = int(CURRENT_THEME.get("panel_radius", 6))
        text = CURRENT_THEME.get("text", "#000000")
        alt = CURRENT_THEME.get("alternate_bg", bg)
        hover = CURRENT_THEME.get("table_hover", alt)
        selection = CURRENT_THEME.get("selection_bg", hover)
        selection_text = CURRENT_THEME.get("highlighted_text", text)
        muted = CURRENT_THEME.get("text_disabled", text)

        self.setStyleSheet(
            f"""
            QDockWidget#ProjectDock {{
                background: {panel_bg};
                border: none;
            }}
            QDockWidget#ProjectDock QWidget {{
                background: {panel_bg};
                color: {text};
            }}
            QFrame#ProjectCard {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: {panel_radius}px;
                padding: 3px 3px 4px 3px;
            }}
            QLabel#ProjectHeaderLabel {{
                color: {text};
                font-size: 10.5pt;
                font-weight: 600;
            }}
            QTreeWidget#ProjectTree {{
                background: {panel_bg};
                border: none;
                font-size: 10.5pt;
                padding: 2px 0px;
            }}
            QTreeWidget#ProjectTree::item {{
                background: transparent;
                color: {text};
                border: 1px solid transparent;
                border-radius: {max(2, panel_radius)}px;
                margin: 1px 3px;
                padding: 3px 8px;
                min-height: 21px;
            }}
            QTreeWidget#ProjectTree::item:hover {{
                background: {hover};
            }}
            QTreeWidget#ProjectTree::item:alternate {{
                background: {alt};
            }}
            QTreeWidget#ProjectTree::item:selected {{
                background: {selection};
                color: {selection_text};
                border: 1px solid {panel_border};
            }}
            QLabel#ProjectEmptyState {{
                color: {muted};
                font-size: 10pt;
                padding: 4px 6px 6px 6px;
            }}
        """
        )

    def set_empty_state_visible(self, visible: bool) -> None:
        """Show or hide the project empty-state message."""
        if hasattr(self, "empty_state_label") and self.empty_state_label is not None:
            self.empty_state_label.setVisible(bool(visible))
