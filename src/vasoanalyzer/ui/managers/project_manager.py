# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""ProjectManager — extracted project lifecycle logic from main_window.py.

Manages project create, open, save, autosave, and close operations.
All host state is accessed via ``self._host`` (the VasoAnalyzerApp main window).
"""

from __future__ import annotations

import contextlib
import copy
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QSettings
from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

if TYPE_CHECKING:
    from PyQt6.QtCore import Qt

    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)


class ProjectManager(QObject):
    """Manages project lifecycle: create, open, save, autosave, close."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def new_project(self, checked: bool = False):
        """Create a new project.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        host = self._host
        manager = getattr(host, "window_manager", None)
        if manager is not None:
            manager.create_project_in_window_via_dialog(host)
            return

        from vasoanalyzer.ui.dialogs.new_project_dialog import NewProjectDialog

        dialog = NewProjectDialog(host, settings=host.settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._create_project_from_inputs(
            dialog.project_name(),
            dialog.project_path(),
            dialog.experiment_name(),
        )

    def _create_project_from_inputs(self, name: str, path: str, exp_name: str | None) -> bool:
        host = self._host

        if not name or not path:
            return False

        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() not in [".vaso", ".vasopack"]:
            path_obj = path_obj.with_suffix(".vaso")
        normalised_path = str(path_obj.resolve(strict=False))

        log.info(
            "UI: Creating new project name=%r path=%s (initial experiment=%r)",
            name,
            normalised_path,
            exp_name or None,
        )

        # Check if user is trying to save to cloud storage
        from vasoanalyzer.core.project import _is_cloud_storage_path

        is_cloud, cloud_service = _is_cloud_storage_path(normalised_path)
        if is_cloud:
            reply = QMessageBox.warning(
                host,
                "Cloud Storage - Known Limitation",
                f"<b>You are creating a project in {cloud_service}</b>\n\n"
                f"<b>Technical Limitation:</b>\n"
                f"SQLite databases (like .vaso project files) can become corrupted when cloud sync services"
                f"upload the file mid-transaction. This happens because the sync daemon may interrupt "
                f"database writes, breaking integrity.\n\n"
                f"<b>Mitigations in place:</b>\n"
                f"• VasoAnalyzer uses WAL mode for better resilience\n"
                f"• Automatic recovery attempts if corruption occurs\n"
                f"• Risk is highest during active editing and autosaves\n\n"
                f"<b>Best practice:</b>\n"
                f"Store active projects locally (~/Documents, ~/Desktop), then copy .vaso "
                f"files to cloud storage for backup and sharing.\n\n"
                f"<b>Continue creating project in {cloud_service}?</b>",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return False

        from vasoanalyzer.core.project import Experiment, Project
        from vasoanalyzer.services.project_service import save_project_file

        project = Project(name=name, path=normalised_path)
        if exp_name:
            project.experiments.append(Experiment(name=exp_name))
            if project.ui_state is None:
                project.ui_state = {}
            project.ui_state["last_experiment"] = exp_name

        self._replace_current_project(project)
        if project.experiments:
            host.current_experiment = project.experiments[0]

        save_project_file(host.current_project, normalised_path)
        host.update_recent_projects(normalised_path)
        host.refresh_project_tree()

        # Note: ProjectContext will be created when project is reopened via open_project_file()

        if host.project_tree and project.experiments:
            root_item = host.project_tree.topLevelItem(0)
            if root_item and root_item.childCount():
                first_exp_item = root_item.child(0)
                host.project_tree.setCurrentItem(first_exp_item)

        # Switch to analysis workspace so user can see project panel
        host.show_analysis_workspace()
        host._reveal_project_sidebar()

        host.statusBar().showMessage(
            "Project created. Use the Add Data actions to start populating your experiment.",
            6000,
        )
        host._update_storage_mode_indicator(normalised_path, force_message=True)
        return True

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------

    def _open_project_file_legacy(self, path: str | None = None):
        host = self._host

        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                host,
                "Open Project",
                "",
                "Vaso Projects (*.vaso);;All Files (*)",
            )
            if not path:
                return

        path_obj = Path(path).expanduser().resolve(strict=False)
        path = str(path_obj)

        host._clear_canvas_and_table()

        from vasoanalyzer.core.project import Project, ProjectUpgradeRequired, load_project
        from vasoanalyzer.services.project_service import (
            import_project_bundle,
            is_valid_autosave_snapshot,
            pending_autosave_path,
            quarantine_autosave_snapshot,
            restore_autosave,
        )

        project: Project | None = None
        project_path = path
        restored_from_autosave = False

        if path_obj.suffix.lower() == ".vasopack":
            base_dir = QFileDialog.getExistingDirectory(
                host,
                "Select Folder to Unpack Bundle",
                path_obj.parent.as_posix(),
            )
            if not base_dir:
                return
            stem = path_obj.stem
            target_dir = Path(base_dir).expanduser().resolve(strict=False) / stem
            counter = 1
            while target_dir.exists():
                counter += 1
                target_dir = Path(base_dir) / f"{stem}_{counter}"
            try:
                project = import_project_bundle(path, target_dir.as_posix())
                project_path = project.path or target_dir.joinpath(f"{stem}.vaso").as_posix()
                host.statusBar().showMessage(f"\u2713 Bundle unpacked to {target_dir}", 5000)
            except Exception as exc:
                QMessageBox.critical(
                    host,
                    "Bundle Import Error",
                    f"Could not unpack bundle:\n{exc}",
                )
                return
        else:
            autosave_candidate = pending_autosave_path(path)
            if autosave_candidate:
                if not is_valid_autosave_snapshot(autosave_candidate):
                    quarantine_autosave_snapshot(autosave_candidate)
                    log.warning("Discarded corrupt autosave snapshot: %s", autosave_candidate)
                    QMessageBox.warning(
                        host,
                        "Autosave Discarded",
                        (
                            "The autosave snapshot for this project was corrupted and "
                            "has been discarded.\n\nThe original project will be opened instead."
                        ),
                    )
                    autosave_candidate = None
                else:
                    try:
                        autosave_mtime = os.path.getmtime(autosave_candidate)
                        project_mtime = os.path.getmtime(path)
                    except OSError:
                        autosave_mtime = project_mtime = 0

                    if autosave_mtime > project_mtime:
                        choice = QMessageBox.question(
                            host,
                            "Recover Autosave?",
                            (
                                "An autosave snapshot newer than this project was found.\n"
                                "Would you like to recover it?"
                            ),
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.Yes,
                        )
                        if choice == QMessageBox.StandardButton.Yes:
                            try:
                                project = restore_autosave(path)
                                restored_from_autosave = True
                                with contextlib.suppress(OSError):
                                    os.remove(autosave_candidate)
                            except Exception as exc:
                                QMessageBox.warning(
                                    host,
                                    "Autosave Recovery Failed",
                                    (
                                        "Could not restore autosave:\n"
                                        f"{exc}\n\nOpening original file instead."
                                    ),
                                )

            if project is None:
                try:
                    project = load_project(path)
                except ProjectUpgradeRequired:
                    choice = QMessageBox.question(
                        host,
                        "Convert Project",
                        (
                            "This project uses an older format.\n\n"
                            "Convert it to the new single-file .vaso format now?\n"
                            "A backup (.bak1) will be kept for safety."
                        ),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if choice != QMessageBox.StandardButton.Yes:
                        host.statusBar().showMessage("Conversion cancelled.", 5000)
                        return
                    try:
                        from vasoanalyzer.core.project import convert_project

                        ctx = convert_project(path)
                        with contextlib.suppress(Exception):
                            ctx.close()
                        project = load_project(path)
                        host.statusBar().showMessage(
                            "\u2713 Project converted to single-file format.", 5000
                        )
                    except Exception as exc:
                        QMessageBox.critical(
                            host,
                            "Project Conversion Failed",
                            f"Could not convert project:\n{exc}",
                        )
                        return
                except Exception as exc:
                    error_msg = str(exc)

                    # Check if this was a database corruption error
                    if "corrupted" in error_msg.lower() or "malformed" in error_msg.lower():
                        # Check if project is in cloud storage
                        from vasoanalyzer.core.project import _is_cloud_storage_path

                        is_cloud, cloud_service = _is_cloud_storage_path(path)

                        cloud_warning = ""
                        if is_cloud:
                            cloud_warning = (
                                f"\n\n\u26a0\ufe0f IMPORTANT: This project is stored in {cloud_service}.\n"
                                f"SQLite databases are INCOMPATIBLE with cloud storage and will become corrupted.\n\n"
                                f"To fix this:\n"
                                f"1. Move this project to a LOCAL folder (e.g., ~/Documents or ~/Desktop)\n"
                                f"2. Create a new project in the local folder\n"
                                f"3. Never store .vaso projects in iCloud, Dropbox, or other cloud storage\n\n"
                            )

                        if "backup was created" in error_msg:
                            # Recovery was attempted but failed
                            QMessageBox.critical(
                                host,
                                "Project Database Corrupted",
                                f"The project database is corrupted and automatic recovery failed.\n\n"
                                f"Error: {exc}"
                                f"{cloud_warning}\n"
                                f"A backup of your corrupted file has been created at:\n"
                                f"{path}.backup\n\n"
                                f"Recovery options:\n"
                                f"1. Try opening the backup file\n"
                                f"2. Contact support for manual recovery\n"
                                f"3. Create a new project and re-import your data",
                            )
                        else:
                            # Generic database error
                            QMessageBox.critical(
                                host,
                                "Project Database Error",
                                f"Could not open project due to database error:\n\n{exc}"
                                f"{cloud_warning}\n"
                                f"The database may be corrupted. Please check the file:\n{path}",
                            )
                    else:
                        # Other errors
                        QMessageBox.critical(
                            host,
                            "Project Load Error",
                            f"Could not open project:\n{exc}",
                        )
                    return

        self._replace_current_project(project)
        host.apply_ui_state(getattr(host.current_project, "ui_state", None))
        host.refresh_project_tree()
        host.show_analysis_workspace()
        host._reveal_project_sidebar()

        status = f"\u2713 Project loaded: {host.current_project.name}"
        if restored_from_autosave:
            status += " (autosave recovered)"
        host.statusBar().showMessage(status, 5000)
        host._update_storage_mode_indicator(project_path, force_message=True)

        if project_path:
            host.update_recent_projects(project_path)
        tree = host.project_tree
        restored = host.restore_last_selection()
        if not restored:
            first_sample_item = None
            first_exp_item = None
            if tree and host.current_project.experiments:
                from PyQt6.QtCore import Qt

                root_item = tree.topLevelItem(0)
                first_exp = host.current_project.experiments[0]
                if root_item is not None:
                    for i in range(root_item.childCount()):
                        child = root_item.child(i)
                        if child.data(0, Qt.ItemDataRole.UserRole) is first_exp:
                            first_exp_item = child
                            if first_exp.samples:
                                target_sample = first_exp.samples[0]
                                for j in range(child.childCount()):
                                    sample_child = child.child(j)
                                    if sample_child.data(0, Qt.ItemDataRole.UserRole) is target_sample:
                                        first_sample_item = sample_child
                                        break
                            break

            if first_sample_item is not None and tree:
                tree.setCurrentItem(first_sample_item)
                host.on_tree_item_clicked(first_sample_item, 0)
            elif host.current_project.experiments and host.current_project.experiments[0].samples:
                first_sample = host.current_project.experiments[0].samples[0]
                host.load_sample_into_view(first_sample)
            else:
                if first_exp_item is not None and tree:
                    tree.setCurrentItem(first_exp_item)
                    host.on_tree_item_clicked(first_exp_item, 0)
                elif tree and tree.topLevelItemCount():
                    root = tree.topLevelItem(0)
                    if root is not None:
                        tree.setCurrentItem(root)
                        host.on_tree_item_clicked(root, 0)
                host.show_analysis_workspace()
        host._reset_session_dirty()

    def open_project_file(self, path: str | bool | None = None):
        """Open a project file.

        Args:
            path: Path to project file, or boolean from Qt signal (ignored), or None for file dialog
        """
        from vasoanalyzer.app.openers import open_project_file as _open_project_file

        # Ignore boolean argument from Qt signals (e.g., QAction.triggered)
        if isinstance(path, bool):
            path = None

        return _open_project_file(self._host, path)

    # ------------------------------------------------------------------
    # Save helpers
    # ------------------------------------------------------------------

    def _prepare_project_for_save(self) -> None:
        """Capture UI state into the project before dispatching a background save."""
        host = self._host

        if not host.current_project:
            return

        settings = QSettings("TykockiLab", "VasoAnalyzer")
        embed = settings.value("snapshots/embed_stacks", False, type=bool)
        host.current_project.embed_snapshots = bool(embed)

        host.current_project.ui_state = host.gather_ui_state()
        if host.current_sample:
            state = host.gather_sample_state()
            host.current_sample.ui_state = state
            host.project_state[id(host.current_sample)] = state

    def _project_snapshot_for_save(self, project) -> "Project":
        """Create a lightweight snapshot of ``project`` suitable for background save."""
        import vasoanalyzer.core.project as project_module

        snap = copy.copy(project)
        snap.resources = project_module.ProjectResources()
        snap._store = None  # Ensure thread-local store is opened inside the worker
        if hasattr(snap, "_store_cleanup_registered"):
            delattr(snap, "_store_cleanup_registered")
        return snap

    def _set_save_actions_enabled(self, enabled: bool) -> None:
        """Enable/disable save-related actions while a background save is running."""
        host = self._host

        for action in (
            getattr(host, "action_save_project", None),
            getattr(host, "action_save_project_as", None),
            getattr(host, "save_session_action", None),
        ):
            if action is not None:
                action.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Background save
    # ------------------------------------------------------------------

    def _start_background_save(
        self,
        path: str | None,
        *,
        skip_optimize: bool,
        reason: str = "manual",
        mode: str = "manual",
        ctx: dict | None = None,
    ) -> None:
        """Dispatch a background save job using the thread pool."""
        host = self._host

        project = host.current_project
        if project is None:
            return

        target_path = path or getattr(project, "path", None)
        if not target_path:
            host.statusBar().showMessage("No project path available to save.", 5000)
            return

        if host._save_in_progress:
            log.debug("Save already in progress, skipping concurrent save request")
            host.statusBar().showMessage("Save already in progress\u2026", 3000)
            return

        if mode != "autosave":
            self._prepare_project_for_save()
        host._save_in_progress = True
        host._active_save_reason = reason
        host._active_save_path = target_path
        host._active_save_mode = mode
        host._last_save_error = None
        if mode != "autosave":
            self._set_save_actions_enabled(False)
        progress_label = "Autosaving project\u2026" if mode == "autosave" else "Saving project\u2026"
        host.show_progress(progress_label, maximum=100)

        if mode == "autosave":
            host._autosave_in_progress = True
            host._active_autosave_ctx = ctx or {}

        project_snapshot = self._project_snapshot_for_save(project)

        from vasoanalyzer.ui.main_window import _SaveJob

        job = _SaveJob(
            project_snapshot,
            target_path,
            skip_optimize=skip_optimize,
            mode=mode,
        )
        job.signals.progressChanged.connect(self._on_save_progress_changed)
        job.signals.finished.connect(self._on_save_finished)
        job.signals.error.connect(self._on_save_error)
        host._thread_pool.start(job)
        log.info(
            "Background save started path=%s reason=%s mode=%s",
            target_path,
            reason,
            mode,
        )
        if mode == "autosave":
            log.debug(
                "Autosave scheduled ctx=%s current_sample_id=%s rev=%s",
                host._active_autosave_ctx,
                getattr(host.current_sample, "id", None),
                host._project_state_rev,
            )

    # ------------------------------------------------------------------
    # Save callbacks (connected to _SaveJob signals)
    # ------------------------------------------------------------------

    def _on_save_progress_changed(self, percent: int, message: str) -> None:
        """Update the progress label from save worker step signals."""
        host = self._host
        host._progress_animator.update_label(message)
        host.statusBar().showMessage(message)

    def _on_save_error(self, details: str) -> None:
        host = self._host

        host._last_save_error = details
        mode = host._active_save_mode or "manual"
        prefix = "Autosave" if mode == "autosave" else "Save"
        log.error("Error during project %s: %s", mode, details)
        if mode == "autosave":
            host._autosave_in_progress = False
            host._active_autosave_ctx = None
        host.statusBar().showMessage(f"{prefix} failed: {details}", 5000)

    def _on_save_finished(self, ok: bool, duration_sec: float, path: str) -> None:
        host = self._host

        resolved_path = (
            path or host._active_save_path or getattr(host.current_project, "path", None)
        )
        reason = host._active_save_reason or "manual"
        mode = host._active_save_mode or "manual"

        if ok:
            log.info(
                "Background save completed path=%s reason=%s mode=%s duration=%.2fs",
                resolved_path,
                reason,
                mode,
                duration_sec,
            )
            if host.current_project and reason == "save_as" and resolved_path:
                host.current_project.path = resolved_path
            if mode == "autosave":
                if resolved_path:
                    host.last_autosave_path = resolved_path
                message = (
                    f"Project saved: {Path(resolved_path).name} ({duration_sec:.2f}s)"
                    if resolved_path
                    else "Project saved"
                )
                host.statusBar().showMessage(message, 2500)
            else:
                if resolved_path:
                    host.update_recent_projects(resolved_path)
                    host._update_storage_mode_indicator(resolved_path)
                message = (
                    f"Project saved: {Path(resolved_path).name} ({duration_sec:.2f}s)"
                    if resolved_path
                    else "Project saved"
                )
                host.statusBar().showMessage(message, 2500)
                reset_reason = (
                    "manual save" if reason in ("manual", "save_as") else f"{reason} save"
                )
                host._reset_session_dirty(reason=reset_reason)
                host._update_window_title()
            host.hide_progress()
        else:
            log.error(
                "Background save failed path=%s reason=%s mode=%s duration=%.2fs",
                resolved_path,
                reason,
                mode,
                duration_sec,
            )
            message = f"Save failed: {Path(resolved_path).name}" if resolved_path else "Save failed"
            if host._last_save_error:
                message = f"{message} \u2014 {host._last_save_error}"
            message = f"{message} ({duration_sec:.2f}s)"
            host.statusBar().showMessage(message, 5000)
            host.hide_progress()

        if mode == "autosave":
            log.debug(
                "Autosave finished ok=%s ctx=%s live_sample_id=%s rev_now=%s",
                ok,
                host._active_autosave_ctx,
                getattr(host.current_sample, "id", None),
                host._project_state_rev,
            )
            host._autosave_in_progress = False
            host._active_autosave_ctx = None
        host._active_save_reason = None
        host._active_save_path = None
        host._active_save_mode = None
        host._last_save_error = None
        self._set_save_actions_enabled(True)
        host._save_in_progress = False

    # ------------------------------------------------------------------
    # Save / Save As actions
    # ------------------------------------------------------------------

    def save_project_file(self, checked: bool = False):
        """Save the current project file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        host = self._host

        if host.current_project and host.current_project.path:
            project_path = host.current_project.path
            log.info("Manual save requested path=%s", project_path)
            self._start_background_save(project_path, skip_optimize=False, reason="manual")
        elif host.current_project:
            self.save_project_file_as()

    def save_project_file_as(self, checked: bool = False):
        """Save project to a new file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        host = self._host

        if not host.current_project:
            return
        path, _ = QFileDialog.getSaveFileName(
            host,
            "Save Project As",
            host.current_project.path or "",
            "Vaso Projects (*.vaso)",
        )
        if not path:
            return

        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() != ".vaso":
            path_obj = path_obj.with_suffix(".vaso")
        path = str(path_obj.resolve(strict=False))

        # Check if user is trying to save to cloud storage
        from vasoanalyzer.core.project import _is_cloud_storage_path

        is_cloud, cloud_service = _is_cloud_storage_path(path)
        if is_cloud:
            reply = QMessageBox.warning(
                host,
                "Cloud Storage - Known Limitation",
                f"<b>You are saving to {cloud_service}</b>\n\n"
                f"<b>Technical Limitation:</b>\n"
                f"SQLite databases (like .vaso project files) can become corrupted when cloud sync services"
                f"upload the file mid-transaction. This happens because the sync daemon may interrupt "
                f"database writes, breaking integrity.\n\n"
                f"<b>Mitigations in place:</b>\n"
                f"• VasoAnalyzer uses WAL mode for better resilience\n"
                f"• Automatic recovery attempts if corruption occurs\n"
                f"• Risk is highest during active editing and autosaves\n\n"
                f"<b>Best practice:</b>\n"
                f"Store active projects locally (~/Documents, ~/Desktop), then copy .vaso "
                f"files to cloud storage for backup and sharing.\n\n"
                f"<b>Continue saving to {cloud_service}?</b>",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

        log.info("Manual save (Save As) requested destination=%s", path)
        self._start_background_save(path, skip_optimize=False, reason="save_as")

    # ------------------------------------------------------------------
    # Autosave
    # ------------------------------------------------------------------

    def _run_deferred_autosave(self):
        host = self._host

        reason = host._pending_autosave_reason or "deferred"
        host._pending_autosave_reason = None
        log.info(
            "Autosave: running deferred autosave reason=%s path=%s",
            reason,
            getattr(host.current_project, "path", None),
        )
        if host.current_project and host.current_project.path:
            ctx = host._pending_autosave_ctx or {}
            self.auto_save_project(reason=reason, ctx=ctx)

    def request_deferred_autosave(self, delay_ms: int = 2000, *, reason: str = "deferred") -> None:
        """Schedule an autosave after ``delay_ms`` to coalesce rapid edits."""
        host = self._host

        if not host.current_project or not host.current_project.path:
            host._pending_autosave_reason = None
            host._deferred_autosave_timer.stop()
            return

        self._bump_project_state_rev(f"autosave scheduled ({reason})")
        ctx = {
            "rev": host._project_state_rev,
            "sample_id": getattr(host.current_sample, "id", None),
            "reason": reason,
            "utc": datetime.utcnow().isoformat() + "Z",
        }
        host._pending_autosave_ctx = ctx
        host._pending_autosave_reason = reason
        host._deferred_autosave_timer.start(max(0, int(delay_ms)))

    def auto_save_project(self, reason: str | None = None, ctx: dict | None = None):
        """Write an autosave snapshot when a project is available."""
        host = self._host

        host._deferred_autosave_timer.stop()
        host._pending_autosave_reason = None
        if ctx is None and host._pending_autosave_ctx:
            ctx = host._pending_autosave_ctx

        if not host.current_project or not host.current_project.path:
            return

        project_path = host.current_project.path
        # Prevent concurrent saves (don't autosave if manual save is in progress)
        if host._save_in_progress:
            log.info(
                "Manual save in progress, deferring autosave path=%s reason=%s",
                project_path,
                reason or "auto",
            )
            # Reschedule autosave for later
            self.request_deferred_autosave(delay_ms=5000, reason=reason or "deferred")
            return

        log.info("Autosave started path=%s reason=%s", project_path, reason or "auto")
        self._start_background_save(
            path=None,
            skip_optimize=True,
            reason=reason or "auto",
            mode="autosave",
            ctx=ctx,
        )

    def _autosave_tick(self):
        host = self._host

        if not host.current_project or not host.current_project.path:
            return
        if not host.session_dirty:
            return
        ctx = {
            "rev": host._project_state_rev,
            "sample_id": getattr(host.current_sample, "id", None),
            "reason": "timer",
            "utc": datetime.utcnow().isoformat() + "Z",
        }
        host._pending_autosave_ctx = ctx
        self.auto_save_project(reason="timer", ctx=ctx)

    def _bump_project_state_rev(self, reason: str) -> None:
        host = self._host

        host._project_state_rev += 1
        log.debug("Project state rev bumped to %s (%s)", host._project_state_rev, reason)

    # ------------------------------------------------------------------
    # Replace / close current project
    # ------------------------------------------------------------------

    def _replace_current_project(self, project):
        """Swap the active project, ensuring old resources are released."""
        host = self._host

        if project is host.current_project:
            return

        # Close old project context before replacing
        old_ctx = getattr(host, "project_ctx", None)
        if old_ctx is not None:
            try:
                from vasoanalyzer.core.project import close_project_ctx

                close_project_ctx(old_ctx)
                log.debug("Closed previous ProjectContext")
            except Exception:
                log.debug("Failed to close previous ProjectContext", exc_info=True)
            host.project_ctx = None
            host.project_path = None
            host.project_meta = {}

        old_project = host.current_project
        host.current_project = project
        host.current_experiment = None
        host.current_sample = None
        host.project_state.clear()
        host._pending_sample_loads.clear()
        host._processing_pending_sample_loads = False
        host._cache_root_hint = project.path if project and getattr(project, "path", None) else None
        host.data_cache = None
        host._missing_assets.clear()
        if host.action_relink_assets:
            host.action_relink_assets.setEnabled(False)
        if host._relink_dialog:
            host._relink_dialog.hide()
        host._update_metadata_panel(project)
        host._update_window_title()
        host._update_storage_mode_indicator(
            getattr(project, "path", None) if project else None, show_message=False
        )

        if old_project is not None:
            try:
                old_project.close()
            except Exception:
                log.debug("Failed to close previous project resources", exc_info=True)

        host._next_step_hint_dismissed = False
        host._update_next_step_hint()
        host._update_plot_empty_state()
        # Kick off background preload of embedded datasets for fast switching
        host._start_project_preload()
