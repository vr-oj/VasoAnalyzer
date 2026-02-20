from __future__ import annotations

from vasoanalyzer.ui.plots.track_frame import TrackFrame
from vasoanalyzer.ui.theme import CURRENT_THEME, DARK_THEME, LIGHT_THEME


def test_plot_divider_theme_values_exist_and_differ() -> None:
    assert LIGHT_THEME.get("plot_divider") == "#CCCCCC"
    assert DARK_THEME.get("plot_divider") == "#3A3A3A"
    assert LIGHT_THEME.get("plot_divider") != DARK_THEME.get("plot_divider")


def test_track_frame_divider_uses_plot_divider_theme_key(qt_app) -> None:
    frame = TrackFrame()
    original = dict(CURRENT_THEME)
    try:
        CURRENT_THEME.clear()
        CURRENT_THEME.update(LIGHT_THEME)
        CURRENT_THEME["plot_divider"] = "#123456"
        assert frame._divider_color().name().lower() == "#123456"
    finally:
        CURRENT_THEME.clear()
        CURRENT_THEME.update(original)
