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
    import logging

    log = logging.getLogger(__name__)

    log.debug("open_project_file called with path: %s", path)

    previous_project = getattr(window, "current_project", None)
    previous_ctx: ProjectContext | None = getattr(window, "project_ctx", None)

    log.debug("   Previous project: %s", previous_project.name if previous_project else None)
    log.debug("   Previous ctx: %s", type(previous_ctx).__name__ if previous_ctx else None)

    window._open_project_file_legacy(path)

    current_project = getattr(window, "current_project", None)
    log.debug(
        "   After _open_project_file_legacy: current_project = %s",
        current_project.name if current_project else None,
    )

    if current_project is previous_project:
        log.debug("   Project unchanged, returning early")
        return

    if previous_ctx is not None:
        log.debug("   Closing previous ProjectContext")
        with contextlib.suppress(Exception):
            close_project_ctx(previous_ctx)

    project_path = getattr(current_project, "path", None)
    log.debug("   Project path: %s", project_path)

    if project_path:
        # Check if project already has a store with a repository
        # (from being loaded by _open_project_file_legacy)
        existing_store = getattr(current_project, "_store", None)
        log.debug("   Existing store from loaded project: %s", existing_store)

        if existing_store:
            # Create repository from the existing store
            log.debug("Creating repository from existing store...")
            try:
                from vasoanalyzer.services.project_service import SQLiteProjectRepository

                repo = SQLiteProjectRepository(existing_store)
                log.debug("Repository created from existing store: %s", repo)

                # Create ProjectContext with the existing repository
                # We don't need to call open_project_ctx which would try to open the file again
                from vasoanalyzer.core.file_lock import ProjectFileLock

                # Acquire file lock
                file_lock = ProjectFileLock(project_path)
                try:
                    file_lock.acquire(timeout=5)
                    log.debug("Acquired lock for project: %s", project_path)
                except RuntimeError as e:
                    log.error(f"Failed to acquire lock: {e}")
                    file_lock = None

                # Read metadata
                meta: dict = {}
                read_meta = getattr(repo, "read_meta", None)
                if callable(read_meta):
                    with contextlib.suppress(Exception):
                        meta = dict(read_meta())

                # Create ProjectContext with existing repo
                ctx = ProjectContext(path=project_path, repo=repo, meta=meta, file_lock=file_lock)
                log.debug("ProjectContext created from existing store: %s", ctx)
                log.debug("   ctx.repo: %s", ctx.repo)
            except Exception as exc:
                log.error(f"❌ Failed to create repo from existing store: {exc}", exc_info=True)
                # Fall back to trying to open a new context
                log.debug("   Falling back to open_project_ctx...")
                try:
                    ctx = open_project_ctx(project_path)
                    log.debug("ProjectContext created via fallback: %s", ctx)
                except Exception as fallback_exc:
                    log.error(f"❌ Fallback also failed: {fallback_exc}", exc_info=True)
                    raise
        else:
            # No existing store, try to open normally
            log.debug("   No existing store, calling open_project_ctx...")
            try:
                log.debug("Creating ProjectContext for: %s", project_path)
                ctx = open_project_ctx(project_path)
                log.debug("ProjectContext created successfully: %s", ctx)
                log.debug("   ctx.repo: %s", ctx.repo)
            except ProjectUpgradeRequired as exc:
                log.error(f"❌ ProjectUpgradeRequired exception: {exc}", exc_info=True)
                log.debug("   Project upgrade required, prompting user...")
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
                    log.debug("   User cancelled conversion")
                    return
                ctx = convert_project(project_path)
                window.statusBar().showMessage(
                    "\u2713 Project converted to single-file format.", 5000
                )
                log.debug("Project converted and context created: %s", ctx)
            except Exception as exc:
                log.error(f"❌ UNEXPECTED exception in open_project_ctx: {exc}", exc_info=True)
                log.error(f"   Exception type: {type(exc)}")
                log.error("   This exception prevents ProjectContext from being created!")
                # Re-raise to let caller handle it
                raise

        window.project_ctx = ctx
        window.project_path = ctx.path
        window.project_meta = ctx.meta
        log.debug("ProjectContext attached to window")
        log.debug("   window.project_ctx = %s", window.project_ctx)
        log.debug("   window.project_ctx.repo = %s", window.project_ctx.repo)
        flush = getattr(window, "_flush_pending_sample_loads", None)
        if callable(flush):
            flush()
    else:
        log.warning("No project path, setting project_ctx to None")
        window.project_ctx = None
        window.project_path = None
        window.project_meta = {}


def open_samples_in_dual_view(window: VasoAnalyzerApp, samples: Sequence | None) -> None:
    """Delegate to the legacy dual-view opener."""

    window._open_samples_in_dual_view_legacy(samples)
