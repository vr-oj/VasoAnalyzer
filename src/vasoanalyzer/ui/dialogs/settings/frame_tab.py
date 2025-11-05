from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:  # pragma: no cover
    try:
        from vasoanalyzer.ui.dialogs.unified_settings_dialog import (
            UnifiedPlotSettingsDialog as DialogT,
        )
    except Exception:  # pragma: no cover
        from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedSettingsDialog as DialogT
else:  # pragma: no cover

    class DialogT:  # type: ignore
        pass


from ._shared import block_signals

__all__ = ["FrameTabRefs", "create_frame_tab_widgets", "populate_frame_tab", "wire_frame_tab"]


@dataclass
class FrameTabRefs:
    tab: QWidget
    origin_mode: QComboBox
    origin_x: QDoubleSpinBox
    origin_y: QDoubleSpinBox
    size_preset: QComboBox
    fig_w: QDoubleSpinBox
    fig_h: QDoubleSpinBox


def create_frame_tab_widgets(dialog: DialogT, window) -> FrameTabRefs:
    tab = QWidget(parent=dialog)
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    origin_box = QGroupBox("Axis Origin", tab)
    origin_layout = QVBoxLayout(origin_box)
    origin_layout.setContentsMargins(12, 12, 12, 12)
    origin_layout.setSpacing(8)

    origin_hint = QLabel(
        "Shift where the axes cross. Manual mode anchors them to a specific data point.",
        origin_box,
    )
    origin_hint.setWordWrap(True)
    origin_hint.setObjectName("PlotSettingsHint")
    origin_layout.addWidget(origin_hint)

    origin_form = QFormLayout()
    origin_form.setLabelAlignment(Qt.AlignRight)
    origin_form.setHorizontalSpacing(12)
    origin_form.setVerticalSpacing(6)

    origin_mode = QComboBox(origin_box)
    origin_mode.addItems(["Automatic", "Manual"])
    origin_form.addRow("Mode:", origin_mode)

    origin_x = QDoubleSpinBox(origin_box)
    origin_x.setDecimals(2)
    origin_x.setRange(-1e6, 1e6)
    origin_form.addRow("Y ↔ X at X:", origin_x)

    origin_y = QDoubleSpinBox(origin_box)
    origin_y.setDecimals(2)
    origin_y.setRange(-1e6, 1e6)
    origin_form.addRow("X ↔ Y at Y:", origin_y)

    origin_layout.addLayout(origin_form)
    layout.addWidget(origin_box)

    size_box = QGroupBox("Figure Size", tab)
    size_layout = QVBoxLayout(size_box)
    size_layout.setContentsMargins(12, 12, 12, 12)
    size_layout.setSpacing(8)

    size_hint = QLabel(
        "Choose a preset or enter custom width/height (inches) for export and layout decisions.",
        size_box,
    )
    size_hint.setWordWrap(True)
    size_hint.setObjectName("PlotSettingsHint")
    size_layout.addWidget(size_hint)

    size_form = QFormLayout()
    size_form.setLabelAlignment(Qt.AlignRight)
    size_form.setHorizontalSpacing(12)
    size_form.setVerticalSpacing(6)

    size_preset = QComboBox(size_box)
    size_preset.addItems(["Auto (Wide)", "Square", "Custom"])
    size_form.addRow("Preset:", size_preset)

    fig_w = QDoubleSpinBox(size_box)
    fig_w.setRange(1, 30)
    fig_w.setDecimals(1)
    size_form.addRow("Width (in):", fig_w)

    fig_h = QDoubleSpinBox(size_box)
    fig_h.setRange(1, 30)
    fig_h.setDecimals(1)
    size_form.addRow("Height (in):", fig_h)

    size_layout.addLayout(size_form)
    layout.addWidget(size_box)

    layout.addStretch(1)

    return FrameTabRefs(
        tab=tab,
        origin_mode=origin_mode,
        origin_x=origin_x,
        origin_y=origin_y,
        size_preset=size_preset,
        fig_w=fig_w,
        fig_h=fig_h,
    )


def populate_frame_tab(dialog: DialogT) -> None:
    """Populate Frame tab controls with the current dialog state."""

    fig_w, fig_h = dialog.fig.get_size_inches()
    widgets = [
        dialog.origin_mode,
        dialog.origin_x,
        dialog.origin_y,
        dialog.size_preset,
        dialog.fig_w,
        dialog.fig_h,
    ]

    with block_signals(widgets):
        dialog.origin_mode.setCurrentText("Automatic")
        dialog.origin_x.setValue(0.0)
        dialog.origin_y.setValue(0.0)

        dialog.size_preset.setCurrentText("Auto (Wide)")
        dialog.fig_w.setValue(round(fig_w, 1))
        dialog.fig_h.setValue(round(fig_h, 1))


def wire_frame_tab(dialog: DialogT) -> None:
    """Connect Frame tab signals (guarded to avoid duplicate wiring)."""

    if getattr(dialog, "_frame_tab_wired", False):
        return

    dialog.origin_mode.currentTextChanged.connect(dialog._toggle_origin_inputs)
    dialog.size_preset.currentTextChanged.connect(dialog._toggle_size_inputs)

    dialog._frame_tab_wired = True
