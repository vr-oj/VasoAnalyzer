# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import sys
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (
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

_IS_MACOS = sys.platform == "darwin"
_IS_WINDOWS = sys.platform == "win32"


@dataclass
class SubfolderRef:
    """Sentinel stored as UserRole data on subfolder tree items."""

    name: str
    experiment: Any  # vasoanalyzer.core.project.Experiment


class ExperimentTreeWidget(QTreeWidget):
    """QTreeWidget that supports experiment reorder and dataset drag-to-comparison."""

    experiment_reordered = pyqtSignal()

    def startDrag(self, supported_actions):
        """Emit a dataset MIME drag for sample items; fall back to default for experiments."""
        item = self.currentItem()
        if item is not None:
            obj = item.data(0, Qt.ItemDataRole.UserRole)
            from vasoanalyzer.core.project import SampleN

            if isinstance(obj, SampleN):
                dataset_id = getattr(obj, "dataset_id", None)
                if dataset_id is not None:
                    from vasoanalyzer.ui.drag_drop import encode_dataset_mime

                    name = getattr(obj, "name", "") or ""
                    mime = encode_dataset_mime(dataset_id, name)
                    drag = QDrag(self)
                    drag.setMimeData(mime)
                    drag.exec(Qt.DropAction.CopyAction)
                    return
        super().startDrag(supported_actions)

    def dropEvent(self, event):
        dragged = self.currentItem()
        if dragged is None:
            event.ignore()
            return
        parent = dragged.parent()
        # Only allow internal drops for direct children of the root (experiment level).
        # Reject drops of the root itself, subfolder items, or sample items.
        if parent is None or parent.parent() is not None:
            event.ignore()
            return
        super().dropEvent(event)
        self.experiment_reordered.emit()


class ProjectExplorerWidget(QDockWidget):
    """Dock widget containing the hierarchical project tree."""

    def __init__(self, parent=None):
        super().__init__("Project", parent)
        self.setObjectName("ProjectDock")
        self.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        empty_title = QWidget(self)
        empty_title.setMaximumHeight(0)
        self.setTitleBarWidget(empty_title)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
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
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setObjectName("ProjectSeparator")

        self.tree = ExperimentTreeWidget()
        self.tree.setObjectName("ProjectTree")
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(False)
        self.tree.setIndentation(16)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setAnimated(True)

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
        """Show or hide the dock."""
        if open_:
            self.show()
            self.raise_()
        else:
            self.hide()

    def apply_theme(self) -> None:
        """Apply palette-derived colors to the dock contents."""
        bg = CURRENT_THEME.get("table_bg", "#ffffff")
        panel_bg = CURRENT_THEME.get("panel_bg", bg)
        panel_border = CURRENT_THEME.get("panel_border", "#D1D5DB")
        panel_radius = int(CURRENT_THEME.get("panel_radius", 6))
        text = CURRENT_THEME.get("text", "#111827")
        hover = CURRENT_THEME.get("table_hover", "#F3F4F6")
        selection = CURRENT_THEME.get("selection_bg", "#3B82F6")
        selection_text = CURRENT_THEME.get("highlighted_text", "#FFFFFF")
        muted = CURRENT_THEME.get("text_disabled", "#9CA3AF")

        # Platform tweaks
        if _IS_MACOS:
            base_font_size = "10.5pt"
            header_font_size = "11pt"
            item_padding = "3px 6px"
            item_min_height = "22px"
        elif _IS_WINDOWS:
            base_font_size = "9pt"
            header_font_size = "9.5pt"
            item_padding = "3px 6px"
            item_min_height = "20px"
        else:
            base_font_size = "10pt"
            header_font_size = "10.5pt"
            item_padding = "3px 6px"
            item_min_height = "20px"

        item_radius = max(3, panel_radius - 1)

        self.setStyleSheet(
            f"""
            QDockWidget#ProjectDock {{
                background: {panel_bg};
                border: none;
            }}
            QDockWidget#ProjectDock > QWidget {{
                background: {panel_bg};
            }}
            QFrame#ProjectCard {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: {panel_radius}px;
            }}
            QFrame#ProjectSeparator {{
                border: none;
                border-top: 1px solid {panel_border};
                margin: 0px 2px;
                max-height: 1px;
            }}
            QLabel#ProjectHeaderLabel {{
                color: {text};
                font-size: {header_font_size};
                font-weight: 600;
                background: transparent;
                padding: 0px 2px;
            }}
            QTreeWidget#ProjectTree {{
                background: {panel_bg};
                color: {text};
                border: none;
                font-size: {base_font_size};
                outline: none;
                padding: 2px 0px;
                show-decoration-selected: 1;
            }}
            QTreeWidget#ProjectTree::item {{
                color: {text};
                border: 1px solid transparent;
                border-radius: {item_radius}px;
                margin: 1px 4px 1px 0px;
                padding: {item_padding};
                min-height: {item_min_height};
            }}
            QTreeWidget#ProjectTree::item:hover {{
                background: {hover};
                border-color: transparent;
            }}
            QTreeWidget#ProjectTree::item:selected {{
                background: {selection};
                color: {selection_text};
                border-color: transparent;
            }}
            QTreeWidget#ProjectTree::item:selected:hover {{
                background: {selection};
                color: {selection_text};
            }}
            QTreeWidget#ProjectTree::branch {{
                background: {panel_bg};
            }}
            QTreeWidget#ProjectTree::branch:has-children:!has-siblings:closed,
            QTreeWidget#ProjectTree::branch:closed:has-children:has-siblings {{
                border-image: none;
                image: none;
            }}
            QTreeWidget#ProjectTree::branch:open:has-children:!has-siblings,
            QTreeWidget#ProjectTree::branch:open:has-children:has-siblings {{
                border-image: none;
                image: none;
            }}
            QLabel#ProjectEmptyState {{
                color: {muted};
                font-size: {base_font_size};
                background: transparent;
                padding: 6px 4px 8px 4px;
            }}
        """
        )

    def set_empty_state_visible(self, visible: bool) -> None:
        """Show or hide the project empty-state message."""
        if hasattr(self, "empty_state_label") and self.empty_state_label is not None:
            self.empty_state_label.setVisible(bool(visible))
