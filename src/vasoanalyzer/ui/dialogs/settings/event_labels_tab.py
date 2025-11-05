from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.constants import DEFAULT_STYLE
from vasoanalyzer.ui.dialogs.settings._shared import block_signals
from vasoanalyzer.ui.event_label_editor import EventLabelEditor

if TYPE_CHECKING:  # pragma: no cover
    try:
        from vasoanalyzer.ui.dialogs.unified_settings_dialog import (
            UnifiedPlotSettingsDialog as DialogT,
        )
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
    event_color_btn: QWidget  # created by dialog._make_color_button(...)
    event_labels_v3_toggle: QCheckBox
    event_label_mode: QComboBox  # Mode selector: vertical/horizontal/belt
    event_cluster_style: QComboBox
    event_max_per_cluster: QSpinBox
    event_label_lanes: QSpinBox
    event_belt_baseline: QCheckBox
    event_span_siblings: QCheckBox
    event_auto_mode: QCheckBox
    event_density_compact: QDoubleSpinBox
    event_density_belt: QDoubleSpinBox
    event_outline_enabled: QCheckBox
    event_outline_width: QDoubleSpinBox
    event_outline_color_btn: QWidget
    event_tooltips_enabled: QCheckBox
    event_tooltip_proximity: QSpinBox
    event_legend_enabled: QCheckBox
    event_legend_location: QComboBox
    event_list: QListWidget
    event_editor: QWidget  # EventLabelEditor
    event_overrides_box: QGroupBox
    event_empty_label: QLabel


def create_event_labels_tab_widgets(dialog: DialogT, window) -> EventLabelsTabRefs:
    """
    BUILD UI ONLY (no value-setting other than construction defaults, and only
    the connects that are strictly part of construction if any—signal wiring
    will move to wire_event_labels_tab).
    Lines mapped from unified_settings_dialog.py: 656–704, 705–724, 726–731.
    """
    fonts = list(dialog._font_choices)

    # Create scroll area to prevent widget collapse
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QScrollArea.NoFrame)

    # Create content widget that will be scrolled
    content_widget = QWidget()
    main_layout = QVBoxLayout(content_widget)
    main_layout.setContentsMargins(12, 12, 12, 12)
    main_layout.setSpacing(12)

    intro = QLabel(
        "Configure vertical event labels with dashed line markers. "
        "Adjust typography for all labels or customize individual events below."
    )
    intro.setWordWrap(True)
    intro.setObjectName("EventLabelsIntro")
    main_layout.addWidget(intro)

    # Two-column grid layout for group boxes
    grid = QGridLayout()
    grid.setSpacing(12)
    grid.setColumnStretch(0, 2)
    grid.setColumnStretch(1, 3)

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
        if hasattr(dialog, "DEFAULT_STYLE")
        else dialog.style.get("event_color", "#000000")
    )
    defaults_form.addRow("Event Color:", event_color_btn)

    # Add to grid: left column, row 0
    grid.addWidget(defaults_box, 0, 0)

    # Behaviour controls
    behaviour_box = QGroupBox("Label Clustering & Behaviour")
    behaviour_form = QFormLayout(behaviour_box)
    behaviour_form.setLabelAlignment(Qt.AlignRight)

    # Hidden: Auto mode and density controls (not needed for vertical labels)
    event_auto_mode = QCheckBox("Automatic density switching")
    event_auto_mode.setChecked(False)
    event_auto_mode.setVisible(False)

    event_density_compact = QDoubleSpinBox()
    event_density_compact.setRange(0.0, 10.0)
    event_density_compact.setDecimals(3)
    event_density_compact.setSingleStep(0.05)
    event_density_compact.setValue(0.8)
    event_density_compact.setVisible(False)

    event_density_belt = QDoubleSpinBox()
    event_density_belt.setRange(0.0, 10.0)
    event_density_belt.setDecimals(3)
    event_density_belt.setSingleStep(0.05)
    event_density_belt.setValue(0.25)
    event_density_belt.setVisible(False)

    # Event Labels v3 always enabled (hidden, no need for toggle)
    event_labels_v3_toggle = QCheckBox("Enable Event Labels v3")
    event_labels_v3_toggle.setChecked(True)  # Always on
    event_labels_v3_toggle.setVisible(False)  # Hide - no need to toggle

    # Hidden: Mode selector (locked to vertical)
    event_label_mode = QComboBox()
    event_label_mode.addItem("Vertical (Above Plot)", "vertical")
    event_label_mode.addItem("Horizontal (Inside Plot)", "horizontal")
    event_label_mode.addItem("Horizontal Belt (Outside Plot)", "horizontal_outside")
    event_label_mode.setCurrentIndex(0)  # Always vertical
    event_label_mode.setVisible(False)

    event_cluster_style = QComboBox()
    event_cluster_style.addItem("First label", "first")
    event_cluster_style.addItem("Most common style", "most_common")
    event_cluster_style.addItem("Highest priority", "priority")
    event_cluster_style.addItem("Blend colour", "blend_color")
    behaviour_form.addRow("Cluster Style:", event_cluster_style)

    event_max_per_cluster = QSpinBox()
    event_max_per_cluster.setRange(1, 4)
    event_max_per_cluster.setValue(1)
    behaviour_form.addRow("Max per Cluster:", event_max_per_cluster)

    # Hidden: Horizontal lanes (not used in vertical mode)
    event_label_lanes = QSpinBox()
    event_label_lanes.setRange(1, 12)
    event_label_lanes.setValue(3)
    event_label_lanes.setVisible(False)

    # Hidden: Belt baseline (not used in vertical mode)
    event_belt_baseline = QCheckBox("Show belt baseline")
    event_belt_baseline.setChecked(True)
    event_belt_baseline.setVisible(False)

    event_span_siblings = QCheckBox("Span shared axes")
    event_span_siblings.setChecked(True)
    behaviour_form.addRow("Span Axes:", event_span_siblings)

    # Add to grid: right column, row 0
    grid.addWidget(behaviour_box, 0, 1)

    # Text Outline (left column, row 1)
    outline_box = QGroupBox("Text Outline")
    outline_form = QFormLayout(outline_box)
    outline_form.setLabelAlignment(Qt.AlignRight)

    event_outline_enabled = QCheckBox("Enable outline")
    event_outline_enabled.setChecked(False)
    outline_form.addRow("Enabled:", event_outline_enabled)

    event_outline_width = QDoubleSpinBox()
    event_outline_width.setRange(0.0, 10.0)
    event_outline_width.setDecimals(2)
    event_outline_width.setSingleStep(0.1)
    outline_form.addRow("Width (px):", event_outline_width)

    outline_default = DEFAULT_STYLE.get("event_label_outline_color", "#FFFFFFFF")
    event_outline_color_btn = dialog._make_color_button(outline_default)
    outline_form.addRow("Outline Color:", event_outline_color_btn)

    # Add to grid: left column, row 1
    grid.addWidget(outline_box, 1, 0)

    interaction_box = QGroupBox("Interaction & Legend")
    interaction_form = QFormLayout(interaction_box)
    interaction_form.setLabelAlignment(Qt.AlignRight)

    event_tooltips_enabled = QCheckBox("Show hover tooltips")
    event_tooltips_enabled.setChecked(True)
    interaction_form.addRow("Tooltips:", event_tooltips_enabled)

    event_tooltip_proximity = QSpinBox()
    event_tooltip_proximity.setRange(1, 200)
    event_tooltip_proximity.setValue(10)
    interaction_form.addRow("Tooltip Radius (px):", event_tooltip_proximity)

    event_legend_enabled = QCheckBox("Show compact legend")
    event_legend_enabled.setChecked(True)
    interaction_form.addRow("Compact Legend:", event_legend_enabled)

    event_legend_location = QComboBox()
    event_legend_location.addItems(
        [
            "upper right",
            "upper left",
            "lower left",
            "lower right",
            "upper center",
            "lower center",
            "center",
            "center left",
            "center right",
        ]
    )
    interaction_form.addRow("Legend Position:", event_legend_location)

    # Add to grid: right column, row 1
    grid.addWidget(interaction_box, 1, 1)

    # Add the grid to the main layout
    main_layout.addLayout(grid)

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
    event_list.setMaximumWidth(300)
    # NOTE: signal connects move to wire_event_labels_tab
    overrides_layout.addWidget(event_list, 1)

    event_editor = EventLabelEditor(dialog)
    event_editor.setMinimumWidth(350)
    # NOTE: connects move to wire_event_labels_tab
    overrides_layout.addWidget(event_editor, 2)

    # Add overrides box below the grid, spanning full width
    main_layout.addWidget(overrides_box, 1)

    event_empty_label = QLabel("No events found for this sample.")
    event_empty_label.setAlignment(Qt.AlignCenter)
    event_empty_label.setStyleSheet("color: #666666;")
    main_layout.addWidget(event_empty_label)

    main_layout.addStretch(1)

    # Set content widget in scroll area
    scroll_area.setWidget(content_widget)

    # Create container widget with scroll area
    container = QWidget()
    container_layout = QVBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.addWidget(scroll_area)

    # Return refs so the dialog can reattach attributes it expects
    return EventLabelsTabRefs(
        tab=container,
        event_font_family=event_font_family,
        event_font_size=event_font_size,
        event_bold=event_bold,
        event_italic=event_italic,
        event_color_btn=event_color_btn,
        event_labels_v3_toggle=event_labels_v3_toggle,
        event_label_mode=event_label_mode,
        event_cluster_style=event_cluster_style,
        event_max_per_cluster=event_max_per_cluster,
        event_label_lanes=event_label_lanes,
        event_belt_baseline=event_belt_baseline,
        event_span_siblings=event_span_siblings,
        event_auto_mode=event_auto_mode,
        event_density_compact=event_density_compact,
        event_density_belt=event_density_belt,
        event_outline_enabled=event_outline_enabled,
        event_outline_width=event_outline_width,
        event_outline_color_btn=event_outline_color_btn,
        event_tooltips_enabled=event_tooltips_enabled,
        event_tooltip_proximity=event_tooltip_proximity,
        event_legend_enabled=event_legend_enabled,
        event_legend_location=event_legend_location,
        event_list=event_list,
        event_editor=event_editor,
        event_overrides_box=overrides_box,
        event_empty_label=event_empty_label,
    )


def populate_event_labels_tab(dialog: DialogT) -> None:
    """
    Move ONLY the value-setting lines from legacy:
      - setCurrentText / setValue / setChecked that read from dialog.style or DEFAULT_STYLE
    Lines mapped from legacy: 675–684 (and any similar set* calls in the elided region).
    """
    default_style = getattr(dialog, "DEFAULT_STYLE", DEFAULT_STYLE)
    style = getattr(dialog, "style", {})

    with block_signals(
        [
            getattr(dialog, "event_font_family", None),
            getattr(dialog, "event_font_size", None),
            getattr(dialog, "event_labels_v3_toggle", None),
            getattr(dialog, "event_label_mode", None),
            getattr(dialog, "event_cluster_style", None),
            getattr(dialog, "event_max_per_cluster", None),
            getattr(dialog, "event_label_lanes", None),
            getattr(dialog, "event_belt_baseline", None),
            getattr(dialog, "event_span_siblings", None),
            getattr(dialog, "event_auto_mode", None),
            getattr(dialog, "event_density_compact", None),
            getattr(dialog, "event_density_belt", None),
            getattr(dialog, "event_outline_enabled", None),
            getattr(dialog, "event_outline_width", None),
            getattr(dialog, "event_outline_color_btn", None),
        ]
    ):
        dialog.event_font_family.setCurrentText(
            style.get("event_font_family", default_style.get("event_font_family", "Arial"))
        )
        dialog.event_font_size.setValue(
            int(style.get("event_font_size", default_style.get("event_font_size", 10)))
        )
        dialog.event_labels_v3_toggle.setChecked(
            bool(
                style.get(
                    "event_labels_v3_enabled",
                    default_style.get("event_labels_v3_enabled", True),
                )
            )
        )
        mode_value = str(
            style.get(
                "event_label_mode",
                default_style.get("event_label_mode", "vertical"),
            )
        ).lower()
        mode_idx = dialog.event_label_mode.findData(mode_value)
        if mode_idx < 0:
            mode_idx = 0
        dialog.event_label_mode.setCurrentIndex(mode_idx)
        policy_value = str(
            style.get(
                "event_label_style_policy",
                default_style.get("event_label_style_policy", "first"),
            )
        ).lower()
        idx = dialog.event_cluster_style.findData(policy_value)
        if idx < 0:
            idx = 0
        dialog.event_cluster_style.setCurrentIndex(idx)
        dialog.event_max_per_cluster.setValue(
            int(
                style.get(
                    "event_label_max_per_cluster",
                    default_style.get("event_label_max_per_cluster", 1),
                )
            )
        )
        dialog.event_label_lanes.setValue(
            int(
                style.get(
                    "event_label_lanes",
                    default_style.get("event_label_lanes", 3),
                )
            )
        )
        dialog.event_belt_baseline.setChecked(
            bool(
                style.get(
                    "event_label_belt_baseline",
                    default_style.get("event_label_belt_baseline", True),
                )
            )
        )
        dialog.event_span_siblings.setChecked(
            bool(
                style.get(
                    "event_label_span_siblings",
                    default_style.get("event_label_span_siblings", True),
                )
            )
        )

        dialog.event_auto_mode.setChecked(
            bool(
                style.get(
                    "event_label_auto_mode",
                    default_style.get("event_label_auto_mode", False),
                )
            )
        )
        dialog.event_density_compact.setValue(
            float(
                style.get(
                    "event_label_density_compact",
                    default_style.get("event_label_density_compact", 0.8),
                )
            )
        )
        dialog.event_density_belt.setValue(
            float(
                style.get(
                    "event_label_density_belt",
                    default_style.get("event_label_density_belt", 0.25),
                )
            )
        )
        dialog.event_outline_enabled.setChecked(
            bool(
                style.get(
                    "event_label_outline_enabled",
                    default_style.get("event_label_outline_enabled", False),
                )
            )
        )
        dialog.event_outline_width.setValue(
            float(
                style.get(
                    "event_label_outline_width",
                    default_style.get("event_label_outline_width", 0.0),
                )
            )
        )
        with contextlib.suppress(AttributeError):
            dialog.event_outline_color_btn.setProperty(
                "color",
                style.get(
                    "event_label_outline_color",
                    default_style.get("event_label_outline_color", "#FFFFFFFF"),
                ),
            )
            if hasattr(dialog, "_set_button_color"):
                dialog._set_button_color(
                    dialog.event_outline_color_btn,
                    style.get(
                        "event_label_outline_color",
                        default_style.get("event_label_outline_color", "#FFFFFFFF"),
                    ),
                )

    dialog.event_tooltips_enabled.setChecked(
        bool(
            style.get(
                "event_label_tooltips_enabled",
                default_style.get("event_label_tooltips_enabled", True),
            )
        )
    )
    dialog.event_tooltip_proximity.setValue(
        int(
            style.get(
                "event_label_tooltip_proximity",
                default_style.get("event_label_tooltip_proximity", 10),
            )
        )
    )
    dialog.event_legend_enabled.setChecked(
        bool(
            style.get(
                "event_label_legend_enabled",
                default_style.get("event_label_legend_enabled", True),
            )
        )
    )
    dialog.event_legend_location.setCurrentText(
        str(
            style.get(
                "event_label_legend_loc",
                default_style.get("event_label_legend_loc", "upper right"),
            )
        )
    )

    return


def wire_event_labels_tab(dialog: DialogT) -> None:
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

    lane_spin = getattr(dialog, "event_label_lanes", None)
    if lane_spin is not None and hasattr(dialog, "_on_event_lane_count_changed"):
        lane_spin.valueChanged.connect(dialog._on_event_lane_count_changed)

    dialog._event_labels_tab_wired = current_refs
    return
