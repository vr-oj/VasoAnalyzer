# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""SampleManager -- sample lifecycle logic extracted from VasoAnalyzerApp."""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from PyQt6.QtCore import QByteArray, QMimeData, QObject, QRunnable, QSettings, QTimer, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QTreeWidgetItem,
)

from collections.abc import Mapping
from vasoanalyzer.core.project import Attachment, Experiment, SampleN
from vasoanalyzer.core.project_context import ProjectContext
from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.io.events import find_matching_event_file, load_events
from vasoanalyzer.io.traces import load_trace
from vasoanalyzer.services.cache_service import DataCache, cache_dir_for_project
from vasoanalyzer.storage.dataset_package import (
    DatasetPackageValidationError,
    export_dataset_package,
    import_dataset_package,
)
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:
    from vasoanalyzer.services.types import ProjectRepository
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)


class SampleManager(QObject):
    """Manages sample lifecycle: loading, activation, state gather/apply."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

    def _ensure_data_cache(self, hint_path: str | None = None) -> DataCache:
        """Return the active DataCache, creating it when necessary."""
        h = self._host

        if h.current_project and getattr(h.current_project, "path", None):
            base_hint = h.current_project.path
        elif hint_path:
            try:
                base_hint = Path(hint_path).expanduser().resolve(strict=False).parent.as_posix()
            except Exception:
                base_hint = Path(hint_path).expanduser().parent.as_posix()
        else:
            base_hint = h._cache_root_hint

        cache_root = cache_dir_for_project(base_hint)
        cache_root = cache_root.expanduser().resolve(strict=False)

        if h.data_cache is None or h.data_cache.root != cache_root:
            h.data_cache = DataCache(cache_root)
            h.data_cache.mirror_sources = h._mirror_sources_enabled
        h._cache_root_hint = base_hint
        return h.data_cache

    def _update_sample_link_metadata(self, sample: SampleN, kind: str, path_obj: Path) -> None:
        h = self._host
        path_attr = f"{kind}_path"
        hint_attr = f"{kind}_hint"
        relative_attr = f"{kind}_relative"
        signature_attr = f"{kind}_signature"

        path_str = path_obj.expanduser().resolve(strict=False).as_posix()
        setattr(sample, path_attr, path_str)
        setattr(sample, hint_attr, path_str)

        signature = h._compute_path_signature(path_obj)
        if signature:
            setattr(sample, signature_attr, signature)

        base_dir = h._project_base_dir()
        if base_dir:
            try:
                rel = os.path.relpath(path_str, os.fspath(base_dir))
            except Exception:
                rel = path_obj.name
        else:
            rel = path_obj.name
        setattr(sample, relative_attr, os.path.normpath(rel))

    def _resolve_sample_link(self, sample: SampleN, kind: str) -> str | None:
        h = self._host
        path_attr = f"{kind}_path"
        hint_attr = f"{kind}_hint"
        relative_attr = f"{kind}_relative"

        # If the dataset is embedded (dataset_id present) we should not probe external files.
        if getattr(sample, "dataset_id", None) is not None:
            return getattr(sample, path_attr, None)

        current_path = getattr(sample, path_attr, None)
        if current_path and Path(current_path).exists():
            return current_path

        candidates: list[Path] = []
        base_dir = h._project_base_dir()
        relative = getattr(sample, relative_attr, None)
        if relative and base_dir:
            candidates.append((base_dir / Path(relative)).resolve(strict=False))

        hint = getattr(sample, hint_attr, None)
        if hint:
            candidates.append(Path(hint).expanduser().resolve(strict=False))

        if current_path:
            candidates.append(Path(current_path).expanduser().resolve(strict=False))

        for candidate in candidates:
            if candidate.exists():
                h._update_sample_link_metadata(sample, kind, candidate)
                h._clear_missing_asset(sample, kind)
                return candidate.as_posix()

        return current_path

    def import_dataset_from_project_action(self, checked: bool = False):
        """Import dataset(s) from another project without leaving the current window."""
        h = self._host

        if not h.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before importing."
            )
            return
        if not h.current_project.path:
            h.save_project_file_as()
            if not h.current_project or not h.current_project.path:
                return

        settings = QSettings("TykockiLab", "VasoAnalyzer")
        dest_experiments = [
            (exp.name, getattr(exp, "experiment_id", None))
            for exp in h.current_project.experiments
        ] or [("Default", None)]
        initial_preserve = settings.value(
            "import_from_project_preserve_experiments", False, type=bool
        )
        initial_dest_id = settings.value(
            "import_from_project_last_dest_experiment_id", None, type=str
        )
        from vasoanalyzer.ui.dialogs.source_project_browser import SourceProjectBrowserDialog, build_import_plan
        dialog = SourceProjectBrowserDialog(
            h,
            current_project_path=h.current_project.path,
            current_experiments=dest_experiments,
            initial_preserve=initial_preserve,
            initial_dest_experiment_id=initial_dest_id,
        )
        source_path, dataset_entries, dest_exp, preserve, dest_exp_id = dialog.exec_with_source()
        if not source_path or not dataset_entries:
            return

        # Ensure destination is saved before mutation
        h.save_project_file()

        imported_ids: list[int] = []
        dest_expanded = set()
        plan = build_import_plan(dataset_entries, dest_exp, preserve)
        failures: list[tuple[str, str, str]] = []
        root_temp_dir = tempfile.mkdtemp(prefix="vasods_import_")
        try:
            for entry, target_exp in plan:
                pkg_path = Path(root_temp_dir) / f"dataset_{entry.dataset_id}.vasods"
                try:
                    export_dataset_package(source_path, entry.dataset_id, pkg_path)
                    new_id = import_dataset_package(
                        h.current_project.path,
                        pkg_path,
                        target_experiment_name=target_exp,
                    )
                    imported_ids.append(int(new_id))
                    if target_exp:
                        dest_expanded.add(target_exp)
                except Exception as exc:
                    failures.append((entry.dataset_name, entry.experiment_name, str(exc)))
        except DatasetPackageValidationError as exc:
            QMessageBox.warning(h, "Import Failed", f"Dataset package is invalid:\n{exc}")
            return
        except Exception as exc:
            QMessageBox.critical(h, "Import Failed", f"Could not import dataset:\n{exc}")
            return
        finally:
            try:
                shutil.rmtree(root_temp_dir, ignore_errors=True)
            except Exception:
                log.debug("Failed to remove temp import dir %s", root_temp_dir, exc_info=True)

        if not imported_ids:
            if failures:
                details = "\n".join(f"- {name} ({exp}): {err}" for name, exp, err in failures)
                QMessageBox.critical(
                    h,
                    "Import Failed",
                    f"No datasets were imported.\n\nErrors:\n{details}",
                )
            return

        # Reload project to reflect new datasets and select the first imported one
        h.open_project_file(h.current_project.path)
        if dest_expanded:
            for name in dest_expanded:
                h._expand_experiment_in_tree(name)
        h._select_dataset_ids(imported_ids)
        h.statusBar().showMessage(
            f"\u2713 Imported {len(imported_ids)} dataset(s) from {Path(source_path).name}", 5000
        )
        # Persist user choices
        settings.setValue("import_from_project_preserve_experiments", bool(preserve))
        if dest_exp_id:
            settings.setValue("import_from_project_last_dest_experiment_id", dest_exp_id)
        elif dest_exp and not preserve:
            # Fall back to name if no id available
            settings.setValue("import_from_project_last_dest_experiment_id", dest_exp)

        if failures:
            detail = "\n".join(f"- {name} ({exp}): {err}" for name, exp, err in failures)
            msg = QMessageBox(self)
            msg.setWindowTitle("Import Partial")
            msg.setText(
                f"Imported {len(imported_ids)} dataset(s) from {Path(source_path).name}.\n"
                f"Failed {len(failures)} dataset(s)."
            )
            msg.setInformativeText("You can copy the details for support.")
            copy_btn = msg.addButton("Copy details", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Ok)
            msg.setDetailedText(detail)
            msg.exec()
            if msg.clickedButton() is copy_btn:
                QApplication.clipboard().setText(detail)

    def import_dataset_package_action(self, checked: bool = False):
        """Import a .vasods package into the current project."""
        h = self._host

        if not h.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before importing."
            )
            return

        if not h.current_project.path:
            h.save_project_file_as()
            if not h.current_project or not h.current_project.path:
                return

        pkg_path, _ = QFileDialog.getOpenFileName(
            h,
            "Import Dataset Package",
            "",
            "Dataset Packages (*.vasods)",
        )
        if not pkg_path:
            return

        default_exp = None
        if getattr(h, "current_experiment", None):
            default_exp = h.current_experiment.name
        elif getattr(h.current_project, "experiments", None):
            default_exp = h.current_project.experiments[0].name

        target_exp = h._prompt_experiment_for_import(default_exp)
        if not target_exp:
            return

        # Flush current edits before mutating the project file
        h.save_project_file()

        try:
            import_dataset_package(
                h.current_project.path,
                pkg_path,
                target_experiment_name=target_exp,
            )
        except DatasetPackageValidationError as exc:
            QMessageBox.warning(h, "Import Failed", f"Dataset package is invalid:\n{exc}")
            return
        except Exception as exc:
            QMessageBox.critical(h, "Import Failed", f"Could not import dataset:\n{exc}")
            return

        # Reload project to reflect the new dataset
        h.open_project_file(h.current_project.path)
        h.statusBar().showMessage(f"\u2713 Dataset imported into '{target_exp}'", 5000)

    def _gather_selected_samples_for_copy(self) -> list[SampleN]:
        h = self._host
        samples = h._selected_samples_from_tree()
        if not samples and getattr(h, "current_sample", None):
            samples = [h.current_sample]
        return [s for s in samples if getattr(s, "dataset_id", None) is not None]

    def copy_selected_datasets(self) -> None:
        """Copy selected datasets to a temp .vasods set and place paths on clipboard."""
        h = self._host

        if not h.current_project or not h.current_project.path:
            QMessageBox.information(
                self, "No Project", "Open or save a project before copying datasets."
            )
            return

        samples = h._gather_selected_samples_for_copy()
        if not samples:
            QMessageBox.information(h, "No Dataset", "Select a dataset to copy.")
            return

        # Ensure datasets are saved before exporting
        h.save_project_file()

        settings = QSettings("TykockiLab", "VasoAnalyzer")
        preserve = settings.value("import_from_project_preserve_experiments", True, type=bool)

        root_temp_dir = tempfile.mkdtemp(prefix="vasods_clip_")
        payload_entries = []
        try:
            for sample in samples:
                ds_id = getattr(sample, "dataset_id", None)
                if ds_id is None:
                    continue
                pkg_path = Path(root_temp_dir) / f"dataset_{ds_id}.vasods"
                export_dataset_package(h.current_project.path, ds_id, pkg_path)
                payload_entries.append(
                    {
                        "path": pkg_path.as_posix(),
                        "dataset_id": ds_id,
                        "dataset_name": sample.name or f"Dataset {ds_id}",
                        "experiment": h._experiment_name_for_sample(sample),
                    }
                )
        except Exception:
            shutil.rmtree(root_temp_dir, ignore_errors=True)
            raise

        if not payload_entries:
            shutil.rmtree(root_temp_dir, ignore_errors=True)
            QMessageBox.warning(h, "Copy Failed", "No datasets were copied.")
            return

        payload = {
            "version": 1,
            "preserve": bool(preserve),
            "source_project": h.current_project.path,
            "temp_dir": root_temp_dir,
            "entries": payload_entries,
        }
        mime_data_json = _json.dumps(payload)
        mime = QMimeData()
        mime.setData(_CLIP_MIME, mime_data_json.encode("utf-8"))
        mime.setText(mime_data_json)
        QApplication.clipboard().setMimeData(mime)
        h.statusBar().showMessage(
            f"\u2713 Copied {len(payload_entries)} dataset(s) to clipboard", 4000
        )

    def paste_datasets(self) -> None:
        """Paste datasets from clipboard into the current project."""
        h = self._host

        if not h.current_project or not h.current_project.path:
            QMessageBox.information(
                self, "No Project", "Open or save a project before pasting datasets."
            )
            return

        mime = QApplication.clipboard().mimeData()
        raw = None
        if mime and mime.hasFormat(_CLIP_MIME):
            raw = bytes(mime.data(_CLIP_MIME)).decode("utf-8", errors="ignore")
        elif mime and mime.hasText():
            raw = mime.text()
        if not raw:
            QMessageBox.information(h, "Nothing to Paste", "Clipboard has no datasets.")
            return
        try:
            payload = _json.loads(raw)
        except Exception:
            QMessageBox.warning(h, "Paste Failed", "Clipboard data is not valid.")
            return

        entries = payload.get("entries") or []
        if not isinstance(entries, list) or not entries:
            QMessageBox.information(h, "Nothing to Paste", "Clipboard has no datasets.")
            return

        preserve = bool(payload.get("preserve", True))
        temp_dir = payload.get("temp_dir")
        imported_ids: list[int] = []
        dest_expanded = set()
        failures: list[tuple[str, str]] = []

        dest_exp = getattr(h, "current_experiment", None)
        dest_name = dest_exp.name if dest_exp else None

        h.save_project_file()

        try:
            for entry in entries:
                pkg_path = entry.get("path")
                if not pkg_path or not Path(pkg_path).exists():
                    failures.append((entry.get("dataset_name") or "Dataset", "Package missing"))
                    continue
                source_exp = entry.get("experiment")
                target_exp = source_exp if preserve else dest_name
                if not target_exp:
                    target_exp = source_exp or dest_name or "Imported"
                try:
                    new_id = import_dataset_package(
                        h.current_project.path,
                        pkg_path,
                        target_experiment_name=target_exp,
                    )
                    imported_ids.append(int(new_id))
                    if target_exp:
                        dest_expanded.add(target_exp)
                except Exception as exc:
                    failures.append((entry.get("dataset_name") or "Dataset", str(exc)))
        finally:
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    log.debug("Failed to remove clipboard temp dir %s", temp_dir, exc_info=True)

        if not imported_ids and failures:
            detail = "\n".join(f"- {name}: {err}" for name, err in failures)
            QMessageBox.critical(
                h,
                "Paste Failed",
                f"No datasets were pasted.\n\nErrors:\n{detail}",
            )
            return

        if imported_ids:
            h.open_project_file(h.current_project.path)
            if dest_expanded:
                for name in dest_expanded:
                    h._expand_experiment_in_tree(name)
            h._select_dataset_ids(imported_ids)
            h.statusBar().showMessage(
                f"\u2713 Pasted {len(imported_ids)} dataset(s) from clipboard", 4000
            )
        if failures:
            detail = "\n".join(f"- {name}: {err}" for name, err in failures)
            msg = QMessageBox(self)
            msg.setWindowTitle("Paste Partial")
            msg.setText(f"Pasted {len(imported_ids)} dataset(s); {len(failures)} failed.")
            msg.setInformativeText("You can copy the details for support.")
            copy_btn = msg.addButton("Copy details", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Ok)
            msg.setDetailedText(detail)
            msg.exec()
            if msg.clickedButton() is copy_btn:
                QApplication.clipboard().setText(detail)

    def _persist_sample_ui_state(self, sample: SampleN, state: dict) -> None:
        """Persist UI state for a specific sample without relying on current selection."""
        h = self._host

        if sample is None:
            return
        sample.ui_state = state
        h.project_state[id(sample)] = state

    def _get_sample_data_quality(self, sample: SampleN) -> str | None:
        """Read the stored data-quality flag from a sample's UI state."""
        h = self._host
        state = getattr(sample, "ui_state", None)
        if isinstance(state, dict):
            value = state.get("data_quality")
            if value in {"good", "questionable", "bad"}:
                return value
        return None

    @staticmethod
    def _iter_sample_items(exp_item):
        """Yield all sample QTreeWidgetItems under an experiment item, including inside subfolders."""
        for k in range(exp_item.childCount()):
            child = exp_item.child(k)
            if child is None:
                continue
            obj = child.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(obj, SampleN):
                yield child
            else:
                # Subfolder item — search its children
                for m in range(child.childCount()):
                    sample_child = child.child(m)
                    if sample_child is not None and isinstance(
                        sample_child.data(0, Qt.ItemDataRole.UserRole), SampleN
                    ):
                        yield sample_child

    def _update_tree_icons_for_samples(self, samples: Sequence[SampleN]) -> None:
        h = self._host
        if not h.project_tree:
            return
        for sample in samples:
            found = False
            for i in range(h.project_tree.topLevelItemCount()):
                project_item = h.project_tree.topLevelItem(i)
                if project_item is None:
                    continue
                for j in range(project_item.childCount()):
                    exp_item = project_item.child(j)
                    if exp_item is None:
                        continue
                    for sample_item in self._iter_sample_items(exp_item):
                        if sample_item.data(0, Qt.ItemDataRole.UserRole) is sample:
                            quality = h._get_sample_data_quality(sample)
                            sample_item.setIcon(0, h._data_quality_icon(quality))
                            sample_item.setToolTip(
                                0,
                                f"Data quality: {h._data_quality_label(quality)}",
                            )
                            found = True
                            break
                    if found:
                        break
                if found:
                    break

    def _set_samples_data_quality(self, samples: Sequence[SampleN], quality: str | None) -> None:
        h = self._host
        if not samples:
            return
        changed = False
        for sample in samples:
            if not isinstance(sample.ui_state, dict):
                sample.ui_state = {}
            previous = sample.ui_state.get("data_quality")
            if quality is None:
                if sample.ui_state.pop("data_quality", None) is not None:
                    changed = True
            elif previous != quality:
                sample.ui_state["data_quality"] = quality
                changed = True
            h.project_state[id(sample)] = sample.ui_state
        if changed:
            h._update_tree_icons_for_samples(samples)
            h.mark_session_dirty(reason="sample data quality updated")

    def _select_dataset_ids(self, dataset_ids: Sequence[int]) -> None:
        h = self._host
        if not dataset_ids or not h.current_project:
            return
        target_set = {int(d) for d in dataset_ids if d is not None}
        for exp in h.current_project.experiments:
            for sample in exp.samples:
                if getattr(sample, "dataset_id", None) in target_set:
                    h.load_sample_into_view(sample)
                    h._select_tree_item_for_sample(sample)
                    return

    def _select_tree_item_for_sample(self, sample: SampleN | None) -> None:
        h = self._host
        if sample is None or not h.project_tree:
            return

        tree = h.project_tree
        for i in range(tree.topLevelItemCount()):
            project_item = tree.topLevelItem(i)
            if project_item is None:
                continue
            for j in range(project_item.childCount()):
                exp_item = project_item.child(j)
                if exp_item is None:
                    continue
                for sample_item in self._iter_sample_items(exp_item):
                    if sample_item.data(0, Qt.ItemDataRole.UserRole) is sample:
                        tree.blockSignals(True)
                        tree.setCurrentItem(sample_item)
                        tree.blockSignals(False)
                        tree.scrollToItem(sample_item)
                        return

    def _selected_samples_from_tree(self) -> list[SampleN]:
        h = self._host
        if not h.project_tree:
            return []
        samples: list[SampleN] = []
        for item in h.project_tree.selectedItems() or []:
            obj = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(obj, SampleN) and obj not in samples:
                samples.append(obj)
        return samples

    def _experiment_name_for_sample(self, sample: SampleN) -> str | None:
        h = self._host
        if not h.current_project:
            return None
        for exp in h.current_project.experiments:
            if sample in exp.samples:
                return exp.name
        return None

    def _open_first_sample_if_none_active(self) -> None:
        h = self._host
        if h.current_project is None:
            return
        if getattr(h, "current_sample", None) is not None:
            return

        first_sample: SampleN | None = None
        for exp in h.current_project.experiments:
            if not exp.samples:
                continue
            candidates = sorted(exp.samples, key=lambda s: (s.name or "").lower())
            if candidates:
                first_sample = candidates[0]
                break

        if first_sample is None:
            return

        h.load_sample_into_view(first_sample)
        h._select_tree_item_for_sample(first_sample)

    def _activate_sample(
        self,
        sample: SampleN,
        experiment: Experiment | None,
        *,
        ensure_loaded: bool = False,
    ) -> None:
        h = self._host
        log.info(
            "UI: sample selected -> %s (dataset_id=%s) trace_data=%s events_data=%s",
            getattr(sample, "name", "<unknown>"),
            getattr(sample, "dataset_id", None),
            isinstance(getattr(sample, "trace_data", None), pd.DataFrame),
            isinstance(getattr(sample, "events_data", None), pd.DataFrame),
        )
        if h.current_sample and h.current_sample is not sample:
            state = h.gather_sample_state()
            if h._autosave_in_progress:
                log.debug(
                    "Autosave in progress; deferring persistence of sample state id=%s",
                    getattr(h.current_sample, "id", None),
                )
                h._cached_sample_state = state
            else:
                h._persist_sample_ui_state(h.current_sample, state)
        need_load = ensure_loaded or (h.current_sample is not sample)
        h.current_sample = sample
        h.current_experiment = experiment
        if need_load or h.trace_model is None:
            h.load_sample_into_view(sample)

    def on_sample_notes_changed(self, text: str) -> None:
        h = self._host
        if not isinstance(h.current_sample, SampleN):
            return
        notes = text.strip() or None
        if h.current_sample.notes != notes:
            h.current_sample.notes = notes
            if h.metadata_dock:
                h.metadata_dock.sample_form.set_metadata(h.current_sample)
            h.mark_session_dirty()

    def on_sample_add_attachment(self) -> None:
        h = self._host
        if not isinstance(h.current_sample, SampleN):
            return
        paths, _ = QFileDialog.getOpenFileNames(
            h,
            "Add Sample Attachment",
            "",
            "All Files (*.*)",
        )
        added = False
        for path in paths:
            if not path:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            attachment = Attachment(name=name, filename=os.path.basename(path))
            attachment.source_path = path
            h.current_sample.attachments.append(attachment)
            added = True
        if added:
            if h.metadata_dock:
                h.metadata_dock.refresh_attachments(h.current_sample.attachments)
            h.mark_session_dirty()

    def on_sample_remove_attachment(self, index: int) -> None:
        h = self._host
        if not isinstance(h.current_sample, SampleN):
            return
        attachments = h.current_sample.attachments
        if 0 <= index < len(attachments):
            attachments.pop(index)
            if h.metadata_dock:
                h.metadata_dock.refresh_attachments(attachments)
            h.mark_session_dirty()

    def on_sample_open_attachment(self, index: int) -> None:
        h = self._host
        if not isinstance(h.current_sample, SampleN):
            return
        h._open_attachment_for(h.current_sample.attachments, index)

    def _queue_sample_load_until_context(self, sample: SampleN) -> bool:
        """Defer sample loading until a ProjectContext is available."""
        h = self._host
        if sample.dataset_id is None:
            return False
        h._pending_sample_loads[sample.dataset_id] = sample
        log.debug(
            "Deferring load for '%s' (dataset_id=%s) until ProjectContext is ready",
            sample.name,
            sample.dataset_id,
        )
        return True

    def _flush_pending_sample_loads(self) -> None:
        """Retry any deferred sample loads once the ProjectContext is ready."""
        h = self._host
        if not h._pending_sample_loads or h._processing_pending_sample_loads:
            return
        h._processing_pending_sample_loads = True
        try:
            pending_samples = list(h._pending_sample_loads.values())
            h._pending_sample_loads.clear()
            for sample in pending_samples:
                try:
                    h.load_sample_into_view(sample)
                except Exception:
                    log.warning(
                        "Deferred load failed for sample '%s'",
                        sample.name,
                        exc_info=True,
                    )
        finally:
            h._processing_pending_sample_loads = False

    def _log_sample_data_summary(
        self,
        sample: SampleN,
        trace_df: pd.DataFrame | None = None,
        events_df: pd.DataFrame | None = None,
    ) -> None:
        """Emit a concise INFO log summarising the trace/events payload being shown."""
        h = self._host

        if getattr(h, "_sample_summary_logged", False):
            return

        sample_name = getattr(sample, "name", getattr(sample, "label", "N/A"))
        dataset_id = getattr(sample, "dataset_id", None)

        trace_source = (
            trace_df if isinstance(trace_df, pd.DataFrame) else getattr(sample, "trace_data", None)
        )
        if not isinstance(trace_source, pd.DataFrame):
            return

        events_source = events_df
        if events_source is None:
            events_source = getattr(sample, "events_data", None)

        if isinstance(events_source, pd.DataFrame):
            event_rows = len(events_source.index)
            first_event = (
                events_source.iloc[0]["Event"]
                if not events_source.empty and "Event" in events_source.columns
                else None
            )
            log.info(
                "DEBUG load: sample '%s' events_data rows=%s first_label=%r",
                sample_name,
                event_rows,
                first_event,
            )
        elif events_source is None:
            event_rows = 0
        else:
            try:
                event_rows = len(events_source)
            except TypeError:
                event_rows = 0
            log.info(
                "DEBUG load: sample '%s' events_source type=%s rows=%s",
                sample_name,
                type(events_source),
                event_rows,
            )

        h._sample_summary_logged = True

        log.info(
            "UI: Loading sample %s (dataset_id=%s) trace_rows=%d trace_columns=%s events_rows=%d",
            sample_name,
            dataset_id,
            len(trace_source.index),
            list(trace_source.columns),
            event_rows,
        )

    def load_sample_into_view(self, sample: SampleN):
        """Load a sample's trace and events into the main view."""
        h = self._host
        t0 = time.perf_counter()
        try:
            log.debug("Loading sample %s", sample.name)

            if h.current_sample and h.current_sample is not sample:
                state = h.gather_sample_state()
                h.current_sample.ui_state = state
                h.project_state[id(h.current_sample)] = state
                # Persist change log before switching away
                h.current_sample.change_log = h._change_log.serialize()

            h.current_sample = sample
            h._sample_summary_logged = False
            h._last_track_layout_sample_id = None
            h._select_tree_item_for_sample(sample)

            token = object()
            h._current_sample_token = token

            # Validate cache - check if cached data belongs to current dataset_id
            # If a dataset was just loaded and the cache id never set, adopt the current dataset_id
            if (
                sample.trace_data is not None
                and getattr(sample, "_trace_cache_dataset_id", None) is None
            ):
                sample._trace_cache_dataset_id = sample.dataset_id
            if (
                sample.events_data is not None
                and getattr(sample, "_events_cache_dataset_id", None) is None
            ):
                sample._events_cache_dataset_id = sample.dataset_id

            trace_cache_valid = (
                sample.trace_data is not None
                and getattr(sample, "_trace_cache_dataset_id", None) == sample.dataset_id
            )
            events_cache_valid = (
                sample.events_data is not None
                and getattr(sample, "_events_cache_dataset_id", None) == sample.dataset_id
            )

            # Invalidate stale cache
            if sample.trace_data is not None and not trace_cache_valid:
                log.warning(
                    "CACHE_INVALID: trace cache for '%s' invalid (dataset_id=%s, cached_id=%s), clearing",
                    sample.name,
                    sample.dataset_id,
                    getattr(sample, "_trace_cache_dataset_id", None),
                )
                sample.trace_data = None
                sample._trace_cache_dataset_id = None

            if sample.events_data is not None and not events_cache_valid:
                log.warning(
                    "CACHE_INVALID: events cache for '%s' invalid (dataset_id=%s, cached_id=%s), clearing",
                    sample.name,
                    sample.dataset_id,
                    getattr(sample, "_events_cache_dataset_id", None),
                )
                sample.events_data = None
                sample._events_cache_dataset_id = None

            needs_trace = sample.trace_data is None and sample.dataset_id is not None
            needs_events = sample.events_data is None and sample.dataset_id is not None
            needs_results = (
                sample.analysis_results is None
                and sample.dataset_id is not None
                and (sample.analysis_result_keys is None or bool(sample.analysis_result_keys))
            )

            # Prevent duplicate loads for the same dataset
            if (
                sample.dataset_id is not None
                and sample.dataset_id in h._loading_dataset_ids
                and (needs_trace or needs_events or needs_results)
            ):
                log.info(
                    "DATASET_LOAD_SKIP: dataset_id=%s already loading, skipping duplicate load request",
                    sample.dataset_id,
                )
                return

            ctx = getattr(h, "project_ctx", None)
            log.debug("load_sample_into_view: ctx type=%s ctx=%s", type(ctx), ctx)

            project_path = (
                ctx.path
                if isinstance(ctx, ProjectContext)
                else getattr(h.current_project, "path", None)
            )
            repo = ctx.repo if isinstance(ctx, ProjectContext) else None

            # Extract staging DB path for thread-safe access
            staging_db_path: str | None = None
            if repo is not None:
                try:
                    # Try to get staging path from the store's handle
                    store = getattr(repo, "_store", None)
                    if store is not None:
                        handle = getattr(store, "handle", None)
                        if handle is not None:
                            staging_path = getattr(handle, "staging_path", None)
                            if staging_path is not None:
                                staging_db_path = str(staging_path)
                                log.debug(
                                    "Extracted staging DB path for thread-safe access: %s",
                                    staging_db_path,
                                )
                except Exception as e:
                    log.warning(f"Could not extract staging DB path: {e}")
            # Fallback: extract staging DB path directly from project._store when ctx is None.
            # This is the common case during an import session — project_ctx is not set but
            # _save_project_bundle already opened and attached a staging DB to the project.
            if staging_db_path is None and h.current_project is not None:
                try:
                    project_store = getattr(h.current_project, "_store", None)
                    if project_store is not None:
                        handle = getattr(project_store, "handle", None)
                        if handle is not None:
                            staging_path = getattr(handle, "staging_path", None)
                            if staging_path is not None:
                                staging_db_path = str(staging_path)
                                log.debug(
                                    "Extracted staging DB path from project._store: %s",
                                    staging_db_path,
                                )
                except Exception as e:
                    log.debug("Could not extract staging DB path from project._store: %s", e)

            log.debug(
                "load_sample_into_view: repo=%s project_path=%s needs_events=%s dataset_id=%s",
                repo,
                project_path,
                needs_events,
                sample.dataset_id,
            )

            # CRITICAL: If repo is None but we have a project context, something is wrong
            if repo is None and ctx is not None:
                log.warning("Repo is None but project context exists: %s", ctx)
            if repo is None and project_path and sample.dataset_id is not None:
                log.debug(
                    "No repo from project_ctx for '%s'; background job will open project context",
                    sample.name,
                )
            if repo is None and staging_db_path is None and project_path and needs_events:
                log.warning(
                    "Background job will create a NEW project context which means a NEW staging database; "
                    "events may not be found."
                )

            load_async = bool(
                (repo or project_path) and (needs_trace or needs_events or needs_results)
            )
            force_sync = os.environ.get("VA_FORCE_SYNC_LOAD", "0") == "1"
            if force_sync:
                if load_async:
                    log.info(
                        "VA_FORCE_SYNC_LOAD=1: forcing synchronous dataset load for sample '%s'",
                        sample.name,
                    )
                load_async = False

            log.info(
                "DATASET_LOAD: sample='%s' dataset_id=%s cached=(trace=%s, events=%s) "
                "needs=(trace=%s, events=%s, results=%s) load_async=%s",
                sample.name,
                sample.dataset_id,
                sample.trace_data is not None,
                sample.events_data is not None,
                needs_trace,
                needs_events,
                needs_results,
                load_async,
            )

            h._start_sample_load_progress(sample.name)
            h._prepare_sample_view(sample)

            if load_async:
                # Mark this dataset as loading
                if sample.dataset_id is not None:
                    h._loading_dataset_ids.add(sample.dataset_id)
                    log.debug(
                        "DATASET_LOAD_START: dataset_id=%s added to in-flight set",
                        sample.dataset_id,
                    )

                h.statusBar().showMessage(f"Loading {sample.name}…", 2000)
                h._begin_sample_load_job(
                    sample,
                    token,
                    repo,
                    project_path,
                    load_trace=needs_trace,
                    load_events=needs_events,
                    load_results=needs_results,
                    staging_db_path=staging_db_path,
                )
                return

            h._log_sample_data_summary(sample)
            h._render_sample(sample)
            h._finish_sample_load_progress()

        finally:
            log.debug("load_sample_into_view completed in %.3f s", time.perf_counter() - t0)

    def _prepare_sample_view(self, sample: SampleN) -> None:
        h = self._host
        log.debug(
            "DATASET_PREPARE: sample='%s' clearing canvas + event table for load",
            sample.name,
        )
        h.show_analysis_workspace()
        h._reset_event_table_for_loading()
        # Clear the plot/canvas to avoid stale visuals while loading.
        h._clear_slider_markers()
        h.trace_data = None
        if hasattr(h, "plot_host"):
            h.plot_host.clear()
            initial_specs = [
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            ]
            h.plot_host.ensure_channels(initial_specs)
            inner_track = h.plot_host.track("inner")
            h.ax = inner_track.ax if inner_track else None
            h._bind_primary_axis_callbacks()
        h.ax2 = None
        h.outer_line = None
        h.trace_model = None
        h._refresh_trace_navigation_data()
        if h.zoom_dock:
            h.zoom_dock.set_trace_model(None)
        if h.scope_dock:
            h.scope_dock.set_trace_model(None)
        h.canvas.draw_idle()

        # Clear snapshot UI
        h.snapshot_frames = []
        h.frames_metadata = []
        h._set_playback_state(False)
        h.toggle_snapshot_viewer(False, source="data")
        if h.snapshot_widget is not None:
            h.snapshot_widget.hide()
            h.snapshot_widget.clear()
        h._reset_snapshot_speed()
        h.metadata_details_label.setText("No metadata available.")
        h._clear_event_highlight()
        h._clear_pins()
        h._layout_log_ready = False
        h._last_tiff_page_time_warning_key = None
        h._update_plot_empty_state()

    def _begin_sample_load_job(
        self,
        sample: SampleN,
        token: object,
        repo: ProjectRepository | None,
        project_path: str | None,
        *,
        load_trace: bool,
        load_events: bool,
        load_results: bool,
        staging_db_path: str | None = None,
    ) -> None:
        h = self._host
        from vasoanalyzer.ui.main_window import _SampleLoadJob
        job = _SampleLoadJob(
            repo,
            project_path,
            sample,
            token,
            load_trace=load_trace,
            load_events=load_events,
            load_results=load_results,
            staging_db_path=staging_db_path,
        )
        job.signals.finished.connect(h._on_sample_load_finished)
        job.signals.error.connect(h._on_sample_load_error)
        job.signals.progressChanged.connect(h._update_sample_load_progress)
        h._thread_pool.start(job)

    def _on_sample_load_finished(
        self,
        token: object,
        sample: SampleN,
        trace_df: pd.DataFrame | None,
        events_df: pd.DataFrame | None,
        analysis_results: dict[str, Any] | None,
    ) -> None:
        h = self._host
        # Remove from in-flight tracking
        if sample.dataset_id is not None:
            h._loading_dataset_ids.discard(sample.dataset_id)
            log.debug(
                "DATASET_LOAD_FINISH: dataset_id=%s removed from in-flight set",
                sample.dataset_id,
            )

        if token != h._current_sample_token or sample is not h.current_sample:
            log.warning(
                "DATASET_LOAD_DISCARDED: sample='%s' dataset_id=%s reason=%s current_sample='%s'",
                sample.name,
                sample.dataset_id,
                ("token_mismatch" if token != h._current_sample_token else "sample_changed"),
                getattr(h.current_sample, "name", None),
            )
            # Clear any partial cache from this discarded load to prevent corruption
            # Only clear if this sample is NOT the current sample (we switched away)
            if sample is not h.current_sample:
                if trace_df is not None and sample.trace_data is None:
                    log.debug("DATASET_LOAD_DISCARDED: clearing partial trace cache")
                if events_df is not None and sample.events_data is None:
                    log.debug("DATASET_LOAD_DISCARDED: clearing partial events cache")
                # Note: We don't set sample.trace_data/events_data here because
                # the data might be useful if user switches back. Cache validation
                # will handle correctness on next load.
            return
        t0 = time.perf_counter()
        if trace_df is not None:
            sample.trace_data = trace_df
            sample._trace_cache_dataset_id = sample.dataset_id
        if events_df is not None:
            sample.events_data = events_df
            sample._events_cache_dataset_id = sample.dataset_id
        if analysis_results:
            sample.analysis_results = analysis_results
            sample.analysis_result_keys = list(analysis_results.keys())
        elif sample.analysis_result_keys is None:
            sample.analysis_result_keys = []

        trace_data = trace_df if trace_df is not None else sample.trace_data
        events_data = events_df if events_df is not None else sample.events_data

        if trace_data is None:
            log.warning(
                "Sample load finished without trace data for %s (dataset_id=%s)",
                getattr(sample, "name", "<unknown>"),
                getattr(sample, "dataset_id", None),
            )
            h._finish_sample_load_progress()
            return
        if events_data is None:
            log.info(
                "Sample load finished without events for %s (dataset_id=%s)",
                getattr(sample, "name", "<unknown>"),
                getattr(sample, "dataset_id", None),
            )

        h._log_sample_data_summary(sample, trace_data, events_data)
        log.info(
            "UI: _on_sample_load_finished resolved data for %s (dataset_id=%s); calling _render_sample",
            getattr(sample, "name", "<unknown>"),
            getattr(sample, "dataset_id", None),
        )
        h.statusBar().showMessage(f"{sample.name} ready", 2000)
        h._render_sample(sample)
        h._finish_sample_load_progress()
        log.info(
            "Timing: sample '%s' render pipeline finished in %.2f ms",
            getattr(sample, "name", "<unknown>"),
            (time.perf_counter() - t0) * 1000,
        )

    def _on_sample_load_error(self, token: object, sample: SampleN, message: str) -> None:
        h = self._host
        # Remove from in-flight tracking
        if sample.dataset_id is not None:
            h._loading_dataset_ids.discard(sample.dataset_id)
            log.debug(
                "DATASET_LOAD_ERROR: dataset_id=%s removed from in-flight set",
                sample.dataset_id,
            )

        if token != h._current_sample_token or sample is not h.current_sample:
            return
        log.warning("Embedded data load failed for %s: %s", sample.name, message)
        h.statusBar().showMessage(
            f"Embedded data not available ({message})",
            6000,
        )
        h._render_sample(sample)
        h._finish_sample_load_progress()

    def _render_sample(self, sample: SampleN) -> None:
        h = self._host
        # Restore change log for this sample
        h._change_log.clear()
        saved_log = getattr(sample, "change_log", None)
        if isinstance(saved_log, list):
            h._change_log.load(saved_log)
        # Also import any existing edit_history entries not yet in the change log
        h._change_log.merge_edit_history(getattr(sample, "edit_history", None))

        # Prevent review prompts from firing during intermediate sample rendering steps.
        h._suppress_review_prompt = True
        try:
            log.info(
                "UI: _render_sample called for %s (dataset_id=%s)",
                getattr(sample, "name", "<unknown>"),
                getattr(sample, "dataset_id", None),
            )
            style = None
            if isinstance(sample.ui_state, dict):
                style = sample.ui_state.get("style_settings") or sample.ui_state.get("plot_style")
            from vasoanalyzer.ui.main_window import _StyleHolder
            from vasoanalyzer.ui.constants import DEFAULT_STYLE
            merged_style = {**DEFAULT_STYLE, **style} if style else DEFAULT_STYLE.copy()
            h._style_holder = _StyleHolder(merged_style.copy())
            h._style_manager.replace(merged_style)

            cache: DataCache | None = None
            try:
                trace_source = None
                if sample.trace_data is not None:
                    trace = sample.trace_data
                    # For embedded datasets, avoid touching external paths (may be on iCloud)
                    if getattr(sample, "dataset_id", None) is not None:
                        trace_source = sample.name
                    else:
                        trace_source = sample.trace_path or sample.name
                elif sample.trace_path and sample.dataset_id is None:
                    resolved_trace = h._resolve_sample_link(sample, "trace")
                    if not resolved_trace or not Path(resolved_trace).exists():
                        raise FileNotFoundError(str(sample.trace_path))
                    cache = h._ensure_data_cache(resolved_trace)
                    trace = load_trace(resolved_trace, cache=cache)
                    sample.trace_path = resolved_trace
                    h._clear_missing_asset(sample, "trace")
                    h.trace_file_path = resolved_trace
                    trace_source = resolved_trace
                else:
                    QMessageBox.warning(h, "No Trace", "Sample has no trace data.")
                    return
            except FileNotFoundError as exc:
                missing = getattr(exc, "filename", None) or sample.trace_path
                h._handle_missing_asset(sample, "trace", missing, str(exc))
                QMessageBox.warning(
                    h,
                    "Trace File Missing",
                    "The trace file could not be located. Use Relink Missing Files to update the link.",
                )
                return
            except Exception as error:
                QMessageBox.critical(h, "Trace Load Error", str(error))
                return

            h.sampling_rate_hz = h._compute_sampling_rate(trace)
            if trace_source:
                display_name = (
                    os.path.basename(trace_source)
                    if isinstance(trace_source, str)
                    else str(trace_source)
                )
                prefix = "Sample"
                tooltip = (
                    sample.name if getattr(sample, "dataset_id", None) is not None else trace_source
                )
                # Only probe filesystem when not embedded
                if (
                    isinstance(trace_source, str)
                    and getattr(sample, "dataset_id", None) is None
                    and os.path.exists(trace_source)
                ):
                    prefix = "Trace"
                    h.trace_file_path = trace_source
                else:
                    h.trace_file_path = None
                h._set_status_source(f"{prefix} · {display_name}", tooltip)
            else:
                h._set_status_source(f"Sample · {sample.name}", sample.name)
                h.trace_file_path = None
            h._reset_session_dirty()

            labels, times, frames, diam, od = [], [], [], [], []
            try:
                # If events are embedded in the repo but not materialised on the sample, fetch them now.
                if sample.events_data is None and sample.dataset_id is not None:
                    repo_ctx = getattr(h, "project_ctx", None)
                    repo = repo_ctx.repo if isinstance(repo_ctx, ProjectContext) else None
                    get_events = getattr(repo, "get_events", None)
                    if callable(get_events):
                        with contextlib.suppress(Exception):
                            sample.events_data = project_module._format_events_df(
                                get_events(sample.dataset_id)  # type: ignore[arg-type]
                            )

                if sample.events_data is not None:
                    labels, times, frames = load_events(sample.events_data)
                    h._clear_missing_asset(sample, "events")
                elif sample.events_path and sample.dataset_id is None:
                    resolved_events = h._resolve_sample_link(sample, "events")
                    if not resolved_events or not Path(resolved_events).exists():
                        raise FileNotFoundError(str(sample.events_path))
                    event_cache = cache or h._ensure_data_cache(resolved_events)
                    labels, times, frames = load_events(resolved_events, cache=event_cache)
                    sample.events_path = resolved_events
                    h._clear_missing_asset(sample, "events")
                else:
                    labels, times, frames = [], [], []

                diam = []
                if times:
                    arr_t = trace["Time (s)"].values
                    arr_d = trace["Inner Diameter"].values
                    arr_od = (
                        trace["Outer Diameter"].values
                        if "Outer Diameter" in trace.columns
                        else None
                    )
                    # Extract stored OD/ID from the events DataFrame as fallback
                    # when the trace has NaN at the event time (e.g. legacy files
                    # with sparse inner-diameter measurements).
                    stored_id: list[float | None] = []
                    stored_od: list[float | None] = []
                    ev_df = sample.events_data if sample.events_data is not None else None
                    if ev_df is not None and isinstance(ev_df, pd.DataFrame):
                        for col_name, out_list in (
                            ("id_diam", stored_id),
                            ("od", stored_od),
                        ):
                            if col_name in ev_df.columns:
                                for val in ev_df[col_name]:
                                    try:
                                        fv = float(val)
                                        out_list.append(fv if np.isfinite(fv) else None)
                                    except (TypeError, ValueError):
                                        out_list.append(None)
                            else:
                                out_list.extend([None] * len(times))
                    else:
                        stored_id = [None] * len(times)
                        stored_od = [None] * len(times)

                    for i, t in enumerate(times):
                        idx_evt = int(np.argmin(np.abs(arr_t - t)))
                        id_val = float(arr_d[idx_evt])
                        if not np.isfinite(id_val) and i < len(stored_id) and stored_id[i] is not None:
                            id_val = stored_id[i]
                        diam.append(id_val)
                        if arr_od is not None:
                            od_val = float(arr_od[idx_evt])
                            if not np.isfinite(od_val) and i < len(stored_od) and stored_od[i] is not None:
                                od_val = stored_od[i]
                            od.append(od_val)
                        elif i < len(stored_od) and stored_od[i] is not None:
                            od.append(stored_od[i])
            except FileNotFoundError as exc:
                missing = getattr(exc, "filename", None) or sample.events_path
                h._handle_missing_asset(sample, "events", missing, str(exc))
            except Exception as error:
                QMessageBox.warning(h, "Event Load Error", str(error))

            # Batch all plot updates to avoid multiple redraws during sample rendering
            plot_host = getattr(h, "plot_host", None)
            # Suspending/resuming updates can block in some render backends (e.g., pyqtgraph).
            # Only do it for backends that support fast suspend, and measure the resume cost.
            suspend_updates = False
            if plot_host is not None:
                try:
                    backend = plot_host.get_render_backend()
                    suspend_updates = backend != "pyqtgraph"
                except Exception:
                    suspend_updates = False
            if suspend_updates:
                plot_host.suspend_updates()

            try:
                h.trace_data = h._prepare_trace_dataframe(trace)
                h._update_trace_sync_state()
                h._layout_log_ready = True
                h._reset_channel_view_defaults()
                h.xlim_full = None
                h.ylim_full = None
                from vasoanalyzer.ui.main_window import DEFAULT_LEGEND_SETTINGS, _copy_legend_settings
                h.legend_settings = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)
                h.compute_frame_trace_indices()
                t_ev = time.perf_counter()
                h.load_project_events(
                    labels,
                    times,
                    frames,
                    diam,
                    od,
                    refresh_plot=False,
                    auto_export=True,
                )
                log.info(
                    "Timing: load_project_events for '%s' took %.2f ms",
                    getattr(sample, "name", "<unknown>"),
                    (time.perf_counter() - t_ev) * 1000,
                )
                t_plot = time.perf_counter()
                h.update_plot()
                h._apply_event_label_mode()
                h._sync_event_controls()
                h._update_trace_controls_state()
                log.info(
                    "Timing: update_plot for '%s' took %.2f ms",
                    getattr(sample, "name", "<unknown>"),
                    (time.perf_counter() - t_plot) * 1000,
                )
                state_to_apply = h.project_state.get(
                    id(sample), getattr(sample, "ui_state", None)
                )
                t_state = time.perf_counter()
                h.apply_sample_state(state_to_apply)
                log.info(
                    "Timing: apply_sample_state for '%s' took %.2f ms",
                    getattr(sample, "name", "<unknown>"),
                    (time.perf_counter() - t_state) * 1000,
                )
                if (
                    h._plot_host_is_pyqtgraph()
                    and plot_host is not None
                    and hasattr(plot_host, "log_data_and_view_ranges")
                ):
                    plot_host.log_data_and_view_ranges("after_sample_render")

                t_after = time.perf_counter()
                if h.current_project is not None:
                    if not isinstance(h.current_project.ui_state, dict):
                        h.current_project.ui_state = {}
                    if h.current_experiment:
                        h.current_project.ui_state["last_experiment"] = (
                            h.current_experiment.name
                        )
                    h.current_project.ui_state["last_sample"] = sample.name
                    if getattr(sample, "dataset_id", None) is not None:
                        h.current_project.ui_state["last_dataset_id"] = int(sample.dataset_id)

                h._sync_autoscale_y_action_from_host()
                h._update_snapshot_viewer_state(sample)
                h._update_gif_animator_state()
                h._update_home_resume_button()
                h._update_metadata_panel(sample)
                log.info(
                    "Timing: post-plot UI updates for '%s' took %.2f ms",
                    getattr(sample, "name", "<unknown>"),
                    (time.perf_counter() - t_after) * 1000,
                )
            finally:
                # Always resume updates even if there was an error
                if suspend_updates and plot_host is not None:
                    t_resume = time.perf_counter()
                    plot_host.resume_updates()
                    log.info(
                        "Timing: plot_host.resume_updates for '%s' took %.2f ms",
                        getattr(sample, "name", "<unknown>"),
                        (time.perf_counter() - t_resume) * 1000,
                    )
        finally:
            h._suppress_review_prompt = False
            h._update_review_notice_visibility()
            h._update_plot_empty_state()
            h._set_event_table_enabled(h.trace_data is not None)

    def add_sample(self, experiment):
        h = self._host
        nname, ok = QInputDialog.getText(h, "Sample Name", "Name:")
        if ok and nname:
            experiment.samples.append(SampleN(name=nname))
            h.refresh_project_tree()

    def add_sample_to_current_experiment(self, checked: bool = False):
        """Add a sample to the current experiment.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        h = self._host
        if not h.current_experiment:
            QMessageBox.warning(
                h,
                "No Experiment Selected",
                "Please select an experiment first.",
            )
            return
        h.add_sample(h.current_experiment)

    def load_data_into_sample(self, sample: SampleN):
        h = self._host
        log.debug("Loading data into sample: %s", sample.name)
        trace_path, _ = QFileDialog.getOpenFileName(
            self, "Select Trace File", "", "CSV Files (*.csv)"
        )
        if not trace_path:
            return

        log.debug("Reading trace file: %s", Path(trace_path).name)
        try:
            df = h.load_trace_and_event_files(trace_path)
            log.debug("Loaded %d trace samples for manual update", len(df))
        except Exception as e:
            log.error(f"  ✗ Failed to load trace data: {e}")
            return

        trace_obj = Path(trace_path).expanduser().resolve(strict=False)
        h._update_sample_link_metadata(sample, "trace", trace_obj)
        sample.trace_data = df
        event_path = find_matching_event_file(trace_path)
        if event_path and os.path.exists(event_path):
            event_obj = Path(event_path).expanduser().resolve(strict=False)
            h._update_sample_link_metadata(sample, "events", event_obj)
            log.debug("Found matching event file: %s", Path(event_path).name)

        h.refresh_project_tree()

        log.debug("Sample '%s' updated successfully", sample.name)

        if h.current_project and h.current_project.path:
            save_project(h.current_project, h.current_project.path)

    def _sample_values_at_time(
        self, time_sec: float
    ) -> tuple[float | None, float | None, float | None, float | None]:
        """Sample ID/OD/Avg P/Set P at a given time using current trace data."""
        h = self._host
        if h.trace_data is None or "Time (s)" not in h.trace_data.columns:
            return (None, None, None, None)
        try:
            target_time = float(time_sec)
        except Exception:
            return (None, None, None, None)

        times = h.trace_data["Time (s)"].to_numpy()
        if times.size == 0:
            return (None, None, None, None)

        idx = int(np.argmin(np.abs(times - target_time)))

        def _sample_column(label: str | None) -> float | None:
            if not label or label not in h.trace_data.columns:
                return None
            try:
                value = h.trace_data[label].iloc[idx]
            except Exception:
                return None
            if pd.isna(value):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        id_val = _sample_column("Inner Diameter")
        od_val = _sample_column("Outer Diameter")
        avg_val = _sample_column(h._trace_label_for("p_avg"))
        set_val = _sample_column(h._trace_label_for("p2"))
        return (id_val, od_val, avg_val, set_val)

    def _start_sample_load_progress(self, sample_name: str) -> None:
        """Begin status-bar progress indication for sample load."""
        h = self._host
        if h._progress_bar is None:
            return
        h._progress_bar.setRange(0, 0)
        h._progress_bar.setVisible(True)
        h._progress_bar.setFormat(f"Loading {sample_name}…")
        if h.statusBar() is not None:
            h.statusBar().showMessage(f"Loading {sample_name}…")

    def _update_sample_load_progress(self, percent: int, label: str) -> None:
        """Update status-bar sample load progress."""
        h = self._host
        if h._progress_bar is None:
            return
        if h._progress_bar.minimum() == 0 and h._progress_bar.maximum() == 0:
            h._progress_bar.setRange(0, 100)
        h._progress_bar.setValue(max(0, min(percent, 100)))
        h._progress_bar.setFormat(f"{label}… %p%")

    def _finish_sample_load_progress(self) -> None:
        """Hide status-bar sample load progress."""
        h = self._host
        if h._progress_bar is None:
            return
        h._progress_bar.setVisible(False)
        if h.statusBar() is not None:
            h.statusBar().clearMessage()

    def _get_trace_model_for_sample(self, sample: SampleN | None) -> TraceModel:
        """Return a TraceModel for the current trace_data, using a per-dataset cache."""
        h = self._host

        if h.trace_data is None:
            raise ValueError("trace_data is not available")

        dsid = getattr(sample, "dataset_id", None) if sample is not None else None
        if dsid is not None:
            cached = h._trace_model_cache.get(dsid)
            if cached is not None:
                return cached

        model = TraceModel.from_dataframe(h.trace_data)
        if dsid is not None:
            h._trace_model_cache[dsid] = model
        return model

    def sample_inner_diameter(self, time_value: float) -> float | None:
        h = self._host
        if h.trace_data is None:
            return None
        if "Time (s)" not in h.trace_data.columns:
            return None
        if "Inner Diameter" not in h.trace_data.columns:
            return None

        times = h.trace_data["Time (s)"].to_numpy()
        values = h.trace_data["Inner Diameter"].to_numpy()
        if times.size == 0:
            return None
        try:
            return float(np.interp(time_value, times, values))
        except Exception:
            return None

    def gather_ui_state(self):
        h = self._host
        # Close review dock before capturing state so it doesn't reopen on restart
        review_dock = getattr(h, "review_dock", None)
        if review_dock is not None and review_dock.isVisible():
            review_dock.hide()

        state = {
            "geometry": h.saveGeometry().data().hex(),
            "window_state": h.saveState().data().hex(),
        }
        h._sync_track_visibility_from_host()
        state.update(h._collect_plot_view_state())
        layout_state = h._serialize_plot_layout()
        if layout_state:
            state["plot_layout"] = layout_state
        if h.current_experiment:
            state["last_experiment"] = h.current_experiment.name
            log.debug(
                "SAVE_STATE: Saving last_experiment='%s'",
                h.current_experiment.name,
            )
        if h.current_sample:
            state["last_sample"] = h.current_sample.name
            if getattr(h.current_sample, "dataset_id", None) is not None:
                state["last_dataset_id"] = int(h.current_sample.dataset_id)
            log.debug(
                "SAVE_STATE: Saving last_sample='%s'",
                h.current_sample.name,
            )
        if hasattr(h, "data_splitter") and h.data_splitter is not None:
            with contextlib.suppress(Exception):
                state["splitter_state"] = bytes(h.data_splitter.saveState()).hex()
        # Save trace visibility state
        if hasattr(h, "id_toggle_act") and h.id_toggle_act is not None:
            state["inner_trace_visible"] = h.id_toggle_act.isChecked()
        if hasattr(h, "od_toggle_act") and h.od_toggle_act is not None:
            state["outer_trace_visible"] = h.od_toggle_act.isChecked()
        host = getattr(h, "plot_host", None)
        if hasattr(h, "avg_pressure_toggle_act") and h.avg_pressure_toggle_act is not None:
            state["avg_pressure_visible"] = h.avg_pressure_toggle_act.isChecked()
        elif host is not None:
            with contextlib.suppress(Exception):
                state["avg_pressure_visible"] = host.is_channel_visible("avg_pressure")
        if hasattr(h, "set_pressure_toggle_act") and h.set_pressure_toggle_act is not None:
            state["set_pressure_visible"] = h.set_pressure_toggle_act.isChecked()
        elif host is not None:
            with contextlib.suppress(Exception):
                state["set_pressure_visible"] = host.is_channel_visible("set_pressure")
        # Capture experiment expand/collapse states from the tree at save-time.
        # Must be here because gather_ui_state() completely overwrites project.ui_state,
        # discarding whatever _on_tree_experiment_expand_changed had stored in memory.
        if getattr(h, "project_tree", None):
            experiment_expanded: dict[str, bool] = {}
            for _i in range(h.project_tree.topLevelItemCount()):
                _root = h.project_tree.topLevelItem(_i)
                for _j in range(_root.childCount()):
                    _exp_item = _root.child(_j)
                    _obj = _exp_item.data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(_obj, Experiment):
                        experiment_expanded[_obj.name] = _exp_item.isExpanded()
            if experiment_expanded:
                state["experiment_expanded"] = experiment_expanded
        return state

    def _invalidate_sample_state_cache(self):
        """Invalidate the cached sample state to force recomputation on next gather."""
        h = self._host
        h._sample_state_dirty = True
        h._cached_sample_state = None
        # Also invalidate snapshot style since it's part of the state
        h._snapshot_style_dirty = True
        h._cached_snapshot_style = None

    def gather_sample_state(self):
        """Gather current sample state (cached for performance)."""
        h = self._host
        # Return cached version if still valid
        if not h._sample_state_dirty and h._cached_sample_state is not None:
            h._sync_sample_events_dataframe(h._cached_sample_state)
            return h._cached_sample_state

        h._normalize_event_label_meta(len(h.event_table_data))
        # Start from existing UI state so we don't drop custom keys (e.g., data_quality)
        base_state: dict[str, Any] = {}
        if h.current_sample and isinstance(h.current_sample.ui_state, dict):
            base_state = copy.deepcopy(h.current_sample.ui_state)
        # preserve any previously saved style_settings
        prev = base_state.get("style_settings", {}) or {}
        x_axis = h._x_axis_for_style()
        focused_row = None
        event_table = getattr(h, "event_table", None)
        event_table_action = getattr(h, "event_table_action", None)
        if event_table is not None:
            with contextlib.suppress(Exception):
                idx = event_table.currentIndex()
                if idx.isValid():
                    focused_row = int(idx.row())
        state = {**base_state}
        state.update(
            {
                "table_fontsize": h.event_table.font().pointSize(),
                "event_table_data": list(h.event_table_data),
                "event_label_meta": copy.deepcopy(h.event_label_meta),
                "event_table_path": (
                    str(h._event_table_path) if h._event_table_path else None
                ),
                "event_table_visible": (
                    bool(event_table_action.isChecked())
                    if event_table_action is not None
                    else (bool(event_table.isVisible()) if event_table is not None else None)
                ),
                "pins": [
                    coords
                    for marker, _ in h.pinned_points
                    if (coords := h._pin_coords(marker))
                ],
                "plot_style": h.get_current_plot_style(),
                "grid_visible": h.grid_visible,
                "inner_trace_visible": (
                    h.id_toggle_act.isChecked() if h.id_toggle_act is not None else True
                ),
                "outer_trace_visible": (
                    h.od_toggle_act.isChecked() if h.od_toggle_act is not None else False
                ),
                "avg_pressure_visible": (
                    h.avg_pressure_toggle_act.isChecked()
                    if h.avg_pressure_toggle_act is not None
                    else (
                        getattr(h.plot_host, "is_channel_visible", lambda *_: True)(
                            "avg_pressure"
                        )
                        if hasattr(h, "plot_host")
                        else True
                    )
                ),
                "set_pressure_visible": (
                    h.set_pressure_toggle_act.isChecked()
                    if h.set_pressure_toggle_act is not None
                    else (
                        getattr(h.plot_host, "is_channel_visible", lambda *_: False)(
                            "set_pressure"
                        )
                        if hasattr(h, "plot_host")
                        else False  # Default: hide Set Pressure track
                    )
                ),
                "axis_settings": {
                    "x": {"label": x_axis.get_xlabel() if x_axis else ""},
                    "y": {"label": h.ax.get_ylabel()},
                },
                "time_cursor": {
                    "t": float(h._time_cursor_time)
                    if h._time_cursor_time is not None
                    else None,
                    "visible": bool(h._time_cursor_visible),
                },
                "focused_event_row": focused_row,
                "event_lines_visible": bool(h._event_lines_visible),
                "event_label_mode": str(h._event_label_mode or "indices"),
                "snapshot_viewer_visible": (
                    bool(h.snapshot_viewer_action.isChecked())
                    if getattr(h, "snapshot_viewer_action", None) is not None
                    else bool(h._snapshot_view_visible())
                ),
            }
        )
        if isinstance(h.legend_settings, dict):
            state["legend_settings"] = copy.deepcopy(h.legend_settings)
        # Always record whatever is in ui_state["style_settings"], even if empty
        state["style_settings"] = prev
        if h.ax2 is not None:
            state["axis_settings"]["y_outer"] = {"label": h.ax2.get_ylabel()}
        h._sync_track_visibility_from_host()
        layout_state = h._serialize_plot_layout()
        if layout_state:
            state["plot_layout"] = layout_state
        state.update(h._collect_plot_view_state())

        h._sync_sample_events_dataframe(state)
        # Cache the result
        h._cached_sample_state = state
        h._sample_state_dirty = False
        return state

    def apply_ui_state(self, state):
        h = self._host
        if not state:
            return
        geom = state.get("geometry")
        if geom:
            h.restoreGeometry(bytes.fromhex(geom))
        wstate = state.get("window_state")
        if wstate:
            h.restoreState(bytes.fromhex(wstate))
        is_pg = h._plot_host_is_pyqtgraph()
        if "axis_xlim" in state:
            h._apply_time_window(state["axis_xlim"])
        if "axis_ylim" in state:
            if is_pg:
                inner_track = h.plot_host.track("inner") if hasattr(h, "plot_host") else None
                if inner_track is not None:
                    inner_track.set_ylim(*state["axis_ylim"])
            elif h.ax is not None:
                h.ax.set_ylim(state["axis_ylim"])
        splitter_state = state.get("splitter_state")
        if splitter_state and hasattr(h, "data_splitter") and h.data_splitter is not None:
            with contextlib.suppress(Exception):
                h.data_splitter.restoreState(bytes.fromhex(splitter_state))
        plot_layout = state.get("plot_layout")
        if plot_layout:
            h._pending_plot_layout = plot_layout
        pyqtgraph_tracks = state.get("pyqtgraph_track_state")
        if pyqtgraph_tracks:
            h._apply_pyqtgraph_track_state(pyqtgraph_tracks)
        if is_pg and "event_text_labels_on_trace" in state:
            plot_host = getattr(h, "plot_host", None)
            if plot_host is not None:
                plot_host.set_event_labels_visible(bool(state["event_text_labels_on_trace"]))
        # Restore trace visibility state
        if (
            "inner_trace_visible" in state
            and hasattr(h, "id_toggle_act")
            and h.id_toggle_act is not None
        ):
            h.id_toggle_act.blockSignals(True)
            h.id_toggle_act.setChecked(state["inner_trace_visible"])
            h.id_toggle_act.blockSignals(False)
        if (
            "outer_trace_visible" in state
            and hasattr(h, "od_toggle_act")
            and h.od_toggle_act is not None
        ):
            h.od_toggle_act.blockSignals(True)
            h.od_toggle_act.setChecked(state["outer_trace_visible"])
            h.od_toggle_act.blockSignals(False)
        if (
            "avg_pressure_visible" in state
            and hasattr(h, "avg_pressure_toggle_act")
            and h.avg_pressure_toggle_act is not None
        ):
            h.avg_pressure_toggle_act.blockSignals(True)
            h.avg_pressure_toggle_act.setChecked(state["avg_pressure_visible"])
            h.avg_pressure_toggle_act.blockSignals(False)
            h._apply_channel_toggle("avg_pressure", state["avg_pressure_visible"])
        if (
            "set_pressure_visible" in state
            and hasattr(h, "set_pressure_toggle_act")
            and h.set_pressure_toggle_act is not None
        ):
            h.set_pressure_toggle_act.blockSignals(True)
            h.set_pressure_toggle_act.setChecked(state["set_pressure_visible"])
            h.set_pressure_toggle_act.blockSignals(False)
            h._apply_channel_toggle("set_pressure", state["set_pressure_visible"])
        # Apply the visibility changes after restoring state
        if "inner_trace_visible" in state or "outer_trace_visible" in state:
            inner_on = state.get("inner_trace_visible", True)
            outer_on = state.get("outer_trace_visible", False)
            h._rebuild_channel_layout(inner_on, outer_on, redraw=False)
        h.canvas.draw_idle()

    def _sample_is_embedded(self, sample: SampleN | None) -> bool:
        h = self._host
        if sample is None or getattr(sample, "dataset_id", None) is None:
            return False
        has_external = bool(
            getattr(sample, "trace_path", None)
            or getattr(sample, "events_path", None)
            or getattr(sample, "trace_relative", None)
            or getattr(sample, "events_relative", None)
        )
        return not has_external

    def apply_sample_state(self, state):
        h = self._host
        t0 = time.perf_counter()
        h._restoring_sample_state = True
        try:
            if not state:
                return
            sample = getattr(h, "current_sample", None)
            is_embedded = h._sample_is_embedded(sample)
            h._event_table_path = state.get("event_table_path")
            h._pending_snapshot_visibility = None

            # ── minimal restore for embedded datasets to avoid pyqtgraph stalls
            if is_embedded:
                # Restore inner/outer toggles
                for key, act_name, channel in (
                    ("inner_trace_visible", "id_toggle_act", "inner"),
                    ("outer_trace_visible", "od_toggle_act", "outer"),
                ):
                    if key in state and hasattr(h, act_name):
                        act = getattr(h, act_name)
                        if act is not None:
                            act.blockSignals(True)
                            act.setChecked(bool(state[key]))
                            act.blockSignals(False)
                            h._apply_channel_toggle(channel, bool(state[key]))
                # Restore channel toggles for pressure tracks
                for key, act_name, channel in (
                    ("avg_pressure_visible", "avg_pressure_toggle_act", "avg_pressure"),
                    ("set_pressure_visible", "set_pressure_toggle_act", "set_pressure"),
                ):
                    if key in state and hasattr(h, act_name):
                        act = getattr(h, act_name)
                        if act is not None:
                            act.blockSignals(True)
                            act.setChecked(bool(state[key]))
                            act.blockSignals(False)
                            h._apply_channel_toggle(channel, bool(state[key]))
                if "axis_xlim" in state:
                    h._apply_time_window(state["axis_xlim"])
                h.canvas.draw_idle()
                log.info(
                    "Timing: apply_sample_state (embedded fast path) total=%.2f ms",
                    (time.perf_counter() - t0) * 1000,
                )
                return

            layout = state.get("plot_layout")
            # Applying stored plot layouts on embedded datasets is expensive on pyqtgraph;
            # skip restoring layout/track state on load when we have embedded data.
            if layout and not is_embedded:
                h._pending_plot_layout = layout
            pyqtgraph_tracks = state.get("pyqtgraph_track_state")
            if pyqtgraph_tracks and not is_embedded:
                h._apply_pyqtgraph_track_state(pyqtgraph_tracks)
            t_events = time.perf_counter()
            event_rows = state.get("event_table_data")
            # Only restore saved event rows when the state actually contains data; otherwise
            # keep the freshly populated events from storage.
            if isinstance(event_rows, list) and event_rows:
                h.event_table_data = event_rows
                meta_payload = state.get("event_label_meta")

                # CRITICAL FIX (Bug #3): Improved deserialization with fallback
                if isinstance(meta_payload, list):
                    try:
                        h.event_label_meta = [
                            (
                                h._with_default_review_state(item)
                                if isinstance(item, Mapping)
                                else h._with_default_review_state(None)
                            )
                            for item in meta_payload
                        ]
                    except Exception as e:
                        # If deserialization fails, try to preserve existing states
                        log.error(
                            f"Failed to deserialize event_label_meta for sample "
                            f"{getattr(sample, 'name', 'unknown')}: {e}. "
                            f"Attempting fallback to preserve review states."
                        )
                        # Fallback: try to get review states from events DataFrame
                        h._fallback_restore_review_states(len(event_rows))
                else:
                    # meta_payload is None or not a list - try fallback
                    if meta_payload is not None:
                        log.warning(
                            f"event_label_meta is not a list for sample "
                            f"{getattr(sample, 'name', 'unknown')} "
                            f"(got {type(meta_payload).__name__}). Using fallback."
                        )
                    h._fallback_restore_review_states(len(event_rows))

                h.populate_table()
                h._update_review_notice_visibility()
            event_table_visible = state.get("event_table_visible")
            if event_table_visible is not None:
                h._set_event_table_visible(
                    bool(event_table_visible),
                    source="restore",
                )
            event_lines_visible = state.get("event_lines_visible")
            if event_lines_visible is not None:
                h._event_lines_visible = bool(event_lines_visible)
                plot_host = getattr(h, "plot_host", None)
                if plot_host is not None:
                    plot_host.set_event_lines_visible(h._event_lines_visible)
                else:
                    h._toggle_event_lines_legacy(h._event_lines_visible)
            event_label_mode = state.get("event_label_mode")
            if event_label_mode:
                h._set_event_label_mode(str(event_label_mode))
            h._sync_event_controls()
            snapshot_visible = state.get("snapshot_viewer_visible")
            if snapshot_visible is not None:
                h._pending_snapshot_visibility = bool(snapshot_visible)
            cursor_payload = state.get("time_cursor")
            if isinstance(cursor_payload, Mapping):
                cursor_time = cursor_payload.get("t")
                cursor_visible = cursor_payload.get("visible", True)
            else:
                cursor_time = None
                cursor_visible = True
            try:
                cursor_time = float(cursor_time) if cursor_time is not None else None
            except (TypeError, ValueError):
                cursor_time = None
            h._time_cursor_visible = bool(cursor_visible)
            focused_row = state.get("focused_event_row")
            applied_focus = False
            if focused_row is not None and h.event_table_data:
                try:
                    row = int(focused_row)
                except (TypeError, ValueError):
                    row = None
                if row is not None:
                    row = max(0, min(row, len(h.event_table_data) - 1))
                    event_table = getattr(h, "event_table", None)
                    if event_table is not None:
                        event_table.blockSignals(True)
                    try:
                        h._focus_event_row(row, source="restore")
                        applied_focus = True
                    finally:
                        if event_table is not None:
                            event_table.blockSignals(False)
            if not applied_focus:
                h._time_cursor_time = cursor_time
                plot_host = getattr(h, "plot_host", None)
                if plot_host is not None and hasattr(plot_host, "set_time_cursor"):
                    with contextlib.suppress(Exception):
                        if cursor_time is None:
                            plot_host.set_time_cursor(None, visible=False)
                        else:
                            plot_host.set_time_cursor(
                                cursor_time,
                                visible=h._time_cursor_visible,
                            )
            t_axes = time.perf_counter()
            is_pg = h._plot_host_is_pyqtgraph()
            if "axis_xlim" in state:
                h._apply_time_window(state["axis_xlim"])
            if "axis_ylim" in state:
                if is_pg:
                    inner_track = (
                        h.plot_host.track("inner") if hasattr(h, "plot_host") else None
                    )
                    if inner_track is not None:
                        inner_track.set_ylim(*state["axis_ylim"])
                elif h.ax is not None:
                    h.ax.set_ylim(state["axis_ylim"])
            if "axis_outer_ylim" in state:
                if is_pg:
                    outer_track = (
                        h.plot_host.track("outer") if hasattr(h, "plot_host") else None
                    )
                    if outer_track is not None:
                        outer_track.set_ylim(*state["axis_outer_ylim"])
                elif h.ax2 is not None:
                    h.ax2.set_ylim(state["axis_outer_ylim"])
            t_font = time.perf_counter()
            if "table_fontsize" in state:
                font = h.event_table.font()
                font.setPointSize(state["table_fontsize"])
                h.event_table.setFont(font)
            t_pins = time.perf_counter()
            if "pins" in state:
                for marker, label in h.pinned_points:
                    h._safe_remove_artist(marker)
                    h._safe_remove_artist(label)
                h.pinned_points.clear()
                if is_pg:
                    inner_track = (
                        h.plot_host.track("inner") if hasattr(h, "plot_host") else None
                    )
                    if inner_track is not None:
                        inner_track.clear_pins()
                        for x, y in state.get("pins", []):
                            label_text = f"{x:.2f} s\n{y:.1f} µm"
                            marker, text_item = inner_track.add_pin(x, y, label_text)
                            h.pinned_points.append((marker, text_item))
                else:
                    for x, y in state.get("pins", []):
                        marker = h.ax.plot(x, y, "ro", markersize=6)[0]
                        label = h.ax.annotate(
                            f"{x:.2f} s\n{y:.1f} µm",
                            xy=(x, y),
                            xytext=(6, 6),
                            textcoords="offset points",
                            bbox=dict(boxstyle="round,pad=0.3", fc="#F8F8F8", ec="#CCCCCC", lw=1),
                            fontsize=8,
                        )
                        h.pinned_points.append((marker, label))

            if "grid_visible" in state:
                h.grid_visible = state["grid_visible"]
                if is_pg:
                    for track in getattr(h.plot_host, "tracks", lambda: [])():
                        track.set_grid_visible(h.grid_visible)
                elif h.ax is not None:
                    h.ax.grid(h.grid_visible)
                    if h.grid_visible:
                        h.ax.grid(color=CURRENT_THEME["grid_color"])
            if (
                ("inner_trace_visible" in state or "outer_trace_visible" in state)
                and hasattr(h, "id_toggle_act")
                and h.id_toggle_act is not None
            ):
                inner_on = state.get(
                    "inner_trace_visible",
                    h.id_toggle_act.isChecked(),
                )
                outer_on = state.get(
                    "outer_trace_visible",
                    (h.od_toggle_act.isChecked() if h.od_toggle_act is not None else False),
                )
                outer_supported = h._outer_channel_available()
                h._apply_toggle_state(inner_on, outer_on, outer_supported=outer_supported)
                h._rebuild_channel_layout(inner_on, outer_on, redraw=False)
            # Apply avg/set visibility after layout so ancillary tracks stay in sync
            if (
                "avg_pressure_visible" in state
                and hasattr(h, "avg_pressure_toggle_act")
                and h.avg_pressure_toggle_act is not None
            ):
                h.avg_pressure_toggle_act.blockSignals(True)
                h.avg_pressure_toggle_act.setChecked(state["avg_pressure_visible"])
                h.avg_pressure_toggle_act.blockSignals(False)
                h._apply_channel_toggle("avg_pressure", state["avg_pressure_visible"])
            if (
                "set_pressure_visible" in state
                and hasattr(h, "set_pressure_toggle_act")
                and h.set_pressure_toggle_act is not None
            ):
                h.set_pressure_toggle_act.blockSignals(True)
                h.set_pressure_toggle_act.setChecked(state["set_pressure_visible"])
                h.set_pressure_toggle_act.blockSignals(False)
                h._apply_channel_toggle("set_pressure", state["set_pressure_visible"])

            legend_settings = state.get("legend_settings")
            if isinstance(legend_settings, dict):
                h.apply_legend_settings(legend_settings, mark_dirty=False)

            # ─── restore style settings ─────────────────────────────────────
            style = state.get("style_settings") or state.get("plot_style")
            if style:
                h.apply_plot_style(style, persist=False)
                if (
                    state.get("plot_style")
                    and hasattr(h, "plot_style_dialog")
                    and h.plot_style_dialog
                ):
                    with contextlib.suppress(AttributeError):
                        h.plot_style_dialog.set_style(state["plot_style"])
            if "axis_settings" in state:
                x_label = state["axis_settings"].get("x", {}).get("label")
                y_label = state["axis_settings"].get("y", {}).get("label")
                y_outer_label = state["axis_settings"].get("y_outer", {}).get("label")
                if x_label:
                    h._set_shared_xlabel(x_label)
                if y_label:
                    h.ax.set_ylabel(y_label)
                if y_outer_label and h.ax2 is not None:
                    h.ax2.set_ylabel(y_outer_label)
            h._apply_time_mode(h._time_mode, persist=False)
            t_layout = time.perf_counter()
            h._apply_pending_plot_layout()
            t_pyqtgraph = time.perf_counter()
            h._apply_pending_pyqtgraph_track_state()
            t_draw = time.perf_counter()
            h.canvas.draw_idle()
            t_end = time.perf_counter()
            log.info(
                "Timing: apply_sample_state breakdown (ms) events=%.2f axes=%.2f font=%.2f pins=%.2f layout=%.2f pyqtgraph=%.2f draw=%.2f total=%.2f",
                (t_events - t0) * 1000,
                (t_font - t_events) * 1000,
                (t_pins - t_font) * 1000,
                (t_layout - t_pins) * 1000,
                (t_pyqtgraph - t_layout) * 1000,
                (t_draw - t_pyqtgraph) * 1000,
                (t_end - t_draw) * 1000,
                (t_end - t0) * 1000,
            )

        finally:
            h._restoring_sample_state = False
            log.debug("apply_sample_state completed in %.3f s", time.perf_counter() - t0)
