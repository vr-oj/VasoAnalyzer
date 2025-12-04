# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# mypy: ignore-errors

"""
Project operations mixin for VasoAnalyzerApp.

This mixin contains all project-related functionality including:
- Project file operations (new, open, save, export)
- Project tree management and refresh
- Experiment and sample management
- Autosave functionality
- Project context menu handlers
- Tree item event handlers
- Recent projects management
- Metadata panel updates for projects
"""

import contextlib
import logging
import os
from functools import partial
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import (
    QAction,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
    QStyle,
    QTreeWidgetItem,
)

from vasoanalyzer.core.project import (
    Experiment,
    Project,
    SampleN,
    load_project,
    save_project,
)
from vasoanalyzer.services.project_service import (
    autosave_project,
    export_project_bundle,
    export_project_single_file,
    import_project_bundle,
    is_valid_autosave_snapshot,
    pending_autosave_path,
    quarantine_autosave_snapshot,
    restore_autosave,
    save_project_file,
)
from vasoanalyzer.ui.dialogs.new_project_dialog import NewProjectDialog
from vasoanalyzer.ui.dialogs.relink_dialog import MissingAsset, _MissingAssetScanJob

log = logging.getLogger(__name__)


class ProjectMixin:
    """Mixin providing project management functionality for VasoAnalyzerApp."""

    # ===== Core Project Operations =====

    def _replace_current_project(self, project):
        """Swap the active project, ensuring old resources are released."""

        if project is self.current_project:
            return

        old_project = self.current_project
        self.current_project = project
        self.current_experiment = None
        self.current_sample = None
        self.project_state.clear()
        self._cache_root_hint = project.path if project and getattr(project, "path", None) else None
        self.data_cache = None
        self._missing_assets.clear()
        if self.action_relink_assets:
            self.action_relink_assets.setEnabled(False)
        if self._relink_dialog:
            self._relink_dialog.hide()
        self._update_metadata_panel(project)
        self._update_window_title()

        if old_project is not None:
            try:
                old_project.close()
            except Exception:
                log.debug("Failed to close previous project resources", exc_info=True)

    def _project_base_dir(self) -> Path | None:
        if self.current_project and self.current_project.path:
            try:
                return Path(self.current_project.path).expanduser().resolve(strict=False).parent
            except Exception:
                return Path(self.current_project.path).expanduser().parent
        return None

    def new_project(self):
        dialog = NewProjectDialog(self, settings=self.settings)
        if dialog.exec_() != QDialog.Accepted:
            return

        name = dialog.project_name()
        path = dialog.project_path()
        exp_name = dialog.experiment_name()

        if not name or not path:
            return

        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() != ".vaso":
            path_obj = path_obj.with_suffix(".vaso")
        normalised_path = str(path_obj.resolve(strict=False))

        project = Project(name=name, path=normalised_path)
        if exp_name:
            project.experiments.append(Experiment(name=exp_name))
            if project.ui_state is None:
                project.ui_state = {}
            project.ui_state["last_experiment"] = exp_name

        self._replace_current_project(project)
        if project.experiments:
            self.current_experiment = project.experiments[0]

        # Show progress bar during initial save
        self.show_progress("Creating project", maximum=0)
        try:
            save_project_file(self.current_project, normalised_path)
            self.update_recent_projects(normalised_path)
        finally:
            self.hide_progress()

        self.refresh_project_tree()

        if self.project_tree and project.experiments:
            root_item = self.project_tree.topLevelItem(0)
            if root_item and root_item.childCount():
                first_exp_item = root_item.child(0)
                self.project_tree.setCurrentItem(first_exp_item)

        # Switch to analysis workspace so user can start working
        self.show_analysis_workspace()

        self.statusBar().showMessage(
            "Project created. Use the Add Data actions to start populating your experiment.",
            6000,
        )

    def _open_project_file_legacy(self, path: str | None = None):
        if path is None:
            # Support both file selection and directory selection for bundles
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Project",
                "",
                "Vaso Projects (*.vaso);;Vaso Bundles (*.vasopack);;All Files (*)",
            )
            # If user didn't select a file, try directory selection for .vasopack bundles
            if not path:
                bundle_path = QFileDialog.getExistingDirectory(
                    self,
                    "Open Project Bundle (or Cancel to browse files)",
                    "",
                )
                if bundle_path and Path(bundle_path).suffix == ".vasopack":
                    path = bundle_path
                elif not bundle_path:
                    return
                else:
                    # Selected a directory that's not .vasopack
                    QMessageBox.warning(
                        self,
                        "Invalid Bundle",
                        "Please select a .vasopack bundle directory or .vaso file.",
                    )
                    return

            if not path:
                return

        path_obj = Path(path).expanduser().resolve(strict=False)
        path = str(path_obj)

        self._clear_canvas_and_table()

        project: Project | None = None
        project_path = path
        restored_from_autosave = False

        # Show progress bar during load
        self.show_progress("Loading project", maximum=0)  # Indeterminate progress
        try:
            # Check if this is a new-style bundle directory
            if path_obj.is_dir() and path_obj.suffix.lower() == ".vasopack":
                # New snapshot-based bundle format - open directly
                try:
                    project = load_project_file(path)
                    project_path = path
                    self.statusBar().showMessage(f"\u2713 Opened bundle: {path_obj.name}", 3000)
                except Exception as exc:
                    self.hide_progress()
                    QMessageBox.critical(
                        self,
                        "Bundle Open Error",
                        f"Could not open bundle:\n{exc}",
                    )
                    return
            elif path_obj.is_file() and path_obj.suffix.lower() == ".vasopack":
                # Old ZIP-based bundle format - needs unpacking
                self.hide_progress()  # Hide during user dialog
                base_dir = QFileDialog.getExistingDirectory(
                    self,
                    "Select Folder to Unpack Legacy Bundle",
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
                self.show_progress("Unpacking legacy bundle", maximum=0)
                try:
                    project = import_project_bundle(path, target_dir.as_posix())
                    project_path = project.path or target_dir.joinpath(f"{stem}.vaso").as_posix()
                    self.statusBar().showMessage(
                        f"\u2713 Legacy bundle unpacked to {target_dir}", 5000
                    )
                except Exception as exc:
                    self.hide_progress()
                    QMessageBox.critical(
                        self,
                        "Bundle Import Error",
                        f"Could not unpack legacy bundle:\n{exc}",
                    )
                    return
            else:
                autosave_candidate = pending_autosave_path(path)
                if autosave_candidate:
                    if not is_valid_autosave_snapshot(autosave_candidate):
                        quarantine_autosave_snapshot(autosave_candidate)
                        log.warning("Discarded corrupt autosave snapshot: %s", autosave_candidate)
                        self.hide_progress()
                        QMessageBox.warning(
                            self,
                            "Autosave Discarded",
                            (
                                "The autosave snapshot for this project was corrupted and "
                                "has been discarded.\n\nThe original project will be opened instead."
                            ),
                        )
                        self.show_progress("Loading project", maximum=0)
                        autosave_candidate = None
                    else:
                        try:
                            autosave_mtime = os.path.getmtime(autosave_candidate)
                            project_mtime = os.path.getmtime(path)
                        except OSError:
                            autosave_mtime = project_mtime = 0

                        if autosave_mtime > project_mtime:
                            self.hide_progress()  # Hide during user dialog
                            choice = QMessageBox.question(
                                self,
                                "Recover Autosave?",
                                (
                                    "An autosave snapshot newer than this project was found.\n"
                                    "Would you like to recover it?"
                                ),
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes,
                            )
                            self.show_progress("Loading project", maximum=0)
                            if choice == QMessageBox.Yes:
                                try:
                                    project = restore_autosave(path)
                                    restored_from_autosave = True
                                    with contextlib.suppress(OSError):
                                        os.remove(autosave_candidate)
                                except Exception as exc:
                                    self.hide_progress()
                                    QMessageBox.warning(
                                        self,
                                        "Autosave Recovery Failed",
                                        (
                                            "Could not restore autosave:\n"
                                            f"{exc}\n\nOpening original file instead."
                                        ),
                                    )
                                    self.show_progress("Loading project", maximum=0)

                if project is None:
                    try:
                        project = load_project(path)
                    except Exception as exc:
                        self.hide_progress()
                        QMessageBox.critical(
                            self,
                            "Project Load Error",
                            f"Could not open project:\n{exc}",
                        )
                        return
        finally:
            self.hide_progress()

        self._replace_current_project(project)
        self.apply_ui_state(getattr(self.current_project, "ui_state", None))
        self.refresh_project_tree()
        self.show_analysis_workspace()

        status = f"\u2713 Project loaded: {self.current_project.name}"
        if restored_from_autosave:
            status += " (autosave recovered)"
        self.statusBar().showMessage(status, 5000)

        if project_path:
            self.update_recent_projects(project_path)
        tree = self.project_tree
        restored = self.restore_last_selection()
        if not restored:
            first_sample_item = None
            first_exp_item = None
            if tree and self.current_project.experiments:
                root_item = tree.topLevelItem(0)
                first_exp = self.current_project.experiments[0]
                if root_item is not None:
                    for i in range(root_item.childCount()):
                        child = root_item.child(i)
                        if child.data(0, Qt.UserRole) is first_exp:
                            first_exp_item = child
                            if first_exp.samples:
                                target_sample = first_exp.samples[0]
                                for j in range(child.childCount()):
                                    sample_child = child.child(j)
                                    if sample_child.data(0, Qt.UserRole) is target_sample:
                                        first_sample_item = sample_child
                                        break
                            break

            if first_sample_item is not None and tree:
                tree.setCurrentItem(first_sample_item)
                self.on_tree_item_clicked(first_sample_item, 0)
            elif self.current_project.experiments and self.current_project.experiments[0].samples:
                first_sample = self.current_project.experiments[0].samples[0]
                self.load_sample_into_view(first_sample)
            else:
                if first_exp_item is not None and tree:
                    tree.setCurrentItem(first_exp_item)
                    self.on_tree_item_clicked(first_exp_item, 0)
                elif tree and tree.topLevelItemCount():
                    root = tree.topLevelItem(0)
                    if root is not None:
                        tree.setCurrentItem(root)
                        self.on_tree_item_clicked(root, 0)
                self.show_analysis_workspace()
        self._reset_session_dirty()

    def open_project_file(self, path: str | None = None):
        from vasoanalyzer.app.openers import open_project_file as _open_project_file

        return _open_project_file(self, path)

    def save_project_file(self):
        if self.current_project and self.current_project.path:
            settings = QSettings("TykockiLab", "VasoAnalyzer")
            embed = settings.value("snapshots/embed_stacks", False, type=bool)
            self.current_project.embed_snapshots = bool(embed)

            self.current_project.ui_state = self.gather_ui_state()
            if self.current_sample:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state

            # Show progress bar during save
            self.show_progress("Saving project", maximum=0)  # Indeterminate progress
            try:
                save_project_file(self.current_project)
                self.update_recent_projects(self.current_project.path)
                self.statusBar().showMessage("\u2713 Project saved", 3000)
                self._reset_session_dirty()
                self._update_window_title()
            finally:
                self.hide_progress()
        elif self.current_project:
            self.save_project_file_as()

    def save_project_file_as(self):
        if not self.current_project:
            return

        # Offer both single-file and folder bundle formats
        current_path = self.current_project.path or ""
        filters = "VasoAnalyzer Projects (*.vaso);;Folder Bundles (*.vasopack)"

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            current_path,
            filters,
        )
        if path:
            path_obj = Path(path).expanduser()

            # Enforce extension based on selected filter
            if "Folder Bundles" in selected_filter:
                if path_obj.suffix.lower() != ".vasopack":
                    path_obj = path_obj.with_suffix(".vasopack")
            else:
                # Default to .vaso (single-file container)
                if path_obj.suffix.lower() != ".vaso":
                    path_obj = path_obj.with_suffix(".vaso")

            path = str(path_obj.resolve(strict=False))
            settings = QSettings("TykockiLab", "VasoAnalyzer")
            embed = settings.value("snapshots/embed_stacks", False, type=bool)
            self.current_project.embed_snapshots = bool(embed)
            self.current_project.ui_state = self.gather_ui_state()
            if self.current_sample:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state

            # Show progress bar during save
            self.show_progress("Saving project", maximum=0)  # Indeterminate progress
            try:
                save_project_file(self.current_project, path)
                self.update_recent_projects(path)

                # Show success message with appropriate format name
                format_name = "bundle" if path_obj.suffix == ".vasopack" else "project"
                self.statusBar().showMessage(
                    f"\u2713 {format_name.capitalize()} saved: {path_obj.name}", 3000
                )
            finally:
                self.hide_progress()
        else:
            return

        self._reset_session_dirty()
        self._update_window_title()

    def export_project_bundle_action(self):
        if not self.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before exporting."
            )
            return

        if not self.current_project.path:
            self.save_project_file_as()
            if not self.current_project or not self.current_project.path:
                return

        default_stem = Path(self.current_project.path).with_suffix("").name
        default_path = (
            Path(self.current_project.path).with_name(f"{default_stem}.vasopack").as_posix()
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Project Bundle",
            default_path,
            "Vaso Bundles (*.vasopack)",
        )
        if not path:
            return
        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() != ".vasopack":
            path_obj = path_obj.with_suffix(".vasopack")
        path = str(path_obj.resolve(strict=False))

        self.current_project.ui_state = self.gather_ui_state()
        if self.current_sample:
            state = self.gather_sample_state()
            self.current_sample.ui_state = state
            self.project_state[id(self.current_sample)] = state

        try:
            export_project_bundle(self.current_project, path)
            self.statusBar().showMessage(f"\u2713 Bundle saved: {path}", 5000)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Could not export bundle:\n{exc}",
            )

    def export_shareable_project(self):
        """Export a DELETE-mode single-file copy of the current project."""

        if not self.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before exporting."
            )
            return

        if not self.current_project.path:
            self.save_project_file_as()
            if not self.current_project or not self.current_project.path:
                return

        # Ensure latest edits are flushed before exporting.
        self.save_project_file()
        if not self.current_project or not self.current_project.path:
            return

        stem = Path(self.current_project.path).with_suffix("").name
        default_path = (
            Path(self.current_project.path).with_name(f"{stem}.shareable.vaso").as_posix()
        )
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export Shareable Project",
            default_path,
            "Vaso Projects (*.vaso)",
        )
        if not dest:
            return

        dest_path = Path(dest).expanduser()
        if dest_path.suffix.lower() != ".vaso":
            dest_path = dest_path.with_suffix(".vaso")
        dest_path = dest_path.resolve(strict=False)

        try:
            exported = export_project_single_file(
                self.current_project,
                destination=dest_path.as_posix(),
                ensure_saved=False,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Could not export shareable project:\n{exc}",
            )
            return

        self.statusBar().showMessage(f"\u2713 Shareable project saved: {exported}", 5000)

    # ===== Autosave Methods =====

    def _run_deferred_autosave(self):
        reason = self._pending_autosave_reason or "deferred"
        self._pending_autosave_reason = None
        if self.current_project and self.current_project.path:
            self.auto_save_project(reason=reason)

    def request_deferred_autosave(self, delay_ms: int = 2000, *, reason: str = "deferred") -> None:
        """Schedule an autosave after ``delay_ms`` to coalesce rapid edits."""

        if not self.current_project or not self.current_project.path:
            self._pending_autosave_reason = None
            self._deferred_autosave_timer.stop()
            return

        self._pending_autosave_reason = reason
        self._deferred_autosave_timer.start(max(0, int(delay_ms)))

    def auto_save_project(self, reason: str | None = None):
        """Write an autosave snapshot when a project is available."""

        self._deferred_autosave_timer.stop()
        self._pending_autosave_reason = None

        if not self.current_project or not self.current_project.path:
            return

        try:
            settings = QSettings("TykockiLab", "VasoAnalyzer")
            embed = settings.value("snapshots/embed_stacks", False, type=bool)
            self.current_project.embed_snapshots = bool(embed)

            self.current_project.ui_state = self.gather_ui_state()
            if self.current_sample:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state

            autosave_path = autosave_project(self.current_project)
            if autosave_path:
                self.last_autosave_path = autosave_path
                log.debug(
                    "Autosave written to %s (reason=%s)",
                    autosave_path,
                    reason or "manual",
                )
        except Exception as exc:
            log.error("Failed to write autosave (%s): %s", reason or "manual", exc)

    def _autosave_tick(self):
        if not self.current_project or not self.current_project.path:
            return
        if not self.session_dirty:
            return
        self.auto_save_project(reason="timer")

    # ===== Project Tree Management =====

    def refresh_project_tree(self):
        if not self.project_tree:
            return
        self.project_tree.clear()
        if not self.current_project:
            return
        root = QTreeWidgetItem([self.current_project.name])
        root.setData(0, Qt.UserRole, self.current_project)
        root.setFlags(root.flags() | Qt.ItemIsEditable)
        root.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
        self.project_tree.addTopLevelItem(root)
        for exp in self.current_project.experiments:
            exp_item = QTreeWidgetItem([exp.name])
            exp_item.setData(0, Qt.UserRole, exp)
            exp_item.setFlags(exp_item.flags() | Qt.ItemIsEditable)
            exp_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileDialogListView))
            root.addChild(exp_item)
            for s in exp.samples:
                has_data = bool(
                    s.trace_path or s.trace_data is not None or s.dataset_id is not None
                )
                status = "✓" if has_data else "✗"
                item = QTreeWidgetItem([f"{s.name} {status}"])
                item.setData(0, Qt.UserRole, s)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                exp_item.addChild(item)

                # Add figures folder if sample has figures
                import logging

                log = logging.getLogger(__name__)
                log.info(
                    f"Checking figures for sample '{s.name}': figure_configs={s.figure_configs}"
                )

                if s.figure_configs and len(s.figure_configs) > 0:
                    log.info(
                        f"Sample '{s.name}' has {len(s.figure_configs)} figure(s), adding to tree"
                    )
                    figures_folder = QTreeWidgetItem(["📊 Figures"])
                    figures_folder.setData(0, Qt.UserRole, ("figures_folder", s))
                    figures_folder.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    item.addChild(figures_folder)

                    # Add each figure
                    for fig_id, fig_data in s.figure_configs.items():
                        fig_name = fig_data.get("figure_name", fig_id)
                        log.info(f"Adding figure to tree: {fig_name} (ID: {fig_id})")
                        fig_item = QTreeWidgetItem([fig_name])
                        fig_item.setData(0, Qt.UserRole, ("figure", s, fig_id, fig_data))
                        fig_item.setIcon(
                            0, self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
                        )
                        fig_item.setToolTip(
                            0, f"Created: {fig_data.get('metadata', {}).get('created', 'Unknown')}"
                        )
                        figures_folder.addChild(fig_item)
                else:
                    log.info(f"Sample '{s.name}' has no figures or figure_configs is None/empty")
        self.project_tree.expandAll()
        self._update_metadata_panel(self.current_project)
        self._schedule_missing_asset_scan()

    def _schedule_missing_asset_scan(self) -> None:
        if self.current_project is None or not getattr(self.current_project, "experiments", None):
            return
        if getattr(self.current_project, "path", None) is None:
            return
        token = object()
        self._pending_asset_scan_token = token
        job = _MissingAssetScanJob(self.current_project, token)
        job.signals.finished.connect(self._on_missing_asset_scan_finished)
        job.signals.error.connect(self._on_missing_asset_scan_error)
        self._thread_pool.start(job)

    def _on_missing_asset_scan_finished(
        self,
        token: object,
        payload: tuple[list[MissingAsset], list[str]],
    ) -> None:
        if token != self._pending_asset_scan_token:
            return
        self._pending_asset_scan_token = None

        sample_assets, project_messages = payload
        self._project_missing_messages = project_messages

        updated = False
        for asset in sample_assets:
            key = (id(asset.sample), asset.kind)
            existing = self._missing_assets.get(key)
            if existing is None:
                self._missing_assets[key] = asset
                updated = True
            else:
                existing.current_path = asset.current_path
                existing.relative = asset.relative
                existing.hint = asset.hint
                existing.signature = asset.signature

        if updated and self._relink_dialog:
            self._relink_dialog.set_assets(self._missing_assets.values())

        if self.action_relink_assets:
            self.action_relink_assets.setEnabled(bool(self._missing_assets))

        snapshot = (len(sample_assets), len(project_messages))
        if snapshot != self._last_missing_assets_snapshot and (sample_assets or project_messages):
            self._report_missing_assets(sample_assets, project_messages)
            self._last_missing_assets_snapshot = snapshot

    def _on_missing_asset_scan_error(self, token: object, message: str) -> None:
        if token != self._pending_asset_scan_token:
            return
        self._pending_asset_scan_token = None
        log.debug("Missing asset scan failed: %s", message)

    def _report_missing_assets(
        self,
        sample_assets: list[MissingAsset],
        project_messages: list[str],
    ) -> None:
        entries: list[str] = []
        for asset in sample_assets:
            path_text = asset.current_path or "—"
            entries.append(f"{asset.label}: {path_text}")
        for message in project_messages:
            entries.append(f"Project: {message}")

        if not entries:
            return

        summary = "\n".join(f"• {entry}" for entry in entries[:6])
        if len(entries) > 6:
            summary += f"\n… and {len(entries) - 6} more."
        QMessageBox.warning(
            self,
            "Missing Linked Files",
            (
                "Some linked resources could not be found. "
                "You may need to relink them before continuing.\n\n"
                f"{summary}"
            ),
        )

    # ===== Tree Item Event Handlers =====

    def on_tree_item_clicked(self, item, _):
        obj = item.data(0, Qt.UserRole)
        if isinstance(obj, SampleN):
            if self.current_sample and self.current_sample is not obj:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state
            self.current_sample = obj
            parent = item.parent()
            self.current_experiment = parent.data(0, Qt.UserRole) if parent else None
            # Open the sample on single-click
            self.load_sample_into_view(obj)
        elif isinstance(obj, Experiment):
            self.current_experiment = obj
            self.current_sample = None
            if self.current_project is not None:
                if not isinstance(self.current_project.ui_state, dict):
                    self.current_project.ui_state = {}
                self.current_project.ui_state["last_experiment"] = obj.name
                self.current_project.ui_state.pop("last_sample", None)
        else:
            self.current_sample = None
            self.current_experiment = None
        self._update_metadata_panel(obj)

    def on_tree_item_changed(self, item, _):
        obj = item.data(0, Qt.UserRole)
        if obj is None:
            return

        text = item.text(0)

        def _clean(txt: str) -> str:
            txt = txt.strip()
            if txt.endswith(" \u2713") or txt.endswith(" \u2717"):
                txt = txt[:-2]
            return txt.strip()

        name = _clean(text)

        if isinstance(obj, SampleN):
            obj.name = name
            has_data = bool(
                obj.trace_path or obj.trace_data is not None or obj.dataset_id is not None
            )
            status = "\u2713" if has_data else "\u2717"
            self.project_tree.blockSignals(True)
            item.setText(0, f"{name} {status}")
            self.project_tree.blockSignals(False)
        elif isinstance(obj, Experiment | Project):
            obj.name = name

    def on_tree_item_double_clicked(self, item, _):
        """Deprecated handler kept for backward compatibility."""
        obj = item.data(0, Qt.UserRole)
        if isinstance(obj, SampleN):
            self.load_sample_into_view(obj)

    def on_tree_selection_changed(self):
        if not self.project_tree:
            return
        selection = self.project_tree.selectedItems()
        if not selection:
            self._update_metadata_panel()
            return
        obj = selection[0].data(0, Qt.UserRole)
        self._update_metadata_panel(obj)

    def restore_last_selection(self) -> bool:
        if not self.project_tree or not self.current_project:
            return False

        state = getattr(self.current_project, "ui_state", {}) or {}
        last_exp = state.get("last_experiment")
        if not last_exp:
            return False
        last_sample = state.get("last_sample")

        root = self.project_tree.topLevelItem(0)
        if root is None:
            return False

        exp_item = None
        sample_item = None

        for i in range(root.childCount()):
            child = root.child(i)
            obj = child.data(0, Qt.UserRole)
            if isinstance(obj, Experiment) and obj.name == last_exp:
                exp_item = child
                if last_sample:
                    for j in range(child.childCount()):
                        sample_child = child.child(j)
                        sample_obj = sample_child.data(0, Qt.UserRole)
                        if isinstance(sample_obj, SampleN) and sample_obj.name == last_sample:
                            sample_item = sample_child
                            break
                break

        if sample_item is not None:
            self.project_tree.setCurrentItem(sample_item)
            self.on_tree_item_clicked(sample_item, 0)
            return True

        if exp_item is not None:
            self.project_tree.setCurrentItem(exp_item)
            self.on_tree_item_clicked(exp_item, 0)
            return True

        return False

    # ===== Metadata Panel Updates =====

    def on_project_description_changed(self, text: str) -> None:
        if not self.current_project:
            return
        description = text.strip() or None
        if self.current_project.description != description:
            self.current_project.description = description
            if self.metadata_dock:
                self.metadata_dock.project_form.set_metadata(self.current_project)
            self.mark_session_dirty()

    def on_project_tags_changed(self, tags: list[str]) -> None:
        if not self.current_project:
            return
        if self.current_project.tags != tags:
            self.current_project.tags = tags
            if self.metadata_dock:
                self.metadata_dock.project_form.set_metadata(self.current_project)
            self.mark_session_dirty()

    def on_project_add_attachment(self) -> None:
        if not self.current_project:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Project Attachment",
            "",
            "All Files (*.*)",
        )
        added = False
        for path in paths:
            if not path:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            from vasoanalyzer.core.project import Attachment

            attachment = Attachment(name=name, filename=os.path.basename(path))
            attachment.source_path = path
            self.current_project.attachments.append(attachment)
            added = True
        if added:
            if self.metadata_dock:
                self.metadata_dock.refresh_attachments(self.current_project.attachments)
            self.mark_session_dirty()

    def on_project_remove_attachment(self, index: int) -> None:
        if not self.current_project:
            return
        attachments = self.current_project.attachments
        if 0 <= index < len(attachments):
            attachments.pop(index)
            if self.metadata_dock:
                self.metadata_dock.refresh_attachments(attachments)
            self.mark_session_dirty()

    def on_project_open_attachment(self, index: int) -> None:
        if not self.current_project:
            return
        self._open_attachment_for(self.current_project.attachments, index)

    def on_experiment_notes_changed(self, text: str) -> None:
        if not isinstance(self.current_experiment, Experiment):
            return
        notes = text.strip() or None
        if self.current_experiment.notes != notes:
            self.current_experiment.notes = notes
            if self.metadata_dock:
                self.metadata_dock.experiment_form.set_metadata(self.current_experiment)
            self.mark_session_dirty()

    def on_experiment_tags_changed(self, tags: list[str]) -> None:
        if not isinstance(self.current_experiment, Experiment):
            return
        if self.current_experiment.tags != tags:
            self.current_experiment.tags = tags
            if self.metadata_dock:
                self.metadata_dock.experiment_form.set_metadata(self.current_experiment)
            self.mark_session_dirty()

    def on_sample_notes_changed(self, text: str) -> None:
        if not isinstance(self.current_sample, SampleN):
            return
        notes = text.strip() or None
        if self.current_sample.notes != notes:
            self.current_sample.notes = notes
            if self.metadata_dock:
                self.metadata_dock.sample_form.set_metadata(self.current_sample)
            self.mark_session_dirty()

    def on_sample_add_attachment(self) -> None:
        if not isinstance(self.current_sample, SampleN):
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Sample Attachment",
            "",
            "All Files (*.*)",
        )
        added = False
        for path in paths:
            if not path:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            from vasoanalyzer.core.project import Attachment

            attachment = Attachment(name=name, filename=os.path.basename(path))
            attachment.source_path = path
            self.current_sample.attachments.append(attachment)
            added = True
        if added:
            if self.metadata_dock:
                self.metadata_dock.refresh_attachments(self.current_sample.attachments)
            self.mark_session_dirty()

    def on_sample_remove_attachment(self, index: int) -> None:
        if not isinstance(self.current_sample, SampleN):
            return
        attachments = self.current_sample.attachments
        if 0 <= index < len(attachments):
            attachments.pop(index)
            if self.metadata_dock:
                self.metadata_dock.refresh_attachments(attachments)
            self.mark_session_dirty()

    def on_sample_open_attachment(self, index: int) -> None:
        if not isinstance(self.current_sample, SampleN):
            return
        self._open_attachment_for(self.current_sample.attachments, index)

    # ===== Experiment and Sample Management =====

    def show_project_context_menu(self, pos):
        item = self.project_tree.itemAt(pos)
        menu = QMenu()

        selected_samples = [
            it.data(0, Qt.UserRole)
            for it in self.project_tree.selectedItems()
            if isinstance(it.data(0, Qt.UserRole), SampleN)
        ]
        open_act = None
        dual_act = None
        if selected_samples:
            open_act = menu.addAction("Open Selected Datasets…")
            if len(selected_samples) == 2:
                dual_act = menu.addAction("Open Dual View…")

        if item is None:
            add_exp = menu.addAction("Add Experiment")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == add_exp:
                self.add_experiment()
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
            return

        obj = item.data(0, Qt.UserRole)
        if isinstance(obj, Project):
            add_exp = menu.addAction("Add Experiment")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == add_exp:
                self.add_experiment()
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
        elif isinstance(obj, Experiment):
            add_n = menu.addAction("Add N")
            import_folder = menu.addAction("Import Folder…")
            del_exp = menu.addAction("Delete Experiment")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == add_n:
                self.add_sample(obj)
            elif action == import_folder:
                self._handle_import_folder(target_experiment=obj)
            elif action == del_exp:
                self.delete_experiment(obj)
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
        elif isinstance(obj, SampleN):
            load_data = menu.addAction("Load Data Into N…")
            save_n = menu.addAction("Save N As…")
            del_n = menu.addAction("Delete N")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == load_data:
                self.load_data_into_sample(obj)
            elif action == save_n:
                self.save_sample_as(obj)
            elif action == del_n:
                self.delete_sample(obj)
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)

    def add_experiment(self):
        if not self.current_project:
            return
        name, ok = QInputDialog.getText(self, "Experiment Name", "Name:")
        if ok and name:
            exp = Experiment(name=name)
            self.current_project.experiments.append(exp)
            self.current_experiment = exp
            self.refresh_project_tree()

    def delete_experiment(self, experiment: Experiment) -> None:
        if not self.current_project or experiment not in self.current_project.experiments:
            return

        sample_count = len(experiment.samples)
        message = "Delete this experiment?"
        if sample_count:
            message = (
                f"Delete experiment '{experiment.name}' and its {sample_count} sample(s)?\n"
                "This action cannot be undone."
            )

        confirm = QMessageBox.question(
            self,
            "Delete Experiment",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        for sample in experiment.samples:
            self.project_state.pop(id(sample), None)
            if self.current_sample is sample:
                self.current_sample = None

        self.current_project.experiments.remove(experiment)

        if self.current_experiment is experiment:
            self.current_experiment = None

        self.refresh_project_tree()
        self.mark_session_dirty()
        self.auto_save_project(reason="delete_experiment")
        self._update_home_resume_button()
        self._update_metadata_panel(self.current_project)

    def add_sample(self, experiment):
        nname, ok = QInputDialog.getText(self, "Sample Name", "Name:")
        if ok and nname:
            experiment.samples.append(SampleN(name=nname))
            self.refresh_project_tree()

    def add_sample_to_current_experiment(self):
        if not self.current_experiment:
            QMessageBox.warning(
                self,
                "No Experiment Selected",
                "Please select an experiment first.",
            )
            return
        self.add_sample(self.current_experiment)

    def add_data_to_current_experiment(self):
        if not self.current_experiment:
            QMessageBox.warning(
                self,
                "No Experiment Selected",
                "Please select an experiment first.",
            )
            return

        nname, ok = QInputDialog.getText(self, "Sample Name", "Name:")
        if not ok or not nname:
            return
        sample = SampleN(name=nname)
        self.current_experiment.samples.append(sample)
        self.refresh_project_tree()
        self.load_data_into_sample(sample)
        self.statusBar().showMessage(
            f"\u2713 {nname} loaded into Experiment '{self.current_experiment.name}'",
            3000,
        )
        if self.current_project and self.current_project.path:
            save_project(self.current_project, self.current_project.path)

    def load_data_into_sample(self, sample: SampleN):
        log.info("Loading data into sample %s", sample.name)
        trace_path, _ = QFileDialog.getOpenFileName(
            self, "Select Trace File", "", "CSV Files (*.csv)"
        )
        if not trace_path:
            return

        # Show progress during data load
        self.show_progress(f"Loading data into {sample.name}", maximum=0)
        try:
            try:
                df = self.load_trace_and_event_files(trace_path)
            except Exception:
                self.hide_progress()
                return

            trace_obj = Path(trace_path).expanduser().resolve(strict=False)
            self._update_sample_link_metadata(sample, "trace", trace_obj)
            sample.trace_data = df
            from vasoanalyzer.io.events import find_matching_event_file

            event_path = find_matching_event_file(trace_path)
            if event_path and os.path.exists(event_path):
                event_obj = Path(event_path).expanduser().resolve(strict=False)
                self._update_sample_link_metadata(sample, "events", event_obj)

            self.refresh_project_tree()

            log.info("Sample %s updated with data", sample.name)

            if self.current_project and self.current_project.path:
                save_project(self.current_project, self.current_project.path)
        finally:
            self.hide_progress()

    def _handle_import_folder(self, target_experiment=None):
        """Handle the Import Folder action."""
        from vasoanalyzer.services.folder_import_service import scan_folder_with_status
        from vasoanalyzer.ui.dialogs.folder_import_dialog import FolderImportDialog

        # Determine target experiment
        if target_experiment is None:
            target_experiment = self.current_experiment

        if target_experiment is None:
            QMessageBox.warning(
                self,
                "No Experiment Selected",
                "Please select an experiment before importing a folder.",
            )
            return

        # Prompt for folder selection
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Import",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )

        if not folder_path:
            return

        # Scan folder for trace files
        try:
            candidates = scan_folder_with_status(folder_path, target_experiment)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Scan Error",
                f"Failed to scan folder:\n{e}",
            )
            log.exception("Error scanning folder: %s", folder_path)
            return

        if not candidates:
            QMessageBox.information(
                self,
                "No Files Found",
                "No trace files were found in the selected folder or its subfolders.",
            )
            return

        # Show preview dialog
        dialog = FolderImportDialog(candidates, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        selected = dialog.selected_candidates
        if not selected:
            return

        # Import selected files
        self._import_candidates(selected, target_experiment)

    def _import_candidates(self, candidates, target_experiment):
        """Import a list of candidates into an experiment."""
        from vasoanalyzer.services.folder_import_service import get_file_signature

        success_count = 0
        error_count = 0
        errors = []

        total = len(candidates)
        # Show progress bar with real progress
        self.show_progress(f"Importing samples", maximum=total)
        try:
            for idx, candidate in enumerate(candidates, 1):
                try:
                    # Update progress message
                    self._progress_bar.setFormat(
                        f"Importing {idx}/{total}: {candidate.subfolder} %p%"
                    )

                    # Create sample
                    sample = SampleN(name=candidate.subfolder)

                    # Load trace data
                    df = self.load_trace_and_event_files(candidate.trace_file)
                    sample.trace_data = df

                    # Update metadata for trace
                    trace_obj = Path(candidate.trace_file).expanduser().resolve(strict=False)
                    self._update_sample_link_metadata(sample, "trace", trace_obj)

                    # Store file signature for change detection
                    sample.trace_sig = get_file_signature(candidate.trace_file)

                    # Load events if found
                    if candidate.events_file and os.path.exists(candidate.events_file):
                        event_obj = Path(candidate.events_file).expanduser().resolve(strict=False)
                        self._update_sample_link_metadata(sample, "events", event_obj)
                        sample.events_sig = get_file_signature(candidate.events_file)

                    # Add to experiment
                    target_experiment.samples.append(sample)
                    success_count += 1

                    # Update progress
                    self.update_progress(idx)

                except Exception as e:
                    error_count += 1
                    errors.append(f"{candidate.subfolder}: {str(e)}")
                    log.exception("Error importing %s", candidate.trace_file)
        finally:
            self.hide_progress()

        # Refresh UI
        self.refresh_project_tree()

        # Save project with progress indication
        if self.current_project and self.current_project.path:
            self.show_progress("Saving project", maximum=0)
            try:
                save_project(self.current_project, self.current_project.path)
            finally:
                self.hide_progress()

        # Show summary
        if error_count == 0:
            self.statusBar().showMessage(
                f"✓ Successfully imported {success_count} sample(s) into '{target_experiment.name}'",
                5000,
            )
        else:
            message = f"Imported {success_count} sample(s) with {error_count} error(s)."
            if errors:
                message += "\n\nErrors:\n" + "\n".join(errors[:5])
                if len(errors) > 5:
                    message += f"\n... and {len(errors) - 5} more"
            QMessageBox.warning(self, "Import Complete with Errors", message)

    def delete_sample(self, sample: SampleN):
        if not self.current_project:
            return
        for exp in self.current_project.experiments:
            if sample in exp.samples:
                exp.samples.remove(sample)
                if self.current_sample is sample:
                    self.current_sample = None
                self.refresh_project_tree()
                if self.current_project.path:
                    save_project_file(self.current_project, self.current_project.path)
                break

    def save_sample_as(self, sample):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Sample", f"{sample.name}.vaso", "Vaso Sample (*.vaso)"
        )
        if path:
            tmp_proj = Project(
                name=sample.name, experiments=[Experiment(name="exp", samples=[sample])]
            )
            save_project(tmp_proj, path)

    # ===== Recent Projects Management =====

    def show_project_file_info(self) -> None:
        message = (
            "<b>Single-File .vaso Projects</b><br><br>"
            "<ul>"
            "<li>SQLite v3 container that stores datasets, traces, UI state, and metadata together.</li>"
            "<li>All imported assets are embedded, deduplicated by SHA-256, and compressed for portability.</li>"
            "<li>Saves are atomic and crash-safe, with periodic autosave snapshots you can restore on reopen.</li>"
            "</ul>"
        )
        QMessageBox.information(self, "About Project File", message)

    def build_recent_projects_menu(self):
        if not hasattr(self, "recent_projects_menu") or self.recent_projects_menu is None:
            return
        self.recent_projects_menu.clear()

        if not self.recent_projects:
            self.recent_projects_menu.addAction("No recent projects").setEnabled(False)
            return

        for path in self.recent_projects:
            label = os.path.basename(path)
            action = QAction(label, self)
            action.setToolTip(path)
            action.triggered.connect(partial(self.open_recent_project, path))
            self.recent_projects_menu.addAction(action)

        self.recent_projects_menu.addSeparator()
        clear_action = QAction("Clear Recent Projects", self)
        clear_action.triggered.connect(self.clear_recent_projects)
        self.recent_projects_menu.addAction(clear_action)

    def load_recent_projects(self):
        recent = self.settings.value("recentProjects", [])
        if recent is None:
            recent = []
        self.recent_projects = recent

    def update_recent_projects(self, path):
        if path not in self.recent_projects:
            self.recent_projects = [path] + self.recent_projects[:4]
            self.settings.setValue("recentProjects", self.recent_projects)
        self.build_recent_projects_menu()
        self._refresh_home_recent()

    def save_recent_projects(self):
        self.settings.setValue("recentProjects", self.recent_projects)

    def remove_recent_project(self, path: str) -> None:
        if path not in self.recent_projects:
            return
        self.recent_projects = [p for p in self.recent_projects if p != path]
        self.save_recent_projects()
        self.build_recent_projects_menu()
        self._refresh_home_recent()

    def clear_recent_projects(self):
        self.recent_projects = []
        self.save_recent_projects()
        self.build_recent_projects_menu()
        self._refresh_home_recent()

    def open_recent_project(self, path):
        # Use the standard open flow which creates ProjectContext
        from vasoanalyzer.app.openers import open_project_file

        # Show progress during load
        self.show_progress("Loading project", maximum=0)
        try:
            open_project_file(self, path)
        except Exception as e:
            self.hide_progress()
            import logging

            log = logging.getLogger(__name__)
            log.error(f"Failed to open recent project: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Project Load Error",
                f"Could not open project:\n{e}",
            )
            return
        finally:
            self.hide_progress()

        # Load first sample if available
        if (
            self.current_project
            and self.current_project.experiments
            and self.current_project.experiments[0].samples
        ):
            first_sample = self.current_project.experiments[0].samples[0]
            self.load_sample_into_view(first_sample)
