# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Dialog for recovering from application crashes."""

import os
from pathlib import Path
from datetime import datetime
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QDialogButtonBox,
    QMessageBox,
)


class CrashRecoveryDialog(QDialog):
    """Dialog offering to recover unsaved work after a crash."""

    def __init__(self, autosave_files, parent=None):
        super().__init__(parent)
        self.autosave_files = autosave_files
        self.selected_file = None

        self.setWindowTitle("Recover Unsaved Work")
        self.setMinimumSize(600, 400)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header with warning icon
        header_layout = QHBoxLayout()
        warning_label = QLabel("⚠️")
        warning_label.setStyleSheet("font-size: 48px;")
        header_layout.addWidget(warning_label)

        message = QLabel(
            "<b>VasoAnalyzer closed unexpectedly.</b><br><br>"
            "The following projects have unsaved changes that can be recovered:"
        )
        message.setWordWrap(True)
        header_layout.addWidget(message, 1)
        layout.addLayout(header_layout)

        # List of recoverable files
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)

        for autosave_path in self.autosave_files:
            autosave_path = Path(autosave_path)
            project_path = autosave_path.with_suffix("")

            # Get modification time
            try:
                mtime = os.path.getmtime(autosave_path)
                timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            except OSError:
                timestamp = "Unknown"

            # Create list item
            item_text = (
                f"{project_path.name}\n"
                f"Location: {project_path.parent}\n"
                f"Last saved: {timestamp}"
            )

            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, str(autosave_path))
            self.file_list.addItem(item)

        self.file_list.setCurrentRow(0)  # Select first item
        layout.addWidget(self.file_list)

        # Info label
        info_label = QLabel(
            "💡 Select a project and click 'Recover' to restore your work.\n"
            "The autosave file will be used to restore the project."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("padding: 8px; background-color: #f0f0f0; border-radius: 4px;")
        layout.addWidget(info_label)

        # Buttons
        button_layout = QHBoxLayout()

        self.discard_all_btn = QPushButton("Discard All")
        self.discard_all_btn.setToolTip("Delete all autosave files and start fresh")
        self.discard_all_btn.clicked.connect(self._on_discard_all)

        button_box = QDialogButtonBox()
        recover_btn = button_box.addButton("Recover Selected", QDialogButtonBox.AcceptRole)
        cancel_btn = button_box.addButton("Remind Me Later", QDialogButtonBox.RejectRole)

        recover_btn.setDefault(True)
        button_box.accepted.connect(self._on_recover)
        button_box.rejected.connect(self.reject)

        button_layout.addWidget(self.discard_all_btn)
        button_layout.addStretch()
        button_layout.addWidget(button_box)

        layout.addLayout(button_layout)

    def _on_recover(self):
        """Handle recover button click."""
        current = self.file_list.currentItem()
        if current:
            self.selected_file = current.data(Qt.UserRole)
            self.accept()
        else:
            QMessageBox.warning(
                self,
                "No Selection",
                "Please select a project to recover."
            )

    def _on_discard_all(self):
        """Handle discard all button click."""
        reply = QMessageBox.question(
            self,
            "Discard All Autosaves",
            "Are you sure you want to discard all autosave files?\n\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # Delete all autosave files
            for autosave_path in self.autosave_files:
                try:
                    os.remove(autosave_path)
                except OSError as e:
                    QMessageBox.warning(
                        self,
                        "Delete Failed",
                        f"Could not delete {autosave_path}:\n{e}"
                    )

            self.reject()
