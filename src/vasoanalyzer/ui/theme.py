# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import re
from typing import cast

from matplotlib import rcParams
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

# -----------------------------------------------------------------------------
# Centralized Theme Definitions for VasoAnalyzer
# -----------------------------------------------------------------------------
# Define color tokens for the application theme
LIGHT_THEME = {
    "window_bg": "#FFFFFF",
    "text": "#000000",
    "button_bg": "#FFFFFF",
    "button_hover_bg": "#E6F0FF",
    "button_active_bg": "#CCE0FF",
    "toolbar_bg": "#F0F0F0",
    "table_bg": "#FFFFFF",
    "table_text": "#000000",
    "selection_bg": "#E6F0FF",
    "alternate_bg": "#F5F5F5",
    "hover_label_bg": "rgba(255,255,255,220)",
    "hover_label_border": "#888888",
    "grid_color": "#CCCCCC",
    "cursor_a": "#3366FF",
    "cursor_b": "#FF6B3D",
    "cursor_text": "#222222",
}

# Currently applied theme; defaults to light until explicitly changed
CURRENT_THEME = LIGHT_THEME

# Font settings
FONTS = {
    "family": "Arial",
    "axis_size": 14,
    "tick_size": 12,
    "event_size": 10,
    "pin_size": 10,
    "header_size": 13,
    "category_size": 15,
    "description_size": 17,
}

# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------


def css_rgba_to_mpl(color: str):
    """Convert an ``rgba(r,g,b,a)`` CSS color string to a matplotlib RGBA tuple."""
    if isinstance(color, str):
        m = re.fullmatch(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", color)
        if m:
            r, g, b, a = map(int, m.groups())
            return (r / 255, g / 255, b / 255, a / 255)
    return color


# -----------------------------------------------------------------------------
# Qt Palette & Stylesheet Application
# -----------------------------------------------------------------------------


def apply_qt_palette(theme: dict):
    """
    Create and apply a QPalette based on the provided theme dict.
    """
    palette = QPalette()
    # Window backgrounds and text
    palette.setColor(QPalette.Window, QColor(theme["window_bg"]))
    palette.setColor(QPalette.WindowText, QColor(theme["text"]))
    # Base (e.g., table background) and alternate
    palette.setColor(QPalette.Base, QColor(theme["table_bg"]))
    palette.setColor(QPalette.AlternateBase, QColor(theme["alternate_bg"]))
    # Buttons
    palette.setColor(QPalette.Button, QColor(theme["button_bg"]))
    palette.setColor(QPalette.ButtonText, QColor(theme["text"]))
    # Selections
    palette.setColor(QPalette.Highlight, QColor(theme["selection_bg"]))
    palette.setColor(QPalette.HighlightedText, QColor(theme["text"]))
    # Tooltips / hover labels
    palette.setColor(QPalette.ToolTipBase, QColor(theme["hover_label_bg"]))
    palette.setColor(QPalette.ToolTipText, QColor(theme["text"]))
    # Apply globally on the current application instance
    app = QApplication.instance()
    if app is not None:
        cast(QApplication, app).setPalette(palette)


def apply_qt_stylesheet(theme: dict):
    """
    Return a stylesheet string using theme tokens and font settings.
    """
    return f"""
QWidget {{
    background-color: {theme["window_bg"]};
    color: {theme["text"]};
    font-family: {FONTS["family"]};
}}
QPushButton {{
    background-color: {theme["button_bg"]};
    color: {theme["text"]};
    border: 1px solid {theme["grid_color"]};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background-color: {theme["button_hover_bg"]};
}}
QToolButton {{
    background-color: {theme["button_bg"]};
    color: {theme["text"]};
    border: 1px solid {theme["grid_color"]};
    border-radius: 6px;
    padding: 6px;
}}
QToolButton:hover {{
    background-color: {theme["button_hover_bg"]};
}}
QToolButton:checked,
QPushButton:checked {{
    background-color: {theme["button_active_bg"]};
}}
QToolTip {{
    background-color: {theme["hover_label_bg"]};
    color: {theme["text"]};
    border: 1px solid {theme["hover_label_border"]};
    padding: 2px 6px;
    border-radius: 5px;
}}
QTableWidget {{
    background-color: {theme["table_bg"]};
    color: {theme["table_text"]};
    alternate-background-color: {theme["alternate_bg"]};
}}
QTableWidget::item:selected {{
    background-color: {theme["selection_bg"]};
    color: {theme["table_text"]};
}}
QTableWidget::item:selected:!active {{
    background-color: {theme["selection_bg"]};
    color: {theme["table_text"]};
}}
QTableView::item:selected {{
    background-color: {theme["selection_bg"]};
    color: {theme["table_text"]};
}}
QTableView::item:selected:!active {{
    background-color: {theme["selection_bg"]};
    color: {theme["table_text"]};
}}
QHeaderView::section {{
    background-color: {theme["button_bg"]};
    color: {theme["text"]};
    font-weight: bold;
}}
QSlider::groove:horizontal, QSlider::groove:vertical {{
    background: {theme["grid_color"]};
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal, QSlider::handle:vertical {{
    background: {theme["button_bg"]};
    border: 1px solid {theme["grid_color"]};
    width: 12px;
    height: 12px;
    margin: -4px;
    border-radius: 6px;
}}
"""


# -----------------------------------------------------------------------------
# Matplotlib Style Application
# -----------------------------------------------------------------------------


def apply_matplotlib_style(theme: dict):
    """
    Update matplotlib rcParams according to the theme.
    """
    rcParams.update(
        {
            "axes.labelcolor": theme["text"],
            "xtick.color": theme["text"],
            "ytick.color": theme["text"],
            "text.color": theme["text"],
            "figure.facecolor": theme["window_bg"],
            "figure.edgecolor": theme["window_bg"],
            "grid.color": theme["grid_color"],
            "savefig.facecolor": theme["window_bg"],
            "savefig.edgecolor": theme["window_bg"],
        }
    )


# -----------------------------------------------------------------------------
# Convenience functions
# -----------------------------------------------------------------------------


def apply_light_theme():
    global CURRENT_THEME
    CURRENT_THEME = LIGHT_THEME
    apply_qt_palette(LIGHT_THEME)
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(apply_qt_stylesheet(LIGHT_THEME))
    apply_matplotlib_style(LIGHT_THEME)
