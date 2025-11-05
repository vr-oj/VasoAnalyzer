# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Dialog showing all keyboard shortcuts in the application."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
)


class KeyboardShortcutsDialog(QDialog):
    """Display all keyboard shortcuts with search functionality."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(700, 500)
        self.shortcuts_data = []

        self._setup_ui()
        self._collect_shortcuts()
        self._populate_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("All keyboard shortcuts available in VasoAnalyzer")
        header.setStyleSheet("font-weight: bold; font-size: 12pt; padding: 8px;")
        layout.addWidget(header)

        # Search box
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter shortcuts by name or key...")
        self.search_box.textChanged.connect(self._filter_shortcuts)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_box)
        layout.addLayout(search_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Action", "Shortcut", "Category"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.close)
        layout.addWidget(button_box)

    def _collect_shortcuts(self):
        """Collect all shortcuts from parent window's actions."""
        if not self.parent_window:
            return

        # Collect from all QActions in the main window
        actions = self.parent_window.findChildren(type(self.parent_window.actions()[0]))

        for action in actions:
            if not action.shortcut().isEmpty():
                text = action.text().replace("&", "")  # Remove mnemonics
                shortcut = action.shortcut().toString()

                # Determine category from action name or text
                category = self._categorize_action(text, action)

                self.shortcuts_data.append({
                    "action": text,
                    "shortcut": shortcut,
                    "category": category
                })

        # Sort by category, then by action name
        self.shortcuts_data.sort(key=lambda x: (x["category"], x["action"]))

    def _categorize_action(self, text, action):
        """Categorize action based on its text or properties."""
        text_lower = text.lower()

        if any(kw in text_lower for kw in ["new", "open", "save", "export", "import", "close", "quit", "exit"]):
            return "File"
        elif any(kw in text_lower for kw in ["undo", "redo", "cut", "copy", "paste", "delete"]):
            return "Edit"
        elif any(kw in text_lower for kw in ["zoom", "pan", "reset", "fit", "grid", "fullscreen", "inner", "outer"]):
            return "View"
        elif any(kw in text_lower for kw in ["project", "sample", "experiment"]):
            return "Project"
        elif any(kw in text_lower for kw in ["snapshot", "tiff", "image"]):
            return "Snapshot"
        elif any(kw in text_lower for kw in ["help", "guide", "manual", "about"]):
            return "Help"
        else:
            return "General"

    def _populate_table(self):
        """Populate table with shortcuts data."""
        self.table.setRowCount(len(self.shortcuts_data))

        for row, item in enumerate(self.shortcuts_data):
            action_item = QTableWidgetItem(item["action"])
            shortcut_item = QTableWidgetItem(item["shortcut"])
            category_item = QTableWidgetItem(item["category"])

            # Make shortcut column bold
            font = shortcut_item.font()
            font.setBold(True)
            shortcut_item.setFont(font)

            self.table.setItem(row, 0, action_item)
            self.table.setItem(row, 1, shortcut_item)
            self.table.setItem(row, 2, category_item)

    def _filter_shortcuts(self, text):
        """Filter table based on search text."""
        search_text = text.lower()

        for row in range(self.table.rowCount()):
            action_item = self.table.item(row, 0)
            shortcut_item = self.table.item(row, 1)
            category_item = self.table.item(row, 2)

            # Check if search text matches any column
            matches = (
                search_text in action_item.text().lower() or
                search_text in shortcut_item.text().lower() or
                search_text in category_item.text().lower()
            )

            self.table.setRowHidden(row, not matches)
