# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import re
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _sanitize_project_name(name: str) -> str:
    slug = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    slug = re.sub(r"\s+", " ", slug)
    return slug


class NewProjectDialog(QDialog):
    """Guided dialog for setting up a new project and its first experiment."""

    def __init__(self, parent=None, *, settings=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Project")
        self.setModal(True)
        self._settings = settings
        self._selected_directory = ""
        self._preview_path = ""
        self._resolved_project_path = ""

        self._default_dir = self._resolve_default_directory()

        self._build_ui()
        self._apply_defaults()

    # ------------------------------------------------------------------#
    def _resolve_default_directory(self) -> str:
        if self._settings is None:
            return str(Path.home() / "Documents")
        default_dir = self._settings.value("projects/last_directory", "", type=str)
        if not default_dir:
            default_dir = self._settings.value("paths/last_project_directory", "", type=str)
        if not default_dir:
            default_dir = str(Path.home() / "Documents")
        return default_dir

    # ------------------------------------------------------------------#
    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        intro = QLabel("Create a project to organize datasets, events, and exports.")
        intro.setWordWrap(True)
        main_layout.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        main_layout.addLayout(form)

        self.project_name_edit = QLineEdit(self)
        self.project_name_edit.setPlaceholderText("e.g. Vaso Study 2025")
        form.addRow("Project name:", self.project_name_edit)

        path_container = QWidget(self)
        path_layout = QHBoxLayout(path_container)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(6)
        self.project_path_edit = QLineEdit(self)
        self.project_path_edit.setPlaceholderText("Choose a folder")
        self.project_path_edit.setReadOnly(True)
        self.project_path_edit.setToolTip("")
        self.choose_location_button = QPushButton("Choose…", self)
        self.choose_location_button.clicked.connect(self._choose_location)
        path_layout.addWidget(self.project_path_edit, stretch=1)
        path_layout.addWidget(self.choose_location_button, stretch=0)
        form.addRow("Location:", path_container)

        self.create_experiment_checkbox = QCheckBox("Create first experiment", self)
        self.create_experiment_checkbox.setChecked(True)
        form.addRow("Create first experiment:", self.create_experiment_checkbox)

        self.experiment_name_edit = QLineEdit(self)
        self.experiment_name_edit.setPlaceholderText("e.g. Baseline")
        form.addRow("Experiment name:", self.experiment_name_edit)

        self.preview_label = QLabel("", self)
        self.preview_label.setWordWrap(False)
        self.preview_label.setStyleSheet("color: palette(mid);")
        main_layout.addWidget(self.preview_label)

        self.hint_label = QLabel("", self)
        self.hint_label.setWordWrap(False)
        self.hint_label.setStyleSheet("color: palette(mid);")
        self.hint_label.setVisible(False)
        main_layout.addWidget(self.hint_label)

        button_box = QHBoxLayout()
        button_box.setContentsMargins(0, 0, 0, 0)
        button_box.setSpacing(8)
        main_layout.addLayout(button_box)

        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self.reject)
        button_box.addStretch(1)
        button_box.addWidget(self.cancel_button)

        self.create_button = QPushButton("Create", self)
        self.create_button.setDefault(True)
        self.create_button.setAutoDefault(True)
        self.create_button.clicked.connect(self.accept)
        button_box.addWidget(self.create_button)

        self.project_name_edit.textChanged.connect(self._on_project_name_changed)
        self.create_experiment_checkbox.toggled.connect(self._toggle_experiment_input)
        self.experiment_name_edit.textChanged.connect(self._update_validation)

    # ------------------------------------------------------------------#
    def _apply_defaults(self) -> None:
        self.project_name_edit.setText("Untitled Project")
        self._set_location(self._default_dir)
        self._toggle_experiment_input(self.create_experiment_checkbox.isChecked())
        self.project_name_edit.setFocus(Qt.OtherFocusReason)
        self.project_name_edit.selectAll()
        self._update_preview()
        self._update_validation()

    # ------------------------------------------------------------------#
    def _toggle_experiment_input(self, checked: bool) -> None:
        self.experiment_name_edit.setEnabled(checked)
        if checked and not self.experiment_name_edit.text().strip():
            self.experiment_name_edit.setText("Experiment 1")
        self._update_validation()

    # ------------------------------------------------------------------#
    def _on_project_name_changed(self, text: str) -> None:
        _ = text
        self._update_preview()
        self._update_validation()

    # ------------------------------------------------------------------#
    def _set_location(self, directory: str) -> None:
        self._selected_directory = directory.strip()
        self.project_path_edit.setText(self._selected_directory)
        self.project_path_edit.setToolTip(self._selected_directory)
        self._update_preview()
        self._update_validation()

    # ------------------------------------------------------------------#
    def _choose_location(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Project Location",
            self.project_path_edit.text() or self._default_dir,
        )
        if not directory:
            return
        self._default_dir = directory
        self._set_location(directory)
        if self._settings:
            self._settings.setValue("projects/last_directory", directory)

    # ------------------------------------------------------------------#
    def _build_project_path(self) -> Path | None:
        name = _sanitize_project_name(self.project_name_edit.text())
        if not name:
            return None
        if not self._selected_directory:
            return None
        return Path(self._selected_directory).expanduser() / f"{name}.vaso"

    # ------------------------------------------------------------------#
    def _update_preview(self) -> None:
        path = self._build_project_path()
        self._preview_path = str(path) if path else ""
        self._refresh_preview_label()

    # ------------------------------------------------------------------#
    def _refresh_preview_label(self) -> None:
        if not self._preview_path:
            self.preview_label.setText("")
            self.preview_label.setToolTip("")
            return
        full_text = f"Will create: {self._preview_path}"
        if self.preview_label.width() > 0:
            metrics = QFontMetrics(self.preview_label.font())
            display = metrics.elidedText(
                full_text, Qt.ElideMiddle, self.preview_label.width()
            )
        else:
            display = full_text
        self.preview_label.setText(display)
        self.preview_label.setToolTip(self._preview_path)

    # ------------------------------------------------------------------#
    def _update_validation(self) -> bool:
        hint = ""
        if not _sanitize_project_name(self.project_name_edit.text()):
            hint = "Enter a project name."
        elif not self._selected_directory:
            hint = "Choose a location for the project."
        elif (
            self.create_experiment_checkbox.isChecked()
            and not self.experiment_name_edit.text().strip()
        ):
            hint = "Enter a name for the first experiment."

        is_valid = not hint
        self.create_button.setEnabled(is_valid)
        self.hint_label.setText(hint)
        self.hint_label.setVisible(bool(hint))
        return is_valid

    # ------------------------------------------------------------------#
    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_preview_label()

    # ------------------------------------------------------------------#
    def accept(self) -> None:
        if not self._update_validation():
            return
        name = _sanitize_project_name(self.project_name_edit.text())
        project_path = self._build_project_path()
        if project_path is None:
            return

        try:
            project_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(
                self, "Create Project", f"Unable to prepare the target folder:\n{exc}"
            )
            return

        if self._settings:
            self._settings.setValue("projects/last_directory", str(project_path.parent))

        self.project_name_edit.setText(name)
        self._resolved_project_path = str(project_path)
        super().accept()

    # ------------------------------------------------------------------#
    def project_name(self) -> str:
        return self.project_name_edit.text().strip()

    # ------------------------------------------------------------------#
    def project_path(self) -> str:
        if self._resolved_project_path:
            return self._resolved_project_path
        path = self._build_project_path()
        return str(path) if path else ""

    # ------------------------------------------------------------------#
    def experiment_name(self) -> str | None:
        if not self.create_experiment_checkbox.isChecked():
            return None
        exp_name = self.experiment_name_edit.text().strip()
        return exp_name or None
