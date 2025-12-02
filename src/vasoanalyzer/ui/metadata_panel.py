# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Dock widget that surfaces project / experiment / sample metadata."""

from __future__ import annotations

from collections.abc import Iterable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.core.audit import EditAction
from vasoanalyzer.core.project import Attachment, Experiment, Project, SampleN


def _format_attachment(att: Attachment) -> str:
    label = att.name or att.filename or "Attachment"
    filename = att.filename or "unspecified"
    return f"{label} \N{EN DASH} {filename}"


def _tags_to_string(tags: Iterable[str] | None) -> str:
    if not tags:
        return ""
    return ", ".join(sorted({t.strip() for t in tags if t and t.strip()}))


def _parse_tags(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


class _BaseForm(QWidget):
    """Shared helpers for the metadata forms."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._block_updates = False

    def _block(self):
        self._block_updates = True

    def _unblock(self):
        self._block_updates = False


class _ProjectMetadataForm(_BaseForm):
    description_changed = pyqtSignal(str)
    tags_changed = pyqtSignal(list)
    attachment_add_requested = pyqtSignal()
    attachment_remove_requested = pyqtSignal(int)
    attachment_open_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setPlaceholderText("Project description / notes…")
        self.description_edit.textChanged.connect(self._on_description_changed)
        form.addRow("Description", self.description_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Comma-separated tags (e.g., control, drug A)")
        self.tags_edit.editingFinished.connect(self._on_tagsEdited)
        form.addRow("Tags", self.tags_edit)

        self.attachments_label = QLabel("Attachments")
        self.attachments_list = QListWidget()
        self.attachments_list.itemDoubleClicked.connect(self._on_open_attachment)
        layout.addWidget(self.attachments_label)
        layout.addWidget(self.attachments_list)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add…")
        self.remove_btn = QPushButton("Remove")
        self.open_btn = QPushButton("Open")
        self.remove_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.add_btn.clicked.connect(self.attachment_add_requested)
        self.remove_btn.clicked.connect(self._on_remove_attachment)
        self.open_btn.clicked.connect(self._on_open_attachment)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.remove_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.attachments_list.currentRowChanged.connect(self._on_attachment_selection)

    # ------------------------------------------------------------------
    def set_metadata(self, project: Project | None) -> None:
        self._block()
        if project is None:
            self.description_edit.clear()
            self.tags_edit.clear()
            self.attachments_list.clear()
        else:
            self.description_edit.setPlainText(project.description or "")
            self.tags_edit.setText(_tags_to_string(project.tags))
            self._populate_attachments(project.attachments)
        self._on_attachment_selection(self.attachments_list.currentRow())
        self._unblock()

    def _populate_attachments(self, attachments: Iterable[Attachment] | None) -> None:
        self.attachments_list.clear()
        if not attachments:
            return
        for att in attachments:
            item = QListWidgetItem(_format_attachment(att))
            self.attachments_list.addItem(item)

    # ------------------------------------------------------------------
    def _current_index(self) -> int:
        return self.attachments_list.currentRow()

    def _on_description_changed(self) -> None:
        if self._block_updates:
            return
        self.description_changed.emit(self.description_edit.toPlainText())

    def _on_tagsEdited(self) -> None:
        if self._block_updates:
            return
        self.tags_changed.emit(_parse_tags(self.tags_edit.text()))

    def _on_attachment_selection(self, row: int) -> None:
        has_selection = row >= 0
        self.remove_btn.setEnabled(has_selection)
        self.open_btn.setEnabled(has_selection)

    def _on_remove_attachment(self) -> None:
        row = self._current_index()
        if row >= 0:
            self.attachment_remove_requested.emit(row)

    def _on_open_attachment(self, *_args) -> None:
        row = self._current_index()
        if row >= 0:
            self.attachment_open_requested.emit(row)


class _ExperimentMetadataForm(_BaseForm):
    notes_changed = pyqtSignal(str)
    tags_changed = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QFormLayout(self)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Experiment notes…")
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        layout.addRow("Notes", self.notes_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Comma-separated tags")
        self.tags_edit.editingFinished.connect(self._on_tags_edited)
        layout.addRow("Tags", self.tags_edit)

    def set_metadata(self, experiment: Experiment | None) -> None:
        self._block()
        if experiment is None:
            self.notes_edit.clear()
            self.tags_edit.clear()
        else:
            self.notes_edit.setPlainText(experiment.notes or "")
            self.tags_edit.setText(_tags_to_string(experiment.tags))
        self._unblock()

    def _on_notes_changed(self) -> None:
        if self._block_updates:
            return
        self.notes_changed.emit(self.notes_edit.toPlainText())

    def _on_tags_edited(self) -> None:
        if self._block_updates:
            return
        self.tags_changed.emit(_parse_tags(self.tags_edit.text()))


class _SampleMetadataForm(_BaseForm):
    notes_changed = pyqtSignal(str)
    attachment_add_requested = pyqtSignal()
    attachment_remove_requested = pyqtSignal(int)
    attachment_open_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Sample notes…")
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        form.addRow("Notes", self.notes_edit)

        self.edit_history_group = QGroupBox("Edit History")
        self.edit_history_text = QPlainTextEdit()
        self.edit_history_text.setReadOnly(True)
        edit_layout = QVBoxLayout(self.edit_history_group)
        edit_layout.setContentsMargins(6, 6, 6, 6)
        edit_layout.addWidget(self.edit_history_text)
        layout.addWidget(self.edit_history_group)

        self.analysis_label = QLabel("Analysis Results")
        self.analysis_summary = QPlainTextEdit()
        self.analysis_summary.setReadOnly(True)
        self.analysis_summary.setPlaceholderText("No analysis results in project.")
        layout.addWidget(self.analysis_label)
        layout.addWidget(self.analysis_summary)

        self.fig_label = QLabel("Figure Configurations")
        self.figure_summary = QPlainTextEdit()
        self.figure_summary.setReadOnly(True)
        self.figure_summary.setPlaceholderText("No figure configuration saved.")
        layout.addWidget(self.fig_label)
        layout.addWidget(self.figure_summary)

        self.attachments_label = QLabel("Attachments")
        self.attachments_list = QListWidget()
        self.attachments_list.itemDoubleClicked.connect(self._on_open_attachment)
        layout.addWidget(self.attachments_label)
        layout.addWidget(self.attachments_list)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add…")
        self.open_btn = QPushButton("Open")
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.add_btn.clicked.connect(self.attachment_add_requested)
        self.open_btn.clicked.connect(self._on_open_attachment)
        self.remove_btn.clicked.connect(self._on_remove_attachment)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.remove_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.attachments_list.currentRowChanged.connect(self._on_attachment_selection)

    def set_metadata(self, sample: SampleN | None) -> None:
        self._block()
        if sample is None:
            self.notes_edit.clear()
            self.analysis_summary.clear()
            self.figure_summary.clear()
            self.attachments_list.clear()
            self._set_edit_history(None)
        else:
            self.notes_edit.setPlainText(sample.notes or "")
            self._populate_analysis(sample)
            self._populate_figures(sample.figure_configs)
            self._populate_attachments(sample.attachments)
            self._set_edit_history(sample)
        self._on_attachment_selection(self.attachments_list.currentRow())
        self._unblock()

    def _populate_analysis(self, sample: SampleN) -> None:
        analysis = getattr(sample, "analysis_results", None)
        if analysis:
            lines = []
            for key, value in analysis.items():
                if hasattr(value, "shape"):
                    try:
                        rows, cols = value.shape
                        lines.append(f"{key}: DataFrame {rows}×{cols}")
                    except Exception:
                        lines.append(f"{key}: {type(value).__name__}")
                else:
                    lines.append(f"{key}: {value}")
            self.analysis_summary.setPlainText("\n".join(lines))
            return

        keys = getattr(sample, "analysis_result_keys", []) or []
        if keys:
            preview = "\n".join(f"{name} (loaded on demand)" for name in keys)
            self.analysis_summary.setPlainText(preview)
        else:
            self.analysis_summary.clear()

    def _populate_figures(self, figure_configs) -> None:
        if not figure_configs:
            self.figure_summary.clear()
            return
        lines = []
        for key in figure_configs:
            lines.append(str(key))
        self.figure_summary.setPlainText("\n".join(lines))

    def _populate_attachments(self, attachments: Iterable[Attachment] | None) -> None:
        self.attachments_list.clear()
        if not attachments:
            return
        for att in attachments:
            self.attachments_list.addItem(QListWidgetItem(_format_attachment(att)))

    def _current_index(self) -> int:
        return self.attachments_list.currentRow()

    def _set_edit_history(self, sample: SampleN | None) -> None:
        if sample is None:
            self.edit_history_text.clear()
            self.edit_history_group.setEnabled(False)
            return

        history = getattr(sample, "edit_history", None)
        if not history:
            self.edit_history_text.setPlainText("No edit history.")
            self.edit_history_group.setEnabled(False)
            return

        lines: list[str] = []
        for entry in history:
            if not isinstance(entry, dict):
                continue
            try:
                action = EditAction.from_dict(entry)
                lines.append(action.summary())
            except Exception:
                continue

        if not lines:
            self.edit_history_text.setPlainText("No edit history.")
            self.edit_history_group.setEnabled(False)
        else:
            self.edit_history_text.setPlainText("\n".join(lines))
            self.edit_history_group.setEnabled(True)

    def _on_notes_changed(self) -> None:
        if self._block_updates:
            return
        self.notes_changed.emit(self.notes_edit.toPlainText())

    def _on_attachment_selection(self, row: int) -> None:
        has = row >= 0
        self.open_btn.setEnabled(has)
        self.remove_btn.setEnabled(has)

    def _on_remove_attachment(self) -> None:
        row = self._current_index()
        if row >= 0:
            self.attachment_remove_requested.emit(row)

    def _on_open_attachment(self, *_args) -> None:
        row = self._current_index()
        if row >= 0:
            self.attachment_open_requested.emit(row)


class MetadataDock(QDockWidget):
    """Dock widget that surfaces metadata for the current selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Details", parent)
        self.setObjectName("MetadataDock")
        self._current_kind: str | None = None

        self.stacked = QStackedWidget()
        self.setWidget(self.stacked)

        self._blank = QWidget()
        blank_layout = QVBoxLayout(self._blank)
        label = QLabel("Select a project, experiment, or sample to view details.")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        blank_layout.addStretch(1)
        blank_layout.addWidget(label)
        blank_layout.addStretch(1)

        self.project_form = _ProjectMetadataForm()
        self.experiment_form = _ExperimentMetadataForm()
        self.sample_form = _SampleMetadataForm()

        self.stacked.addWidget(self._blank)
        self.stacked.addWidget(self.project_form)
        self.stacked.addWidget(self.experiment_form)
        self.stacked.addWidget(self.sample_form)

        self.show_blank()

    # ------------------------------------------------------------------
    def show_blank(self) -> None:
        self._current_kind = None
        self.stacked.setCurrentWidget(self._blank)

    def show_project(self, project: Project | None) -> None:
        self._current_kind = "project"
        self.project_form.set_metadata(project)
        self.stacked.setCurrentWidget(self.project_form)

    def show_experiment(self, experiment: Experiment | None) -> None:
        self._current_kind = "experiment"
        self.experiment_form.set_metadata(experiment)
        self.stacked.setCurrentWidget(self.experiment_form)

    def show_sample(self, sample: SampleN | None) -> None:
        self._current_kind = "sample"
        self.sample_form.set_metadata(sample)
        self.stacked.setCurrentWidget(self.sample_form)

    # ------------------------------------------------------------------
    def refresh_attachments(self, attachments: Iterable[Attachment] | None) -> None:
        if self._current_kind == "project":
            self.project_form._populate_attachments(attachments)
        elif self._current_kind == "sample":
            self.sample_form._populate_attachments(attachments)
