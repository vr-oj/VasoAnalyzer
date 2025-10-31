# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# PlotStyleEditor - redesigned dialog with live preview
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import (
    Any,
    TypedDict,
)

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import DEFAULT_STYLE
from ..event_label_editor import EventLabelEditor

EventMeta = dict[str, Any]


class EventOverride(TypedDict):
    label: str
    time: float
    meta: EventMeta


EventUpdateCallback = Callable[[list[str], list[EventMeta]], None]


class PlotStyleEditor(QDialog):
    """Dialog for adjusting plot fonts, colors, lines, and per-event labels."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial: Mapping[str, Any] | None = None,
        event_labels: Sequence[str] | None = None,
        event_times: Sequence[float] | None = None,
        event_meta: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plot Style Editor")
        self.setFont(QFont("Arial", 10))
        self.initial: dict[str, Any] = dict(initial) if initial else {}
        self.apply_callback: Callable[[dict[str, Any]], None] | None = None
        self.event_update_callback: EventUpdateCallback | None = None
        self._event_entries: list[EventOverride] = []
        self._suppress_event_editor = False
        self._event_updates_fired = False
        self._load_event_entries(event_labels, event_times, event_meta)

        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(8)

        # Tabs
        tabs = QTabWidget()
        main.addWidget(tabs, 1)
        self.tabs = tabs
        self._tab_aliases: dict[str, int] = {}

        def register_tab(widget: QWidget, title: str, aliases: Iterable[str]) -> None:
            widget.setObjectName(title.replace(" ", "") + "Tab")
            index = self.tabs.addTab(widget, title)
            for alias in {title.lower(), *aliases}:
                self._tab_aliases[alias] = index

        register_tab(
            self._make_axis_titles_tab(),
            "Axis Titles",
            {"axis", "axis_titles", "titles"},
        )
        register_tab(
            self._make_tick_labels_tab(),
            "Tick Labels",
            {"tick", "ticks", "tick_labels"},
        )
        register_tab(
            self._make_event_labels_tab(),
            "Event Labels",
            {"event", "events", "event_labels"},
        )
        register_tab(
            self._make_pinned_labels_tab(),
            "Pinned Labels",
            {"pinned", "pins", "pinned_labels"},
        )
        register_tab(
            self._make_trace_style_tab(),
            "Trace Style",
            {"trace", "traces", "trace_style", "line", "lines"},
        )
        register_tab(
            self._make_highlights_tab(),
            "Highlights",
            {"highlight", "highlights", "event_highlight"},
        )

        # Preview canvas
        screen = QApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch() if screen is not None else 96
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(3, 2), dpi=dpi))
        self.ax = self.canvas.figure.subplots()
        main.addWidget(self.canvas, 1)
        self._update_preview()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply
            | QDialogButtonBox.Reset
            | QDialogButtonBox.RestoreDefaults
            | QDialogButtonBox.Ok
            | QDialogButtonBox.Cancel
        )
        apply_button = buttons.button(QDialogButtonBox.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(self._apply)
        reset_button = buttons.button(QDialogButtonBox.Reset)
        if reset_button is not None:
            reset_button.clicked.connect(self._reset)
        defaults_button = buttons.button(QDialogButtonBox.RestoreDefaults)
        if defaults_button is not None:
            defaults_button.clicked.connect(self._defaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

        self._updating = False

    # ------------------------------------------------------------------
    # Event override helpers
    def _load_event_entries(
        self,
        labels: Sequence[str] | None,
        times: Sequence[float] | None,
        meta: Sequence[Mapping[str, Any]] | None,
    ) -> None:
        self._event_entries.clear()
        if not labels:
            return

        times_list: list[float] = []
        if times is not None:
            for value in times:
                try:
                    times_list.append(float(value))
                except (TypeError, ValueError):
                    times_list.append(0.0)
        meta_list: list[Mapping[str, Any]] = list(meta or [])
        if len(meta_list) < len(labels):
            meta_list.extend({} for _ in range(len(labels) - len(meta_list)))

        for idx, raw_label in enumerate(labels):
            entry_meta = meta_list[idx] if idx < len(meta_list) else {}
            time_val = times_list[idx] if idx < len(times_list) else 0.0
            label_text = str(raw_label) if raw_label is not None else ""
            normalized_meta: EventMeta = dict(entry_meta) if isinstance(entry_meta, Mapping) else {}
            entry: EventOverride = {
                "label": label_text,
                "time": time_val,
                "meta": normalized_meta,
            }
            self._event_entries.append(entry)

    # ------------------------------------------------------------------
    # Tab builders
    def _make_axis_titles_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Axis Title Font & Color")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.axis_font_size = QSpinBox()
        self.axis_font_size.setRange(6, 48)
        self.axis_font_size.setValue(
            int(round(self.initial.get("axis_font_size", DEFAULT_STYLE["axis_font_size"])))
        )
        self.axis_font_size.valueChanged.connect(self._on_change)
        form.addRow("Font Size:", self.axis_font_size)

        self.axis_font_family = QComboBox()
        self.axis_font_family.addItems(["Arial", "Helvetica", "Times New Roman", "Courier New"])
        self.axis_font_family.setCurrentText(
            self.initial.get("axis_font_family", DEFAULT_STYLE["axis_font_family"])
        )
        self.axis_font_family.currentIndexChanged.connect(self._on_change)
        form.addRow("Font Family:", self.axis_font_family)

        self.axis_bold = QCheckBox("Bold")
        self.axis_bold.setChecked(self.initial.get("axis_bold", DEFAULT_STYLE["axis_bold"]))
        self.axis_bold.stateChanged.connect(self._on_change)
        self.axis_italic = QCheckBox("Italic")
        self.axis_italic.setChecked(self.initial.get("axis_italic", DEFAULT_STYLE["axis_italic"]))
        self.axis_italic.stateChanged.connect(self._on_change)
        form.addRow(self.axis_bold, self.axis_italic)

        self.axis_color = QPushButton()
        self.axis_color.setFixedWidth(60)
        self._set_button_color(
            self.axis_color,
            self.initial.get("axis_color", DEFAULT_STYLE["axis_color"]),
        )
        self.axis_color.clicked.connect(
            lambda: self._choose_color(self.axis_color, self._on_change)
        )
        form.addRow("Color:", self.axis_color)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _make_tick_labels_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Tick Label Style")
        form = QFormLayout()

        self.tick_font_size = QSpinBox()
        self.tick_font_size.setRange(6, 32)
        self.tick_font_size.setValue(
            int(round(self.initial.get("tick_font_size", DEFAULT_STYLE["tick_font_size"])))
        )
        self.tick_font_size.valueChanged.connect(self._on_change)
        form.addRow("Font Size:", self.tick_font_size)

        self.tick_color = QPushButton()
        self.tick_color.setFixedWidth(60)
        self._set_button_color(
            self.tick_color,
            self.initial.get("tick_color", DEFAULT_STYLE["tick_color"]),
        )
        self.tick_color.clicked.connect(
            lambda: self._choose_color(self.tick_color, self._on_change)
        )
        form.addRow("Color:", self.tick_color)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _make_event_labels_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Event Label Style")
        form = QFormLayout()

        self.event_font_size = QSpinBox()
        self.event_font_size.setRange(6, 32)
        self.event_font_size.setValue(
            int(round(self.initial.get("event_font_size", DEFAULT_STYLE["event_font_size"])))
        )
        self.event_font_size.valueChanged.connect(self._on_change)
        form.addRow("Font Size:", self.event_font_size)

        self.event_font_family = QComboBox()
        self.event_font_family.addItems(["Arial", "Helvetica", "Times New Roman", "Courier New"])
        self.event_font_family.setCurrentText(
            self.initial.get("event_font_family", DEFAULT_STYLE["event_font_family"])
        )
        self.event_font_family.currentIndexChanged.connect(self._on_change)
        form.addRow("Font Family:", self.event_font_family)

        self.event_bold = QCheckBox("Bold")
        self.event_bold.setChecked(self.initial.get("event_bold", DEFAULT_STYLE["event_bold"]))
        self.event_bold.stateChanged.connect(self._on_change)
        self.event_italic = QCheckBox("Italic")
        self.event_italic.setChecked(
            self.initial.get("event_italic", DEFAULT_STYLE["event_italic"])
        )
        self.event_italic.stateChanged.connect(self._on_change)
        form.addRow(self.event_bold, self.event_italic)

        self.event_color = QPushButton()
        self.event_color.setFixedWidth(60)
        self._set_button_color(
            self.event_color,
            self.initial.get("event_color", DEFAULT_STYLE["event_color"]),
        )
        self.event_color.clicked.connect(
            lambda: self._choose_color(self.event_color, self._on_change)
        )
        form.addRow("Color:", self.event_color)

        grp.setLayout(form)
        layout.addWidget(grp)

        overrides_header = QLabel("Per-Event Overrides")
        overrides_header.setObjectName("EventOverridesHeader")
        overrides_header.setStyleSheet("font-weight: 600;")
        layout.addWidget(overrides_header)

        overrides_container = QHBoxLayout()
        overrides_container.setSpacing(10)

        self.event_list = QListWidget()
        self.event_list.setAlternatingRowColors(True)
        self.event_list.setSelectionMode(QListWidget.SingleSelection)
        self.event_list.currentRowChanged.connect(self._on_event_row_changed)
        overrides_container.addWidget(self.event_list, 1)

        self.event_editor = EventLabelEditor(self)
        self.event_editor.styleChanged.connect(self._on_event_style_changed)
        self.event_editor.labelTextChanged.connect(self._on_event_label_changed)
        overrides_container.addWidget(self.event_editor, 2)

        layout.addLayout(overrides_container)
        self._refresh_event_list()
        layout.addStretch()
        return w

    def _format_event_list_item(self, entry: EventOverride) -> str:
        label = entry.get("label") or "(Untitled)"
        try:
            time_val = float(entry["time"])
            return f"{label} — {time_val:.2f} s"
        except (KeyError, TypeError, ValueError):
            return label

    def _refresh_event_list(self) -> None:
        if not hasattr(self, "event_list"):
            return
        self.event_list.blockSignals(True)
        self.event_list.clear()
        for entry in self._event_entries:
            item = QListWidgetItem(self._format_event_list_item(entry))
            self.event_list.addItem(item)
        self.event_list.blockSignals(False)
        has_events = bool(self._event_entries)
        self.event_list.setEnabled(has_events)
        if has_events:
            self.event_list.setCurrentRow(0)
        else:
            self.event_editor.clear()

    def _on_event_row_changed(self, row: int) -> None:
        if self._suppress_event_editor:
            return
        if not (0 <= row < len(self._event_entries)):
            self.event_editor.clear()
            return
        entry = self._event_entries[row]
        self._suppress_event_editor = True
        self.event_editor.set_event(
            row,
            entry.get("label", ""),
            entry.get("time", 0.0),
            entry.get("meta", {}),
            max_lanes=2,
        )
        self._suppress_event_editor = False

    def _on_event_style_changed(self, index: int, meta: Mapping[str, Any] | None) -> None:
        if self._suppress_event_editor or not (0 <= index < len(self._event_entries)):
            return
        updated_meta: EventMeta = dict(meta or {})
        self._event_entries[index]["meta"] = updated_meta
        self._event_updates_fired = False

    def _on_event_label_changed(self, index: int, text: str) -> None:
        if self._suppress_event_editor or not (0 <= index < len(self._event_entries)):
            return
        normalized = text.strip()
        self._event_entries[index]["label"] = normalized
        self._update_event_list_item(index)
        self._event_updates_fired = False

    def _update_event_list_item(self, index: int) -> None:
        if not hasattr(self, "event_list"):
            return
        item = self.event_list.item(index)
        if item is None:
            return
        item.setText(self._format_event_list_item(self._event_entries[index]))

    def set_event_update_callback(self, callback: EventUpdateCallback | None) -> None:
        self.event_update_callback = callback

    def _emit_event_updates(self) -> None:
        labels, meta = self.get_event_overrides()
        if callable(self.event_update_callback):
            self.event_update_callback(labels, meta)
        self._event_updates_fired = True

    def get_event_overrides(self) -> tuple[list[str], list[EventMeta]]:
        if not self._event_entries:
            return ([], [])
        labels = [entry["label"] for entry in self._event_entries]
        meta = [dict(entry["meta"]) for entry in self._event_entries]
        return labels, meta

    def event_updates_emitted(self) -> bool:
        return bool(self._event_updates_fired)

    def _make_pinned_labels_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Pinned Label Style")
        form = QFormLayout()

        self.pin_font_size = QSpinBox()
        self.pin_font_size.setRange(6, 32)
        self.pin_font_size.setValue(
            int(round(self.initial.get("pin_font_size", DEFAULT_STYLE["pin_font_size"])))
        )
        self.pin_font_size.valueChanged.connect(self._on_change)
        form.addRow("Font Size:", self.pin_font_size)

        self.pin_font_family = QComboBox()
        self.pin_font_family.addItems(["Arial", "Helvetica", "Times New Roman", "Courier New"])
        self.pin_font_family.setCurrentText(
            self.initial.get("pin_font_family", DEFAULT_STYLE["pin_font_family"])
        )
        self.pin_font_family.currentIndexChanged.connect(self._on_change)
        form.addRow("Font Family:", self.pin_font_family)

        self.pin_bold = QCheckBox("Bold")
        self.pin_bold.setChecked(self.initial.get("pin_bold", DEFAULT_STYLE["pin_bold"]))
        self.pin_bold.stateChanged.connect(self._on_change)
        self.pin_italic = QCheckBox("Italic")
        self.pin_italic.setChecked(self.initial.get("pin_italic", DEFAULT_STYLE["pin_italic"]))
        self.pin_italic.stateChanged.connect(self._on_change)
        form.addRow(self.pin_bold, self.pin_italic)

        self.pin_color = QPushButton()
        self.pin_color.setFixedWidth(60)
        self._set_button_color(
            self.pin_color,
            self.initial.get("pin_color", DEFAULT_STYLE["pin_color"]),
        )
        self.pin_color.clicked.connect(lambda: self._choose_color(self.pin_color, self._on_change))
        form.addRow("Color:", self.pin_color)

        self.pin_size = QSpinBox()
        self.pin_size.setRange(2, 20)
        self.pin_size.setValue(int(round(self.initial.get("pin_size", DEFAULT_STYLE["pin_size"]))))
        self.pin_size.valueChanged.connect(self._on_change)
        form.addRow("Marker Size:", self.pin_size)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _make_trace_style_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp_in = QGroupBox("Inner Trace Style")
        form_in = QFormLayout()
        self.line_width = QDoubleSpinBox()
        self.line_width.setRange(0.5, 10)
        self.line_width.setValue(self.initial.get("line_width", DEFAULT_STYLE["line_width"]))
        self.line_width.valueChanged.connect(self._on_change)
        form_in.addRow("Line Width:", self.line_width)

        styles = ["Solid", "Dashed", "Dotted", "DashDot"]
        self.line_style = QComboBox()
        self.line_style.addItems(styles)
        self.line_style.setCurrentText(
            self.initial.get("line_style", DEFAULT_STYLE.get("line_style", "solid")).capitalize()
        )
        self.line_style.currentIndexChanged.connect(self._on_change)
        form_in.addRow("Line Style:", self.line_style)

        self.line_color = QPushButton()
        self.line_color.setFixedWidth(60)
        self._set_button_color(
            self.line_color,
            self.initial.get("line_color", DEFAULT_STYLE["line_color"]),
        )
        self.line_color.clicked.connect(
            lambda: self._choose_color(self.line_color, self._on_change)
        )
        form_in.addRow("Color:", self.line_color)
        grp_in.setLayout(form_in)
        layout.addWidget(grp_in)

        grp_out = QGroupBox("Outer Trace Style")
        form_out = QFormLayout()
        self.outer_line_width = QDoubleSpinBox()
        self.outer_line_width.setRange(0.5, 10)
        self.outer_line_width.setValue(
            self.initial.get("outer_line_width", DEFAULT_STYLE["outer_line_width"])
        )
        self.outer_line_width.valueChanged.connect(self._on_change)
        form_out.addRow("Line Width:", self.outer_line_width)

        self.outer_line_style = QComboBox()
        self.outer_line_style.addItems(styles)
        self.outer_line_style.setCurrentText(
            self.initial.get(
                "outer_line_style",
                DEFAULT_STYLE.get("outer_line_style", "solid"),
            ).capitalize()
        )
        self.outer_line_style.currentIndexChanged.connect(self._on_change)
        form_out.addRow("Line Style:", self.outer_line_style)

        self.outer_line_color = QPushButton()
        self.outer_line_color.setFixedWidth(60)
        self._set_button_color(
            self.outer_line_color,
            self.initial.get("outer_line_color", DEFAULT_STYLE["outer_line_color"]),
        )
        self.outer_line_color.clicked.connect(
            lambda: self._choose_color(self.outer_line_color, self._on_change)
        )
        form_out.addRow("Color:", self.outer_line_color)
        grp_out.setLayout(form_out)
        layout.addWidget(grp_out)

        layout.addStretch()
        return w

    def _make_highlights_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Event Highlight")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.event_highlight_color_btn = QPushButton()
        self.event_highlight_color_btn.setFixedWidth(60)
        self._set_button_color(
            self.event_highlight_color_btn,
            self.initial.get(
                "event_highlight_color",
                DEFAULT_STYLE.get("event_highlight_color", "#1D5CFF"),
            ),
        )
        self.event_highlight_color_btn.clicked.connect(
            lambda: self._choose_color(self.event_highlight_color_btn, self._on_change)
        )
        form.addRow("Color:", self.event_highlight_color_btn)

        self.event_highlight_alpha_spin = QDoubleSpinBox()
        self.event_highlight_alpha_spin.setRange(0.0, 1.0)
        self.event_highlight_alpha_spin.setSingleStep(0.05)
        self.event_highlight_alpha_spin.setDecimals(2)
        self.event_highlight_alpha_spin.setValue(
            float(
                self.initial.get(
                    "event_highlight_alpha",
                    DEFAULT_STYLE.get("event_highlight_alpha", 0.95),
                )
            )
        )
        self.event_highlight_alpha_spin.valueChanged.connect(self._on_change)
        form.addRow("Base Opacity:", self.event_highlight_alpha_spin)

        self.event_highlight_duration_spin = QSpinBox()
        self.event_highlight_duration_spin.setRange(0, 60000)
        self.event_highlight_duration_spin.setSingleStep(100)
        self.event_highlight_duration_spin.setSuffix(" ms")
        self.event_highlight_duration_spin.setValue(
            int(
                self.initial.get(
                    "event_highlight_duration_ms",
                    DEFAULT_STYLE.get("event_highlight_duration_ms", 2000),
                )
            )
        )
        self.event_highlight_duration_spin.valueChanged.connect(self._on_change)
        form.addRow("Fade Duration:", self.event_highlight_duration_spin)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    # ------------------------------------------------------------------
    # Helpers
    def _set_button_color(self, btn: QPushButton, hexcolor: str | None) -> None:
        value = hexcolor or ""
        btn.setStyleSheet(f"background:{value};border:1px solid #888;")
        btn.setProperty("color", value)

    def _choose_color(self, btn: QPushButton, callback: Callable[[], None]) -> None:
        from PyQt5.QtWidgets import QColorDialog

        col = QColorDialog.getColor(QColor(btn.property("color")), self)
        if col.isValid():
            self._set_button_color(btn, col.name())
            callback()

    def _on_change(self) -> None:
        if self._updating:
            return
        style = self._gather()
        parent = self.parent()
        if callable(self.apply_callback):
            self.apply_callback(style)
        elif parent is not None and hasattr(parent, "apply_plot_style"):
            parent.apply_plot_style(style)
        self._update_preview()

    def _populate(self, style: Mapping[str, Any]) -> None:
        self._updating = True
        self.axis_font_size.setValue(
            int(round(style.get("axis_font_size", DEFAULT_STYLE["axis_font_size"])))
        )
        self.axis_font_family.setCurrentText(
            style.get("axis_font_family", DEFAULT_STYLE["axis_font_family"])
        )
        self.axis_bold.setChecked(style.get("axis_bold", DEFAULT_STYLE["axis_bold"]))
        self.axis_italic.setChecked(style.get("axis_italic", DEFAULT_STYLE["axis_italic"]))
        self._set_button_color(
            self.axis_color, style.get("axis_color", DEFAULT_STYLE["axis_color"])
        )

        self.tick_font_size.setValue(
            int(round(style.get("tick_font_size", DEFAULT_STYLE["tick_font_size"])))
        )
        self._set_button_color(
            self.tick_color, style.get("tick_color", DEFAULT_STYLE["tick_color"])
        )

        self.event_font_size.setValue(
            int(round(style.get("event_font_size", DEFAULT_STYLE["event_font_size"])))
        )
        self.event_font_family.setCurrentText(
            style.get("event_font_family", DEFAULT_STYLE["event_font_family"])
        )
        self.event_bold.setChecked(style.get("event_bold", DEFAULT_STYLE["event_bold"]))
        self.event_italic.setChecked(style.get("event_italic", DEFAULT_STYLE["event_italic"]))
        self._set_button_color(
            self.event_color, style.get("event_color", DEFAULT_STYLE["event_color"])
        )

        self.pin_font_size.setValue(
            int(round(style.get("pin_font_size", DEFAULT_STYLE["pin_font_size"])))
        )
        self.pin_font_family.setCurrentText(
            style.get("pin_font_family", DEFAULT_STYLE["pin_font_family"])
        )
        self.pin_bold.setChecked(style.get("pin_bold", DEFAULT_STYLE["pin_bold"]))
        self.pin_italic.setChecked(style.get("pin_italic", DEFAULT_STYLE["pin_italic"]))
        self._set_button_color(self.pin_color, style.get("pin_color", DEFAULT_STYLE["pin_color"]))
        self.pin_size.setValue(int(round(style.get("pin_size", DEFAULT_STYLE["pin_size"]))))

        self.line_width.setValue(style.get("line_width", DEFAULT_STYLE["line_width"]))
        self.line_style.setCurrentText(
            style.get("line_style", DEFAULT_STYLE.get("line_style", "solid")).capitalize()
        )
        self._set_button_color(
            self.line_color, style.get("line_color", DEFAULT_STYLE["line_color"])
        )
        self.outer_line_width.setValue(
            style.get("outer_line_width", DEFAULT_STYLE["outer_line_width"])
        )
        self.outer_line_style.setCurrentText(
            style.get(
                "outer_line_style",
                DEFAULT_STYLE.get("outer_line_style", "solid"),
            ).capitalize()
        )
        self._set_button_color(
            self.outer_line_color,
            style.get("outer_line_color", DEFAULT_STYLE["outer_line_color"]),
        )
        self._set_button_color(
            self.event_highlight_color_btn,
            style.get(
                "event_highlight_color",
                DEFAULT_STYLE.get("event_highlight_color", "#1D5CFF"),
            ),
        )
        self.event_highlight_alpha_spin.setValue(
            float(
                style.get(
                    "event_highlight_alpha",
                    DEFAULT_STYLE.get("event_highlight_alpha", 0.95),
                )
            )
        )
        self.event_highlight_duration_spin.setValue(
            int(
                style.get(
                    "event_highlight_duration_ms",
                    DEFAULT_STYLE.get("event_highlight_duration_ms", 2000),
                )
            )
        )
        self._updating = False
        self._update_preview()

    def _gather(self) -> dict[str, Any]:
        return {
            "axis_font_size": self.axis_font_size.value(),
            "axis_font_family": self.axis_font_family.currentText(),
            "axis_bold": self.axis_bold.isChecked(),
            "axis_italic": self.axis_italic.isChecked(),
            "axis_color": self.axis_color.property("color"),
            "tick_font_size": self.tick_font_size.value(),
            "tick_color": self.tick_color.property("color"),
            "event_font_size": self.event_font_size.value(),
            "event_font_family": self.event_font_family.currentText(),
            "event_bold": self.event_bold.isChecked(),
            "event_italic": self.event_italic.isChecked(),
            "event_color": self.event_color.property("color"),
            "pin_font_size": self.pin_font_size.value(),
            "pin_font_family": self.pin_font_family.currentText(),
            "pin_bold": self.pin_bold.isChecked(),
            "pin_italic": self.pin_italic.isChecked(),
            "pin_color": self.pin_color.property("color"),
            "pin_size": self.pin_size.value(),
            "line_width": self.line_width.value(),
            "line_style": self.line_style.currentText().lower(),
            "line_color": self.line_color.property("color"),
            "outer_line_width": self.outer_line_width.value(),
            "outer_line_style": self.outer_line_style.currentText().lower(),
            "outer_line_color": self.outer_line_color.property("color"),
            "event_highlight_color": self.event_highlight_color_btn.property("color"),
            "event_highlight_alpha": self.event_highlight_alpha_spin.value(),
            "event_highlight_duration_ms": self.event_highlight_duration_spin.value(),
        }

    def get_style(self) -> dict[str, Any]:
        """Public accessor for the current style settings."""
        return self._gather()

    def set_style(self, style: Mapping[str, Any]) -> None:
        """Update the dialog controls to reflect ``style``."""
        self._populate(style)

    def _apply(self) -> None:
        params = self._gather()
        parent = self.parent()
        if callable(self.apply_callback):
            self.apply_callback(params)
        elif parent is not None and hasattr(parent, "apply_plot_style"):
            parent.apply_plot_style(params)
        self._emit_event_updates()
        self._update_preview()

    def _reset(self) -> None:
        self._populate(self.initial)

    def _defaults(self) -> None:
        self._populate(DEFAULT_STYLE)

    def select_tab(self, key: Any) -> None:
        """Focus the tab matching ``key`` if available."""

        if not key:
            return
        key = str(key).strip().lower()
        index = self._tab_aliases.get(key)
        if index is None:
            for alias, idx in self._tab_aliases.items():
                if key in alias:
                    index = idx
                    break
        if index is not None:
            self.tabs.setCurrentIndex(index)

    def _update_preview(self) -> None:
        p = self._gather()
        self.ax.clear()
        x = [0, 1, 2, 3, 4]
        self.ax.plot(
            x,
            x,
            linewidth=p["line_width"],
            color=p["line_color"],
            linestyle=p.get("line_style", "solid"),
        )
        self.ax.plot(
            x,
            [4 - i for i in x],
            linewidth=p["outer_line_width"],
            color=p["outer_line_color"],
            linestyle=p.get("outer_line_style", "solid"),
        )
        for lbl in (self.ax.xaxis.get_label(), self.ax.yaxis.get_label()):
            lbl.set_fontsize(p["axis_font_size"])
            lbl.set_fontfamily(p["axis_font_family"])
            lbl.set_fontweight("bold" if p["axis_bold"] else "normal")
            lbl.set_fontstyle("italic" if p["axis_italic"] else "normal")
            lbl.set_color(p["axis_color"])
        for tick in self.ax.get_xticklabels() + self.ax.get_yticklabels():
            tick.set_fontsize(p["tick_font_size"])
            tick.set_color(p["tick_color"])
        self.canvas.draw_idle()

    def accept(self) -> None:
        self._emit_event_updates()
        super().accept()
