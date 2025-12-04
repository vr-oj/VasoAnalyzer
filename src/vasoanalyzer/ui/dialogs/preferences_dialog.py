"""
Application preferences dialog for VasoAnalyzer.
"""

from __future__ import annotations

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

__all__ = ["PreferencesDialog"]


class PreferencesDialog(QDialog):
    """Dialog for configuring application-wide preferences."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)

        self.settings = QSettings("TykockiLab", "VasoAnalyzer")

        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        """Build the preferences dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Create tab widget
        tabs = QTabWidget()
        tabs.addTab(self._create_general_tab(), "General")
        tabs.addTab(self._create_projects_tab(), "Projects")
        tabs.addTab(self._create_autosave_tab(), "Autosave && Snapshots")
        tabs.addTab(self._create_advanced_tab(), "Advanced")

        layout.addWidget(tabs)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _create_general_tab(self):
        """Create general settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

        # Default Directories
        dir_group = QGroupBox("Default Directories")
        dir_layout = QFormLayout(dir_group)
        dir_layout.setSpacing(8)

        # Project directory
        project_dir_layout = QHBoxLayout()
        self.project_dir_edit = QLineEdit()
        self.project_dir_edit.setPlaceholderText("~/Documents/VasoAnalyzer")
        project_dir_browse = QPushButton("Browse...")
        project_dir_browse.clicked.connect(self._browse_project_dir)
        project_dir_layout.addWidget(self.project_dir_edit)
        project_dir_layout.addWidget(project_dir_browse)
        dir_layout.addRow("Default save location:", project_dir_layout)

        # Data import directory
        import_dir_layout = QHBoxLayout()
        self.import_dir_edit = QLineEdit()
        self.import_dir_edit.setPlaceholderText("~/Documents")
        import_dir_browse = QPushButton("Browse...")
        import_dir_browse.clicked.connect(self._browse_import_dir)
        import_dir_layout.addWidget(self.import_dir_edit)
        import_dir_layout.addWidget(import_dir_browse)
        dir_layout.addRow("Default data location:", import_dir_layout)

        layout.addWidget(dir_group)

        # Appearance
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QFormLayout(appearance_group)
        appearance_layout.setSpacing(8)

        self.theme_mode_combo = QComboBox()
        self.theme_mode_combo.addItem("Follow system", "system")
        self.theme_mode_combo.addItem("Light", "light")
        self.theme_mode_combo.addItem("Dark", "dark")
        self.theme_mode_combo.setEditable(False)

        appearance_layout.addRow("Theme (requires restart):", self.theme_mode_combo)
        layout.addWidget(appearance_group)

        # Startup Options
        startup_group = QGroupBox("Startup")
        startup_layout = QVBoxLayout(startup_group)
        startup_layout.setSpacing(8)

        self.show_welcome_checkbox = QCheckBox("Show welcome dialog on startup")
        startup_layout.addWidget(self.show_welcome_checkbox)

        self.restore_session_checkbox = QCheckBox("Restore last session on startup")
        startup_layout.addWidget(self.restore_session_checkbox)

        layout.addWidget(startup_group)

        layout.addStretch()
        return widget

    def _create_projects_tab(self):
        """Create project settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

        # Project Format Settings
        format_group = QGroupBox("Project Format")
        format_layout = QVBoxLayout(format_group)
        format_layout.setSpacing(8)

        # Bundle format preference
        self.bundle_format_checkbox = QCheckBox(
            "Use single-file project format (.vaso) for new projects"
        )
        format_layout.addWidget(self.bundle_format_checkbox)

        help_label = QLabel(
            "<small><b>Recommended (default):</b> Single-file format (.vaso) is crash-proof, "
            "works safely with cloud storage (Dropbox, iCloud, Google Drive), and is easy to "
            "share and backup like LabChart or Prism files. Uses snapshot-based saves internally.</small>"
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #666;")
        format_layout.addWidget(help_label)

        layout.addWidget(format_group)

        # Migration Options
        migration_group = QGroupBox("Migration && Compatibility")
        migration_layout = QVBoxLayout(migration_group)
        migration_layout.setSpacing(8)

        self.auto_migrate_checkbox = QCheckBox(
            "Automatically migrate legacy projects to new format"
        )
        self.auto_migrate_checkbox.setChecked(True)
        migration_layout.addWidget(self.auto_migrate_checkbox)

        self.keep_legacy_checkbox = QCheckBox("Keep legacy files after migration (.vaso.legacy)")
        self.keep_legacy_checkbox.setChecked(True)
        migration_layout.addWidget(self.keep_legacy_checkbox)

        migration_help = QLabel(
            "<small>When opening old .vaso or .vasopack projects, automatically convert them "
            "to the new format and keep backups for safety.</small>"
        )
        migration_help.setWordWrap(True)
        migration_help.setStyleSheet("color: #666;")
        migration_layout.addWidget(migration_help)

        layout.addWidget(migration_group)

        layout.addStretch()
        return widget

    def _create_autosave_tab(self):
        """Create autosave and snapshot settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

        # Autosave Settings
        autosave_group = QGroupBox("Autosave")
        autosave_layout = QFormLayout(autosave_group)
        autosave_layout.setSpacing(8)

        self.enable_autosave_checkbox = QCheckBox("Enable autosave")
        autosave_layout.addRow("", self.enable_autosave_checkbox)

        self.autosave_interval_combo = QComboBox()
        self.autosave_interval_combo.addItems(
            ["30 seconds", "1 minute", "2 minutes", "5 minutes", "10 minutes"]
        )
        autosave_layout.addRow("Autosave interval:", self.autosave_interval_combo)

        autosave_help = QLabel(
            "<small>Autosave creates periodic snapshots of your work. "
            "If the app crashes, you'll only lose changes since the last autosave.</small>"
        )
        autosave_help.setWordWrap(True)
        autosave_help.setStyleSheet("color: #666;")
        autosave_layout.addRow("", autosave_help)

        layout.addWidget(autosave_group)

        # Snapshot Settings
        snapshot_group = QGroupBox("Snapshot Retention")
        snapshot_layout = QFormLayout(snapshot_group)
        snapshot_layout.setSpacing(8)

        self.snapshot_count_spin = QSpinBox()
        self.snapshot_count_spin.setMinimum(1)
        self.snapshot_count_spin.setMaximum(500)
        self.snapshot_count_spin.setValue(3)
        self.snapshot_count_spin.setSuffix(" snapshots")
        snapshot_layout.addRow("Keep last:", self.snapshot_count_spin)

        self.embed_snapshots_checkbox = QCheckBox(
            "Embed snapshot video into project (larger, fully portable)"
        )
        snapshot_layout.addRow("", self.embed_snapshots_checkbox)

        snapshot_help = QLabel(
            "<small>Projects keep multiple snapshots for recovery. Older snapshots are automatically "
            "deleted when this limit is reached. Each snapshot is a complete copy of your project.</small>"
        )
        snapshot_help.setWordWrap(True)
        snapshot_help.setStyleSheet("color: #666;")
        snapshot_layout.addRow("", snapshot_help)

        # Show disk usage estimate
        self.disk_usage_label = QLabel()
        self.disk_usage_label.setStyleSheet("color: #999;")
        snapshot_layout.addRow("", self.disk_usage_label)
        self._update_disk_usage_estimate()

        # Connect signal to update estimate
        self.snapshot_count_spin.valueChanged.connect(self._update_disk_usage_estimate)

        layout.addWidget(snapshot_group)

        layout.addStretch()
        return widget

    def _create_advanced_tab(self):
        """Create advanced settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

        # Recovery Settings
        recovery_group = QGroupBox("Recovery && Cleanup")
        recovery_layout = QFormLayout(recovery_group)
        recovery_layout.setSpacing(8)

        self.auto_recovery_checkbox = QCheckBox("Enable automatic recovery")
        self.auto_recovery_checkbox.setChecked(True)
        recovery_layout.addRow("", self.auto_recovery_checkbox)

        self.temp_cleanup_spin = QSpinBox()
        self.temp_cleanup_spin.setMinimum(1)
        self.temp_cleanup_spin.setMaximum(168)  # 1 week
        self.temp_cleanup_spin.setValue(24)
        self.temp_cleanup_spin.setSuffix(" hours")
        recovery_layout.addRow("Clean temp files older than:", self.temp_cleanup_spin)

        recovery_help = QLabel(
            "<small>Temporary files from crashed sessions are automatically cleaned up after this time.</small>"
        )
        recovery_help.setWordWrap(True)
        recovery_help.setStyleSheet("color: #666;")
        recovery_layout.addRow("", recovery_help)

        layout.addWidget(recovery_group)

        # Performance Settings
        perf_group = QGroupBox("Performance")
        perf_layout = QVBoxLayout(perf_group)
        perf_layout.setSpacing(8)

        self.compress_container_checkbox = QCheckBox(
            "Compress container files (slower saves, smaller files)"
        )
        self.compress_container_checkbox.setChecked(False)
        perf_layout.addWidget(self.compress_container_checkbox)

        perf_help = QLabel(
            "<small>Enabling compression reduces file size by ~10-20% but makes saves slower. "
            "Most SQLite data doesn't compress well.</small>"
        )
        perf_help.setWordWrap(True)
        perf_help.setStyleSheet("color: #666;")
        perf_layout.addWidget(perf_help)

        layout.addWidget(perf_group)

        # Maintenance
        maintenance_group = QGroupBox("Maintenance")
        maintenance_layout = QVBoxLayout(maintenance_group)
        maintenance_layout.setSpacing(8)

        cleanup_button = QPushButton("Clean Up Temp Files Now")
        cleanup_button.clicked.connect(self._cleanup_temp_now)
        maintenance_layout.addWidget(cleanup_button)

        maintenance_help = QLabel(
            "<small>Manually clean up temporary files from previous sessions.</small>"
        )
        maintenance_help.setStyleSheet("color: #666;")
        maintenance_layout.addWidget(maintenance_help)

        layout.addWidget(maintenance_group)

        layout.addStretch()
        return widget

    def _browse_project_dir(self):
        """Browse for default project directory."""
        current = self.project_dir_edit.text() or ""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Default Project Directory", current
        )
        if directory:
            self.project_dir_edit.setText(directory)

    def _browse_import_dir(self):
        """Browse for default import directory."""
        current = self.import_dir_edit.text() or ""
        directory = QFileDialog.getExistingDirectory(self, "Select Default Data Directory", current)
        if directory:
            self.import_dir_edit.setText(directory)

    def _update_disk_usage_estimate(self):
        """Update disk usage estimate label."""
        count = self.snapshot_count_spin.value()
        # Assume average project is 10 MB
        estimated_mb = count * 10
        if estimated_mb < 1024:
            usage_text = (
                f"<small>Estimated disk usage: ~{estimated_mb} MB for typical project</small>"
            )
        else:
            usage_gb = estimated_mb / 1024
            usage_text = (
                f"<small>Estimated disk usage: ~{usage_gb:.1f} GB for typical project</small>"
            )
        self.disk_usage_label.setText(usage_text)

    def _cleanup_temp_now(self):
        """Manually trigger temp file cleanup."""
        try:
            from vasoanalyzer.storage.container_fs import cleanup_stale_temp_dirs

            max_age = self.temp_cleanup_spin.value() * 3600  # Convert hours to seconds
            cleaned = cleanup_stale_temp_dirs(max_age=max_age)

            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.information(
                self, "Cleanup Complete", f"Cleaned up {cleaned} temporary directory(ies)."
            )
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Cleanup Failed", f"Failed to clean up temp files:\n{e}")

    def _load_settings(self):
        """Load current settings into UI."""
        # General
        self.project_dir_edit.setText(self.settings.value("directories/projects", "", type=str))
        self.import_dir_edit.setText(self.settings.value("directories/imports", "", type=str))
        self.show_welcome_checkbox.setChecked(
            self.settings.value("startup/show_welcome", True, type=bool)
        )
        self.restore_session_checkbox.setChecked(
            self.settings.value("startup/restore_session", False, type=bool)
        )

        # Appearance
        mode = self.settings.value("appearance/themeMode", "system", type=str)
        self._initial_theme_mode = mode
        index = self.theme_mode_combo.findData(mode)
        if index < 0:
            index = 0
        self.theme_mode_combo.setCurrentIndex(index)

        # Projects
        self.bundle_format_checkbox.setChecked(
            self.settings.value("project/use_bundle_format", True, type=bool)
        )
        self.auto_migrate_checkbox.setChecked(
            self.settings.value("project/auto_migrate", True, type=bool)
        )
        self.keep_legacy_checkbox.setChecked(
            self.settings.value("project/keep_legacy", True, type=bool)
        )

        # Autosave
        self.enable_autosave_checkbox.setChecked(
            self.settings.value("autosave/enabled", True, type=bool)
        )
        interval_seconds = self.settings.value("autosave/interval", 30, type=int)
        interval_index = {30: 0, 60: 1, 120: 2, 300: 3, 600: 4}.get(interval_seconds, 0)
        self.autosave_interval_combo.setCurrentIndex(interval_index)

        # Snapshots
        self.snapshot_count_spin.setValue(
            self.settings.value("snapshots/keep_count", 3, type=int)
        )
        embed = self.settings.value("snapshots/embed_stacks", False, type=bool)
        self.embed_snapshots_checkbox.setChecked(bool(embed))

        # Advanced
        self.auto_recovery_checkbox.setChecked(
            self.settings.value("recovery/enabled", True, type=bool)
        )
        self.temp_cleanup_spin.setValue(
            self.settings.value("recovery/temp_cleanup_hours", 24, type=int)
        )
        self.compress_container_checkbox.setChecked(
            self.settings.value("performance/compress_containers", False, type=bool)
        )

    def accept(self):
        """Save settings and close dialog."""
        mode = self.theme_mode_combo.currentData()
        # General
        self.settings.setValue("directories/projects", self.project_dir_edit.text())
        self.settings.setValue("directories/imports", self.import_dir_edit.text())
        self.settings.setValue("startup/show_welcome", self.show_welcome_checkbox.isChecked())
        self.settings.setValue("startup/restore_session", self.restore_session_checkbox.isChecked())

        # Appearance
        self.settings.setValue("appearance/themeMode", mode)

        # Projects
        use_bundle = self.bundle_format_checkbox.isChecked()
        self.settings.setValue("project/use_bundle_format", use_bundle)
        self.settings.setValue("project/auto_migrate", self.auto_migrate_checkbox.isChecked())
        self.settings.setValue("project/keep_legacy", self.keep_legacy_checkbox.isChecked())

        # Autosave
        self.settings.setValue("autosave/enabled", self.enable_autosave_checkbox.isChecked())
        interval_map = {0: 30, 1: 60, 2: 120, 3: 300, 4: 600}
        interval_seconds = interval_map.get(self.autosave_interval_combo.currentIndex(), 30)
        self.settings.setValue("autosave/interval", interval_seconds)

        # Snapshots
        self.settings.setValue("snapshots/keep_count", self.snapshot_count_spin.value())
        self.settings.setValue(
            "snapshots/embed_stacks", self.embed_snapshots_checkbox.isChecked()
        )

        # Advanced
        self.settings.setValue("recovery/enabled", self.auto_recovery_checkbox.isChecked())
        self.settings.setValue("recovery/temp_cleanup_hours", self.temp_cleanup_spin.value())
        self.settings.setValue(
            "performance/compress_containers", self.compress_container_checkbox.isChecked()
        )

        # Update global flag for project format
        from vasoanalyzer.storage import project_storage

        project_storage.USE_BUNDLE_FORMAT_BY_DEFAULT = use_bundle

        theme_changed = getattr(self, "_initial_theme_mode", None) != mode
        if theme_changed:
            try:
                from PyQt5.QtWidgets import QMessageBox

                QMessageBox.information(
                    self,
                    "Restart required",
                    "Theme changes will take effect after you restart VasoAnalyzer.",
                )
            except Exception:
                pass

        super().accept()
