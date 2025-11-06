# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""
Folder Import Dialog for batch loading trace files.

This dialog allows users to preview and select which files to import
from a folder structure, with automatic status detection.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from vasoanalyzer.services.folder_import_service import ImportCandidate


class FolderImportDialog(QDialog):
    """Preview and select files to import from a folder."""

    def __init__(self, candidates: list[ImportCandidate], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Folder")
        self.setModal(True)
        self.resize(900, 500)

        self.candidates = candidates
        self.selected_candidates: list[ImportCandidate] = []

        self._build_ui()
        self._populate_table()
        self._update_button_states()

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel(f"Found {len(self.candidates)} trace file(s) in the selected folder.")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Import mode selection
        mode_label = QLabel("Import mode:")
        layout.addWidget(mode_label)

        self.mode_new = QRadioButton("Import only new/unprocessed files")
        self.mode_new.setChecked(True)
        self.mode_new.toggled.connect(self._on_mode_changed)
        layout.addWidget(self.mode_new)

        self.mode_all = QRadioButton("Import all files (including already processed)")
        self.mode_all.toggled.connect(self._on_mode_changed)
        layout.addWidget(self.mode_all)

        self.mode_custom = QRadioButton("Custom selection")
        self.mode_custom.toggled.connect(self._on_mode_changed)
        layout.addWidget(self.mode_custom)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_new)
        self.mode_group.addButton(self.mode_all)
        self.mode_group.addButton(self.mode_custom)

        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Import", "Sample Name", "Trace File", "Events", "Status"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 60)  # Checkbox column
        self.table.setColumnWidth(1, 150)  # Sample name
        self.table.setColumnWidth(2, 300)  # Trace file
        self.table.setColumnWidth(3, 80)  # Events
        self.table.setColumnWidth(4, 150)  # Status
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self.table)

        # Summary label
        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.ok_button = button_box.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Import Selected")
        layout.addWidget(button_box)

    def _populate_table(self) -> None:
        """Populate the table with candidates."""
        # Block signals while populating to avoid triggering itemChanged prematurely
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.candidates))

        for row, candidate in enumerate(self.candidates):
            # Checkbox column
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkbox_item.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, checkbox_item)

            # Sample name (subfolder name)
            name_item = QTableWidgetItem(candidate.subfolder)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 1, name_item)

            # Trace file (relative path for display)
            trace_display = candidate.trace_file
            if len(trace_display) > 50:
                trace_display = "..." + trace_display[-47:]
            trace_item = QTableWidgetItem(trace_display)
            trace_item.setToolTip(candidate.trace_file)
            trace_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 2, trace_item)

            # Events file status
            events_text = "✓" if candidate.events_file else "—"
            events_item = QTableWidgetItem(events_text)
            events_item.setTextAlignment(Qt.AlignCenter)
            if candidate.events_file:
                events_item.setToolTip(candidate.events_file)
            events_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 3, events_item)

            # Status
            status_text, status_tooltip = self._get_status_display(candidate.status)
            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(status_tooltip)
            status_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 4, status_item)

        # Unblock signals now that table is fully populated
        self.table.blockSignals(False)

        # Apply default selection based on mode
        self._on_mode_changed()

    def _get_status_display(self, status: str) -> tuple[str, str]:
        """Get display text and tooltip for a status."""
        status_map = {
            "NEW": ("New", "This file has not been processed yet"),
            "ALREADY_LOADED": (
                "Already loaded",
                "This file is already loaded in the current experiment",
            ),
            "ALREADY_PROCESSED": (
                "Already processed",
                "Output file exists and is up to date",
            ),
            "MODIFIED": (
                "Modified",
                "File has been modified since last processing",
            ),
        }
        return status_map.get(status, (status, ""))

    def _on_mode_changed(self) -> None:
        """Handle mode radio button changes."""
        if self.mode_new.isChecked():
            # Select only NEW and MODIFIED files
            for row, candidate in enumerate(self.candidates):
                should_check = candidate.status in ["NEW", "MODIFIED"]
                item = self.table.item(row, 0)
                if item is None:
                    continue
                item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)
                # Disable checkboxes when not in custom mode
                item.setFlags(Qt.ItemIsEnabled)

        elif self.mode_all.isChecked():
            # Select all files except ALREADY_LOADED
            for row, candidate in enumerate(self.candidates):
                should_check = candidate.status != "ALREADY_LOADED"
                item = self.table.item(row, 0)
                if item is None:
                    continue
                item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)
                item.setFlags(Qt.ItemIsEnabled)

        elif self.mode_custom.isChecked():
            # Enable manual selection
            for row in range(len(self.candidates)):
                item = self.table.item(row, 0)
                if item is None:
                    continue
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)

        self._update_summary()
        self._update_button_states()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        """Handle table item changes."""
        if item.column() == 0:  # Checkbox column
            # If user manually changes a checkbox, switch to custom mode
            if not self.mode_custom.isChecked():
                self.mode_custom.setChecked(True)

            self._update_summary()
            self._update_button_states()

    def _update_summary(self) -> None:
        """Update the summary label."""
        checked_count = 0
        for row in range(len(self.candidates)):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                checked_count += 1

        if checked_count == 0:
            self.summary_label.setText("No files selected for import.")
        elif checked_count == 1:
            self.summary_label.setText("1 file will be imported.")
        else:
            self.summary_label.setText(f"{checked_count} files will be imported.")

    def _update_button_states(self) -> None:
        """Update the state of action buttons."""
        checked_count = 0
        for row in range(len(self.candidates)):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                checked_count += 1
        self.ok_button.setEnabled(checked_count > 0)

    def get_selected_candidates(self) -> list[ImportCandidate]:
        """Get the list of selected candidates."""
        selected = []
        for row, candidate in enumerate(self.candidates):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                selected.append(candidate)
        return selected

    def accept(self) -> None:
        """Accept the dialog and store selected candidates."""
        self.selected_candidates = self.get_selected_candidates()
        super().accept()
