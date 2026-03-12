# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import base64
import sys
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QByteArray, QMimeData, Qt, pyqtSignal
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

# Custom MIME type used to identify an in-tree sample drag (vs. comparison-panel drops)
_INTERNAL_SAMPLE_MIME = "application/x-vasoanalyzer-sample-move"


@dataclass
class SubfolderRef:
    """Sentinel stored as UserRole data on subfolder tree items."""

    name: str
    experiment: Any  # vasoanalyzer.core.project.Experiment


class ExperimentTreeWidget(QTreeWidget):
    """QTreeWidget supporting experiment reorder and sample drag-to-subfolder/experiment."""

    experiment_reordered = pyqtSignal()
    # Emitted when one or more samples are dropped on an experiment/subfolder within the tree.
    # Args: (list[SampleN], target_experiment: Experiment, target_subfolder: str | None)
    sample_moved = pyqtSignal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging_samples: list[Any] = []  # SampleN objects being dragged internally

    # ------------------------------------------------------------------
    # Drag origination
    # ------------------------------------------------------------------

    def startDrag(self, supported_actions):
        from vasoanalyzer.core.project import SampleN

        # Collect all selected SampleN items
        selected_samples = [
            it.data(0, Qt.ItemDataRole.UserRole)
            for it in self.selectedItems()
            if isinstance(it.data(0, Qt.ItemDataRole.UserRole), SampleN)
        ]

        if selected_samples:
            self._dragging_samples = selected_samples
            mime = QMimeData()

            # For a single sample, also include dataset MIME so comparison panel can accept it
            if len(selected_samples) == 1:
                obj = selected_samples[0]
                dataset_id = getattr(obj, "dataset_id", None)
                if dataset_id is not None:
                    from vasoanalyzer.ui.drag_drop import encode_dataset_mime

                    dataset_mime = encode_dataset_mime(dataset_id, getattr(obj, "name", "") or "")
                    for fmt in dataset_mime.formats():
                        mime.setData(fmt, dataset_mime.data(fmt))

            # Internal marker so our dropEvent can distinguish tree-internal drops
            mime.setData(_INTERNAL_SAMPLE_MIME, QByteArray(b"1"))

            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
            self._dragging_samples = []
            return

        # Experiments — use Qt's built-in internal drag for reordering
        super().startDrag(supported_actions)

    # ------------------------------------------------------------------
    # Drag acceptance (visual feedback)
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_INTERNAL_SAMPLE_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_INTERNAL_SAMPLE_MIME):
            target = self.itemAt(event.position().toPoint())
            if target is not None:
                obj = target.data(0, Qt.ItemDataRole.UserRole)
                from vasoanalyzer.core.project import Experiment, SampleN

                if isinstance(obj, (Experiment, SubfolderRef, SampleN)):
                    event.acceptProposedAction()
                    return
            event.ignore()
        else:
            super().dragMoveEvent(event)

    # ------------------------------------------------------------------
    # Drop handling
    # ------------------------------------------------------------------

    def dropEvent(self, event):
        # --- Sample internal move ---
        if event.mimeData().hasFormat(_INTERNAL_SAMPLE_MIME) and self._dragging_samples:
            target_item = self.itemAt(event.position().toPoint())
            if target_item is None:
                event.ignore()
                return

            target_obj = target_item.data(0, Qt.ItemDataRole.UserRole)
            from vasoanalyzer.core.project import Experiment, SampleN

            target_exp = None
            target_sf: str | None = None

            if isinstance(target_obj, Experiment):
                target_exp = target_obj
            elif isinstance(target_obj, SubfolderRef):
                target_exp = target_obj.experiment
                target_sf = target_obj.name
            elif isinstance(target_obj, SampleN):
                # Dropped on a sibling sample — inherit its parent context
                parent = target_item.parent()
                if parent is not None:
                    parent_obj = parent.data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(parent_obj, Experiment):
                        target_exp = parent_obj
                    elif isinstance(parent_obj, SubfolderRef):
                        target_exp = parent_obj.experiment
                        target_sf = parent_obj.name

            if target_exp is not None:
                self.sample_moved.emit(self._dragging_samples, target_exp, target_sf)
                event.acceptProposedAction()
            else:
                event.ignore()
            return

        # --- Experiment reorder ---
        dragged = self.currentItem()
        if dragged is None:
            event.ignore()
            return
        # Only allow reorder for top-level items (experiments have no parent)
        if dragged.parent() is not None:
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
        card_layout.setContentsMargins(6, 6, 6, 6)
        card_layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        title_label = QLabel("Project", card)
        title_label.setObjectName("ProjectHeaderLabel")
        header_layout.addWidget(title_label)
        self.header_label = title_label
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
        self.tree.setIndentation(12)
        self.tree.setRootIsDecorated(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.tree.setAcceptDrops(True)
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

        # Platform tweaks — keep rows compact so more items fit on screen
        if _IS_MACOS:
            base_font_size = "10.5pt"
            header_font_size = "11pt"
            item_padding = "2px 5px"
            item_min_height = "20px"
        elif _IS_WINDOWS:
            base_font_size = "9pt"
            header_font_size = "9.5pt"
            item_padding = "2px 4px"
            item_min_height = "18px"
        else:
            base_font_size = "10pt"
            header_font_size = "10.5pt"
            item_padding = "2px 4px"
            item_min_height = "19px"

        item_radius = max(3, panel_radius - 1)

        def _branch_svg(color: str, direction: str) -> str:
            d = "M5,3 L13,8 L5,13 Z" if direction == "right" else "M3,5 L13,5 L8,13 Z"
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
                f'<path d="{d}" fill="{color}"/></svg>'
            )
            encoded = base64.b64encode(svg.encode()).decode()
            return f"data:image/svg+xml;base64,{encoded}"

        branch_closed_url = _branch_svg(muted, "right")
        branch_open_url = _branch_svg(muted, "down")

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
                image: url("{branch_closed_url}");
            }}
            QTreeWidget#ProjectTree::branch:open:has-children:!has-siblings,
            QTreeWidget#ProjectTree::branch:open:has-children:has-siblings {{
                image: url("{branch_open_url}");
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
