# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Preview dialog shown before committing a data import."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

log = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 10
_MAX_PREVIEW_COLS = 8


class DataPreviewDialog(QDialog):
    """Shows a preview of trace and event data before importing.

    Displays the first few rows of the data so users can verify that
    column mappings are correct before committing the import.
    """

    def __init__(
        self,
        parent=None,
        *,
        trace_path: str | None = None,
        trace_df: pd.DataFrame | None = None,
        events_df: pd.DataFrame | None = None,
        event_count: int = 0,
        source_format: str = "csv",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Data Preview")
        self.setMinimumSize(700, 450)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        filename = Path(trace_path).name if trace_path else "Unknown"
        header = QLabel(f"Preview: {filename}")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header)

        if source_format != "csv":
            format_label = QLabel(f"Format: {source_format}")
            format_label.setStyleSheet("color: #666;")
            layout.addWidget(format_label)

        # Trace preview
        if trace_df is not None and not trace_df.empty:
            trace_group = QGroupBox(f"Trace Data ({len(trace_df):,} rows, {len(trace_df.columns)} columns)")
            trace_layout = QVBoxLayout(trace_group)

            trace_table = self._build_table(trace_df)
            trace_layout.addWidget(trace_table)

            # Summary stats
            stats = self._build_trace_stats(trace_df)
            if stats:
                stats_label = QLabel(stats)
                stats_label.setStyleSheet("color: #666; font-size: 11px;")
                stats_label.setWordWrap(True)
                trace_layout.addWidget(stats_label)

            layout.addWidget(trace_group)

        # Events preview
        if events_df is not None and not events_df.empty:
            events_group = QGroupBox(f"Events ({len(events_df):,} rows)")
            events_layout = QVBoxLayout(events_group)

            events_table = self._build_table(events_df)
            events_layout.addWidget(events_table)

            layout.addWidget(events_group)
        elif event_count > 0:
            events_label = QLabel(f"Events: {event_count} events detected")
            events_label.setStyleSheet("color: #666;")
            layout.addWidget(events_label)

        # Warning area
        warnings = self._check_data_warnings(trace_df, events_df)
        if warnings:
            warn_group = QGroupBox("Warnings")
            warn_layout = QVBoxLayout(warn_group)
            for w in warnings:
                wl = QLabel(f"\u26a0 {w}")
                wl.setWordWrap(True)
                wl.setStyleSheet("color: #d97706;")
                warn_layout.addWidget(wl)
            layout.addWidget(warn_group)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

    def _build_table(self, df: pd.DataFrame) -> QTableWidget:
        """Build a read-only preview table from a DataFrame."""
        preview = df.head(_MAX_PREVIEW_ROWS)
        cols = list(preview.columns[:_MAX_PREVIEW_COLS])
        has_more_cols = len(preview.columns) > _MAX_PREVIEW_COLS

        table = QTableWidget(len(preview), len(cols) + (1 if has_more_cols else 0))
        headers = [str(c) for c in cols]
        if has_more_cols:
            headers.append(f"... +{len(preview.columns) - _MAX_PREVIEW_COLS}")
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for r in range(len(preview)):
            for c, col_name in enumerate(cols):
                val = preview.iloc[r][col_name]
                text = f"{val:.6g}" if isinstance(val, float) else str(val)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, c, item)

        table.resizeColumnsToContents()
        table.setMaximumHeight(min(300, 30 * (len(preview) + 1) + 30))
        return table

    @staticmethod
    def _build_trace_stats(df: pd.DataFrame) -> str:
        """Build a summary string for trace data."""
        parts = []
        # Find time column
        for col in df.columns:
            if "time" in col.lower() or col.lower() in ("t", "t_seconds"):
                numeric = pd.to_numeric(df[col], errors="coerce")
                valid = numeric.dropna()
                if not valid.empty:
                    parts.append(f"Time range: {valid.min():.2f}\u2013{valid.max():.2f} s")
                    duration = valid.max() - valid.min()
                    if duration > 60:
                        parts.append(f"Duration: {duration / 60:.1f} min")
                    else:
                        parts.append(f"Duration: {duration:.1f} s")
                break

        # Check for diameter columns
        for col in df.columns:
            cl = col.lower()
            if "inner" in cl and "diam" in cl:
                numeric = pd.to_numeric(df[col], errors="coerce").dropna()
                if not numeric.empty:
                    parts.append(f"Inner diameter: {numeric.min():.1f}\u2013{numeric.max():.1f}")
                break

        return "  |  ".join(parts)

    @staticmethod
    def _check_data_warnings(
        trace_df: pd.DataFrame | None,
        events_df: pd.DataFrame | None,
    ) -> list[str]:
        """Check for potential data issues and return warning strings."""
        warnings: list[str] = []

        if trace_df is not None:
            # Check for NaN in time column
            for col in trace_df.columns:
                if "time" in col.lower():
                    numeric = pd.to_numeric(trace_df[col], errors="coerce")
                    nan_count = int(numeric.isna().sum())
                    if nan_count > 0:
                        pct = nan_count / len(trace_df) * 100
                        warnings.append(
                            f"Time column '{col}' has {nan_count} non-numeric "
                            f"values ({pct:.1f}%)"
                        )
                    break

            # Check for negative diameter values
            for col in trace_df.columns:
                cl = col.lower()
                if "diam" in cl:
                    numeric = pd.to_numeric(trace_df[col], errors="coerce")
                    neg_count = int((numeric < 0).sum())
                    if neg_count > 0:
                        warnings.append(
                            f"Column '{col}' has {neg_count} negative values "
                            f"(will be treated as missing)"
                        )

        return warnings
