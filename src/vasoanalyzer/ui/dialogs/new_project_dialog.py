# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import re
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
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
        self._path_edited_manually = False

        self._default_dir = (
            self._settings.value("paths/last_project_directory", "", type=str)
            if self._settings
            else ""
        )
        if not self._default_dir:
            self._default_dir = str(Path.home())

        self._build_ui()
        self._apply_defaults()

    # ------------------------------------------------------------------#
    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        intro = QLabel("Follow the steps below to initialise a project and get ready to add data.")
        intro.setWordWrap(True)
        main_layout.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
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
        self.project_path_edit.setPlaceholderText("Select where the project will be saved")
        browse_button = QPushButton("Browse…", self)
        browse_button.clicked.connect(self._choose_path)
        path_layout.addWidget(self.project_path_edit, stretch=1)
        path_layout.addWidget(browse_button, stretch=0)
        form.addRow("Save location:", path_container)

        experiment_container = QWidget(self)
        exp_layout = QHBoxLayout(experiment_container)
        exp_layout.setContentsMargins(0, 0, 0, 0)
        exp_layout.setSpacing(6)
        self.create_experiment_checkbox = QCheckBox("Add first experiment", self)
        self.create_experiment_checkbox.setChecked(True)
        self.experiment_name_edit = QLineEdit(self)
        self.experiment_name_edit.setPlaceholderText("e.g. Baseline")
        exp_layout.addWidget(self.create_experiment_checkbox, stretch=0)
        exp_layout.addWidget(self.experiment_name_edit, stretch=1)
        form.addRow("Experiment:", experiment_container)

        guidance = QLabel(
            "After creating the project, use the toolbar to load traces, events, and images."
        )
        guidance.setWordWrap(True)
        guidance.setStyleSheet("color: palette(mid);")
        main_layout.addWidget(guidance)

        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.project_name_edit.textChanged.connect(self._sync_path_with_name)
        self.project_path_edit.textEdited.connect(self._mark_manual_path)
        self.create_experiment_checkbox.toggled.connect(self._toggle_experiment_input)

    # ------------------------------------------------------------------#
    def _apply_defaults(self) -> None:
        self._toggle_experiment_input(self.create_experiment_checkbox.isChecked())
        self.project_name_edit.setFocus(Qt.OtherFocusReason)

    # ------------------------------------------------------------------#
    def _toggle_experiment_input(self, checked: bool) -> None:
        self.experiment_name_edit.setEnabled(checked)
        if checked and not self.experiment_name_edit.text().strip():
            self.experiment_name_edit.setText("Experiment 1")

    # ------------------------------------------------------------------#
    def _sync_path_with_name(self, text: str) -> None:
        if self._path_edited_manually:
            return
        clean_name = _sanitize_project_name(text)
        if not clean_name:
            self.project_path_edit.clear()
            return
        suggested = Path(self._default_dir) / f"{clean_name}.vaso"
        self.project_path_edit.setText(str(suggested))

    # ------------------------------------------------------------------#
    def _mark_manual_path(self) -> None:
        self._path_edited_manually = True

    # ------------------------------------------------------------------#
    def _choose_path(self) -> None:
        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Create Project",
            self.project_path_edit.text() or self._default_dir,
            "VasoAnalyzer Projects (*.vaso);;Folder Bundles (*.vasopack)",
        )
        if not filename:
            return
        path = Path(filename).expanduser()

        # Enforce extension based on selected filter
        if "Folder Bundles" in selected_filter:
            if path.suffix.lower() != ".vasopack":
                path = path.with_suffix(".vasopack")
        else:
            # Default to .vaso (single-file container)
            if path.suffix.lower() != ".vaso":
                path = path.with_suffix(".vaso")

        self.project_path_edit.setText(str(path))
        self._path_edited_manually = True

    # ------------------------------------------------------------------#
    def accept(self) -> None:
        name = _sanitize_project_name(self.project_name_edit.text())
        if not name:
            QMessageBox.warning(self, "Missing Information", "Please enter a project name.")
            self.project_name_edit.setFocus(Qt.OtherFocusReason)
            return

        path_text = self.project_path_edit.text().strip()
        if not path_text:
            QMessageBox.warning(
                self, "Missing Information", "Select where the project should be saved."
            )
            self.project_path_edit.setFocus(Qt.OtherFocusReason)
            return

        if self.create_experiment_checkbox.isChecked():
            exp_name = self.experiment_name_edit.text().strip()
            if not exp_name:
                QMessageBox.warning(
                    self,
                    "Missing Information",
                    "Provide a name for the first experiment or uncheck the option.",
                )
                self.experiment_name_edit.setFocus(Qt.OtherFocusReason)
                return

        project_path = Path(path_text).expanduser()
        # Ensure valid extension (default to .vaso for new projects)
        if project_path.suffix.lower() not in [".vaso", ".vasopack"]:
            project_path = project_path.with_suffix(".vaso")

        try:
            project_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(
                self, "Create Project", f"Unable to prepare the target folder:\n{exc}"
            )
            return

        if self._settings:
            self._settings.setValue("paths/last_project_directory", str(project_path.parent))

        self.project_name_edit.setText(name)
        self.project_path_edit.setText(str(project_path))
        self._path_edited_manually = True
        super().accept()

    # ------------------------------------------------------------------#
    def project_name(self) -> str:
        return self.project_name_edit.text().strip()

    # ------------------------------------------------------------------#
    def project_path(self) -> str:
        return self.project_path_edit.text().strip()

    # ------------------------------------------------------------------#
    def experiment_name(self) -> str | None:
        if not self.create_experiment_checkbox.isChecked():
            return None
        exp_name = self.experiment_name_edit.text().strip()
        return exp_name or None
