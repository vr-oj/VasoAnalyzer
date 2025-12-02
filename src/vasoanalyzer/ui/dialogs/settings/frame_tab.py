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
    # Canvas size controls (white rectangle boundary)
    canvas_preset: QComboBox
    canvas_w: QDoubleSpinBox
    canvas_h: QDoubleSpinBox
    # Figure size controls (matplotlib plot)
    fig_preset: QComboBox
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

    # Canvas Size Section (white rectangle boundary in Figure Composer)
    canvas_box = QGroupBox("Canvas Size", tab)
    canvas_layout = QVBoxLayout(canvas_box)
    canvas_layout.setContentsMargins(12, 12, 12, 12)
    canvas_layout.setSpacing(8)

    canvas_hint = QLabel(
        "Canvas defines the white rectangle boundary (Figure Composer workspace).",
        canvas_box,
    )
    canvas_hint.setWordWrap(True)
    canvas_hint.setObjectName("PlotSettingsHint")
    canvas_layout.addWidget(canvas_hint)

    canvas_form = QFormLayout()
    canvas_form.setLabelAlignment(Qt.AlignRight)
    canvas_form.setHorizontalSpacing(12)
    canvas_form.setVerticalSpacing(6)

    canvas_preset = QComboBox(canvas_box)
    canvas_preset.addItems(["Auto (Wide)", "Square", "Custom"])
    canvas_form.addRow("Preset:", canvas_preset)

    canvas_w = QDoubleSpinBox(canvas_box)
    canvas_w.setRange(1, 30)
    canvas_w.setDecimals(1)
    canvas_form.addRow("Width (in):", canvas_w)

    canvas_h = QDoubleSpinBox(canvas_box)
    canvas_h.setRange(1, 30)
    canvas_h.setDecimals(1)
    canvas_form.addRow("Height (in):", canvas_h)

    canvas_layout.addLayout(canvas_form)
    layout.addWidget(canvas_box)

    # Figure Size Section (matplotlib plot, can be smaller than canvas)
    fig_box = QGroupBox("Figure Size", tab)
    fig_layout = QVBoxLayout(fig_box)
    fig_layout.setContentsMargins(12, 12, 12, 12)
    fig_layout.setSpacing(8)

    fig_hint = QLabel(
        "Figure is the matplotlib plot (can be smaller than canvas, will be centered).",
        fig_box,
    )
    fig_hint.setWordWrap(True)
    fig_hint.setObjectName("PlotSettingsHint")
    fig_layout.addWidget(fig_hint)

    fig_form = QFormLayout()
    fig_form.setLabelAlignment(Qt.AlignRight)
    fig_form.setHorizontalSpacing(12)
    fig_form.setVerticalSpacing(6)

    fig_preset = QComboBox(fig_box)
    fig_preset.addItems(["Fill Canvas", "Square", "Custom"])
    fig_form.addRow("Preset:", fig_preset)

    fig_w = QDoubleSpinBox(fig_box)
    fig_w.setRange(1, 30)
    fig_w.setDecimals(1)
    fig_form.addRow("Width (in):", fig_w)

    fig_h = QDoubleSpinBox(fig_box)
    fig_h.setRange(1, 30)
    fig_h.setDecimals(1)
    fig_form.addRow("Height (in):", fig_h)

    fig_layout.addLayout(fig_form)
    layout.addWidget(fig_box)

    layout.addStretch(1)

    return FrameTabRefs(
        tab=tab,
        origin_mode=origin_mode,
        origin_x=origin_x,
        origin_y=origin_y,
        canvas_preset=canvas_preset,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        fig_preset=fig_preset,
        fig_w=fig_w,
        fig_h=fig_h,
    )


def populate_frame_tab(dialog: DialogT) -> None:
    """Populate Frame tab controls with the current dialog state."""
    # Get parent window (FigureComposerWindow)
    parent = getattr(dialog, "parent_window", None)

    # Get figure size from parent state variables (not from matplotlib!)
    # Reading from matplotlib gives wrong values after zoom changes DPI
    if parent and hasattr(parent, "_figure_width_in"):
        fig_w = parent._figure_width_in
        fig_h = parent._figure_height_in
    else:
        # Fallback for main window (no zoom system)
        fig_w, fig_h = dialog.fig.get_size_inches()

    # Get canvas size from parent window
    canvas_w = getattr(parent, "_canvas_width_in", fig_w)
    canvas_h = getattr(parent, "_canvas_height_in", fig_h)

    widgets = [
        dialog.origin_mode,
        dialog.origin_x,
        dialog.origin_y,
        dialog.canvas_preset,
        dialog.canvas_w,
        dialog.canvas_h,
        dialog.fig_preset,
        dialog.fig_w,
        dialog.fig_h,
    ]

    with block_signals(widgets):
        # Origin controls
        dialog.origin_mode.setCurrentText("Automatic")
        dialog.origin_x.setValue(0.0)
        dialog.origin_y.setValue(0.0)

        # Canvas preset detection
        default_w = getattr(parent, "_default_frame_width_in", 10.0)
        default_h = getattr(parent, "_default_frame_height_in", 7.5)
        if abs(canvas_w - default_w) < 0.05 and abs(canvas_h - default_h) < 0.05:
            canvas_preset = "Auto (Wide)"
        elif abs(canvas_w - canvas_h) < 0.05:
            canvas_preset = "Square"
        else:
            canvas_preset = "Custom"
        dialog.canvas_preset.setCurrentText(canvas_preset)
        dialog.canvas_w.setValue(round(canvas_w, 1))
        dialog.canvas_h.setValue(round(canvas_h, 1))

        # Figure preset detection
        if abs(fig_w - canvas_w) < 0.05 and abs(fig_h - canvas_h) < 0.05:
            fig_preset = "Fill Canvas"
        elif abs(fig_w - fig_h) < 0.05:
            fig_preset = "Square"
        else:
            fig_preset = "Custom"
        dialog.fig_preset.setCurrentText(fig_preset)
        dialog.fig_w.setValue(round(fig_w, 1))
        dialog.fig_h.setValue(round(fig_h, 1))


def wire_frame_tab(dialog: DialogT) -> None:
    """Connect Frame tab signals (guarded to avoid duplicate wiring)."""

    if getattr(dialog, "_frame_tab_wired", False):
        return

    dialog.origin_mode.currentTextChanged.connect(dialog._toggle_origin_inputs)
    dialog.canvas_preset.currentTextChanged.connect(dialog._toggle_canvas_size_inputs)
    dialog.fig_preset.currentTextChanged.connect(dialog._toggle_fig_size_inputs)

    dialog._frame_tab_wired = True
