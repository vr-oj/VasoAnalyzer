import os

PREVIOUS_PLOT_PATH = os.path.join(
    os.path.expanduser("~"), ".vasoanalyzer_last_plot.pickle"
)

DEFAULT_STYLE = dict(
    axis_font_size=16,
    axis_font_family="Arial",
    axis_bold=True,
    axis_italic=False,
    tick_font_size=12,
    event_font_size=12,
    event_font_family="Arial",
    event_bold=False,
    event_italic=False,
    pin_font_size=10,
    pin_font_family="Arial",
    pin_bold=False,
    pin_italic=False,
    pin_size=6,
    line_width=2,
)
