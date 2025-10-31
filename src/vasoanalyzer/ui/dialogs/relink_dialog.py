"""Dialog for relinking missing project assets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QShowEvent
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from vasoanalyzer.core.project import SampleN


@dataclass
class MissingAsset:
    """Descriptor for an asset that needs to be relinked."""

    sample: SampleN
    kind: str  # "trace", "events", or "attachment"
    label: str
    current_path: str | None
    relative: str | None = None
    hint: str | None = None
    signature: str | None = None
    new_path: str | None = None

    def status(self) -> str:
        candidate = self.new_path or self.current_path
        if candidate and Path(candidate).exists():
            return "Ready"
        return "Missing"


class RelinkDialog(QDialog):
    """Non-modal dialog offering tools to relink missing files."""

    relink_applied = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Relink Missing Files")
        self.setWindowModality(Qt.NonModal)
        self.resize(720, 360)

        self._assets: list[MissingAsset] = []

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel(
            "Select a new root folder or individual files to repair missing links. "
            "Changes apply to all items referencing the same file."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Item", "Current Path", "Relative Path", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        layout.addWidget(self.tree, stretch=1)

        btn_row = QHBoxLayout()
        layout.addLayout(btn_row)

        self.root_btn = QPushButton("Select Root Folder…")
        self.root_btn.clicked.connect(self._choose_root)
        btn_row.addWidget(self.root_btn)

        self.file_btn = QPushButton("Relink Selected…")
        self.file_btn.clicked.connect(self._choose_file_for_selected)
        btn_row.addWidget(self.file_btn)

        btn_row.addStretch(1)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self._emit_changes)
        btn_row.addWidget(self.apply_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self._update_buttons()

    # ------------------------------------------------------------------
    def set_assets(self, assets: Iterable[MissingAsset]) -> None:
        self._assets = list(assets)
        self._refresh_tree()

    # ------------------------------------------------------------------
    def _refresh_tree(self) -> None:
        self.tree.clear()

        ready_brush = QBrush(QColor(Qt.darkGreen))
        missing_brush = QBrush(QColor(Qt.red))

        for asset in self._assets:
            status = asset.status()
            item = QTreeWidgetItem(
                [
                    asset.label,
                    asset.current_path or "—",
                    asset.relative or "—",
                    status,
                ]
            )
            item.setData(0, Qt.UserRole, asset)
            if status == "Ready":
                item.setForeground(3, ready_brush)
            else:
                item.setForeground(3, missing_brush)
            self.tree.addTopLevelItem(item)

        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(3)
        self._update_buttons()

    # ------------------------------------------------------------------
    def _update_buttons(self) -> None:
        has_selection = bool(self.tree.selectedItems())
        self.file_btn.setEnabled(has_selection)
        self.apply_btn.setEnabled(any(asset.new_path for asset in self._assets))

    # ------------------------------------------------------------------
    def _choose_root(self) -> None:
        root = QFileDialog.getExistingDirectory(self, "Select Base Folder")
        if not root:
            return

        root_path = Path(root)
        for asset in self._assets:
            candidate = self._candidate_from_root(root_path, asset)
            if candidate and candidate.exists():
                asset.new_path = candidate.as_posix()
        self._refresh_tree()

    # ------------------------------------------------------------------
    def _candidate_from_root(self, root: Path, asset: MissingAsset) -> Path | None:
        if asset.relative:
            candidate = (root / asset.relative).resolve(strict=False)
            return candidate
        if asset.current_path:
            target = Path(asset.current_path).name
            return (root / target).resolve(strict=False)
        if asset.hint:
            target = Path(asset.hint).name
            return (root / target).resolve(strict=False)
        return None

    # ------------------------------------------------------------------
    def _choose_file_for_selected(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        asset = items[0].data(0, Qt.UserRole)
        if not isinstance(asset, MissingAsset):
            return

        start_dir = asset.hint or asset.current_path or ""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Replacement File", start_dir)
        if not file_path:
            return

        asset.new_path = Path(file_path).expanduser().resolve(strict=False).as_posix()
        self._refresh_tree()

    # ------------------------------------------------------------------
    def _emit_changes(self) -> None:
        ready = [asset for asset in self._assets if asset.new_path]
        if not ready:
            QMessageBox.information(self, "Nothing to Apply", "No files have been relinked yet.")
            return
        self.relink_applied.emit(ready)
        self.close()

    # ------------------------------------------------------------------
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._refresh_tree()
