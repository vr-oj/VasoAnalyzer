from __future__ import annotations

import contextlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QMessageBox

from vasoanalyzer.core.project import (
    ProjectUpgradeRequired,
    close_project_ctx,
    convert_project,
    open_project_ctx,
)
from vasoanalyzer.core.project_context import ProjectContext

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def open_project_file(window: VasoAnalyzerApp, path: str | None = None) -> None:
    """Open a project via the legacy flow while attaching a ProjectContext."""

    previous_project = getattr(window, "current_project", None)
    previous_ctx: ProjectContext | None = getattr(window, "project_ctx", None)

    window._open_project_file_legacy(path)

    current_project = getattr(window, "current_project", None)
    if current_project is previous_project:
        return

    if previous_ctx is not None:
        with contextlib.suppress(Exception):
            close_project_ctx(previous_ctx)

    project_path = getattr(current_project, "path", None)
    if project_path:
        try:
            ctx = open_project_ctx(project_path)
        except ProjectUpgradeRequired as exc:
            choice = QMessageBox.question(
                window,
                "Convert Project",
                (
                    "This project uses an older format.\n\n"
                    "Convert it to the new single-file .vaso format now?\n"
                    "A backup (.bak1) will be kept for safety."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if choice != QMessageBox.Yes:
                window.statusBar().showMessage("Conversion cancelled.", 5000)
                return
            ctx = convert_project(project_path)
            window.statusBar().showMessage("\u2713 Project converted to single-file format.", 5000)
        window.project_ctx = ctx
        window.project_path = ctx.path
        window.project_meta = ctx.meta
    else:
        window.project_ctx = None
        window.project_path = None
        window.project_meta = {}


def open_samples_in_dual_view(window: VasoAnalyzerApp, samples: Sequence | None) -> None:
    """Delegate to the legacy dual-view opener."""

    window._open_samples_in_dual_view_legacy(samples)
