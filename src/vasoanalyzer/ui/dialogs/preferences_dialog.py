"""
Application preferences dialog for VasoAnalyzer.
"""

from __future__ import annotations

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)

__all__ = ["PreferencesDialog"]


class PreferencesDialog(QDialog):
    """Dialog for configuring application-wide preferences."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.setMinimumWidth(500)

        self.settings = QSettings("TykockiLab", "VasoAnalyzer")

        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        """Build the preferences dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Project Format Settings
        project_group = QGroupBox("Project Format")
        project_layout = QVBoxLayout(project_group)
        project_layout.setSpacing(8)

        # Bundle format preference
        self.bundle_format_checkbox = QCheckBox(
            "Use cloud-safe bundle format (.vasopack) for new projects"
        )
        project_layout.addWidget(self.bundle_format_checkbox)

        help_label = QLabel(
            "<small><b>Recommended:</b> Bundle format is crash-proof and works safely with "
            "cloud storage (Dropbox, iCloud, Google Drive). Legacy .vaso format may "
            "corrupt when synced.</small>"
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #666;")
        project_layout.addWidget(help_label)

        layout.addWidget(project_group)

        # Spacer
        layout.addStretch()

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _load_settings(self):
        """Load current settings into UI."""
        use_bundle = self.settings.value("project/use_bundle_format", True, type=bool)
        self.bundle_format_checkbox.setChecked(use_bundle)

    def accept(self):
        """Save settings and close dialog."""
        # Save bundle format preference
        use_bundle = self.bundle_format_checkbox.isChecked()
        self.settings.setValue("project/use_bundle_format", use_bundle)

        # Update global flag
        from vasoanalyzer.storage import project_storage
        project_storage.USE_BUNDLE_FORMAT_BY_DEFAULT = use_bundle

        super().accept()
