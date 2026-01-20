from vasoanalyzer.ui.plots.pyqtgraph_style import (
    PLOT_AXIS_FONT_SIZE,
    PLOT_AXIS_LABELS,
    PLOT_AXIS_TOOLTIPS,
    PLOT_TICK_FONT_SIZE,
    get_pyqtgraph_style,
)
from vasoanalyzer.ui.theme import FONTS


def test_pyqtgraph_style_font_sizes_fixed() -> None:
    style = get_pyqtgraph_style()
    assert style.font_size == PLOT_AXIS_FONT_SIZE
    assert style.tick_font_size == PLOT_TICK_FONT_SIZE


def test_pyqtgraph_style_ignores_theme_size_overrides() -> None:
    original = dict(FONTS)
    try:
        FONTS["axis_size"] = 22
        FONTS["tick_size"] = 18
        style = get_pyqtgraph_style()
        assert style.font_size == PLOT_AXIS_FONT_SIZE
        assert style.tick_font_size == PLOT_TICK_FONT_SIZE
    finally:
        FONTS.clear()
        FONTS.update(original)


def test_pyqtgraph_axis_label_mapping() -> None:
    assert PLOT_AXIS_LABELS["inner"] == "ID (µm)"
    assert PLOT_AXIS_LABELS["outer"] == "OD (µm)"
    assert PLOT_AXIS_LABELS["avg_pressure"] == "P (mmHg)"
    assert PLOT_AXIS_LABELS["set_pressure"] == "SP (mmHg)"
    assert PLOT_AXIS_TOOLTIPS["inner"] == "Inner Diameter"
