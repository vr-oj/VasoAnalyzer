# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# coding: utf-8
"""Wizard interface for mapping events into an Excel template.

This module implements a multi-page ``QWizard`` which guides the user
through selecting an Excel template, choosing rows for event mapping and
optionally previewing the result before saving.  The implementation uses
``openpyxl`` to read and write ``.xlsx`` files while preserving formulas
and ``pandas`` for loading event data from CSV files.

The wizard is largely based on the implementation plan documented in the
project repository.
"""

import csv
import os
from collections import Counter, deque
from dataclasses import dataclass, field
from numbers import Real
from pathlib import Path
from typing import Any, cast

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries
from PyQt5.QtCore import QAbstractTableModel, QMimeData, QModelIndex, QSettings, Qt, pyqtProperty
from PyQt5.QtGui import QBrush, QColor, QFont, QPalette
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

import vasoanalyzer.ui.theme as theme
from vasoanalyzer.excel import (
    TemplateMetadata,
    has_vaso_metadata,
    read_template_metadata,
)

__all__ = ["ExcelMapWizard"]

DEFAULT_QMODEL_INDEX = QModelIndex()

SESSION_EVENT_MIME = "application/vnd.vaso.session-event"


class _WizardUnavailableError(RuntimeError):
    """Raised when a wizard page cannot resolve its hosting wizard."""


class WizardPageBase(QWizardPage):
    """QWizardPage helper exposing a typed reference to the host wizard."""

    def _wizard(self) -> "ExcelMapWizard":
        wizard = super().wizard()
        if wizard is None:
            raise _WizardUnavailableError("Wizard is not available")
        return cast("ExcelMapWizard", wizard)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def load_workbook_preserve(path: str):
    """Load an Excel workbook preserving formulas."""

    return load_workbook(path, data_only=False)


def load_events_csv(path: str) -> pd.DataFrame:
    """Load a CSV file containing event information."""

    with open(path, encoding="utf-8-sig") as handle:
        sample = handle.read(1024)
        handle.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample).delimiter
        except csv.Error:
            if "\t" in sample:
                delimiter = "\t"
            elif ";" in sample:
                delimiter = ";"
            else:
                delimiter = ","

        return pd.read_csv(handle, delimiter=delimiter)


def save_workbook(wb, path: str) -> None:
    """Save an Excel workbook to ``path``."""

    wb.save(path)


# ---------------------------------------------------------------------------
# Model for previewing pandas.DataFrame in a QTableView
# ---------------------------------------------------------------------------


class PandasModel(QAbstractTableModel):
    """Simple table model exposing a pandas DataFrame."""

    def __init__(self, frame: pd.DataFrame):
        super().__init__()
        self._df = frame.reset_index(drop=True)

    def rowCount(self, parent: QModelIndex = DEFAULT_QMODEL_INDEX) -> int:
        return len(self._df)

    def columnCount(self, parent: QModelIndex = DEFAULT_QMODEL_INDEX) -> int:
        return len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        value = self._df.iat[index.row(), index.column()]
        return "" if pd.isna(value) else str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._df.columns[section]
        return str(section + 1)


class SessionValuesTable(QTableWidget):
    """Table showing session events and acting as a drag source."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.verticalHeader().setVisible(False)

    def mimeTypes(self) -> list[str]:
        return [SESSION_EVENT_MIME, "text/plain"]

    def mimeData(self, indexes):  # noqa: N802 - Qt API
        mime = QMimeData()
        if not indexes:
            return mime

        row = indexes[0].row()
        item = self.item(row, 0)
        if item is None:
            return mime

        event_index = item.data(Qt.UserRole)
        if event_index is None:
            return mime

        mime.setData(SESSION_EVENT_MIME, str(int(event_index)).encode())
        mime.setText(item.text())
        return mime


class TemplatePreviewTable(QTableWidget):
    """Preview table that accepts drops on the active measurement column."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drop_context = None
        self._active_drop_column: int | None = None
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self._apply_theme()

    def set_drop_context(self, context) -> None:
        self._drop_context = context

    def set_active_drop_column(self, column_index: int | None) -> None:
        self._active_drop_column = column_index

    def _extract_drop_target(self, event) -> tuple[int, int] | None:
        if self._drop_context is None:
            return None

        event_index = self._drop_context.event_index_from_mime(event.mimeData())
        if event_index is None:
            return None

        index = self.indexAt(event.pos())
        if not index.isValid():
            return None

        if self._active_drop_column is None or index.column() != self._active_drop_column:
            return None

        template_row = self._drop_context.template_row_for_preview_row(index.row())
        if template_row is None:
            return None

        return template_row, event_index

    def dragEnterEvent(self, event):  # noqa: N802 - Qt API
        if self._extract_drop_target(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802 - Qt API
        if self._extract_drop_target(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802 - Qt API
        target = self._extract_drop_target(event)
        if not target:
            event.ignore()
            return

        template_row, event_index = target
        self._drop_context.assign_event_to_row(template_row, event_index)
        event.acceptProposedAction()

    def _apply_theme(self) -> None:
        """Apply theme-driven palette for dark/light modes."""
        palette = self.palette()
        table_bg = theme.CURRENT_THEME.get("table_bg", "#020617")
        alt_bg = theme.CURRENT_THEME.get("alternate_bg", table_bg)
        text = theme.CURRENT_THEME.get("table_text", theme.CURRENT_THEME.get("text", "#FFFFFF"))
        highlight = theme.CURRENT_THEME.get("selection_bg", "#1D4ED8")
        grid = theme.CURRENT_THEME.get("grid_color", "#374151")

        palette.setColor(self.backgroundRole(), QColor(table_bg))
        palette.setColor(self.foregroundRole(), QColor(text))
        palette.setColor(QPalette.Base, QColor(table_bg))
        palette.setColor(QPalette.AlternateBase, QColor(alt_bg))
        palette.setColor(QPalette.Text, QColor(text))
        palette.setColor(QPalette.WindowText, QColor(text))
        palette.setColor(QPalette.Highlight, QColor(highlight))
        palette.setColor(QPalette.HighlightedText, QColor(text))

        self.setPalette(palette)
        self.setStyleSheet(
            f"""
            QTableView {{
                gridline-color: {grid};
                background: {table_bg};
                alternate-background-color: {alt_bg};
                color: {text};
                selection-background-color: {highlight};
            }}
            QHeaderView::section {{
                background: {table_bg};
                color: {text};
            }}
        """
        )

    def apply_theme(self) -> None:
        """Public hook to refresh palette after theme changes."""

        self._apply_theme()


# ---------------------------------------------------------------------------
# Wizard Pages
# ---------------------------------------------------------------------------


class TemplatePage(WizardPageBase):
    """Page for selecting the Excel template and event CSV."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Step 1: Load Template & CSV")
        layout = QVBoxLayout(self)

        self._templatePath = ""
        self._csvPath = ""
        self.registerField("templatePath*", self, "templatePath")
        self.registerField("csvPath*", self, "csvPath")

        self.btn_excel = QPushButton("Load Excel Template…")
        self.lbl_excel = QLabel("No template loaded.")
        self.btn_excel.clicked.connect(self.load_template)
        layout.addWidget(self.btn_excel)
        layout.addWidget(self.lbl_excel)

        # Sheet selector UI
        self.lbl_sheet = QLabel("Select worksheet:")
        self.combo_sheet = QComboBox()
        self.lbl_sheet.setVisible(False)
        self.combo_sheet.setVisible(False)
        self.combo_sheet.currentIndexChanged.connect(self._on_sheet_changed)
        layout.addWidget(self.lbl_sheet)
        layout.addWidget(self.combo_sheet)

        # Recent templates UI
        self.recent_templates_label = QLabel("Recent templates")
        self.recent_templates_list = QListWidget()
        self.recent_templates_list.setSelectionMode(QListWidget.SingleSelection)
        self.recent_templates_list.setAlternatingRowColors(True)
        self.recent_templates_list.setUniformItemSizes(True)
        self.recent_templates_list.itemActivated.connect(self._on_recent_template_activated)
        self.remove_recent_button = QPushButton("Remove selected")
        self.clear_recent_button = QPushButton("Clear all")
        self.remove_recent_button.clicked.connect(self._on_remove_selected_recent_template)
        self.clear_recent_button.clicked.connect(self._on_clear_recent_templates)
        self.recent_templates_label.setVisible(False)
        self.recent_templates_list.setVisible(False)
        self.remove_recent_button.setVisible(False)
        self.clear_recent_button.setVisible(False)
        layout.addWidget(self.recent_templates_label)
        layout.addWidget(self.recent_templates_list)
        recent_buttons_row = QHBoxLayout()
        recent_buttons_row.addStretch()
        recent_buttons_row.addWidget(self.remove_recent_button)
        recent_buttons_row.addWidget(self.clear_recent_button)
        layout.addLayout(recent_buttons_row)

        self.btn_csv = QPushButton("Load Events CSV…")
        self.lbl_csv = QLabel("No events loaded.")
        self.btn_csv.clicked.connect(self.load_csv)
        layout.addWidget(self.btn_csv)
        layout.addWidget(self.lbl_csv)

        self._update_recent_templates_list()

    # Properties exposed as wizard fields
    def get_templatePath(self) -> str:
        return self._templatePath

    def set_templatePath(self, value: str) -> None:
        self._templatePath = value

    templatePath = pyqtProperty(str, fget=get_templatePath, fset=set_templatePath)

    def get_csvPath(self) -> str:
        return self._csvPath

    def set_csvPath(self, value: str) -> None:
        self._csvPath = value

    csvPath = pyqtProperty(str, fget=get_csvPath, fset=set_csvPath)

    # ------------------------------------------------------
    def initializePage(self) -> None:
        super().initializePage()
        self._update_events_status()

    # ------------------------------------------------------
    def _load_template_from_path(self, path: str) -> None:
        """Load a template from the given path and update wizard state."""
        if not path:
            return

        try:
            wb = load_workbook_preserve(path)
        except Exception as exc:  # pragma: no cover - GUI feedback
            QMessageBox.critical(self, "Load Failed", str(exc))
            return

        # Don't set ws yet - wait for sheet selection
        wiz = self._wizard()
        wiz.setField("templatePath", path)
        wiz.wb = wb
        wiz.ws = None  # Will be set after sheet selection
        wiz.selected_sheet_name = None
        wiz.reset_mapping_state()

        # Populate sheet selector
        self._populate_sheet_selector(wb)

        # Try to restore previous sheet preference
        saved_sheet = self._load_sheet_preference(path)
        if saved_sheet and saved_sheet in wb.sheetnames:
            idx = self.combo_sheet.findText(saved_sheet)
            if idx >= 0:
                self.combo_sheet.setCurrentIndex(idx)
                # _on_sheet_changed will be called automatically
        elif self.combo_sheet.count() == 1:
            # Auto-select if only one sheet
            self.combo_sheet.setCurrentIndex(0)
            # _on_sheet_changed will be called automatically
        elif self.combo_sheet.count() > 1:
            # Show selection required message
            self.lbl_excel.setText(
                f"Loaded: {Path(path).name} - Select a worksheet to continue"
            )
            self.lbl_excel.setStyleSheet("color: #8a6d3b;")  # Orange
        else:
            # No sheets available (shouldn't happen)
            self.lbl_excel.setText(f"Loaded: {Path(path).name} - No worksheets found")
            self.lbl_excel.setStyleSheet("color: #a94442;")  # Red

        self._update_recent_templates(path)
        self.completeChanged.emit()

    # ------------------------------------------------------
    def load_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Excel Template",
            "",
            "Excel Files (*.xlsx *.xlsm);;Macro-Enabled (*.xlsm);;Standard (*.xlsx)",
        )
        if not path:
            return
        self._load_template_from_path(path)

    # ------------------------------------------------------
    def load_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            df = self._prepare_events_dataframe(load_events_csv(path))
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid CSV", str(exc))
            return
        except Exception as exc:  # pragma: no cover - GUI feedback
            QMessageBox.critical(self, "Load Failed", str(exc))
            return

        wiz = self._wizard()
        wiz.reset_mapping_state()
        wiz.setField("csvPath", path)
        wiz.set_events_dataframe(df, source="csv")
        self._update_events_status()
        self.completeChanged.emit()

    # ------------------------------------------------------
    def isComplete(self) -> bool:
        wiz = self._wizard()
        has_events = bool(self.field("csvPath")) or getattr(wiz, "eventsDF", None) is not None
        has_sheet_selected = wiz.ws is not None  # Check sheet selection
        return bool(self.field("templatePath") and has_events and has_sheet_selected)

    # ------------------------------------------------------
    def _update_events_status(self) -> None:
        wiz = self._wizard()
        df = getattr(wiz, "eventsDF", None)
        if df is None or df.empty:
            self.lbl_csv.setText("No events loaded.")
            self.btn_csv.setText("Load Events CSV…")
            return

        source = getattr(wiz, "events_source", "session")
        count = len(df)
        noun = "event" if count == 1 else "events"
        if source == "session":
            message = f"Using {count} {noun} from current session."
            self.btn_csv.setText("Replace Events CSV…")
        else:
            csv_path = Path(self.field("csvPath") or "")
            base = csv_path.name if csv_path.name else "external CSV"
            message = f"Loaded {count} {noun} from {base}."
            self.btn_csv.setText("Reload Events CSV…")
        self.lbl_csv.setText(message)

    # ------------------------------------------------------
    def _load_recent_templates(self) -> list[str]:
        """Return the stored recent templates list."""
        settings = self._get_settings()
        paths = settings.value("recentTemplates", [], type=list) or []
        return [p for p in paths if p]

    # ------------------------------------------------------
    def _save_recent_templates(self, paths: list[str]) -> None:
        """Persist the recent templates list."""
        settings = self._get_settings()
        settings.setValue("recentTemplates", paths)

    # ------------------------------------------------------
    def _update_recent_templates_list(self) -> None:
        """Refresh the Recent Templates UI from QSettings."""
        self.recent_templates_list.clear()
        paths = self._load_recent_templates()
        has_items = bool(paths)

        if not has_items:
            self.recent_templates_label.setVisible(False)
            self.recent_templates_list.setVisible(False)
            self.remove_recent_button.setVisible(False)
            self.clear_recent_button.setVisible(False)
            return

        for path in paths:
            file_name = os.path.basename(path)
            item = QListWidgetItem(file_name)
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.recent_templates_list.addItem(item)

        self.recent_templates_label.setVisible(True)
        self.recent_templates_list.setVisible(True)
        self.remove_recent_button.setVisible(True)
        self.clear_recent_button.setVisible(True)

    # ------------------------------------------------------
    def _update_recent_templates(self, path: str) -> None:
        """Update the stored recent templates list and refresh the UI."""
        if not path:
            return

        paths = self._load_recent_templates()
        if path in paths:
            paths.remove(path)
        paths.insert(0, path)
        paths = paths[:5]
        self._save_recent_templates(paths)
        self._update_recent_templates_list()

    # ------------------------------------------------------
    def _on_recent_template_activated(self, item: QListWidgetItem) -> None:
        """Handle activation of a recent template entry."""
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        self._load_template_from_path(path)

    # ------------------------------------------------------
    def _on_clear_recent_templates(self) -> None:
        """Clear all recent templates."""
        self._save_recent_templates([])
        self._update_recent_templates_list()

    # ------------------------------------------------------
    def _on_remove_selected_recent_template(self) -> None:
        """Remove only the currently selected recent template."""
        item = self.recent_templates_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        paths = [p for p in self._load_recent_templates() if p != path]
        self._save_recent_templates(paths)
        self._update_recent_templates_list()

    # ------------------------------------------------------
    @staticmethod
    def _get_settings() -> QSettings:
        return QSettings("TykockiLab", "VasoAnalyzer")

    # ------------------------------------------------------
    def _load_sheet_preference(self, file_path: str) -> str | None:
        """Load previously selected sheet for this file."""
        settings = self._get_settings()
        key = f"excel_sheet_selection/{file_path}"
        return settings.value(key, None, type=str)

    # ------------------------------------------------------
    def _save_sheet_preference(self, file_path: str, sheet_name: str) -> None:
        """Save sheet selection preference."""
        settings = self._get_settings()
        key = f"excel_sheet_selection/{file_path}"
        settings.setValue(key, sheet_name)

    # ------------------------------------------------------
    def _populate_sheet_selector(self, wb) -> None:
        """Populate sheet selector with workbook sheets."""
        from openpyxl import Workbook

        self.combo_sheet.blockSignals(True)
        self.combo_sheet.clear()

        for sheet_name in wb.sheetnames:
            # Skip hidden metadata sheets
            if sheet_name.startswith("VasoMetadata"):
                continue
            # Skip hidden sheets
            sheet = wb[sheet_name]
            if hasattr(sheet, 'sheet_state') and sheet.sheet_state == "hidden":
                continue
            self.combo_sheet.addItem(sheet_name)

        self.combo_sheet.blockSignals(False)

        # Show selector if sheets available
        has_sheets = self.combo_sheet.count() > 0
        self.lbl_sheet.setVisible(has_sheets)
        self.combo_sheet.setVisible(has_sheets)

    # ------------------------------------------------------
    def _on_sheet_changed(self, index: int) -> None:
        """Handle sheet selection change."""
        if index < 0:
            return

        sheet_name = self.combo_sheet.currentText()
        if not sheet_name:
            return

        wiz = self._wizard()
        template_path = self.field("templatePath")

        if not wiz.wb:
            return

        # Update wizard state
        wiz.ws = wiz.wb[sheet_name]
        wiz.selected_sheet_name = sheet_name
        wiz.reset_mapping_state()

        # Save preference
        if template_path:
            self._save_sheet_preference(template_path, sheet_name)

        # Reload metadata for new sheet
        self._reload_metadata_for_sheet(sheet_name)

        # Update UI label
        from pathlib import Path
        self.lbl_excel.setText(f"Loaded: {Path(template_path).name} (Sheet: {sheet_name})")
        self.lbl_excel.setStyleSheet("")

        self.completeChanged.emit()

    # ------------------------------------------------------
    def _reload_metadata_for_sheet(self, sheet_name: str) -> None:
        """Reload metadata for the selected sheet."""
        from vasoanalyzer.excel.template_metadata import read_sheet_specific_metadata

        wiz = self._wizard()
        if not wiz.wb:
            return

        try:
            metadata = read_sheet_specific_metadata(wiz.wb, sheet_name)
            if metadata:
                wiz.template_metadata = metadata
                from pathlib import Path
                template_path = self.field("templatePath")
                status_msg = f"✓ Loaded: {Path(template_path).name} (Sheet: {sheet_name}, metadata detected)"
                self.lbl_excel.setText(status_msg)
                self.lbl_excel.setStyleSheet("color: #3c763d;")  # Green
        except Exception as exc:
            from pathlib import Path
            template_path = self.field("templatePath")
            QMessageBox.warning(
                self,
                "Metadata Error",
                f"Could not load metadata for sheet '{sheet_name}':\n{exc}"
            )
            self.lbl_excel.setText(f"Loaded: {Path(template_path).name} (Sheet: {sheet_name}, metadata error)")
            self.lbl_excel.setStyleSheet("color: #8a6d3b;")  # Orange

    # ------------------------------------------------------
    @staticmethod
    def _prepare_events_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            raise ValueError("Event CSV is empty.")

        rename_map: dict[str, str] = {}

        def _norm(col: str) -> str:
            return "".join(ch for ch in col.lower() if ch.isalnum())

        for col in df.columns:
            norm = _norm(col)
            if norm in {"event", "eventlabel", "label"}:
                rename_map[col] = "Event"
            elif norm in {"time", "times", "seconds", "timeseconds"}:
                rename_map[col] = "Time (s)"
            elif norm in {"id", "innerdiameter", "idum", "idmicrometer", "diameter"}:
                rename_map[col] = "ID (µm)"
            elif norm in {"od", "outerdiameter", "odum", "odmicrometer"}:
                rename_map[col] = "OD (µm)"
            elif norm in {"frame", "framenumber", "frameindex"}:
                rename_map[col] = "Frame"

        if rename_map:
            df = df.rename(columns=rename_map)

        if "Event" not in df.columns:
            raise ValueError("Event CSV must contain an 'Event' column.")

        value_candidates = [col for col in df.columns if col in {"ID (µm)", "OD (µm)"}]
        if not value_candidates:
            raise ValueError("Event CSV must include 'ID (µm)' and/or 'OD (µm)' column.")

        desired_order = [
            col for col in ["Event", "Time (s)", "ID (µm)", "OD (µm)", "Frame"] if col in df.columns
        ]
        df = df[desired_order].copy()
        df["Event"] = df["Event"].astype(str)

        for col in ["Time (s)", "ID (µm)", "OD (µm)"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "Frame" in df.columns:
            df["Frame"] = pd.to_numeric(df["Frame"], errors="coerce")

        return df.reset_index(drop=True)


@dataclass
class SessionEventInfo:
    index: int
    label: str
    time_value: float | None
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def combo_text(self) -> str:
        if self.time_value is None or pd.isna(self.time_value):
            return self.label
        return f"{self.label} ({self.time_value:.2f}s)"


@dataclass
class EventRowInfo:
    row_index: int
    label: str
    is_header: bool
    label_cell: str


@dataclass
class DateColumnOption:
    column_index: int
    cell_address: str
    value: Any
    empty_slots: int
    is_new: bool = False

    @property
    def letter(self) -> str:
        return str(get_column_letter(self.column_index))

    @property
    def display(self) -> str:
        base = self.letter
        if self.value not in (None, ""):
            base = f"{base} – {self.value}"
        if self.is_new:
            base += " (new)"
        elif self.empty_slots == 0:
            base += " (full)"
        return base


class RowMappingPage(WizardPageBase):
    """Interactive mapping page with preview and row-by-row controls."""

    PREVIEW_ROW_LIMIT = 30

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Step 2: Map Events to Template Rows")

        self._event_row_widgets: dict[int, QComboBox] = {}
        self._value_items: dict[int, QTableWidgetItem] = {}
        self._status_items: dict[int, QTableWidgetItem] = {}
        self._template_row_to_table_index: dict[int, int] = {}
        self._preview_row_to_template_row: dict[int, int] = {}
        self._preview_base_values: dict[int, str] = {}
        self._active_preview_column: int | None = None
        self._initialised = False

        root = QVBoxLayout(self)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

        control_row = QHBoxLayout()
        control_row.addWidget(QLabel("Measurement:"))
        self.measurement_combo = QComboBox()
        control_row.addWidget(self.measurement_combo)

        self.pick_date_combo = QComboBox()
        self.pick_date_combo.setVisible(False)
        control_row.addWidget(self.pick_date_combo)

        self.redetect_btn = QToolButton()
        self.redetect_btn.setText("Re-detect")
        control_row.addWidget(self.redetect_btn)

        self.select_unmapped_btn = QToolButton()
        self.select_unmapped_btn.setText("Select Unmapped…")
        self.select_unmapped_btn.setVisible(False)
        control_row.addWidget(self.select_unmapped_btn)

        control_row.addStretch()
        root.addLayout(control_row)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Horizontal)
        root.addWidget(splitter, 1)

        self.preview_table = TemplatePreviewTable()
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setDefaultSectionSize(24)
        self.preview_table.set_drop_context(self)
        self._apply_table_theme(self.preview_table)
        preview_container = QVBoxLayout()
        preview_widget = QFrame()
        preview_widget.setLayout(preview_container)
        preview_container.addWidget(QLabel("Template Preview"))
        preview_container.addWidget(self.preview_table, 1)
        splitter.addWidget(preview_widget)

        self.mapping_table = QTableWidget()
        self.mapping_table.setColumnCount(5)
        self.mapping_table.setHorizontalHeaderLabels(
            ["Row", "Template Label", "Session Event", "Value to Write", "Status"]
        )
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.verticalHeader().setDefaultSectionSize(24)
        self.mapping_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._apply_table_theme(self.mapping_table)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        splitter.addWidget(self.mapping_table)

        self.session_values_table = SessionValuesTable()
        self.session_values_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.session_values_table.verticalHeader().setDefaultSectionSize(24)
        session_container = QVBoxLayout()
        session_widget = QFrame()
        session_widget.setLayout(session_container)
        session_container.addWidget(QLabel("Session Values"))
        session_container.addWidget(self.session_values_table, 1)
        splitter.addWidget(session_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 2)

        helper_lines = [
            "Headers use bold, filled Column A cells; the wizard never writes to them.",
            "To add an event row, type its label in Column A with normal text and no fill.",
            "Pick the active date column in the row of dates; values go into that column.",
            "Override matches using the dropdowns—your selections control the final export.",
        ]
        helper_text = QLabel("\n".join(helper_lines))
        helper_text.setWordWrap(True)
        helper_text.setStyleSheet("color: #555;")
        root.addWidget(helper_text)

        self.measurement_combo.currentTextChanged.connect(self._on_measurement_changed)
        self.redetect_btn.clicked.connect(self._on_redetect)
        self.pick_date_combo.currentIndexChanged.connect(self._on_date_changed)
        self.select_unmapped_btn.clicked.connect(self._select_all_unmapped)

    def _apply_table_theme(self, table) -> None:
        """Apply theme-aware palette and stylesheet to table widgets."""
        palette = table.palette()
        table_bg = theme.CURRENT_THEME.get("table_bg", "#020617")
        alt_bg = theme.CURRENT_THEME.get("alternate_bg", table_bg)
        text = theme.CURRENT_THEME.get("table_text", theme.CURRENT_THEME.get("text", "#FFFFFF"))
        highlight = theme.CURRENT_THEME.get("selection_bg", "#1D4ED8")
        grid = theme.CURRENT_THEME.get("grid_color", "#374151")

        palette.setColor(QPalette.Base, QColor(table_bg))
        palette.setColor(QPalette.AlternateBase, QColor(alt_bg))
        palette.setColor(QPalette.Text, QColor(text))
        palette.setColor(QPalette.WindowText, QColor(text))
        palette.setColor(QPalette.Highlight, QColor(highlight))
        palette.setColor(QPalette.HighlightedText, QColor(text))

        table.setPalette(palette)
        table.setStyleSheet(
            f"""
            QTableView {{
                gridline-color: {grid};
                background: {table_bg};
                alternate-background-color: {alt_bg};
                color: {text};
                selection-background-color: {highlight};
            }}
            QHeaderView::section {{
                background: {table_bg};
                color: {text};
            }}
        """
        )

    # --------------------------------------------------
    def initializePage(self) -> None:
        super().initializePage()
        wiz = self._wizard()
        if not wiz or wiz.wb is None or wiz.ws is None or wiz.eventsDF is None:
            self.info_label.setText("Load an Excel template and event data first.")
            self.setFinalPage(True)
            return

        if not wiz.prepare_layout(auto=True):
            self.info_label.setText(getattr(wiz, "layout_error", ""))
            return

        self._populate_measurement_options()
        self._populate_date_options()
        self._rebuild_mapping_table()
        self._refresh_preview()
        self._refresh_session_values_table()
        self._update_status_banner()
        self._initialised = True

    # --------------------------------------------------
    def _populate_measurement_options(self) -> None:
        wiz = self._wizard()
        self.measurement_combo.blockSignals(True)
        self.measurement_combo.clear()
        for col in wiz.measurement_columns:
            self.measurement_combo.addItem(col)
        if self.measurement_combo.count():
            if wiz.current_measurement:
                idx = self.measurement_combo.findText(wiz.current_measurement)
                if idx >= 0:
                    self.measurement_combo.setCurrentIndex(idx)
            wiz.current_measurement = self.measurement_combo.currentText()
        self.measurement_combo.blockSignals(False)

    # --------------------------------------------------
    def _populate_date_options(self) -> None:
        wiz = self._wizard()
        options = wiz.date_columns or []

        self.pick_date_combo.blockSignals(True)
        self.pick_date_combo.clear()
        for opt in options:
            self.pick_date_combo.addItem(opt.display, opt)

        if not options:
            self.pick_date_combo.setVisible(False)
            return

        current = wiz.active_date_column
        if current:
            for idx, opt in enumerate(options):
                if opt.column_index == current.column_index:
                    self.pick_date_combo.setCurrentIndex(idx)
                    break

        needs_choice = wiz.manual_date_selection_required or len(options) > 1
        self.pick_date_combo.setVisible(needs_choice)
        self.pick_date_combo.blockSignals(False)
        wiz.ensure_active_date_value(self)

    # --------------------------------------------------
    def _refresh_session_values_table(self) -> None:
        wiz = self._wizard()
        events = getattr(wiz, "session_events", [])
        measurement = wiz.current_measurement

        headers = ["Event", "Time (s)", measurement or "Value"]
        table = self.session_values_table
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(events))

        for row_idx, event in enumerate(events):
            event_item = QTableWidgetItem(event.label)
            event_item.setData(Qt.UserRole, event.index)
            table.setItem(row_idx, 0, event_item)

            time_text = ""
            if event.time_value is not None and not pd.isna(event.time_value):
                time_text = f"{event.time_value:.2f}"
            table.setItem(row_idx, 1, QTableWidgetItem(time_text))

            value = event.values.get(measurement) if measurement else float("nan")
            if pd.isna(value):
                value_text = "—"
            elif isinstance(value, Real):
                value_text = f"{value:.2f}"
            else:
                value_text = str(value)
            table.setItem(row_idx, 2, QTableWidgetItem(value_text))

        table.resizeRowsToContents()
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)

    # --------------------------------------------------
    def _rebuild_mapping_table(self) -> None:
        wiz = self._wizard()
        event_rows = [row for row in wiz.event_rows if not row.is_header]

        self.mapping_table.setRowCount(len(event_rows))
        self._event_row_widgets.clear()
        self._value_items.clear()
        self._status_items.clear()
        self._template_row_to_table_index = {}

        font_mono = QFont("Menlo", 10)

        for row_idx, event_row in enumerate(event_rows):
            row_number_item = QTableWidgetItem(str(event_row.row_index))
            row_number_item.setFlags(row_number_item.flags() & ~Qt.ItemIsEditable)
            row_number_item.setFont(font_mono)
            self.mapping_table.setItem(row_idx, 0, row_number_item)

            self._template_row_to_table_index[event_row.row_index] = row_idx

            label_item = QTableWidgetItem(event_row.label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            self.mapping_table.setItem(row_idx, 1, label_item)

            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            combo.addItem("<leave unmapped>", None)
            for event in wiz.session_events:
                combo.addItem(event.combo_text, event.index)

            assignment = wiz.row_assignments.get(event_row.row_index)
            if assignment is not None:
                idx = combo.findData(assignment)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            combo.currentIndexChanged.connect(
                self._make_row_selection_handler(event_row.row_index, combo)
            )
            self.mapping_table.setCellWidget(row_idx, 2, combo)
            self._event_row_widgets[event_row.row_index] = combo

            value_item = QTableWidgetItem("")
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            self.mapping_table.setItem(row_idx, 3, value_item)
            self._value_items[event_row.row_index] = value_item

            status_item = QTableWidgetItem("○")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.mapping_table.setItem(row_idx, 4, status_item)
            self._status_items[event_row.row_index] = status_item

        self.mapping_table.resizeRowsToContents()
        self._refresh_value_column()
        self._refresh_status_icons()

    # --------------------------------------------------
    def _refresh_value_column(self) -> None:
        wiz = self._wizard()
        measurement = wiz.current_measurement
        for row_index, item in self._value_items.items():
            assignment = wiz.row_assignments.get(row_index)
            text = ""
            if assignment is not None:
                value = wiz.value_for_event(assignment, measurement)
                if pd.isna(value):
                    text = "—"
                elif isinstance(value, Real):
                    text = f"{value:.2f}"
                else:
                    text = str(value)
            item.setText(text)

    # --------------------------------------------------
    def _refresh_status_icons(self) -> None:
        wiz = self._wizard()
        assignments = Counter(
            assignment for assignment in wiz.row_assignments.values() if assignment is not None
        )
        duplicates = {idx for idx, count in assignments.items() if count > 1}

        for row_index, item in self._status_items.items():
            assignment = wiz.row_assignments.get(row_index)
            if assignment is None:
                item.setText("○")
                item.setToolTip("No session event mapped")
                item.setForeground(QBrush(QColor("#a94442")))
            elif assignment in duplicates:
                item.setText("!")
                item.setToolTip("Session event reused on multiple rows")
                item.setForeground(QBrush(QColor("#8a6d3b")))
            else:
                item.setText("✓")
                item.setToolTip("Mapped")
                item.setForeground(QBrush(QColor("#3c763d")))

    # --------------------------------------------------
    def _refresh_preview(self) -> None:
        wiz = self._wizard()
        preview_data = wiz.preview_template_data(limit=self.PREVIEW_ROW_LIMIT)
        self.preview_table.clear()
        self._preview_row_to_template_row = {}
        self._preview_base_values = {}
        self._active_preview_column = None
        table_bg = theme.CURRENT_THEME.get("table_bg", "#020617")
        alt_bg = theme.CURRENT_THEME.get("alternate_bg", table_bg)
        table_text = theme.CURRENT_THEME.get(
            "table_text", theme.CURRENT_THEME.get("text", "#FFFFFF")
        )
        active_bg = theme.CURRENT_THEME.get(
            "accent_fill", theme.CURRENT_THEME.get("selection_bg", table_bg)
        )
        event_bg = alt_bg
        header_bg = theme.CURRENT_THEME.get("button_hover_bg", alt_bg)
        if not preview_data:
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            self.preview_table.set_active_drop_column(None)
            return

        headers = [key for key in preview_data[0] if not key.startswith("_")]
        self.preview_table.setColumnCount(len(headers))
        self.preview_table.setHorizontalHeaderLabels(headers)
        self.preview_table.setRowCount(len(preview_data))

        active_col = preview_data[0].get("_active_col")
        active_col_letter = get_column_letter(active_col) if active_col else None
        if active_col_letter and active_col_letter in headers:
            self._active_preview_column = headers.index(active_col_letter)
        self.preview_table.set_active_drop_column(self._active_preview_column)

        for row_idx, row in enumerate(preview_data):
            is_header = row.get("_is_header", False)
            is_event = row.get("_is_event", False)
            active_col = row.get("_active_col")
            template_row_index = row.get("Row")
            for col_idx, key in enumerate(headers):
                value = row.get(key)
                # Format numerical values to 2 decimal places
                if value is None:
                    display_text = ""
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    display_text = f"{value:.2f}"
                else:
                    display_text = str(value)
                item = QTableWidgetItem(display_text)
                item.setForeground(QBrush(QColor(table_text)))
                bg_color = alt_bg if row_idx % 2 else table_bg
                if key not in ("Row", "Label"):
                    col_index = column_index_from_string(key)
                    if active_col and col_index == active_col:
                        bg_color = active_bg
                    elif is_event:
                        bg_color = event_bg
                    if (
                        self._active_preview_column is not None
                        and col_idx == self._active_preview_column
                        and is_event
                        and template_row_index is not None
                    ):
                        # Format base value to 2 decimal places
                        if value is None:
                            base_text = ""
                        elif isinstance(value, (int, float)) and not isinstance(value, bool):
                            base_text = f"{value:.2f}"
                        else:
                            base_text = str(value)
                        self._preview_base_values[template_row_index] = base_text
                        assignment = wiz.row_assignments.get(template_row_index)
                        if assignment is not None:
                            mapped_value = wiz.value_for_event(assignment, wiz.current_measurement)
                            if pd.isna(mapped_value):
                                display_text = "—"
                            elif isinstance(mapped_value, Real):
                                display_text = f"{mapped_value:.2f}"
                            else:
                                display_text = str(mapped_value)
                            item.setText(display_text)
                if is_header and key == "Label":
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    bg_color = header_bg
                item.setBackground(QBrush(QColor(bg_color)))
                self.preview_table.setItem(row_idx, col_idx, item)
            if is_event and template_row_index is not None:
                self._preview_row_to_template_row[row_idx] = template_row_index

        self.preview_table.resizeColumnsToContents()
        self.preview_table.horizontalHeader().setStretchLastSection(True)

    # --------------------------------------------------
    def event_index_from_mime(self, mime: QMimeData) -> int | None:
        if mime is None or not mime.hasFormat(SESSION_EVENT_MIME):
            return None
        try:
            data = bytes(mime.data(SESSION_EVENT_MIME)).decode().strip()
            return int(data)
        except (ValueError, TypeError, AttributeError):
            return None

    # --------------------------------------------------
    def template_row_for_preview_row(self, preview_row: int) -> int | None:
        return self._preview_row_to_template_row.get(preview_row)

    # --------------------------------------------------
    def assign_event_to_row(self, template_row_index: int, session_event_index: int) -> None:
        combo = self._event_row_widgets.get(template_row_index)
        if combo is not None:
            idx = combo.findData(session_event_index)
            combo.blockSignals(True)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        self._apply_assignment(template_row_index, session_event_index)

    # --------------------------------------------------
    def _apply_assignment(self, row_index: int, event_index: int | None) -> None:
        wiz = self._wizard()
        wiz.update_row_assignment(row_index, event_index)
        self._refresh_value_column()
        self._refresh_status_icons()
        self._update_status_banner()
        self._update_preview_cell_for_row(row_index)

    # --------------------------------------------------
    def _update_preview_cell_for_row(self, template_row_index: int) -> None:
        if self._active_preview_column is None:
            return

        preview_row = None
        for row_idx, tmpl_idx in self._preview_row_to_template_row.items():
            if tmpl_idx == template_row_index:
                preview_row = row_idx
                break

        if preview_row is None:
            return

        item = self.preview_table.item(preview_row, self._active_preview_column)
        if item is None:
            return

        wiz = self._wizard()
        assignment = wiz.row_assignments.get(template_row_index)
        if assignment is None:
            base = self._preview_base_values.get(template_row_index)
            if base is None and wiz.ws is not None and wiz.active_date_column is not None:
                value = wiz.ws.cell(
                    row=template_row_index, column=wiz.active_date_column.column_index
                ).value
                base = "" if value is None else str(value)
            item.setText(base or "")
            return

        value = wiz.value_for_event(assignment, wiz.current_measurement)
        if pd.isna(value):
            text = "—"
        elif isinstance(value, Real):
            text = f"{value:.2f}"
        else:
            text = str(value)
        item.setText(text)

    # --------------------------------------------------
    def _update_status_banner(self) -> None:
        wiz = self._wizard()
        if getattr(wiz, "manual_date_selection_required", False):
            self.info_label.setText(
                "Multiple date columns detected. Pick the active date column before continuing."
            )
            self.info_label.setStyleSheet("color: #8a6d3b;")
            return
        unmapped = sum(1 for value in wiz.row_assignments.values() if value is None)
        if unmapped:
            self.info_label.setText(
                f"{unmapped} event row(s) are still unmapped. Only mapped rows will be written."
            )
            self.info_label.setStyleSheet("color: #8a6d3b;")
            self.select_unmapped_btn.setVisible(True)
        else:
            self.info_label.setText(
                "Review the mappings below. You can override any row before saving."
            )
            self.info_label.setStyleSheet("color: #333;")
            self.select_unmapped_btn.setVisible(False)

    # --------------------------------------------------
    def _on_measurement_changed(self, value: str) -> None:
        wiz = self._wizard()
        wiz.current_measurement = value
        self._refresh_value_column()
        self._refresh_status_icons()
        self._update_status_banner()
        self._refresh_preview()
        self._refresh_session_values_table()

    # --------------------------------------------------
    def _on_redetect(self) -> None:
        wiz = self._wizard()
        if not wiz.prepare_layout(auto=True, force=True):
            self.info_label.setText(wiz.layout_error or "Could not re-run detection.")
            self.info_label.setStyleSheet("color: #a94442;")
            return
        self._populate_date_options()
        self._rebuild_mapping_table()
        self._refresh_preview()
        self._refresh_session_values_table()
        self._update_status_banner()

    # --------------------------------------------------
    def _on_date_changed(self, index: int) -> None:
        if index < 0:
            return
        option = self.pick_date_combo.itemData(index)
        if not isinstance(option, DateColumnOption):
            return
        wiz = self._wizard()
        wiz.set_active_date_column(option)
        wiz.ensure_active_date_value(self)
        self._refresh_preview()
        self._refresh_status_icons()

    # --------------------------------------------------
    def _make_row_selection_handler(self, row_index: int, combo: QComboBox):
        def handler() -> None:
            value = combo.currentData()
            self._apply_assignment(row_index, value)

        return handler

    # --------------------------------------------------
    def _select_all_unmapped(self) -> None:
        for _row_index, combo in self._event_row_widgets.items():
            if combo.currentData() is None:
                combo.showPopup()
                break

    # --------------------------------------------------
    def validatePage(self) -> bool:
        wiz = self._wizard()
        wiz.persist_assignments()
        return True

    # --------------------------------------------------
    def isComplete(self) -> bool:
        return True


class PreviewPage(WizardPageBase):
    """Final page showing a preview and allowing export."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Step 4: Preview & Save")
        layout = QVBoxLayout(self)
        self.preview_view = QTableView()
        self.btn_save = QPushButton("Update Template")
        self.btn_save.clicked.connect(self.save_file)
        layout.addWidget(self.preview_view, 1)
        layout.addWidget(self.btn_save)

    # ------------------------------------------------------
    def initializePage(self) -> None:
        wiz = self._wizard()
        if wiz is None:
            return

        wiz.apply_mapping()
        preview_df = wiz.get_preview_dataframe()
        self.preview_view.setModel(PandasModel(preview_df))
        has_mappings = any(value is not None for value in wiz.row_assignments.values())
        self.btn_save.setEnabled(has_mappings)

    # ------------------------------------------------------
    def save_file(self) -> None:
        template_path = self.field("templatePath")
        if not template_path:
            QMessageBox.warning(self, "Error", "Template path not set.")
            return

        target_path = Path(template_path)
        if not target_path.exists():
            QMessageBox.warning(
                self,
                "Missing File",
                "The original template file is no longer available."
                " Please choose a new template before saving.",
            )
            return

        confirm = QMessageBox.question(
            self,
            "Update Template",
            f"This will overwrite {target_path.name} with the mapped values. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        wiz = self._wizard()
        wiz.apply_mapping()

        try:
            save_workbook(wiz.wb, str(target_path))
        except Exception as exc:  # pragma: no cover - GUI feedback
            QMessageBox.critical(self, "Save Failed", str(exc))
            return

        QMessageBox.information(self, "Template Updated", f"Mappings written to {target_path}")
        self.completeChanged.emit()

    # ------------------------------------------------------
    def isComplete(self) -> bool:
        return self._wizard().wb is not None


# ---------------------------------------------------------------------------
# Main wizard class
# ---------------------------------------------------------------------------


class ExcelMapWizard(QWizard):
    """Wizard dialog used to map events to Excel templates."""

    MAX_PREVIEW_COLUMNS = 6

    def __init__(self, parent=None, events_df: pd.DataFrame | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Map Events to Excel")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.HaveFinishButtonOnEarlyPages)
        self.setMinimumSize(1100, 720)
        self.resize(1200, 750)

        # Workbook/session state
        self.wb = None
        self.ws = None
        self.selected_sheet_name: str | None = None
        self.eventsDF: pd.DataFrame | None = None
        self.events_source: str | None = None

        # Template metadata (from VBA macros or auto-detection)
        self.template_metadata: TemplateMetadata | None = None

        # Derived session data
        self.session_events: list[SessionEventInfo] = []
        self.measurement_columns: list[str] = []
        self.current_measurement: str | None = None

        # Template layout metadata
        self.values_block: tuple[int, int, int, int] | None = None
        self.date_row_index: int | None = None
        self.date_columns: list[DateColumnOption] = []
        self.active_date_column: DateColumnOption | None = None
        self.manual_date_selection_required: bool = False
        self.pending_new_date: bool = False
        self.date_columns_bounds: tuple[int, int] = (0, 0)

        # Row mapping state
        self.event_rows: list[EventRowInfo] = []
        self.row_assignments: dict[int, int | None] = {}

        # Cell history for safe replay
        self._original_values: dict[str, Any] = {}
        self._mapped_cells: set[str] = set()

        # Layout detection cache
        self._layout_ready = False
        self.layout_error = ""

        self.addPage(TemplatePage())
        self.addPage(RowMappingPage())
        self.addPage(PreviewPage())

        if events_df is not None:
            self.set_events_dataframe(events_df, source="session")

    # --------------------------------------------------
    def set_events_dataframe(self, df: pd.DataFrame, *, source: str = "session") -> None:
        self.eventsDF = df.reset_index(drop=True)
        self.events_source = source

        numeric_cols: list[str] = []
        for col in self.eventsDF.columns:
            if col == "Event":
                continue
            series = self.eventsDF[col]
            if pd.api.types.is_numeric_dtype(series):
                numeric_cols.append(col)

        if not numeric_cols:
            raise ValueError("Event data must include at least one numeric measurement column.")

        preferred_order = ["ID (µm)", "Inner Diameter (µm)", "ID"]
        for pref in preferred_order:
            if pref in numeric_cols:
                self.current_measurement = pref
                break
        else:
            if self.current_measurement not in numeric_cols:
                self.current_measurement = numeric_cols[0]

        self.measurement_columns = numeric_cols
        self.session_events = []
        time_series = self.eventsDF["Time (s)"] if "Time (s)" in self.eventsDF.columns else None
        for idx, row in self.eventsDF.iterrows():
            label = str(row.get("Event", f"Event {idx + 1}"))
            time_val = (
                float(row["Time (s)"])
                if time_series is not None and not pd.isna(row["Time (s)"])
                else None
            )
            values = {col: row[col] for col in numeric_cols}
            self.session_events.append(
                SessionEventInfo(index=idx, label=label, time_value=time_val, values=values)
            )

        self._layout_ready = False
        self.row_assignments = {}

    # --------------------------------------------------
    def clear_mapped_cells(self) -> None:
        if not self.ws:
            self._mapped_cells.clear()
            return
        for cell in list(self._mapped_cells):
            if cell in self._original_values:
                self.ws[cell] = self._original_values[cell]
        self._mapped_cells.clear()

    # --------------------------------------------------
    def _remember_original(self, cell_address: str) -> None:
        if self.ws is None:
            return
        if cell_address not in self._original_values:
            self._original_values[cell_address] = self.ws[cell_address].value

    # --------------------------------------------------
    def reset_mapping_state(self) -> None:
        self.clear_mapped_cells()
        self._original_values = {}
        self._layout_ready = False
        self.layout_error = ""
        self.date_columns = []
        self.active_date_column = None
        self.manual_date_selection_required = False
        self.pending_new_date = False
        self.event_rows = []
        self.row_assignments = {}

    # --------------------------------------------------
    def _get_defined_range(self, name: str) -> str | None:
        if self.wb is None or self.ws is None:
            return None
        defined = self.wb.defined_names.get(name)
        if not defined:
            return None
        destinations = list(defined.destinations)

        # First, try to find a range specifically for the selected sheet
        for sheet_name, coord in destinations:
            if sheet_name == self.ws.title:
                return coord

        # Fallback: if there's only one destination and it references a different sheet,
        # use that range anyway (assumes same structure across sheets)
        if destinations and len(destinations) == 1:
            sheet_name, coord = destinations[0]
            # Use the same coordinate range on the selected sheet
            return coord

        return None

    # --------------------------------------------------
    def _resolve_ranges(self) -> None:
        """
        Resolve template ranges from metadata or named ranges.

        Priority:
        1. Template metadata (from VBA macros)
        2. Named ranges (VASO_DATES_ROW, VASO_VALUES_BLOCK)
        3. Raise error if neither found
        """
        # Try metadata first
        if self.template_metadata:
            self.date_row_index = self.template_metadata.date_row

            # Build values block from metadata event rows
            if self.template_metadata.event_rows:
                min_row = min(row.row for row in self.template_metadata.event_rows)
                max_row = max(row.row for row in self.template_metadata.event_rows)
            elif self.template_metadata.event_rows_start and self.template_metadata.event_rows_end:
                min_row = self.template_metadata.event_rows_start
                max_row = self.template_metadata.event_rows_end
            else:
                raise ValueError("Template metadata has no event row information")

            # Date column bounds
            if self.template_metadata.date_columns:
                min_col = min(col.column for col in self.template_metadata.date_columns)
                max_col = max(col.column for col in self.template_metadata.date_columns)
            elif (
                self.template_metadata.date_columns_start
                and self.template_metadata.date_columns_end
            ):
                min_col = self.template_metadata.date_columns_start
                max_col = self.template_metadata.date_columns_end
            else:
                # Default to B:Z
                min_col, max_col = 2, 26

            self.values_block = (min_row, max_row, min_col, max_col)
            self.date_columns_bounds = (min_col, max_col)
            return

        # Fallback to named ranges
        date_range = self._get_defined_range("VASO_DATES_ROW")
        if not date_range:
            raise ValueError(
                "Workbook is missing defined name 'VASO_DATES_ROW'.\n\n"
                "Either add VasoAnalyzer metadata (see Excel Template Setup guide)\n"
                "or define named ranges VASO_DATES_ROW and VASO_VALUES_BLOCK."
            )
        d_min_col, d_min_row, d_max_col, d_max_row = range_boundaries(date_range)
        if d_min_row != d_max_row:
            raise ValueError("VASO_DATES_ROW must refer to a single row.")
        self.date_row_index = d_min_row

        values_range = self._get_defined_range("VASO_VALUES_BLOCK")
        if not values_range:
            raise ValueError(
                "Workbook is missing defined name 'VASO_VALUES_BLOCK'.\n\n"
                "Either add VasoAnalyzer metadata (see Excel Template Setup guide)\n"
                "or define named ranges VASO_DATES_ROW and VASO_VALUES_BLOCK."
            )
        v_min_col, v_min_row, v_max_col, v_max_row = range_boundaries(values_range)
        self.values_block = (v_min_row, v_max_row, v_min_col, v_max_col)
        self.date_columns_bounds = (d_min_col, d_max_col)

    # --------------------------------------------------
    @staticmethod
    def _has_fill(cell) -> bool:
        fill = getattr(cell, "fill", None)
        if not fill:
            return False
        pattern = getattr(fill, "patternType", None)
        return not (not pattern or pattern.lower() == "none")

    # --------------------------------------------------
    def _extract_event_rows(self) -> None:
        """
        Extract event rows from template.

        Uses metadata if available, otherwise scans the values block.
        """
        if self.ws is None or self.values_block is None:
            self.event_rows = []
            return

        # Use metadata if available
        if self.template_metadata and self.template_metadata.event_rows:
            rows: list[EventRowInfo] = []
            for meta_row in self.template_metadata.event_rows:
                cell = self.ws.cell(row=meta_row.row, column=self.template_metadata.label_column)
                rows.append(
                    EventRowInfo(
                        row_index=meta_row.row,
                        label=meta_row.label,
                        is_header=meta_row.is_header,
                        label_cell=cell.coordinate,
                    )
                )
            self.event_rows = rows
        else:
            # Fallback: scan values block
            min_row, max_row, _, _ = self.values_block
            scanned_rows: list[EventRowInfo] = []
            for row_idx in range(min_row, max_row + 1):
                cell = self.ws.cell(row=row_idx, column=1)
                value = cell.value
                label = str(value).strip() if value not in (None, "") else ""
                if not label:
                    continue
                is_header = bool(
                    getattr(cell, "font", None) and getattr(cell.font, "bold", False)
                ) and self._has_fill(cell)
                scanned_rows.append(
                    EventRowInfo(
                        row_index=row_idx,
                        label=label,
                        is_header=is_header,
                        label_cell=cell.coordinate,
                    )
                )
            self.event_rows = scanned_rows

        valid_rows = {row.row_index for row in self.event_rows if not row.is_header}
        self.row_assignments = {
            row_idx: self.row_assignments.get(row_idx) for row_idx in valid_rows
        }

    # --------------------------------------------------
    def _build_date_options(self) -> None:
        """
        Build date column options.

        Uses metadata if available, otherwise scans date row.
        """
        self.date_columns = []
        if self.ws is None or self.values_block is None or self.date_row_index is None:
            return

        # Use metadata if available
        if self.template_metadata and self.template_metadata.date_columns:
            for meta_col in self.template_metadata.date_columns:
                cell = self.ws.cell(row=self.date_row_index, column=meta_col.column)
                # Re-count empty slots (metadata might be stale)
                empty_slots = 0
                for event_row in self.event_rows:
                    if event_row.is_header:
                        continue
                    target_cell = self.ws.cell(row=event_row.row_index, column=meta_col.column)
                    if target_cell.value in (None, ""):
                        empty_slots += 1
                option = DateColumnOption(
                    column_index=meta_col.column,
                    cell_address=cell.coordinate,
                    value=cell.value,  # Use current value, not cached
                    empty_slots=empty_slots,
                )
                self.date_columns.append(option)
        else:
            # Fallback: scan date row
            min_row, max_row, min_col, max_col = self.values_block
            d_min_col, d_max_col = self.date_columns_bounds

            for col_idx in range(d_min_col, d_max_col + 1):
                cell = self.ws.cell(row=self.date_row_index, column=col_idx)
                value = cell.value
                empty_slots = 0
                for event_row in self.event_rows:
                    if event_row.is_header:
                        continue
                    if not (min_col <= col_idx <= max_col):
                        continue
                    target_cell = self.ws.cell(row=event_row.row_index, column=col_idx)
                    if target_cell.value in (None, ""):
                        empty_slots += 1
                option = DateColumnOption(
                    column_index=col_idx,
                    cell_address=cell.coordinate,
                    value=value,
                    empty_slots=empty_slots,
                )
                self.date_columns.append(option)

    # --------------------------------------------------
    @staticmethod
    def _is_valid_date(value: Any) -> bool:
        if value in (None, ""):
            return False
        try:
            pd.to_datetime(value)
            return True
        except (ValueError, TypeError, pd.errors.OutOfBoundsDatetime):
            return False

    # --------------------------------------------------
    def auto_select_date_column(self) -> None:
        self.manual_date_selection_required = False
        self.pending_new_date = False
        if not self.date_columns:
            self.active_date_column = None
            return

        if self.active_date_column:
            for option in self.date_columns:
                if option.column_index == self.active_date_column.column_index:
                    self.active_date_column = option
                    break

        valid_dates = [opt for opt in self.date_columns if self._is_valid_date(opt.value)]
        if len(valid_dates) == 1:
            self.active_date_column = valid_dates[0]
            return
        if len(valid_dates) > 1:
            empties = [opt for opt in valid_dates if opt.empty_slots > 0]
            if empties:
                self.active_date_column = max(empties, key=lambda opt: opt.column_index)
            else:
                self.active_date_column = max(valid_dates, key=lambda opt: opt.column_index)
                self.manual_date_selection_required = True
            return

        empty_cells = [opt for opt in self.date_columns if opt.value in (None, "")]
        if empty_cells:
            self.active_date_column = empty_cells[0]
            self.pending_new_date = True
            return

        # Fallback to last column if everything contains non-date data
        self.active_date_column = self.date_columns[-1]
        self.manual_date_selection_required = True

    # --------------------------------------------------
    def ensure_active_date_value(self, parent) -> None:
        if self.ws is None or not self.active_date_column:
            return
        cell = self.ws[self.active_date_column.cell_address]
        if cell.value not in (None, "") and not self.pending_new_date:
            return

        prompt = "Enter the column label (e.g., experiment date) for this mapping:"
        text, ok = QInputDialog.getText(parent, "Set Date Label", prompt)
        if not ok or not text.strip():
            return

        self._remember_original(self.active_date_column.cell_address)
        value = text.strip()
        cell.value = value
        self.active_date_column.value = value
        self.active_date_column.is_new = True
        self._mapped_cells.add(self.active_date_column.cell_address)
        self.pending_new_date = False
        self._update_date_option_value(self.active_date_column.column_index, value)

    # --------------------------------------------------
    def _update_date_option_value(self, column_index: int, value: Any) -> None:
        for option in self.date_columns:
            if option.column_index == column_index:
                option.value = value
                break

    # --------------------------------------------------
    def set_active_date_column(self, option: DateColumnOption) -> None:
        self.active_date_column = option
        self.manual_date_selection_required = False
        self.auto_assign_rows(force=False)

    # --------------------------------------------------
    def update_row_assignment(self, row_index: int, event_index: int | None) -> None:
        if event_index is None:
            self.row_assignments[row_index] = None
        else:
            self.row_assignments[row_index] = int(event_index)

    # --------------------------------------------------
    @staticmethod
    def _normalize_numeric(value: Any) -> Any:
        try:
            return round(float(value), 4)
        except (ValueError, TypeError):
            return str(value).strip()

    # --------------------------------------------------
    def _load_existing_assignments_from_sheet(self) -> None:
        if self.ws is None or self.active_date_column is None or not self.current_measurement:
            return
        col_idx = self.active_date_column.column_index
        measurement = self.current_measurement
        value_map: dict[Any, list[int]] = {}
        for event in self.session_events:
            value = event.values.get(measurement)
            if pd.isna(value):
                continue
            key = self._normalize_numeric(value)
            value_map.setdefault(key, []).append(event.index)

        for row in self.event_rows:
            if row.is_header:
                continue
            if (
                row.row_index not in self.row_assignments
                or self.row_assignments[row.row_index] is not None
            ):
                continue
            cell_value = self.ws.cell(row=row.row_index, column=col_idx).value
            if cell_value in (None, ""):
                continue
            key = self._normalize_numeric(cell_value)
            matches = value_map.get(key)
            if matches:
                self.row_assignments[row.row_index] = matches[0]

    # --------------------------------------------------
    def auto_assign_rows(self, force: bool = False) -> None:
        valid_rows = [row.row_index for row in self.event_rows if not row.is_header]
        if force or not self.row_assignments:
            self.row_assignments = {row_idx: None for row_idx in valid_rows}
        else:
            self.row_assignments = {
                row_idx: self.row_assignments.get(row_idx) for row_idx in valid_rows
            }

        if self.active_date_column:
            self._load_existing_assignments_from_sheet()

        label_map: dict[str, deque[int]] = {}
        for event in self.session_events:
            key = event.label.strip().lower()
            label_map.setdefault(key, deque()).append(event.index)

        for row in self.event_rows:
            if row.is_header:
                continue
            if self.row_assignments.get(row.row_index) is not None:
                continue
            key = row.label.strip().lower()
            queue = label_map.get(key)
            if queue:
                self.row_assignments[row.row_index] = queue.popleft()

    # --------------------------------------------------
    def value_for_event(self, event_index: int, measurement: str | None) -> Any:
        if measurement is None:
            return float("nan")
        if event_index < 0 or event_index >= len(self.session_events):
            return float("nan")
        return self.session_events[event_index].values.get(measurement, float("nan"))

    # --------------------------------------------------
    def prepare_layout(self, auto: bool = False, force: bool = False) -> bool:
        if force:
            self._layout_ready = False

        if self._layout_ready and not force:
            if auto:
                self.auto_select_date_column()
                self.auto_assign_rows(force=False)
            return True

        if self.wb is None or self.ws is None or self.eventsDF is None:
            self.layout_error = "Load an Excel template and event data first."
            return False

        try:
            self._resolve_ranges()
            self._extract_event_rows()
            self._build_date_options()
            self.auto_select_date_column()
            self.auto_assign_rows(force=True)
            self._layout_ready = True
            self.layout_error = ""
        except Exception as exc:  # pragma: no cover - GUI feedback
            self.layout_error = str(exc)
            self._layout_ready = False
            return False

        return True

    # --------------------------------------------------
    def preview_template_data(self, limit: int = 30) -> list[dict[str, Any]]:
        if self.ws is None or self.values_block is None:
            return []

        min_row, max_row, min_col, max_col = self.values_block
        active_col = self.active_date_column.column_index if self.active_date_column else None

        cols = list(range(min_col, max_col + 1))
        if len(cols) > self.MAX_PREVIEW_COLUMNS:
            cols = cols[: self.MAX_PREVIEW_COLUMNS]
            if active_col and active_col not in cols:
                cols.append(active_col)
        cols = sorted(set(cols))

        data: list[dict[str, Any]] = []
        for row_idx in range(min_row, max_row + 1):
            if len(data) >= limit:
                break
            label_cell = self.ws.cell(row=row_idx, column=1)
            label = label_cell.value if label_cell.value not in (None, "") else ""
            is_header = False
            is_event = False
            for event_row in self.event_rows:
                if event_row.row_index == row_idx:
                    is_header = event_row.is_header
                    is_event = not event_row.is_header
                    break
            row_data: dict[str, Any] = {
                "Row": row_idx,
                "Label": label,
                "_is_header": is_header,
                "_is_event": is_event,
                "_active_col": active_col,
            }
            for col_idx in cols:
                letter = get_column_letter(col_idx)
                value = self.ws.cell(row=row_idx, column=col_idx).value
                row_data[letter] = value
            data.append(row_data)
        return data

    # --------------------------------------------------
    def apply_mapping(self) -> list[tuple[int, str, Any]]:
        self.clear_mapped_cells()
        results: list[tuple[int, str, Any]] = []

        if (
            self.ws is None
            or self.values_block is None
            or self.active_date_column is None
            or not self.current_measurement
        ):
            return results

        min_row, max_row, min_col, max_col = self.values_block
        if not (min_col <= self.active_date_column.column_index <= max_col):
            return results

        date_cell = self.ws[self.active_date_column.cell_address]
        if self.active_date_column.value not in (None, ""):
            self._remember_original(self.active_date_column.cell_address)
            date_cell.value = self.active_date_column.value
            self._mapped_cells.add(self.active_date_column.cell_address)

        measurement = self.current_measurement
        for row in self.event_rows:
            if row.is_header:
                continue
            assignment = self.row_assignments.get(row.row_index)
            if assignment is None:
                continue
            if not (min_row <= row.row_index <= max_row):
                continue
            cell_address = f"{self.active_date_column.letter}{row.row_index}"
            self._remember_original(cell_address)
            value = self.value_for_event(assignment, measurement)
            cell_value = None if pd.isna(value) else value
            self.ws[cell_address] = cell_value
            self._mapped_cells.add(cell_address)
            results.append((row.row_index, row.label, cell_value))

        return results

    # --------------------------------------------------
    def persist_assignments(self) -> None:
        # Placeholder for future persistence (e.g., to workbook metadata)
        pass

    # --------------------------------------------------
    def get_preview_dataframe(self, limit: int = 25) -> pd.DataFrame:
        if self.ws is None or self.active_date_column is None or not self.current_measurement:
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        col_idx = self.active_date_column.column_index
        measurement = self.current_measurement

        for row in self.event_rows:
            if row.is_header:
                continue
            cell_value = self.ws.cell(row=row.row_index, column=col_idx).value
            rows.append({"Row": row.row_index, "Label": row.label, measurement: cell_value})
            if len(rows) >= limit:
                break

        return pd.DataFrame(rows)
