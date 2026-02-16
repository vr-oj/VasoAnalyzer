"""Dialog for exporting into the VasoAnalyzer standard Excel template (v1)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from vasoanalyzer.excel.template_v1 import inspect_template, validate_template_or_raise
from vasoanalyzer.excel.writer_v1 import apply_write_plan, build_write_plan
from vasoanalyzer.export.generator import build_export_table, events_from_rows
from vasoanalyzer.export.profiles import PRESSURE_CURVE_STANDARD


class ExcelTemplateExportDialog(QDialog):
    """Simple wizard-style dialog for template export."""

    def __init__(self, parent, *, event_rows: list[tuple]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export to VasoAnalyzer Excel Template")
        self.setMinimumSize(720, 520)

        self._event_rows = list(event_rows or [])
        self._inspection = None
        self._blocks = []
        self._current_plan = None

        layout = QVBoxLayout(self)

        file_group = QGroupBox("Template Workbook")
        file_layout = QGridLayout(file_group)
        file_layout.addWidget(QLabel("Workbook:"), 0, 0)
        self.template_path_edit = QLineEdit()
        self.template_browse_btn = QPushButton("Browse…")
        file_layout.addWidget(self.template_path_edit, 0, 1)
        file_layout.addWidget(self.template_browse_btn, 0, 2)
        layout.addWidget(file_group)

        options_group = QGroupBox("Export Options")
        options_layout = QGridLayout(options_group)
        options_layout.addWidget(QLabel("Block:"), 0, 0)
        self.block_combo = QComboBox()
        options_layout.addWidget(self.block_combo, 0, 1, 1, 2)
        options_layout.addWidget(QLabel("Replicate:"), 1, 0)
        self.replicate_combo = QComboBox()
        options_layout.addWidget(self.replicate_combo, 1, 1, 1, 2)
        options_layout.addWidget(QLabel("Profile:"), 2, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.addItem(PRESSURE_CURVE_STANDARD.display_name, PRESSURE_CURVE_STANDARD)
        options_layout.addWidget(self.profile_combo, 2, 1, 1, 2)
        self.skip_missing_cb = QCheckBox("Skip missing metrics (not recommended)")
        options_layout.addWidget(self.skip_missing_cb, 3, 0, 1, 3)
        layout.addWidget(options_group)

        output_group = QGroupBox("Output")
        output_layout = QGridLayout(output_group)
        output_layout.addWidget(QLabel("Save as:"), 0, 0)
        self.output_path_edit = QLineEdit()
        self.output_browse_btn = QPushButton("Browse…")
        output_layout.addWidget(self.output_path_edit, 0, 1)
        output_layout.addWidget(self.output_browse_btn, 0, 2)
        layout.addWidget(output_group)

        preview_group = QGroupBox("Write Plan Preview")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setHorizontalHeaderLabels(["Metric", "Value", "Target Cell"])
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        preview_layout.addWidget(self.preview_table)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        preview_layout.addWidget(self.status_label)
        layout.addWidget(preview_group, 1)

        btn_row = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.write_btn = QPushButton("Write")
        self.write_btn.setEnabled(False)
        cancel_btn = QPushButton("Close")
        btn_row.addStretch()
        btn_row.addWidget(self.preview_btn)
        btn_row.addWidget(self.write_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.template_browse_btn.clicked.connect(self._choose_template)
        self.output_browse_btn.clicked.connect(self._choose_output)
        self.block_combo.currentIndexChanged.connect(self._refresh_replicates)
        self.preview_btn.clicked.connect(self._preview_plan)
        self.write_btn.clicked.connect(self._write_plan)
        cancel_btn.clicked.connect(self.reject)

    def _choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select VasoAnalyzer template",
            "",
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if not path:
            return
        self.template_path_edit.setText(path)
        self._inspect_template(path)

    def _choose_output(self) -> None:
        start = self.output_path_edit.text().strip()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save output workbook",
            start or "",
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if path:
            self.output_path_edit.setText(path)

    def _inspect_template(self, path: str) -> None:
        try:
            inspection = inspect_template(path)
            validate_template_or_raise(inspection)
        except Exception as exc:
            QMessageBox.critical(self, "Invalid Template", str(exc))
            self._inspection = None
            self._blocks = []
            self.block_combo.clear()
            self.replicate_combo.clear()
            self.write_btn.setEnabled(False)
            return

        self._inspection = inspection
        self._blocks = inspection.blocks
        self.block_combo.clear()
        for block in self._blocks:
            label = block.title or block.block_id
            self.block_combo.addItem(f"{label} ({block.block_id})", block.block_id)

        self._refresh_replicates()
        self._set_default_output_path(path)

        if inspection.warnings:
            self.status_label.setText("\n".join(inspection.warnings))
        else:
            self.status_label.setText("")

    def _refresh_replicates(self) -> None:
        self.replicate_combo.clear()
        block = self._selected_block()
        if block is None:
            return
        ordered = sorted(
            block.replicate_cols,
            key=lambda name: int(name.split("_")[-1]) if name.split("_")[-1].isdigit() else 0,
        )
        self.replicate_combo.addItems(ordered)

    def _set_default_output_path(self, template_path: str) -> None:
        path = Path(template_path)
        if not path.name:
            return
        output = path.with_name(f"{path.stem}_filled{path.suffix}")
        self.output_path_edit.setText(str(output))

    def _selected_block(self):
        block_id = self.block_combo.currentData()
        if not block_id:
            return None
        for block in self._blocks:
            if block.block_id == block_id:
                return block
        return None

    def _profile_to_dataframe(self) -> pd.DataFrame:
        profile = self.profile_combo.currentData()
        events = events_from_rows(self._event_rows)
        table = build_export_table(profile, events)
        rows = [(row[0], row[1]) for row in table.rows if len(row) >= 2]
        return pd.DataFrame(rows, columns=["Metric", "Value"])

    def _preview_plan(self) -> None:
        template_path = self.template_path_edit.text().strip()
        output_path = self.output_path_edit.text().strip()
        block = self._selected_block()
        replicate = self.replicate_combo.currentText()

        self.preview_table.setRowCount(0)
        self.write_btn.setEnabled(False)

        if not (template_path and output_path and block and replicate):
            self.status_label.setText("Select a template, block, replicate, and output path.")
            return

        df = self._profile_to_dataframe()
        try:
            plan = build_write_plan(template_path, output_path, block, replicate, df)
        except Exception as exc:
            self.status_label.setText(str(exc))
            return

        original_missing = list(plan.missing_metrics)
        if plan.missing_metrics and self.skip_missing_cb.isChecked():
            filtered = df[~df["Metric"].isin(plan.missing_metrics)]
            plan = build_write_plan(template_path, output_path, block, replicate, filtered)
            if plan.missing_metrics:
                self.status_label.setText("Missing metrics remain after filtering.")
                return

        self._current_plan = plan
        for item in plan.items:
            row_idx = self.preview_table.rowCount()
            self.preview_table.insertRow(row_idx)
            self.preview_table.setItem(row_idx, 0, QTableWidgetItem(item.metric))
            self.preview_table.setItem(row_idx, 1, QTableWidgetItem(f"{item.value:.2f}"))
            self.preview_table.setItem(row_idx, 2, QTableWidgetItem(item.target_cell))

        messages = []
        if original_missing:
            messages.append("Missing metrics: " + ", ".join(original_missing))
        if plan.warnings:
            messages.extend(plan.warnings)
        self.status_label.setText("\n".join(messages))

        self.write_btn.setEnabled(not original_missing or self.skip_missing_cb.isChecked())

    def _write_plan(self) -> None:
        if self._current_plan is None:
            self._preview_plan()
            if self._current_plan is None:
                return

        try:
            apply_write_plan(self._current_plan)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return

        QMessageBox.information(
            self,
            "Export Complete",
            f"Workbook saved to:\n{self._current_plan.output_path}",
        )
        self.accept()
