from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from matplotlib.axes import Axes
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.dialogs.settings._shared import block_signals
from vasoanalyzer.ui.theme import CURRENT_THEME

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
    "LayoutTabRefs",
    "create_layout_tab_widgets",
    "populate_layout_tab",
    "wire_layout_tab",
]


@dataclass
class LayoutTabRefs:
    tab: QWidget
    layout_controls: dict[str, QDoubleSpinBox]
    layout_sliders: dict[str, QSlider]
    preview_fig: Figure
    preview_canvas: FigureCanvas
    preview_ax: Axes


def _make_slider_row() -> tuple[QWidget, QSlider, QDoubleSpinBox]:
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 100)

    spin = QDoubleSpinBox()
    spin.setRange(0.0, 1.0)
    spin.setSingleStep(0.01)
    spin.setDecimals(2)

    slider.valueChanged.connect(lambda value, target=spin: target.setValue(value / 100))
    spin.valueChanged.connect(lambda value, target=slider: target.setValue(int(value * 100)))

    row.addWidget(slider, 1)
    row.addWidget(spin)
    return container, slider, spin


def create_layout_tab_widgets(dialog: DialogT, window) -> LayoutTabRefs:
    """
    Move ONLY widget creation and layout from _make_layout_tab legacy.
    Return the tab + the controls you need to reattach on dialog.
    """
    content = QWidget()
    main = QHBoxLayout(content)
    main.setContentsMargins(0, 0, 0, 0)
    main.setSpacing(12)

    controls_box = QGroupBox("Subplot Margins & Spacing")
    controls_layout = QVBoxLayout(controls_box)
    controls_layout.setContentsMargins(12, 12, 12, 12)
    controls_layout.setSpacing(10)

    help_lbl = QLabel("Adjust subplot margins in figure fraction (0 → edge, 1 → outside).")
    help_lbl.setWordWrap(True)
    help_lbl.setObjectName("PlotSettingsHint")
    controls_layout.addWidget(help_lbl)

    controls_form = QFormLayout()
    controls_form.setLabelAlignment(Qt.AlignRight)
    controls_form.setHorizontalSpacing(12)
    controls_form.setVerticalSpacing(8)

    labels = [
        ("left", "Left margin"),
        ("right", "Right margin"),
        ("top", "Top margin"),
        ("bottom", "Bottom margin"),
        ("wspace", "Width gap"),
        ("hspace", "Height gap"),
    ]

    sliders: dict[str, QSlider] = {}
    controls: dict[str, QDoubleSpinBox] = {}

    for name, label_text in labels:
        row_widget, slider, spin = _make_slider_row()
        controls_form.addRow(f"{label_text}:", row_widget)
        sliders[name] = slider
        controls[name] = spin

    controls_layout.addLayout(controls_form)
    controls_layout.addStretch(1)

    main.addWidget(controls_box, 1)

    preview_box = QGroupBox("Preview")
    preview_layout = QVBoxLayout(preview_box)
    preview_layout.setContentsMargins(12, 12, 12, 12)
    preview_layout.setSpacing(8)

    dpi = dialog.logicalDpiX()
    preview_fig = Figure(figsize=(2.5, 2.5), facecolor=CURRENT_THEME["window_bg"], dpi=dpi)
    preview_canvas = FigureCanvas(preview_fig)
    preview_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    preview_ax = preview_fig.add_subplot(111)
    preview_ax.axis("off")
    preview_layout.addWidget(preview_canvas, 1)

    main.addWidget(preview_box, 1)
    main.setStretch(0, 1)
    main.setStretch(1, 1)

    scroll = QScrollArea()
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)

    return LayoutTabRefs(
        tab=scroll,
        layout_controls=controls,
        layout_sliders=sliders,
        preview_fig=preview_fig,
        preview_canvas=preview_canvas,
        preview_ax=preview_ax,
    )


def populate_layout_tab(dialog: DialogT) -> None:
    """Filled in slice B (set values using block_signals)."""
    layout_controls = getattr(dialog, "layout_controls", None)
    if not layout_controls:
        dialog.initial_layout = dialog._get_initial_layout()
        return

    params = dialog._get_initial_layout()
    dialog.initial_layout = dict(params)
    sliders = getattr(dialog, "_layout_sliders", {}) or {}
    widgets_to_block = list(layout_controls.values()) + list(sliders.values())

    with block_signals(widgets_to_block):
        for name, control in layout_controls.items():
            value = float(params.get(name, control.value()))
            slider = sliders.get(name)
            if slider is not None:
                slider.setValue(int(value * 100))
            control.setValue(value)

    return


def wire_layout_tab(dialog: DialogT) -> None:
    """Filled in slice C (connect signals; guard duplicate wiring)."""
    controls = getattr(dialog, "layout_controls", None)
    if not controls:
        return

    sentinel = getattr(dialog, "_layout_tab_wired", None)
    if sentinel is controls:
        return

    for control in controls.values():
        control.valueChanged.connect(dialog.update_preview)

    dialog._layout_tab_wired = controls
    return
