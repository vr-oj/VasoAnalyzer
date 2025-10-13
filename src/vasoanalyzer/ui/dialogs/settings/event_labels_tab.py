from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout, QHBoxLayout, QComboBox, QSpinBox, QCheckBox, QListWidget
from PyQt5.QtCore import Qt

from vasoanalyzer.ui.event_label_editor import EventLabelEditor
from vasoanalyzer.ui.constants import DEFAULT_STYLE
from vasoanalyzer.ui.dialogs.settings._shared import block_signals

if TYPE_CHECKING:  # pragma: no cover
    try:
        from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedPlotSettingsDialog as DialogT
    except Exception:
        from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedSettingsDialog as DialogT
else:
    class DialogT:  # type: ignore
        pass

__all__ = [
    "EventLabelsTabRefs",
    "create_event_labels_tab_widgets",
    "populate_event_labels_tab",
    "wire_event_labels_tab",
]

@dataclass
class EventLabelsTabRefs:
    tab: QWidget
    # Keep names that downstream code expects to exist on the dialog:
    event_font_family: QComboBox
    event_font_size: QSpinBox
    event_bold: QCheckBox
    event_italic: QCheckBox
    event_color_btn: QWidget     # created by dialog._make_color_button(...)
    event_list: QListWidget
    event_editor: QWidget        # EventLabelEditor
    event_overrides_box: QGroupBox
    event_empty_label: QLabel

def create_event_labels_tab_widgets(dialog: "DialogT", window) -> EventLabelsTabRefs:
    """
    BUILD UI ONLY (no value-setting other than construction defaults, and only
    the connects that are strictly part of construction if any—signal wiring
    will move to wire_event_labels_tab).
    Lines mapped from unified_settings_dialog.py: 656–704, 705–724, 726–731.
    """
    fonts = list(dialog._font_choices)

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    intro = QLabel(
        "Tune the default typography for all event markers or override specific labels "
        "to adjust their wording, visibility, or placement."
    )
    intro.setWordWrap(True)
    intro.setObjectName("EventLabelsIntro")
    layout.addWidget(intro)

    # Global Label Style
    defaults_box = QGroupBox("Global Label Style")
    defaults_form = QFormLayout(defaults_box)
    defaults_form.setLabelAlignment(Qt.AlignRight)

    event_font_family = QComboBox()
    event_font_family.addItems(fonts)
    # NOTE: initial value will be set in populate_event_labels_tab
    defaults_form.addRow("Font Family:", event_font_family)

    event_font_size = QSpinBox()
    event_font_size.setRange(6, 32)  # range is construction-time
    # NOTE: actual value set in populate_event_labels_tab
    defaults_form.addRow("Font Size:", event_font_size)

    # Bold / Italic row
    event_style_row = QWidget()
    event_style_layout = QHBoxLayout(event_style_row)
    event_style_layout.setContentsMargins(0, 0, 0, 0)
    event_style_layout.setSpacing(8)
    event_bold = QCheckBox("Bold")
    event_italic = QCheckBox("Italic")
    event_style_layout.addWidget(event_bold)
    event_style_layout.addWidget(event_italic)
    event_style_layout.addStretch(1)
    defaults_form.addRow("Text Style:", event_style_row)

    # Color button constructed via dialog helper (construction belongs here)
    # Keep the same default expression used in legacy code:
    # dialog.style.get("event_color", DEFAULT_STYLE["event_color"])
    event_color_btn = dialog._make_color_button(
        dialog.style.get("event_color", dialog.DEFAULT_STYLE["event_color"])
        if hasattr(dialog, "DEFAULT_STYLE") else dialog.style.get("event_color", "#000000")
    )
    defaults_form.addRow("Event Color:", event_color_btn)

    layout.addWidget(defaults_box)

    # Overrides group: list + editor
    overrides_box = QGroupBox("Per-Event Overrides")
    overrides_box.setObjectName("EventOverridesGroup")
    overrides_layout = QHBoxLayout(overrides_box)
    overrides_layout.setContentsMargins(12, 12, 12, 12)
    overrides_layout.setSpacing(12)

    event_list = QListWidget()
    event_list.setAlternatingRowColors(True)
    event_list.setSelectionMode(QListWidget.SingleSelection)
    event_list.setMinimumWidth(220)
    # NOTE: signal connects move to wire_event_labels_tab
    overrides_layout.addWidget(event_list, 1)

    event_editor = EventLabelEditor(dialog)
    # NOTE: connects move to wire_event_labels_tab
    overrides_layout.addWidget(event_editor, 2)

    layout.addWidget(overrides_box, 1)

    event_empty_label = QLabel("No events found for this sample.")
    event_empty_label.setAlignment(Qt.AlignCenter)
    event_empty_label.setStyleSheet("color: #666666;")
    layout.addWidget(event_empty_label)

    layout.addStretch(1)

    # Return refs so the dialog can reattach attributes it expects
    return EventLabelsTabRefs(
        tab=container,
        event_font_family=event_font_family,
        event_font_size=event_font_size,
        event_bold=event_bold,
        event_italic=event_italic,
        event_color_btn=event_color_btn,
        event_list=event_list,
        event_editor=event_editor,
        event_overrides_box=overrides_box,
        event_empty_label=event_empty_label,
    )

def populate_event_labels_tab(dialog: "DialogT") -> None:
    """
    Move ONLY the value-setting lines from legacy:
      - setCurrentText / setValue / setChecked that read from dialog.style or DEFAULT_STYLE
    Lines mapped from legacy: 675–684 (and any similar set* calls in the elided region).
    """
    default_style = getattr(dialog, "DEFAULT_STYLE", DEFAULT_STYLE)
    style = getattr(dialog, "style", {})

    with block_signals([
        getattr(dialog, "event_font_family", None),
        getattr(dialog, "event_font_size", None),
    ]):
        dialog.event_font_family.setCurrentText(
            style.get("event_font_family", default_style.get("event_font_family", "Arial"))
        )
        dialog.event_font_size.setValue(
            int(style.get("event_font_size", default_style.get("event_font_size", 10)))
        )

    return

def wire_event_labels_tab(dialog: "DialogT") -> None:
    """
    Move ONLY the connect(...) lines from legacy.
    Lines mapped from legacy: 715, 719–720 (+ any other .connect calls for this tab).
    Guard with a sentinel so re-building the tab doesn’t double-connect.
    """
    event_list = getattr(dialog, "event_list", None)
    event_editor = getattr(dialog, "event_editor", None)
    current_refs = (event_list, event_editor)

    if getattr(dialog, "_event_labels_tab_wired", None) == current_refs:
        return

    if event_list is not None:
        event_list.currentRowChanged.connect(dialog._on_event_row_changed)

    if event_editor is not None:
        if hasattr(event_editor, "styleChanged"):
            event_editor.styleChanged.connect(dialog._on_event_style_changed)
        if hasattr(event_editor, "labelTextChanged"):
            event_editor.labelTextChanged.connect(dialog._on_event_label_changed)

    dialog._event_labels_tab_wired = current_refs
    return
