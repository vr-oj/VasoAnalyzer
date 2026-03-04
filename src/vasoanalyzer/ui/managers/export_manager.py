# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""ExportManager -- centralises export-related logic extracted from VasoAnalyzerApp."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from PyQt5.QtCore import QObject, Qt
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QFileDialog,
    QMessageBox,
    QWidget,
)

from vasoanalyzer.export.clipboard import render_tsv, write_csv
from vasoanalyzer.export.generator import build_export_table, events_from_rows
from vasoanalyzer.export.profiles import get_profile
from vasoanalyzer.services.project_service import (
    export_project_bundle,
    export_project_single_file,
)
from vasoanalyzer.storage.dataset_package import (
    DatasetPackageValidationError,
    export_dataset_package,
)
from vasoanalyzer.ui.dialogs.excel_mapping_dialog import update_excel_file
from vasoanalyzer.ui.dialogs.excel_template_export_dialog import ExcelTemplateExportDialog

if TYPE_CHECKING:
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)


class ExportManager(QObject):
    """Manages all export operations on behalf of :class:`VasoAnalyzerApp`."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

    # ------------------------------------------------------------------
    # Event-table CSV export
    # ------------------------------------------------------------------

    def auto_export_table(self, checked: bool = False, path: str | None = None):
        """Auto-export event table to CSV.

        Args:
            checked: Unused boolean from Qt signal (ignored)
            path: Optional explicit output path.
        """
        host = self._host
        try:
            sample = getattr(host, "current_sample", None)

            # Resolve the best trace path (prefer the live file on disk)
            candidate_paths: list[str] = []
            if host.trace_file_path:
                candidate_paths.append(os.path.abspath(host.trace_file_path))
            if sample is not None and getattr(sample, "trace_path", None):
                candidate_paths.append(os.path.abspath(sample.trace_path))
                # Try resolving stored links if present
                with contextlib.suppress(Exception):
                    resolved = host._resolve_sample_link(sample, "trace")
                    if resolved:
                        candidate_paths.append(os.path.abspath(resolved))

            trace_path = next(
                (p for p in candidate_paths if p and os.path.isfile(p)), None
            )

            # Name and output directory
            base_name = None
            if sample is not None and getattr(sample, "name", None):
                base_name = str(sample.name).strip()
            if base_name is None and trace_path:
                base_name = os.path.splitext(os.path.basename(trace_path))[0]
            if not base_name:
                base_name = "event"

            if path:
                csv_path = path
                output_dir = os.path.dirname(csv_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
            else:
                if trace_path:
                    output_dir = os.path.dirname(trace_path)
                elif getattr(host.current_project, "path", None):
                    output_dir = os.path.dirname(host.current_project.path)
                else:
                    output_dir = os.getcwd()

                os.makedirs(output_dir, exist_ok=True)
                filename = f"{base_name}_eventDiameters_output.csv"
                csv_path = os.path.join(output_dir, filename)

            has_od = (
                "Outer Diameter" in host.trace_data.columns
                if host.trace_data is not None
                else False
            )
            avg_label = host._trace_label_for("p_avg")
            set_label = host._trace_label_for("p2")
            has_avg_p = host.trace_data is not None and avg_label in host.trace_data.columns
            has_set_p = host.trace_data is not None and set_label in host.trace_data.columns

            # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
            columns = [
                "Event",
                "Time (s)",
                "ID (µm)",
                "OD (µm)",
                "Avg P (mmHg)",
                "Set P (mmHg)",
                "Frame",
            ]
            df = pd.DataFrame(host.event_table_data, columns=columns)

            numeric_cols = [
                "Time (s)",
                "ID (µm)",
                "OD (µm)",
                "Avg P (mmHg)",
                "Set P (mmHg)",
            ]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            # Round numeric columns to 2 decimal places
            if "ID (µm)" in df.columns:
                df["ID (µm)"] = df["ID (µm)"].round(2)
            if "OD (µm)" in df.columns:
                df["OD (µm)"] = df["OD (µm)"].round(2)
            if "Time (s)" in df.columns:
                df["Time (s)"] = df["Time (s)"].round(2)
            if "Avg P (mmHg)" in df.columns:
                df["Avg P (mmHg)"] = df["Avg P (mmHg)"].round(2)
            if "Set P (mmHg)" in df.columns:
                df["Set P (mmHg)"] = df["Set P (mmHg)"].round(2)

            # Drop columns that don't have data
            if not has_od:
                df = df.drop(columns=["OD (µm)"])
            if not has_avg_p:
                df = df.drop(columns=["Avg P (mmHg)"])
            if not has_set_p:
                df = df.drop(columns=["Set P (mmHg)"])

            df.to_csv(csv_path, index=False)
            log.info("Event table auto-exported to:\n%s", csv_path)
        except Exception as e:
            log.error("Failed to auto-export event table:\n%s", e)

        if host.excel_auto_path and host.excel_auto_column:
            update_excel_file(
                host.excel_auto_path,
                host.event_table_data,
                start_row=3,
                column_letter=host.excel_auto_column,
            )

    def _export_event_table_to_path(self, path: str) -> bool:
        """Export the current event table to the given path using auto_export_table.

        Returns True on success, False on error.
        """
        try:
            self.auto_export_table(checked=False, path=path)
        except Exception as exc:
            msg = QMessageBox(self._host)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Failed to export events")
            msg.setText(f"Could not export event table to:\n{path}\n\n{exc}")
            msg.exec_()
            return False

        self._host._event_table_path = path
        self._host._invalidate_sample_state_cache()
        return True

    def _export_event_table_via_dialog(self) -> None:
        """Ask the user where to save the event table, then export if a path was chosen."""
        host = self._host
        initial_dir = ""
        initial_name = "event_table.csv"

        if host._event_table_path:
            initial_dir = os.path.dirname(host._event_table_path)
            initial_name = os.path.basename(host._event_table_path)
        else:
            trace_path = getattr(host, "trace_file_path", None)
            if trace_path:
                initial_dir = os.path.dirname(trace_path)
                base = os.path.splitext(os.path.basename(trace_path))[0]
                initial_name = f"{base}_eventDiameters_output.csv"
            elif getattr(host.current_project, "path", None):
                initial_dir = os.path.dirname(host.current_project.path)

        start_path = (
            os.path.join(initial_dir, initial_name) if initial_dir else initial_name
        )

        path, _ = QFileDialog.getSaveFileName(
            host,
            "Export event table",
            start_path,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        self._export_event_table_to_path(path)

    # ------------------------------------------------------------------
    # Event rows / profile helpers
    # ------------------------------------------------------------------

    def _event_rows_for_export(self) -> list[tuple]:
        host = self._host
        rows = list(getattr(host, "event_table_data", []) or [])
        if not rows or not hasattr(host, "event_table"):
            return rows

        selection = host.event_table.selectionModel()
        if selection is None:
            return rows

        selected_rows = {index.row() for index in selection.selectedRows()}
        if not selected_rows:
            selected_rows = {index.row() for index in selection.selectedIndexes()}

        if not selected_rows:
            return rows

        return [rows[i] for i in sorted(selected_rows) if 0 <= i < len(rows)]

    def _build_export_table_for_profile(self, profile_id: str):
        profile = get_profile(profile_id)
        rows = self._event_rows_for_export()
        events = events_from_rows(rows)
        return profile, build_export_table(profile, events)

    def _show_export_warnings(self, profile_name: str, warnings: Sequence[str]) -> None:
        if not warnings:
            return
        msg = QMessageBox(self._host)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(f"{profile_name} warnings")
        msg.setText("\n".join(warnings))
        msg.setStandardButtons(QMessageBox.Ok)
        msg.open()

    def _copy_event_profile_to_clipboard(
        self, profile_id: str, *, include_header: bool
    ) -> None:
        profile, table = self._build_export_table_for_profile(profile_id)
        if not table.headers and not table.rows:
            return
        text = render_tsv(table, include_header=include_header)
        QApplication.clipboard().setText(text)
        self._show_export_warnings(profile.display_name, table.warnings)

    def _default_event_export_filename(self, profile_id: str) -> str:
        host = self._host
        base_name = None
        sample = getattr(host, "current_sample", None)
        if sample is not None and getattr(sample, "name", None):
            base_name = str(sample.name).strip()
        if base_name is None and host.trace_file_path:
            base_name = os.path.splitext(os.path.basename(host.trace_file_path))[0]
        if not base_name:
            base_name = "event"
        return f"{base_name}_{profile_id}.csv"

    def _export_event_profile_csv_via_dialog(
        self, profile_id: str, *, include_header: bool
    ) -> None:
        host = self._host
        profile, table = self._build_export_table_for_profile(profile_id)
        if not table.headers and not table.rows:
            return

        initial_dir = ""
        if host._event_table_path:
            initial_dir = os.path.dirname(host._event_table_path)
        elif getattr(host.current_project, "path", None):
            initial_dir = os.path.dirname(host.current_project.path)

        filename = self._default_event_export_filename(profile_id)
        start_path = os.path.join(initial_dir, filename) if initial_dir else filename

        path, _ = QFileDialog.getSaveFileName(
            host,
            f"Export {profile.display_name}",
            start_path,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        write_csv(path, table, include_header=include_header)
        self._show_export_warnings(profile.display_name, table.warnings)

    # ------------------------------------------------------------------
    # Excel template export
    # ------------------------------------------------------------------

    def open_excel_template_export_dialog(self, checked: bool = False) -> None:
        host = self._host
        if not getattr(host, "event_table_data", None):
            QMessageBox.warning(host, "No Data", "No event data available to export.")
            return
        dialog = ExcelTemplateExportDialog(host, event_rows=host.event_table_data)
        dialog.exec_()

    # ------------------------------------------------------------------
    # GIF Animator / Sync-Clip exporter
    # ------------------------------------------------------------------

    def _update_gif_animator_state(self) -> None:
        """Enable GIF Animator menu action when sample has required data."""
        host = self._host
        if not host.current_sample:
            host.action_gif_animator.setEnabled(False)
            if hasattr(host, "sync_clip_action") and host.sync_clip_action is not None:
                host.sync_clip_action.setEnabled(False)
            prev_enabled = getattr(host, "_sync_clip_enabled", None)
            if prev_enabled is None or prev_enabled:
                log.info(
                    "Export Clip enabled=%s (trace=%s, tiff=%s, events=%s)",
                    False,
                    False,
                    False,
                    False,
                )
            host._sync_clip_enabled = False
            return

        sample = host.current_sample

        # Check for required data
        has_trace = sample.trace_data is not None or sample.dataset_id is not None
        has_snapshots = (
            isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0
        )
        has_events = sample.events_data is not None and len(sample.events_data) >= 2

        # Enable only if all requirements are met
        should_enable = has_trace and has_snapshots and has_events
        host.action_gif_animator.setEnabled(should_enable)
        if hasattr(host, "sync_clip_action") and host.sync_clip_action is not None:
            host.sync_clip_action.setEnabled(should_enable)
        prev_enabled = getattr(host, "_sync_clip_enabled", None)
        if prev_enabled is None or prev_enabled != should_enable:
            log.info(
                "Export Clip enabled=%s (trace=%s, tiff=%s, events=%s)",
                should_enable,
                has_trace,
                has_snapshots,
                has_events,
            )
        host._sync_clip_enabled = should_enable

    def show_gif_animator(self, checked: bool = False) -> None:
        """Launch GIF Animator window."""
        self.open_sync_clip_exporter(checked)

    def open_sync_clip_exporter(self, checked: bool = False) -> None:
        """Launch GIF Animator window.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        host = self._host
        log.info(
            "UI: Export Clip clicked (enabled=%s)",
            (
                getattr(host, "sync_clip_action", None).isEnabled()
                if isinstance(getattr(host, "sync_clip_action", None), QAction)
                else None
            ),
        )

        def _ensure_window_on_screen(window: QWidget) -> None:
            try:
                frame = window.frameGeometry()
            except Exception:
                return
            screens = QApplication.screens()
            if not screens:
                return
            if any(
                frame.intersects(screen.availableGeometry()) for screen in screens
            ):
                return
            parent_geom = host.geometry()
            frame.moveCenter(parent_geom.center())
            window.move(frame.topLeft())

        if not host.current_sample:
            QMessageBox.information(
                host,
                "Export Clip",
                "Load a trace and TIFF to export a synchronized clip.",
            )
            return

        # Validate requirements
        has_snapshots = (
            isinstance(host.current_sample.snapshots, np.ndarray)
            and host.current_sample.snapshots.size > 0
        )
        has_events = (
            host.current_sample.events_data is not None
            and len(host.current_sample.events_data) >= 2
        )

        if not has_snapshots or not has_events:
            QMessageBox.information(
                host,
                "Export Clip",
                "Load a trace and TIFF and define at least two events to export a synchronized clip.",
            )
            log.info(
                "Export Clip blocked (snapshots=%s, events=%s)",
                has_snapshots,
                has_events,
            )
            return

        # Get trace model (use existing or build)
        if host.trace_model is None:
            try:
                trace_model = host._get_trace_model_for_sample(host.current_sample)
            except Exception:
                trace_model = None
        else:
            trace_model = host.trace_model

        if trace_model is None:
            QMessageBox.information(
                host,
                "Export Clip",
                "Load a trace and TIFF to export a synchronized clip.",
            )
            log.info("Export Clip blocked (trace_model missing)")
            return

        try:
            existing = getattr(host, "_sync_clip_window", None)
            if existing is not None:
                if (
                    getattr(existing, "sample", None) is not host.current_sample
                    or getattr(existing, "trace_model", None) is not trace_model
                ):
                    with contextlib.suppress(Exception):
                        existing.close()
                    host._sync_clip_window = None

            if getattr(host, "_sync_clip_window", None) is None:
                from vasoanalyzer.ui.gif_animator import GifAnimatorWindow

                host._sync_clip_window = GifAnimatorWindow(
                    parent=host,
                    project_ctx=host.project_ctx,
                    sample=host.current_sample,
                    trace_model=trace_model,
                    events_df=host.current_sample.events_data,
                )
                host._sync_clip_window.destroyed.connect(
                    lambda *_: setattr(host, "_sync_clip_window", None)
                )

                from vasoanalyzer.ui.theme import get_theme_manager

                theme_manager = get_theme_manager()
                with contextlib.suppress(Exception):
                    theme_manager.themeChanged.connect(
                        host._sync_clip_window.apply_theme
                    )
                with contextlib.suppress(Exception):
                    host._sync_clip_window.apply_theme(
                        getattr(host, "_active_theme_mode", "light")
                    )

            window = host._sync_clip_window
            window.setWindowFlag(Qt.Window, True)
            window.show()
            if window.isMinimized():
                window.showNormal()
            _ensure_window_on_screen(window)
            window.raise_()
            window.activateWindow()

            n_frames = len(host.current_sample.snapshots) if has_snapshots else 0
            log.info(
                "Export Clip: context set (trace=%s, tiff=%s, frames=%s)",
                trace_model is not None,
                has_snapshots,
                n_frames,
            )
        except Exception:
            log.exception("Export Clip failed to open")
            QMessageBox.information(
                host,
                "Export Clip",
                "Unable to open the exporter window. Check logs for details.",
            )
            return

        log.info("GIF Animator launched")

    # ------------------------------------------------------------------
    # Project bundle / shareable / dataset package exports
    # ------------------------------------------------------------------

    def export_project_bundle_action(self, checked: bool = False):
        """Export project as .vasopack bundle.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        host = self._host
        if not host.current_project:
            QMessageBox.information(
                host, "No Project", "Open or create a project before exporting."
            )
            return

        if not host.current_project.path:
            host.save_project_file_as()
            if not host.current_project or not host.current_project.path:
                return

        default_stem = Path(host.current_project.path).with_suffix("").name
        default_path = (
            Path(host.current_project.path)
            .with_name(f"{default_stem}.vasopack")
            .as_posix()
        )
        path, _ = QFileDialog.getSaveFileName(
            host,
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

        host.current_project.ui_state = host.gather_ui_state()
        if host.current_sample:
            state = host.gather_sample_state()
            host.current_sample.ui_state = state
            host.project_state[id(host.current_sample)] = state

        try:
            export_project_bundle(host.current_project, path)
            host.statusBar().showMessage(f"\u2713 Bundle saved: {path}", 5000)
        except Exception as exc:
            QMessageBox.critical(
                host,
                "Export Failed",
                f"Could not export bundle:\n{exc}",
            )

    def export_shareable_project(self, checked: bool = False):
        """Export a DELETE-mode single-file copy of the current project.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        host = self._host

        if not host.current_project:
            QMessageBox.information(
                host, "No Project", "Open or create a project before exporting."
            )
            return

        if not host.current_project.path:
            host.save_project_file_as()
            if not host.current_project or not host.current_project.path:
                return

        # Ensure latest edits are flushed before exporting.
        host.save_project_file()
        if not host.current_project or not host.current_project.path:
            return

        stem = Path(host.current_project.path).with_suffix("").name
        default_path = (
            Path(host.current_project.path)
            .with_name(f"{stem}.shareable.vaso")
            .as_posix()
        )
        dest, _ = QFileDialog.getSaveFileName(
            host,
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
                host.current_project,
                destination=dest_path.as_posix(),
                ensure_saved=False,
            )
        except Exception as exc:
            QMessageBox.critical(
                host,
                "Export Failed",
                f"Could not export shareable project:\n{exc}",
            )
            return

        host.statusBar().showMessage(
            f"\u2713 Shareable project saved: {exported}", 5000
        )

    def export_dataset_package_action(self, checked: bool = False):
        """Export the currently selected dataset to a .vasods package."""
        host = self._host

        if not host.current_project:
            QMessageBox.information(
                host,
                "No Project",
                "Open or create a project before exporting a dataset.",
            )
            return

        if not host.current_sample:
            QMessageBox.information(
                host, "No Dataset Selected", "Select a dataset to export."
            )
            return

        if not host.current_project.path:
            host.save_project_file_as()
            if not host.current_project or not host.current_project.path:
                return

        dataset_id = getattr(host.current_sample, "dataset_id", None)
        if dataset_id is None:
            # Ensure dataset exists on disk
            host.save_project_file()
            dataset_id = getattr(host.current_sample, "dataset_id", None)

        if dataset_id is None:
            QMessageBox.warning(
                host,
                "Export Blocked",
                "Save the project once before exporting this dataset.",
            )
            return

        sample_name = host.current_sample.name or "Dataset"
        default_path = (
            Path(host.current_project.path)
            .with_name(f"{sample_name}.vasods")
            .as_posix()
        )
        dest, _ = QFileDialog.getSaveFileName(
            host,
            "Export Dataset Package",
            default_path,
            "Dataset Packages (*.vasods)",
        )
        if not dest:
            return

        dest_path = Path(dest).expanduser()
        if dest_path.suffix.lower() != ".vasods":
            dest_path = dest_path.with_suffix(".vasods")
        dest_path = dest_path.resolve(strict=False)

        try:
            export_dataset_package(host.current_project.path, dataset_id, dest_path)
        except DatasetPackageValidationError as exc:
            QMessageBox.warning(
                host, "Export Failed", f"Dataset export failed:\n{exc}"
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                host, "Export Failed", f"Could not export dataset:\n{exc}"
            )
            return

        host.statusBar().showMessage(
            f"\u2713 Dataset exported: {dest_path}", 5000
        )
