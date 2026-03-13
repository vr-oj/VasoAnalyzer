# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Folder Import Dialog for batch loading trace files."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QSizePolicy,
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
        self.should_merge: bool = False
        self.total_count = len(candidates)
        self.new_count = sum(1 for c in candidates if c.status in {"NEW", "MODIFIED"})
        self.current_mode: str = "custom"
        self._custom_initialized = False
        self.folder_path: Path | None = None
        if candidates:
            try:
                self.folder_path = Path(candidates[0].subfolder_path).parent
            except Exception:
                self.folder_path = None

        self._build_ui()
        self._populate_table()
        self._update_button_states()

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Header section
        header_frame = QFrame(self)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        title_label = QLabel("Import from folder", self)
        title_label.setStyleSheet("font-weight: 600; font-size: 16px;")
        header_layout.addWidget(title_label)

        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(6)
        path_text = self.folder_path.as_posix() if self.folder_path else ""
        self.folder_edit = QLineEdit(path_text, self)
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setToolTip(path_text)
        self.folder_edit.setCursorPosition(0)
        self.folder_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        change_btn = QPushButton("Change…", self)
        change_btn.setEnabled(False)
        path_layout.addWidget(self.folder_edit, 1)
        path_layout.addWidget(change_btn, 0)
        header_layout.addLayout(path_layout)

        self.summary_label = QLabel(
            f"Found {self.total_count} trace file(s) in the selected folder.", self
        )
        header_layout.addWidget(self.summary_label)
        layout.addWidget(header_frame)

        # Table caption
        self.table_caption = QLabel(f"Files found ({self.total_count})", self)
        self.table_caption.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.table_caption)

        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Import", "Sample Name", "Trace File", "Events", "Status"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header_item = self.table.horizontalHeaderItem(0)
        if header_item is not None:
            header_item.setText("")
            header_item.setToolTip("Import")
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(3, max(self.table.columnWidth(3), 70))
        self.table.setColumnWidth(4, max(self.table.columnWidth(4), 110))
        self.table.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self.table)

        # Import mode row
        import_layout = QHBoxLayout()
        import_layout.setContentsMargins(0, 0, 0, 0)
        import_layout.setSpacing(12)
        import_label = QLabel("Import:", self)
        import_label.setStyleSheet("font-weight: 600;")
        import_layout.addWidget(import_label)

        self.mode_new = QRadioButton(f"New only ({self.new_count})")
        self.mode_new.toggled.connect(self._on_mode_changed)
        import_layout.addWidget(self.mode_new)

        self.mode_all = QRadioButton(f"All files ({self.total_count})")
        self.mode_all.toggled.connect(self._on_mode_changed)
        import_layout.addWidget(self.mode_all)

        self.mode_custom = QRadioButton("Custom selection")
        self.mode_custom.toggled.connect(self._on_mode_changed)
        import_layout.addWidget(self.mode_custom)

        import_layout.addStretch(1)

        # Merge toggle — enabled only when ≥2 rows are checked
        self.merge_btn = QPushButton("Merge into one dataset", self)
        self.merge_btn.setCheckable(True)
        self.merge_btn.setChecked(False)
        self.merge_btn.setEnabled(False)
        self.merge_btn.setToolTip(
            "Combine all checked traces into a single merged dataset\n"
            "instead of importing each as a separate dataset."
        )
        self.merge_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.merge_btn.toggled.connect(self._update_status_label)
        import_layout.addWidget(self.merge_btn)

        layout.addLayout(import_layout)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_new)
        self.mode_group.addButton(self.mode_all)
        self.mode_group.addButton(self.mode_custom)

        # Status label
        self.status_label = QLabel("Status: 0 file(s) selected.", self)
        layout.addWidget(self.status_label)

        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if self.ok_button:
            self.ok_button.setText("Import Selected")
        layout.addWidget(self.button_box)

    def _populate_table(self) -> None:
        """Populate the table with candidates."""
        # Block signals while populating to avoid triggering itemChanged prematurely
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.candidates))

        for row, candidate in enumerate(self.candidates):
            # Checkbox column
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            checkbox_item.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, checkbox_item)

            # Sample name (subfolder name)
            name_item = QTableWidgetItem(candidate.subfolder)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 1, name_item)

            # Trace file (relative path for display)
            trace_display = candidate.trace_file
            if len(trace_display) > 50:
                trace_display = "..." + trace_display[-47:]
            trace_item = QTableWidgetItem(trace_display)
            trace_item.setToolTip(candidate.trace_file)
            trace_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 2, trace_item)

            # Events file status
            events_text = "✓" if candidate.events_file else "—"
            events_item = QTableWidgetItem(events_text)
            events_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if candidate.events_file:
                events_item.setToolTip(candidate.events_file)
            events_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 3, events_item)

            # Status
            status_text, status_tooltip = self._get_status_display(candidate.status)
            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(status_tooltip)
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 4, status_item)

        # Unblock signals now that table is fully populated
        self.table.blockSignals(False)

        # Apply default selection based on available data
        if self.new_count > 0:
            self.mode_new.setChecked(True)
            self._apply_mode("new")
        else:
            self.mode_custom.setChecked(True)
            self._apply_mode("custom")

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

    def _apply_mode(self, mode: str) -> None:
        """Apply a selection mode to the table."""

        self.current_mode = mode
        row_count = self.table.rowCount()

        self.table.blockSignals(True)
        for row in range(row_count):
            item = self.table.item(row, 0)
            if item is None:
                continue
            candidate = self.candidates[row]

            if mode == "new":
                is_new = candidate.status in {"NEW", "MODIFIED"}
                item.setCheckState(Qt.CheckState.Checked if is_new else Qt.CheckState.Unchecked)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            elif mode == "all":
                if candidate.status == "ALREADY_LOADED":
                    item.setCheckState(Qt.CheckState.Unchecked)
                else:
                    item.setCheckState(Qt.CheckState.Checked)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            else:  # custom
                item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                if not self._custom_initialized:
                    is_new = candidate.status in {"NEW", "MODIFIED"}
                    item.setCheckState(Qt.CheckState.Checked if is_new else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)

        if mode == "custom":
            self._custom_initialized = True

        self._update_status_label()
        self._update_button_states()

    def _on_mode_changed(self) -> None:
        """Handle mode radio button changes."""

        if self.mode_new.isChecked():
            self._apply_mode("new")
        elif self.mode_all.isChecked():
            self._apply_mode("all")
        elif self.mode_custom.isChecked():
            self._apply_mode("custom")

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        """Handle table item changes."""
        if item.column() == 0:  # Checkbox column
            # If user manually changes a checkbox, switch to custom mode
            if not self.mode_custom.isChecked():
                self.mode_custom.setChecked(True)

            self._update_status_label()
            self._update_button_states()

    def _selected_count(self) -> int:
        """Return how many rows are selected for import."""

        count = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                count += 1
        return count

    def _update_status_label(self) -> None:
        """Update the status message beneath the table."""

        if self.total_count == 0:
            self.status_label.setText("No files found.")
            return

        selected = self._selected_count()

        if self.merge_btn.isChecked() and selected >= 2:
            self.status_label.setText(
                f"{selected} checked item(s) will be merged into a single continuous dataset "
                "(sorted by filename)."
            )
            return

        if self.current_mode == "new":
            if self.new_count > 0:
                self.status_label.setText(f"Importing {self.new_count} new file(s).")
            else:
                self.status_label.setText(
                    "No new files found. Use 'Custom selection' to re-import existing files."
                )
        elif self.current_mode == "all":
            self.status_label.setText(
                f"Re-importing {self.total_count} file(s). Existing data may be overwritten."
            )
        else:
            self.status_label.setText(f"{selected} file(s) selected.")

    def _update_button_states(self) -> None:
        """Update the state of action buttons."""
        checked_count = self._selected_count()
        if self.ok_button:
            self.ok_button.setEnabled(checked_count > 0)
        # Merge button requires at least 2 checked items; uncheck if no longer valid
        self.merge_btn.setEnabled(checked_count >= 2)
        if checked_count < 2 and self.merge_btn.isChecked():
            self.merge_btn.setChecked(False)

    def get_selected_candidates(self) -> list[ImportCandidate]:
        """Get the list of selected candidates."""
        selected = []
        for row, candidate in enumerate(self.candidates):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(candidate)
        return selected

    def accept(self) -> None:
        """Accept the dialog and store selected candidates."""
        self.selected_candidates = self.get_selected_candidates()
        self.should_merge = self.merge_btn.isChecked() and len(self.selected_candidates) >= 2
        super().accept()
