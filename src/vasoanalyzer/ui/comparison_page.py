# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Comparison page — full-window side-by-side dataset comparison."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.comparison_window import (
    ComparisonPanel,
    _apply_toolbar_style,
    _CHANNELS,
    _load_icon,
    _MAX_PANELS,
)
from vasoanalyzer.ui.drag_drop import DATASET_MIME_TYPE, decode_dataset_mime
from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)

# Mapping from SQLite canonical column names to UI-facing labels
# expected by TraceModel.from_dataframe.
_DB_TO_UI_COLUMNS = {
    "t_seconds": "Time (s)",
    "inner_diam": "Inner Diameter",
    "outer_diam": "Outer Diameter",
    "p_avg": "Avg Pressure (mmHg)",
    "p1": "Pressure 1 (mmHg)",
    "p2": "Set Pressure (mmHg)",
    "frame_number": "FrameNumber",
    "tiff_page": "TiffPage",
}


class ComparisonPage(QWidget):
    """Full-window comparison page that lives in the main QStackedWidget.

    Mirrors the main data view layout but shows up to 4 datasets
    side-by-side for the selected channel.
    """

    back_requested = pyqtSignal()  # emitted when user clicks "Back to Data"

    def __init__(self, host: "VasoAnalyzerApp", parent: QWidget | None = None):
        super().__init__(parent)
        self._host = host
        self._panels: list[ComparisonPanel] = []
        self._channel = "inner"
        self._mouse_mode = "pan"
        self._sync_enabled = True
        self._syncing_time = False

        self.setObjectName("ComparisonPage")
        self.setAcceptDrops(True)

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header bar (back + toolbar + channel) ────────────────────
        self._header = QFrame()
        self._header.setObjectName("ComparisonHeader")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(10)

        # Back button — styled to match the app
        back_btn = QToolButton()
        back_btn.setObjectName("ComparisonBackBtn")
        back_btn.setIcon(_load_icon("Back.svg"))
        back_btn.setText(" Back to Data")
        back_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        back_btn.setToolTip("Return to the data workspace")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setObjectName("ComparisonSep")
        header_layout.addWidget(sep)

        # Toolbar
        header_layout.addWidget(self._build_toolbar())

        # Channel selector
        ch_label = QLabel("Channel:")
        ch_label.setObjectName("ComparisonChLabel")
        header_layout.addWidget(ch_label)
        self._combo = QComboBox()
        self._combo.setObjectName("ComparisonChannelCombo")
        for key, label in _CHANNELS:
            self._combo.addItem(label, key)
        self._combo.currentIndexChanged.connect(self._on_channel_changed)
        header_layout.addWidget(self._combo)

        header_layout.addStretch()

        # Status hint
        self._hint_label = QLabel()
        self._hint_label.setObjectName("ComparisonHint")
        header_layout.addWidget(self._hint_label)

        outer.addWidget(self._header)

        # ── Thin separator line under header ─────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("ComparisonHeaderLine")
        line.setFixedHeight(1)
        outer.addWidget(line)

        # ── Main content: sidebar + panel grid ───────────────────────
        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._content_splitter.setObjectName("ComparisonSplitter")
        self._content_splitter.setHandleWidth(1)

        # ── Sidebar ──────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("ComparisonSidebar")
        sidebar.setMinimumWidth(170)
        sidebar.setMaximumWidth(260)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 10, 6, 10)
        sidebar_layout.setSpacing(6)

        sidebar_header = QLabel("Datasets")
        sidebar_header.setObjectName("ComparisonSidebarTitle")
        sidebar_layout.addWidget(sidebar_header)

        self._dataset_list = QListWidget()
        self._dataset_list.setObjectName("ComparisonDatasetList")
        self._dataset_list.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        sidebar_layout.addWidget(self._dataset_list, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._add_btn = QPushButton("Add…")
        self._add_btn.setObjectName("ComparisonAddBtn")
        self._add_btn.setToolTip("Select a sample from the project to compare")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_clicked)
        btn_row.addWidget(self._add_btn)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setObjectName("ComparisonRemoveBtn")
        self._remove_btn.setToolTip("Remove selected dataset from comparison")
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        btn_row.addWidget(self._remove_btn)
        sidebar_layout.addLayout(btn_row)

        drop_hint = QLabel("or drag samples from\nthe project tree")
        drop_hint.setObjectName("ComparisonDropHint")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(drop_hint)

        self._content_splitter.addWidget(sidebar)

        # ── Panel area ───────────────────────────────────────────────
        panel_area = QWidget()
        panel_area.setObjectName("ComparisonPanelArea")
        panel_area_layout = QVBoxLayout(panel_area)
        panel_area_layout.setContentsMargins(6, 6, 6, 6)
        panel_area_layout.setSpacing(0)

        # Vertical stack for panels (like main window channel tracks)
        self._panel_stack_widget = QWidget()
        self._panel_stack = QVBoxLayout(self._panel_stack_widget)
        self._panel_stack.setContentsMargins(0, 0, 0, 0)
        self._panel_stack.setSpacing(4)
        panel_area_layout.addWidget(self._panel_stack_widget, 1)

        self._empty_label = QLabel(
            "Add datasets using the sidebar\nor drag them from the project tree"
        )
        self._empty_label.setObjectName("ComparisonEmptyHint")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_area_layout.addWidget(self._empty_label)

        self._content_splitter.addWidget(panel_area)
        self._content_splitter.setStretchFactor(0, 0)
        self._content_splitter.setStretchFactor(1, 1)
        self._content_splitter.setSizes([200, 900])

        outer.addWidget(self._content_splitter, 1)

        self._apply_page_style()
        self._refresh_state()

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setObjectName("PlotToolbar")
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setMovable(False)
        tb.setFloatable(False)
        _apply_toolbar_style(tb)

        # Mouse-mode toggle
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        self._act_pan = QAction(_load_icon("Pan.svg"), "Pan", self)
        self._act_pan.setCheckable(True)
        self._act_pan.setChecked(True)
        self._act_pan.setToolTip("Pan — drag to scroll the trace horizontally")
        self._act_pan.toggled.connect(
            lambda checked: self._set_mouse_mode("pan") if checked else None
        )
        mode_group.addAction(self._act_pan)
        tb.addAction(self._act_pan)

        self._act_zoom_box = QAction(_load_icon("Zoom.svg"), "Select", self)
        self._act_zoom_box.setCheckable(True)
        self._act_zoom_box.setToolTip("Select — drag a rectangle to zoom into that time range")
        self._act_zoom_box.toggled.connect(
            lambda checked: self._set_mouse_mode("rect") if checked else None
        )
        mode_group.addAction(self._act_zoom_box)
        tb.addAction(self._act_zoom_box)

        tb.addSeparator()

        act_zoom_all = QAction(_load_icon("Home.svg"), "Zoom All", self)
        act_zoom_all.setToolTip("Reset all panels to full trace range")
        act_zoom_all.triggered.connect(self._on_zoom_all_x)
        tb.addAction(act_zoom_all)

        act_zoom_in = QAction(_load_icon("Zoom.svg"), "Zoom In", self)
        act_zoom_in.setToolTip("Zoom In — show less time (all panels)")
        act_zoom_in.triggered.connect(lambda: self._on_zoom_x(0.8))
        tb.addAction(act_zoom_in)

        act_zoom_out = QAction(_load_icon("ZoomOut.svg"), "Zoom Out", self)
        act_zoom_out.setToolTip("Zoom Out — show more time (all panels)")
        act_zoom_out.triggered.connect(lambda: self._on_zoom_x(1.25))
        tb.addAction(act_zoom_out)

        tb.addSeparator()

        act_autoscale_once = QAction(_load_icon("autoscale.svg"), "Autoscale Y", self)
        act_autoscale_once.setToolTip("Fit Y axis to visible data (all panels)")
        act_autoscale_once.triggered.connect(self._on_autoscale_y_once)
        tb.addAction(act_autoscale_once)

        return tb

    def _apply_page_style(self) -> None:
        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        text_color = CURRENT_THEME.get("text", "#000000")
        border = CURRENT_THEME.get("panel_border", "#d0d0d0")
        panel_bg = CURRENT_THEME.get("panel_bg", CURRENT_THEME.get("table_bg", bg))
        button_bg = CURRENT_THEME.get("button_bg", panel_bg)
        hover_bg = CURRENT_THEME.get("button_hover_bg", CURRENT_THEME.get("selection_bg", bg))
        pressed_bg = CURRENT_THEME.get("button_active_bg", hover_bg)
        selection_bg = CURRENT_THEME.get("selection_bg", "#cce5ff")
        accent = CURRENT_THEME.get("accent", "#3B82F6")
        radius = int(CURRENT_THEME.get("panel_radius", 6))
        disabled_text = CURRENT_THEME.get("text_disabled", text_color)

        self.setStyleSheet(f"""
            /* Page background */
            QWidget#ComparisonPage {{
                background: {bg};
            }}

            /* Header bar */
            QFrame#ComparisonHeader {{
                background: {bg};
            }}
            QFrame#ComparisonHeaderLine {{
                background: {border};
            }}
            QFrame#ComparisonSep {{
                color: {border};
            }}

            /* Back button */
            QToolButton#ComparisonBackBtn {{
                background: {button_bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                padding: 5px 12px;
                color: {text_color};
                font-weight: 500;
            }}
            QToolButton#ComparisonBackBtn:hover {{
                background: {hover_bg};
            }}
            QToolButton#ComparisonBackBtn:pressed {{
                background: {pressed_bg};
            }}

            /* Channel label */
            QLabel#ComparisonChLabel {{
                color: {text_color};
                font-weight: 500;
            }}

            /* Channel combo */
            QComboBox#ComparisonChannelCombo {{
                background: {button_bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                padding: 4px 8px;
                color: {text_color};
                min-width: 130px;
            }}

            /* Hint label */
            QLabel#ComparisonHint {{
                color: {disabled_text};
                font-size: 12px;
            }}

            /* Sidebar */
            QFrame#ComparisonSidebar {{
                background: {panel_bg};
                border-right: 1px solid {border};
            }}
            QLabel#ComparisonSidebarTitle {{
                color: {text_color};
                font-weight: 600;
                font-size: 13px;
            }}

            /* Dataset list */
            QListWidget#ComparisonDatasetList {{
                background: {bg};
                color: {text_color};
                border: 1px solid {border};
                border-radius: {radius}px;
                outline: none;
            }}
            QListWidget#ComparisonDatasetList::item {{
                padding: 5px 8px;
                border-radius: {max(2, radius - 2)}px;
                margin: 1px 2px;
            }}
            QListWidget#ComparisonDatasetList::item:selected {{
                background: {selection_bg};
            }}
            QListWidget#ComparisonDatasetList::item:hover {{
                background: {hover_bg};
            }}

            /* Sidebar buttons */
            QPushButton#ComparisonAddBtn,
            QPushButton#ComparisonRemoveBtn {{
                background: {button_bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                padding: 5px 10px;
                color: {text_color};
                font-weight: 500;
            }}
            QPushButton#ComparisonAddBtn:hover,
            QPushButton#ComparisonRemoveBtn:hover {{
                background: {hover_bg};
            }}
            QPushButton#ComparisonAddBtn:pressed,
            QPushButton#ComparisonRemoveBtn:pressed {{
                background: {pressed_bg};
            }}
            QPushButton#ComparisonAddBtn:disabled,
            QPushButton#ComparisonRemoveBtn:disabled {{
                color: {disabled_text};
                background: {bg};
            }}

            /* Drop hint */
            QLabel#ComparisonDropHint {{
                color: {disabled_text};
                font-size: 11px;
                padding: 4px;
            }}

            /* Panel area */
            QWidget#ComparisonPanelArea {{
                background: {bg};
            }}

            /* Empty state */
            QLabel#ComparisonEmptyHint {{
                color: {disabled_text};
                font-size: 14px;
                padding: 40px;
            }}

            /* Splitter handle */
            QSplitter#ComparisonSplitter::handle {{
                background: {border};
            }}
        """)

    # ------------------------------------------------------------------
    # Toolbar handlers
    # ------------------------------------------------------------------
    def _set_mouse_mode(self, mode: str) -> None:
        self._mouse_mode = mode
        for panel in self._panels:
            panel.set_mouse_mode(mode)

    def _on_zoom_all_x(self) -> None:
        for panel in self._panels:
            panel.zoom_all_x()

    def _on_zoom_x(self, factor: float) -> None:
        for panel in self._panels:
            panel.zoom_x(factor)

    def _on_autoscale_y_once(self) -> None:
        for panel in self._panels:
            panel.autoscale_y_once()

    def _on_channel_changed(self, index: int) -> None:
        self._channel = self._combo.itemData(index)
        for panel in self._panels:
            panel.set_channel(self._channel)

    # ------------------------------------------------------------------
    # Add / Remove datasets
    # ------------------------------------------------------------------
    def _on_add_clicked(self) -> None:
        """Show a picker listing all project samples and add the selected one."""
        samples = self._get_all_samples()
        if not samples:
            QMessageBox.information(
                self, "No Samples", "Open a project with loaded samples first."
            )
            return

        if len(self._panels) >= _MAX_PANELS:
            QMessageBox.information(
                self, "Maximum Reached", f"You can compare up to {_MAX_PANELS} datasets."
            )
            return

        from PyQt6.QtWidgets import QInputDialog

        names = [f"{s['exp_name']}  /  {s['name']}" for s in samples]
        chosen, ok = QInputDialog.getItem(
            self, "Add Dataset", "Select a sample to compare:", names, 0, False
        )
        if ok and chosen:
            idx = names.index(chosen)
            info = samples[idx]
            self._add_dataset(info["dataset_id"], info["name"])

    def _on_remove_clicked(self) -> None:
        row = self._dataset_list.currentRow()
        if 0 <= row < len(self._panels):
            panel = self._panels[row]
            self._remove_panel(panel)

    def _get_all_samples(self) -> list[dict]:
        """Return a list of dicts with dataset info for all samples in the project."""
        project = self._host.current_project
        if project is None:
            return []
        result = []
        for exp in project.experiments:
            for s in exp.samples:
                did = getattr(s, "dataset_id", None)
                if did is not None:
                    result.append({
                        "dataset_id": did,
                        "name": getattr(s, "name", "") or f"Sample {did}",
                        "exp_name": getattr(exp, "name", "") or "Experiment",
                        "sample": s,
                    })
        return result

    def _add_dataset(self, dataset_id: int, name: str) -> None:
        if len(self._panels) >= _MAX_PANELS:
            return

        # Check for duplicates and suffix if needed
        existing = sum(1 for p in self._panels if p.dataset_id == dataset_id)
        display_name = f"{name} ({existing + 1})" if existing > 0 else name

        trace = self._load_trace(dataset_id)
        if trace is None:
            QMessageBox.information(
                self,
                "Dataset Not Loaded",
                f'Could not load trace data for "{name}".',
            )
            return

        events_info = self._load_events(dataset_id)

        panel = ComparisonPanel(
            dataset_id,
            display_name,
            trace,
            self._channel,
            mouse_mode=self._mouse_mode,
            autoscale_y=False,
            show_nav_bar=False,
            events=events_info,
            parent=self,
        )
        panel.close_requested.connect(self._remove_panel)
        self._panels.append(panel)

        # Add to sidebar list
        item = QListWidgetItem(display_name)
        item.setData(Qt.ItemDataRole.UserRole, dataset_id)
        self._dataset_list.addItem(item)

        self._relayout_panels()
        self._refresh_state()

    def _load_trace(self, dataset_id: int):
        """Return a TraceModel for dataset_id.

        First checks in-memory cache on the sample, then falls back to
        loading from the project's SQLite database.
        """
        from vasoanalyzer.core.trace_model import TraceModel

        project = self._host.current_project
        if project is None:
            return None

        # 1) Try the in-memory cache first
        for exp in project.experiments:
            for s in exp.samples:
                if getattr(s, "dataset_id", None) == dataset_id:
                    if s.trace_data is not None:
                        try:
                            return TraceModel.from_dataframe(s.trace_data)
                        except Exception:
                            log.warning(
                                "Could not build TraceModel from cached data for dataset_id=%s",
                                dataset_id,
                            )

        # 2) Fall back to loading from the project database
        ctx = getattr(self._host, "project_ctx", None)
        if ctx is not None:
            try:
                df = ctx.repo.get_trace(dataset_id)
                if df is not None and not df.empty:
                    # DB uses canonical column names; TraceModel expects UI labels
                    df = df.rename(columns=_DB_TO_UI_COLUMNS)
                    return TraceModel.from_dataframe(df)
            except Exception:
                log.warning(
                    "Could not load trace from database for dataset_id=%s",
                    dataset_id,
                    exc_info=True,
                )

        return None

    def _load_events(self, dataset_id: int) -> dict | None:
        """Return event times and labels for a dataset, or None."""
        import pandas as pd

        project = self._host.current_project
        if project is None:
            return None

        events_df: pd.DataFrame | None = None

        # 1) Try in-memory cache on the sample
        for exp in project.experiments:
            for s in exp.samples:
                if getattr(s, "dataset_id", None) == dataset_id:
                    if s.events_data is not None and not s.events_data.empty:
                        events_df = s.events_data
                    break
            if events_df is not None:
                break

        # 2) Fall back to project database
        if events_df is None:
            ctx = getattr(self._host, "project_ctx", None)
            if ctx is not None:
                with contextlib.suppress(Exception):
                    events_df = ctx.repo.get_events(dataset_id)

        if events_df is None or events_df.empty:
            return None

        # Extract times and labels
        time_col = None
        for candidate in ("Time (s)", "t_seconds", "time"):
            if candidate in events_df.columns:
                time_col = candidate
                break
        label_col = None
        for candidate in ("Event", "event", "label"):
            if candidate in events_df.columns:
                label_col = candidate
                break

        if time_col is None:
            return None

        times = events_df[time_col].tolist()
        labels = events_df[label_col].tolist() if label_col else [str(i + 1) for i in range(len(times))]
        return {"times": times, "labels": labels}

    def _remove_panel(self, panel: ComparisonPanel) -> None:
        if panel in self._panels:
            idx = self._panels.index(panel)
            self._panels.remove(panel)
            # Remove from sidebar list
            if 0 <= idx < self._dataset_list.count():
                self._dataset_list.takeItem(idx)
        panel.setParent(None)
        panel.deleteLater()
        self._relayout_panels()
        self._refresh_state()

    def _relayout_panels(self) -> None:
        """Stack panels vertically — each gets full width, like main window tracks."""
        # Remove all widgets from layout (without deleting them)
        while self._panel_stack.count():
            item = self._panel_stack.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        for panel in self._panels:
            self._panel_stack.addWidget(panel, 1)
            panel.setVisible(True)

    def _refresh_state(self) -> None:
        has_panels = bool(self._panels)
        self._empty_label.setVisible(not has_panels)
        self._panel_stack_widget.setVisible(has_panels)
        self._remove_btn.setEnabled(has_panels)

        remaining = _MAX_PANELS - len(self._panels)
        self._add_btn.setEnabled(remaining > 0)
        if remaining == 0:
            self._hint_label.setText(f"Maximum {_MAX_PANELS} datasets reached")
        elif has_panels:
            slot_word = "slot" if remaining == 1 else "slots"
            self._hint_label.setText(f"{remaining} {slot_word} remaining")
        else:
            self._hint_label.setText("")

    # ------------------------------------------------------------------
    # Drag-and-drop support (from project tree)
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(DATASET_MIME_TYPE) and len(self._panels) < _MAX_PANELS:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(DATASET_MIME_TYPE) and len(self._panels) < _MAX_PANELS:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        data = decode_dataset_mime(event.mimeData())
        if data:
            self._add_dataset(data["dataset_id"], data.get("name", ""))
            event.acceptProposedAction()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear_all(self) -> None:
        """Remove all panels and reset state."""
        for panel in list(self._panels):
            self._remove_panel(panel)

    def apply_theme(self) -> None:
        """Re-apply theming when the app theme changes."""
        self._apply_page_style()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def save_state(self) -> dict | None:
        """Return a serialisable snapshot of the current comparison session."""
        if not self._panels:
            return None
        entries = []
        for panel in self._panels:
            # Resolve sample name from project for reliable restore
            name = ""
            project = self._host.current_project
            if project:
                for exp in project.experiments:
                    for s in exp.samples:
                        if getattr(s, "dataset_id", None) == panel.dataset_id:
                            name = getattr(s, "name", "") or ""
                            break
                    if name:
                        break
            entries.append({"dataset_id": panel.dataset_id, "name": name})
        return {"channel": self._channel, "datasets": entries}

    def restore_state(self, state: dict) -> None:
        """Restore a previously saved comparison session."""
        if not state or not state.get("datasets"):
            return
        # Set channel first
        channel = state.get("channel", "inner")
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == channel:
                self._combo.setCurrentIndex(i)
                break
        # Add datasets
        for entry in state["datasets"]:
            did = entry.get("dataset_id")
            name = entry.get("name", "")
            if did is not None:
                self._add_dataset(did, name)
