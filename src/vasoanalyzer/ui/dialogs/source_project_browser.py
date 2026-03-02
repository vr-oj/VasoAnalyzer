"""Read-only inspector and dialog for importing datasets from another project."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.storage.bundle_adapter import close_project_handle, open_project_handle
from vasoanalyzer.storage.sqlite import projects as _projects


@dataclass
class DatasetInfo:
    dataset_id: int
    dataset_name: str
    experiment_name: str
    experiment_id: str | None = None
    fps: float | None = None
    pixel_size_um: float | None = None
    trace_row_count: int | None = None
    event_count: int | None = None
    notes: str | None = None
    created_utc: str | None = None


@dataclass
class ExperimentInfo:
    name: str
    experiment_id: str | None
    datasets: list[DatasetInfo]


@dataclass
class ProjectInfo:
    project_path: Path
    project_name: str
    project_uuid: str | None
    experiments: list[ExperimentInfo]
    dataset_lookup: dict[int, DatasetInfo]
    dataset_lookup: dict[int, DatasetInfo]


def _read_meta(conn) -> Mapping[str, str]:
    return _projects.read_meta(conn)


def _load_experiments_meta(meta_rows: Mapping[str, str]) -> dict[str, Any]:
    raw = meta_rows.get("experiments_meta")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def inspect_source_project(path: str | Path) -> ProjectInfo:
    """Open ``path`` read-only and return minimal experiment/dataset listing."""

    handle, conn = open_project_handle(path, readonly=True, auto_migrate=False)
    meta_rows = {}
    experiments_meta: dict[str, Any] = {}
    datasets: list[DatasetInfo] = []
    try:
        meta_rows = _read_meta(conn)
        experiments_meta = _load_experiments_meta(meta_rows)

        cur = conn.execute(
            """
            SELECT id, name, notes, fps, pixel_size_um, t0_seconds, created_utc, extra_json
            FROM dataset
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
        for row in rows:
            ds_id, name, notes, fps, pixel_size_um, _t0, created_utc, extra_json = row
            extra = None
            if extra_json:
                try:
                    extra = json.loads(extra_json)
                except Exception:
                    extra = None
            exp_name = "Default"
            exp_id = None
            if isinstance(extra, dict):
                exp_name = extra.get("experiment") or exp_name
                exp_id = extra.get("experiment_id") or exp_id
            evt_count = conn.execute(
                "SELECT COUNT(*) FROM event WHERE dataset_id=? AND deleted_utc IS NULL", (ds_id,)
            ).fetchone()[0]
            trace_count = None
            try:
                trace_count = conn.execute(
                    "SELECT COUNT(*) FROM trace WHERE dataset_id=?", (ds_id,)
                ).fetchone()[0]
            except Exception:
                trace_count = None
            datasets.append(
                DatasetInfo(
                    dataset_id=int(ds_id),
                    dataset_name=name or f"Dataset {ds_id}",
                    experiment_name=exp_name,
                    experiment_id=str(exp_id) if exp_id else None,
                    fps=fps,
                    pixel_size_um=pixel_size_um,
                    trace_row_count=trace_count,
                    event_count=int(evt_count) if evt_count is not None else None,
                    notes=notes,
                    created_utc=created_utc,
                )
            )
    finally:
        close_project_handle(handle, save_before_close=False)

    experiments_by_name: dict[str, ExperimentInfo] = {}
    # Preserve experiment ordering from meta if available
    ordered_names: list[str] = list(experiments_meta.keys()) if experiments_meta else []
    for ds in datasets:
        if ds.experiment_name not in experiments_by_name:
            meta = experiments_meta.get(ds.experiment_name) if experiments_meta else {}
            experiments_by_name[ds.experiment_name] = ExperimentInfo(
                name=ds.experiment_name,
                experiment_id=(meta or {}).get("experiment_id"),
                datasets=[],
            )
        experiments_by_name[ds.experiment_name].datasets.append(ds)
    experiments: list[ExperimentInfo] = []
    used = set()
    for name in ordered_names:
        info = experiments_by_name.get(name)
        if info:
            experiments.append(info)
            used.add(name)
    for name, info in experiments_by_name.items():
        if name not in used:
            experiments.append(info)

    project_name = meta_rows.get("project_name") or Path(path).stem
    project_uuid = meta_rows.get("project_uuid")

    return ProjectInfo(
        project_path=Path(path),
        project_name=project_name,
        project_uuid=project_uuid,
        experiments=experiments,
        dataset_lookup={ds.dataset_id: ds for ds in datasets},
    )


class SourceProjectBrowserDialog(QDialog):
    """Dialog for selecting datasets from another project to import."""

    def __init__(
        self,
        parent: QWidget,
        current_project_path: str,
        current_experiments: Sequence[tuple[str, str | None]],
        *,
        initial_preserve: bool = False,
        initial_dest_experiment_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Dataset from Project")
        self._project_path = current_project_path
        self._current_experiments = list(current_experiments)
        self._initial_preserve = bool(initial_preserve)
        self._initial_dest_experiment_id = initial_dest_experiment_id
        self._source_info: ProjectInfo | None = None
        self._selected_dataset_ids: list[int] = []
        self._dataset_map: dict[int, DatasetInfo] = {}

        self._build_ui()

    # UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.source_label = QLabel("No source selected")
        self.choose_btn = QPushButton("Choose…")
        self.choose_btn.clicked.connect(self._choose_source)
        header.addWidget(self.source_label, 1)
        header.addWidget(self.choose_btn, 0)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Experiment / Dataset"])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        left_layout.addWidget(self.tree)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QFormLayout(right)
        self.detail_name = QLabel("-")
        self.detail_exp = QLabel("-")
        self.detail_events = QLabel("-")
        self.detail_traces = QLabel("-")
        self.detail_fps = QLabel("-")
        self.detail_px = QLabel("-")
        right_layout.addRow("Dataset", self.detail_name)
        right_layout.addRow("Experiment", self.detail_exp)
        right_layout.addRow("Events", self.detail_events)
        right_layout.addRow("Trace rows", self.detail_traces)
        right_layout.addRow("FPS", self.detail_fps)
        right_layout.addRow("Pixel size (µm)", self.detail_px)
        splitter.addWidget(right)

        layout.addWidget(splitter)

        dest_box = QGroupBox("Destination Experiment")
        dest_layout = QHBoxLayout(dest_box)
        self.dest_combo = QComboBox()
        if self._current_experiments:
            for name, exp_id in self._current_experiments:
                self.dest_combo.addItem(name, exp_id)
        else:
            self.dest_combo.addItem("Default", None)
        self.dest_combo.addItem("Create new…", "__create__")
        self.dest_new_name = QLineEdit()
        self.dest_new_name.setPlaceholderText("New experiment name")
        self.dest_new_name.setEnabled(False)
        if self._initial_dest_experiment_id:
            idx = self.dest_combo.findData(self._initial_dest_experiment_id)
            if idx >= 0:
                self.dest_combo.setCurrentIndex(idx)
        self.dest_combo.currentTextChanged.connect(self._on_dest_changed)
        self.preserve_checkbox = QCheckBox("Preserve source experiments")
        self.preserve_checkbox.setToolTip(
            "If checked, each dataset is imported into a destination experiment matching the source."
        )
        self.preserve_checkbox.setChecked(self._initial_preserve)
        dest_layout.addWidget(self.dest_combo)
        dest_layout.addWidget(self.dest_new_name)
        dest_layout.addWidget(self.preserve_checkbox)
        layout.addWidget(dest_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # Data loading -------------------------------------------------------
    def _choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Source Project",
            "",
            "Vaso Projects (*.vaso)",
        )
        if not path:
            return
        self._load_source(path)

    def _load_source(self, path: str) -> None:
        try:
            info = inspect_source_project(path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open Failed",
                f"Could not open source project:\n{exc}",
            )
            return
        self._source_info = info
        self.source_label.setText(f"{info.project_name} — {info.project_path}")
        self._populate_tree(info)

    def _populate_tree(self, info: ProjectInfo) -> None:
        self.tree.clear()
        self._dataset_map = {}
        for exp in info.experiments:
            exp_item = QTreeWidgetItem([exp.name])
            exp_item.setData(
                0,
                Qt.UserRole,
                {"type": "experiment", "experiment": exp.name},
            )
            for ds in exp.datasets:
                self._dataset_map[ds.dataset_id] = ds
                ds_item = QTreeWidgetItem([ds.dataset_name])
                ds_item.setData(
                    0,
                    Qt.UserRole,
                    {
                        "type": "dataset",
                        "dataset_id": ds.dataset_id,
                        "experiment": ds.experiment_name,
                    },
                )
                exp_item.addChild(ds_item)
            self.tree.addTopLevelItem(exp_item)
        self.tree.expandAll()
        if self.tree.topLevelItemCount() > 0:
            first = self.tree.topLevelItem(0)
            if first.childCount() > 0:
                self.tree.setCurrentItem(first.child(0))

    # Selection ----------------------------------------------------------
    def _on_tree_selection(self) -> None:
        items = self.tree.selectedItems()
        self._selected_dataset_ids = []
        if not items:
            self._clear_details()
            return
        ds_items = []
        for it in items:
            payload = it.data(0, Qt.UserRole)
            if isinstance(payload, dict) and payload.get("type") == "dataset":
                ds_items.append(it)
        if not ds_items:
            self._clear_details()
            return
        seen: set[int] = set()
        self._selected_dataset_ids = []
        for it in ds_items:
            payload = it.data(0, Qt.UserRole)
            ds_id = int(payload.get("dataset_id"))
            if ds_id not in seen:
                seen.add(ds_id)
                self._selected_dataset_ids.append(ds_id)
        first = ds_items[0]
        payload = first.data(0, Qt.UserRole)
        ds_id = int(payload.get("dataset_id"))
        exp_name = payload.get("experiment") or "-"
        self._update_details(ds_id, exp_name)

    def _clear_details(self) -> None:
        for label in (
            self.detail_name,
            self.detail_exp,
            self.detail_events,
            self.detail_traces,
            self.detail_fps,
            self.detail_px,
        ):
            label.setText("-")

    def _update_details(self, dataset_id: int, exp_name: str) -> None:
        ds = None
        if self._source_info:
            for exp in self._source_info.experiments:
                for candidate in exp.datasets:
                    if candidate.dataset_id == dataset_id:
                        ds = candidate
                        break
        if ds is None:
            self._clear_details()
            return
        self.detail_name.setText(ds.dataset_name)
        self.detail_exp.setText(exp_name)
        self.detail_events.setText(str(ds.event_count) if ds.event_count is not None else "—")
        self.detail_traces.setText(
            str(ds.trace_row_count) if ds.trace_row_count is not None else "—"
        )
        self.detail_fps.setText(str(ds.fps) if ds.fps is not None else "—")
        self.detail_px.setText(str(ds.pixel_size_um) if ds.pixel_size_um is not None else "—")

    # Destination selection ---------------------------------------------
    def _on_dest_changed(self, text: str) -> None:
        is_new = text == "Create new…"
        self.dest_new_name.setEnabled(is_new)
        if is_new:
            self.dest_new_name.setFocus()
            self.dest_new_name.selectAll()

    def selected_destination(self) -> tuple[str | None, str | None]:
        data = self.dest_combo.currentData()
        choice = self.dest_combo.currentText()
        if data == "__create__":
            name = self.dest_new_name.text().strip()
            return (name or None, None)
        return choice, data

    # Accept -------------------------------------------------------------
    def _on_accept(self) -> None:
        if not self._source_info:
            QMessageBox.warning(self, "Missing Source", "Choose a source project first.")
            return
        if not self._selected_dataset_ids:
            QMessageBox.warning(self, "No Dataset Selected", "Select a dataset to import.")
            return
        dest_exp, _ = self.selected_destination()
        if not dest_exp:
            QMessageBox.warning(self, "Destination Required", "Choose a destination experiment.")
            return
        self.accept()

    # Public API ---------------------------------------------------------
    def exec_with_source(
        self, initial_path: str | None = None
    ) -> tuple[str | None, list[DatasetInfo], str | None, bool, str | None]:
        if initial_path:
            self._load_source(initial_path)
        if self.exec_() == QDialog.Accepted and self._source_info:
            selections: list[DatasetInfo] = []
            for ds_id in self._selected_dataset_ids:
                info = self._dataset_map.get(ds_id)
                if info:
                    selections.append(info)
            dest_name, dest_id = self.selected_destination()
            return (
                str(self._source_info.project_path),
                selections,
                dest_name,
                self.preserve_checkbox.isChecked(),
                dest_id,
            )
        return None, [], None, False, None


def build_import_plan(
    entries: Sequence[DatasetInfo],
    default_experiment: str | None,
    preserve_source: bool,
) -> list[tuple[DatasetInfo, str]]:
    """
    Decide destination experiment for each dataset, preserving order.

    Returns list of (DatasetInfo, dest_experiment_name).
    """

    plan: list[tuple[DatasetInfo, str]] = []
    for entry in entries:
        dest = entry.experiment_name if preserve_source else default_experiment
        if not dest:
            dest = entry.experiment_name or "Imported"
        plan.append((entry, dest))
    return plan
