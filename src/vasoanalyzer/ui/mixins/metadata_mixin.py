# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# mypy: ignore-errors

"""
Metadata panel mixin for VasoAnalyzerApp.

This mixin contains all metadata panel-related functionality including:
- Metadata panel setup and configuration
- Metadata panel visibility management
- Metadata display updates
- Attachment handling for projects and samples
"""

import os

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QStyle,
    QToolButton,
)

from vasoanalyzer.core.project import (
    Attachment,
    Experiment,
    Project,
    SampleN,
)
from vasoanalyzer.ui.metadata_panel import MetadataDock


class MetadataMixin:
    """Mixin class that provides metadata panel functionality."""

    def setup_metadata_panel(self):
        self.metadata_dock = MetadataDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.metadata_dock)

        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.metadata_dock.toggleViewAction())

        # Keep toggle button state in sync with dock visibility.
        self.metadata_dock.visibilityChanged.connect(self._on_metadata_visibility_changed)

        project_form = self.metadata_dock.project_form
        project_form.description_changed.connect(self.on_project_description_changed)
        project_form.tags_changed.connect(self.on_project_tags_changed)
        project_form.attachment_add_requested.connect(self.on_project_add_attachment)
        project_form.attachment_remove_requested.connect(self.on_project_remove_attachment)
        project_form.attachment_open_requested.connect(self.on_project_open_attachment)

        experiment_form = self.metadata_dock.experiment_form
        experiment_form.notes_changed.connect(self.on_experiment_notes_changed)
        experiment_form.tags_changed.connect(self.on_experiment_tags_changed)

        sample_form = self.metadata_dock.sample_form
        sample_form.notes_changed.connect(self.on_sample_notes_changed)
        sample_form.attachment_add_requested.connect(self.on_sample_add_attachment)
        sample_form.attachment_remove_requested.connect(self.on_sample_remove_attachment)
        sample_form.attachment_open_requested.connect(self.on_sample_open_attachment)

        self.metadata_toggle_btn = QToolButton()
        self.metadata_toggle_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.metadata_toggle_btn.setCheckable(True)
        self.metadata_toggle_btn.setChecked(False)
        self.metadata_toggle_btn.setToolTip("Details")
        self.metadata_toggle_btn.clicked.connect(
            lambda checked: self.metadata_dock.setVisible(checked)
        )
        self.toolbar.addWidget(self.metadata_toggle_btn)
        self.metadata_dock.hide()

    def _on_metadata_visibility_changed(self, visible: bool) -> None:
        if not hasattr(self, "metadata_toggle_btn") or self.metadata_toggle_btn is None:
            return
        self.metadata_toggle_btn.blockSignals(True)
        self.metadata_toggle_btn.setChecked(bool(visible))
        self.metadata_toggle_btn.blockSignals(False)

    def _update_metadata_panel(self, obj=None) -> None:
        if not self.metadata_dock:
            return

        target = obj
        if target is None:
            if self.current_sample is not None:
                target = self.current_sample
            elif self.current_experiment is not None:
                target = self.current_experiment
            else:
                target = self.current_project

        if isinstance(target, SampleN):
            self.metadata_dock.show_sample(target)
        elif isinstance(target, Experiment):
            self.metadata_dock.show_experiment(target)
        elif isinstance(target, Project):
            self.metadata_dock.show_project(target)
        else:
            if self.current_project is not None:
                self.metadata_dock.show_project(self.current_project)
            else:
                self.metadata_dock.show_blank()

    def _open_attachment_for(self, attachments: list[Attachment], index: int) -> None:
        if not (0 <= index < len(attachments)):
            return
        att = attachments[index]
        path = self._resolve_attachment_path(att)
        if not path:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Attachment Missing",
                "The attachment file is no longer available on disk.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _resolve_attachment_path(self, att: Attachment) -> str | None:
        for candidate in (att.data_path, att.source_path):
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def _update_metadata_display(self, idx: int) -> None:
        import html

        import numpy as np

        self._update_metadata_button_state()
        if not getattr(self, "frames_metadata", None):
            action = getattr(self, "action_snapshot_metadata", None)
            if action is not None:
                action.setText("Metadata…")
            return
        if idx >= len(self.frames_metadata):
            return

        metadata = self.frames_metadata[idx] or {}
        tag_count = len(metadata)
        tag_label = "tag" if tag_count == 1 else "tags"
        action = getattr(self, "action_snapshot_metadata", None)
        if action is not None:
            action.setText(f"Metadata ({tag_count} {tag_label})")

        if not metadata:
            self.metadata_details_label.setText("No metadata for this frame.")
            return

        lines = []
        for key in sorted(metadata.keys()):
            value = metadata[key]
            if isinstance(value, list | tuple | np.ndarray):
                arr = np.array(value)
                if arr.size > 16:
                    value_repr = f"Array shape {arr.shape}"
                else:
                    value_repr = np.array2string(arr, separator=", ")
            else:
                value_repr = value

            value_repr = str(value_repr).strip()
            escaped_value = html.escape(value_repr).replace("\n", "<br>")
            escaped_key = html.escape(str(key))
            lines.append(f"<b>{escaped_key}</b>: {escaped_value}")

        self.metadata_details_label.setText("<br>".join(lines))

    def _update_metadata_button_state(self) -> None:
        action = getattr(self, "action_snapshot_metadata", None)
        has_metadata = bool(getattr(self, "frames_metadata", []))
        has_frames = bool(self.snapshot_frames)
        enabled = has_metadata and has_frames and self.snapshot_label.isVisible()

        if action is not None:
            action.setEnabled(enabled)
            if not enabled:
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)
                action.setText("Metadata…")

        if not enabled:
            self.metadata_panel.hide()
            self.metadata_details_label.setText("No metadata available.")
            return

        is_visible = self.snapshot_label.isVisible()
        should_show = bool(action and action.isChecked() and enabled)
        self.metadata_panel.setVisible(should_show)
        if not should_show and not is_visible:
            # keep summary text in sync when hiding with the viewer
            self.metadata_details_label.setText("No metadata available.")
