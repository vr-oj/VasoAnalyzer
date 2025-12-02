"""Preset library dock for managing style presets."""

from __future__ import annotations

from typing import Any, cast

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["PresetLibraryDock"]


class PresetLibraryDock(QDockWidget):
    """
    Dockable panel for managing style preset library.

    Features:
    - Tree view of saved presets (built-in + user)
    - Load/Save/Delete/Duplicate actions
    - Preview thumbnails (future)
    - Import/Export preset bundles (future)
    """

    # Signal emitted when user selects a preset to load
    preset_load_requested = pyqtSignal(dict)

    # Signal emitted when user saves a new preset
    preset_save_requested = pyqtSignal(str, str, list)  # name, description, tags

    # Signal emitted when user deletes a preset
    preset_delete_requested = pyqtSignal(str)  # preset name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Preset Library", parent)
        self.setObjectName("PresetLibraryDock")

        # Preset storage (will be synced with parent)
        self._presets: list[dict[str, Any]] = []
        self._built_in_presets: list[dict[str, Any]] = []

        self._build_ui()
        self._apply_theme()

    # ------------------------------------------------------------------ Public API

    def set_presets(
        self, presets: list[dict[str, Any]], built_in: list[dict[str, Any]] | None = None
    ) -> None:
        """
        Update preset library.

        Args:
            presets: User-defined presets
            built_in: Built-in presets (read-only)
        """
        self._presets = presets
        self._built_in_presets = built_in or []
        self._refresh_tree()

    def add_preset(self, preset: dict[str, Any]) -> None:
        """Add a new preset to the library."""
        self._presets.append(preset)
        self._refresh_tree()

    def remove_preset(self, name: str) -> None:
        """Remove a preset by name."""
        self._presets = [p for p in self._presets if p.get("name") != name]
        self._refresh_tree()

    # ------------------------------------------------------------------ UI Construction

    def _build_ui(self) -> None:
        """Build dock UI."""
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header label
        header = QLabel("Style Presets")
        header.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(header)

        # Preset tree
        self.preset_tree = QTreeWidget()
        self.preset_tree.setHeaderLabels(["Name", "Type"])
        self.preset_tree.setRootIsDecorated(True)
        self.preset_tree.setAlternatingRowColors(True)
        self.preset_tree.itemDoubleClicked.connect(self._on_preset_double_clicked)
        layout.addWidget(self.preset_tree, 1)

        # Action buttons
        button_row = QHBoxLayout()
        button_row.setSpacing(4)

        self.load_btn = QPushButton("Load")
        self.load_btn.setToolTip("Load selected preset")
        self.load_btn.clicked.connect(self._on_load_clicked)
        button_row.addWidget(self.load_btn)

        self.save_btn = QPushButton("Save...")
        self.save_btn.setToolTip("Save current style as new preset")
        self.save_btn.clicked.connect(self._on_save_clicked)
        button_row.addWidget(self.save_btn)

        self.duplicate_btn = QPushButton("Duplicate")
        self.duplicate_btn.setToolTip("Duplicate selected preset")
        self.duplicate_btn.clicked.connect(self._on_duplicate_clicked)
        button_row.addWidget(self.duplicate_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Delete selected preset")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        button_row.addWidget(self.delete_btn)

        layout.addLayout(button_row)

        # Summary label
        self.summary_label = QLabel("0 presets")
        self.summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.summary_label)

        self.setWidget(container)

    def _apply_theme(self) -> None:
        """Apply current theme to dock."""
        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        text = CURRENT_THEME.get("text", "#000000")
        self.setStyleSheet(f"""
            QDockWidget {{
                background-color: {bg};
                color: {text};
            }}
            QTreeWidget {{
                background-color: {bg};
                color: {text};
            }}
        """)

    # ------------------------------------------------------------------ Tree Management

    def _refresh_tree(self) -> None:
        """Rebuild preset tree."""
        self.preset_tree.clear()

        # Built-in presets category
        if self._built_in_presets:
            built_in_root = QTreeWidgetItem(self.preset_tree, ["Built-in", ""])
            built_in_root.setExpanded(True)
            for preset in self._built_in_presets:
                name = preset.get("name", "Unnamed")
                item = QTreeWidgetItem(built_in_root, [name, "Built-in"])
                item.setData(0, Qt.UserRole, preset)
                item.setToolTip(0, preset.get("description", ""))

        # User presets category
        if self._presets:
            user_root = QTreeWidgetItem(self.preset_tree, ["User", ""])
            user_root.setExpanded(True)
            for preset in self._presets:
                name = preset.get("name", "Unnamed")
                tags_str = ", ".join(preset.get("tags", []))
                item = QTreeWidgetItem(user_root, [name, tags_str or "User"])
                item.setData(0, Qt.UserRole, preset)
                item.setToolTip(0, preset.get("description", ""))

        # Update summary
        total = len(self._built_in_presets) + len(self._presets)
        self.summary_label.setText(f"{total} preset{'s' if total != 1 else ''}")

    # ------------------------------------------------------------------ Actions

    def _get_selected_preset(self) -> dict[str, Any] | None:
        """Get currently selected preset data."""
        items = self.preset_tree.selectedItems()
        if not items:
            return None
        item = items[0]
        return cast(dict[str, Any] | None, item.data(0, Qt.UserRole))

    def _is_built_in_preset(self, preset: dict[str, Any] | None) -> bool:
        """Check if preset is built-in (read-only)."""
        if not preset:
            return False
        name = preset.get("name")
        return any(p.get("name") == name for p in self._built_in_presets)

    def _on_preset_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle double-click on preset item."""
        preset = item.data(0, Qt.UserRole)
        if preset:
            self.preset_load_requested.emit(preset)

    def _on_load_clicked(self) -> None:
        """Load selected preset."""
        preset = self._get_selected_preset()
        if not preset:
            QMessageBox.information(self, "No Selection", "Please select a preset to load.")
            return
        self.preset_load_requested.emit(preset)

    def _on_save_clicked(self) -> None:
        """Save current style as new preset."""
        name, ok = QInputDialog.getText(
            self,
            "Save Preset",
            "Enter preset name:",
        )
        if not ok or not name.strip():
            return

        name = name.strip()

        # Check for duplicate names
        existing_names = [p.get("name") for p in self._presets + self._built_in_presets]
        if name in existing_names:
            QMessageBox.warning(
                self,
                "Duplicate Name",
                f"A preset named '{name}' already exists. Please choose a different name.",
            )
            return

        # Request description (optional)
        description, ok = QInputDialog.getText(
            self,
            "Preset Description",
            "Enter description (optional):",
        )
        if not ok:
            description = ""

        # TODO: Add tag input dialog
        tags: list[str] = []

        self.preset_save_requested.emit(name, description, tags)

    def _on_duplicate_clicked(self) -> None:
        """Duplicate selected preset."""
        preset = self._get_selected_preset()
        if not preset:
            QMessageBox.information(self, "No Selection", "Please select a preset to duplicate.")
            return

        original_name = preset.get("name", "Unnamed")
        new_name, ok = QInputDialog.getText(
            self,
            "Duplicate Preset",
            "Enter name for duplicated preset:",
            text=f"{original_name} (Copy)",
        )
        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()

        # Check for duplicate names
        existing_names = [p.get("name") for p in self._presets + self._built_in_presets]
        if new_name in existing_names:
            QMessageBox.warning(
                self,
                "Duplicate Name",
                f"A preset named '{new_name}' already exists.",
            )
            return

        # Create duplicated preset
        duplicated = {
            "name": new_name,
            "description": preset.get("description", ""),
            "tags": preset.get("tags", []).copy(),
            "style": preset.get("style", {}).copy(),
        }

        self.add_preset(duplicated)
        QMessageBox.information(self, "Preset Duplicated", f"Preset '{new_name}' created.")

    def _on_delete_clicked(self) -> None:
        """Delete selected preset."""
        preset = self._get_selected_preset()
        if not preset:
            QMessageBox.information(self, "No Selection", "Please select a preset to delete.")
            return

        if self._is_built_in_preset(preset):
            QMessageBox.warning(
                self,
                "Cannot Delete",
                "Built-in presets cannot be deleted.",
            )
            return

        name = preset.get("name", "Unnamed")
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete preset '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.preset_delete_requested.emit(name)
            self.remove_preset(name)
            QMessageBox.information(self, "Preset Deleted", f"Preset '{name}' has been deleted.")
