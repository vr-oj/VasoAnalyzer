from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QScrollArea,
    QSpinBox,
    QWidget,
)

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedPlotSettingsDialog as DialogT
else:  # pragma: no cover

    class DialogT:  # type: ignore
        """Fallback dialog stub for type checking."""

        pass


__all__ = ["build_axis_tab"]


def build_axis_tab(dialog: DialogT, window=None) -> QWidget:
    content = QWidget()
    grid = QGridLayout(content)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(12)

    # -- X Axis ---------------------------------------------------
    x_grp = QGroupBox("X Axis")
    x_form = QFormLayout(x_grp)
    x_form.setLabelAlignment(Qt.AlignRight)
    dialog.x_auto = QCheckBox("Auto range")
    dialog.x_auto.setChecked(dialog.ax.get_autoscalex_on())
    dialog.x_min = QDoubleSpinBox()
    dialog.x_min.setSuffix(" s")
    dialog.x_min.setRange(-1e6, 1e6)
    dialog.x_min.setValue(round(dialog.ax.get_xlim()[0], 2))
    dialog.x_max = QDoubleSpinBox()
    dialog.x_max.setSuffix(" s")
    dialog.x_max.setRange(-1e6, 1e6)
    dialog.x_max.setValue(round(dialog.ax.get_xlim()[1], 2))
    dialog.x_auto.toggled.connect(
        lambda b: dialog._toggle_range_inputs([dialog.x_min, dialog.x_max], not b)
    )
    dialog._toggle_range_inputs([dialog.x_min, dialog.x_max], not dialog.x_auto.isChecked())
    x_form.addRow(dialog.x_auto)
    x_form.addRow("Range:", dialog._pair(dialog.x_min, dialog.x_max))
    dialog.x_scale = QComboBox()
    dialog.x_scale.addItems(["Linear", "Log"])
    dialog.x_scale.setCurrentText("Log" if dialog.ax.get_xscale() == "log" else "Linear")
    x_form.addRow("Scale:", dialog.x_scale)
    dialog.x_ticks = QSpinBox()
    dialog.x_ticks.setRange(2, 20)
    dialog.x_ticks.setValue(len(dialog.ax.get_xticks()))
    x_form.addRow("Major ticks:", dialog.x_ticks)
    grid.addWidget(x_grp, 0, 0)

    # -- Top Plot (primary Y) -------------------------------------
    top_title = dialog._axis_section_title(dialog.ax, "Top Plot")
    top_units = dialog._axis_units_suffix(dialog.ax)
    y_grp = QGroupBox(top_title)
    y_form = QFormLayout(y_grp)
    y_form.setLabelAlignment(Qt.AlignRight)
    dialog.y_auto = QCheckBox("Auto range")
    dialog.y_auto.setChecked(dialog.ax.get_autoscaley_on())
    dialog.yi_min = QDoubleSpinBox()
    if top_units:
        dialog.yi_min.setSuffix(top_units)
    dialog.yi_min.setRange(-1e6, 1e6)
    dialog.yi_min.setValue(round(dialog.ax.get_ylim()[0], 2))
    dialog.yi_max = QDoubleSpinBox()
    if top_units:
        dialog.yi_max.setSuffix(top_units)
    dialog.yi_max.setRange(-1e6, 1e6)
    dialog.yi_max.setValue(round(dialog.ax.get_ylim()[1], 2))
    dialog.y_auto.toggled.connect(
        lambda b: dialog._toggle_range_inputs([dialog.yi_min, dialog.yi_max], not b)
    )
    dialog._toggle_range_inputs([dialog.yi_min, dialog.yi_max], not dialog.y_auto.isChecked())
    y_form.addRow(dialog.y_auto)
    y_form.addRow("Range:", dialog._pair(dialog.yi_min, dialog.yi_max))
    dialog.y_scale = QComboBox()
    dialog.y_scale.addItems(["Linear", "Log"])
    dialog.y_scale.setCurrentText("Log" if dialog.ax.get_yscale() == "log" else "Linear")
    y_form.addRow("Scale:", dialog.y_scale)
    dialog.y_ticks = QSpinBox()
    dialog.y_ticks.setRange(2, 20)
    dialog.y_ticks.setValue(len(dialog.ax.get_yticks()))
    y_form.addRow("Major ticks:", dialog.y_ticks)
    grid.addWidget(y_grp, 0, 1)

    # -- Bottom Plot (secondary Y) --------------------------------
    if dialog.ax2 is not None:
        bottom_title = dialog._axis_section_title(dialog.ax2, "Bottom Plot")
        bottom_units = dialog._axis_units_suffix(dialog.ax2)
        yo_grp = QGroupBox(bottom_title)
        yo_form = QFormLayout(yo_grp)
        yo_form.setLabelAlignment(Qt.AlignRight)
        dialog.yo_auto = QCheckBox("Auto range")
        dialog.yo_auto.setChecked(dialog.ax2.get_autoscaley_on())
        dialog.yo_min = QDoubleSpinBox()
        if bottom_units:
            dialog.yo_min.setSuffix(bottom_units)
        dialog.yo_min.setRange(-1e6, 1e6)
        dialog.yo_min.setValue(round(dialog.ax2.get_ylim()[0], 2))
        dialog.yo_max = QDoubleSpinBox()
        if bottom_units:
            dialog.yo_max.setSuffix(bottom_units)
        dialog.yo_max.setRange(-1e6, 1e6)
        dialog.yo_max.setValue(round(dialog.ax2.get_ylim()[1], 2))
        dialog.yo_auto.toggled.connect(
            lambda b: dialog._toggle_range_inputs([dialog.yo_min, dialog.yo_max], not b)
        )
        dialog._toggle_range_inputs([dialog.yo_min, dialog.yo_max], not dialog.yo_auto.isChecked())
        yo_form.addRow(dialog.yo_auto)
        yo_form.addRow("Range:", dialog._pair(dialog.yo_min, dialog.yo_max))
        dialog.yo_scale = QComboBox()
        dialog.yo_scale.addItems(["Linear", "Log"])
        dialog.yo_scale.setCurrentText("Log" if dialog.ax2.get_yscale() == "log" else "Linear")
        yo_form.addRow("Scale:", dialog.yo_scale)
        dialog.yo_ticks = QSpinBox()
        dialog.yo_ticks.setRange(2, 20)
        dialog.yo_ticks.setValue(len(dialog.ax2.get_yticks()))
        yo_form.addRow("Major ticks:", dialog.yo_ticks)
        grid.addWidget(yo_grp, 1, 0)

    # -- Grid & Ticks ---------------------------------------------
    tick_grp = QGroupBox("Grid && Ticks")
    tick_form = QFormLayout(tick_grp)
    dialog.show_grid = QCheckBox("Show grid")
    grid_state = getattr(dialog.parent_window, "grid_visible", None)
    if grid_state is None:
        grid_state = any(line.get_visible() for line in dialog.ax.get_xgridlines())
    dialog.show_grid.setChecked(bool(grid_state))
    dialog.tick_length = QDoubleSpinBox()
    dialog.tick_length.setRange(0.0, 20.0)
    dialog.tick_length.setValue(float(dialog.style.get("tick_length", 4.0)))
    dialog.tick_width = QDoubleSpinBox()
    dialog.tick_width.setRange(0.5, 5.0)
    dialog.tick_width.setValue(float(dialog.style.get("tick_width", 1.0)))
    tick_form.addRow(dialog.show_grid)
    tick_form.addRow("Tick length:", dialog.tick_length)
    tick_form.addRow("Tick width:", dialog.tick_width)
    grid.addWidget(tick_grp, 1, 1)

    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    grid.setRowStretch(2, 1)

    scroll = QScrollArea()
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)

    return scroll
