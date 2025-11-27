# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import re
import subprocess
import sys
from typing import cast

from matplotlib import rcParams
from PyQt5.QtCore import QSettings
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

DARK_THEME = dict(LIGHT_THEME)
DARK_THEME.update(
    {
        # Surfaces
        "window_bg": "#020617",  # near-black navy
        "plot_bg": "#020617",
        "toolbar_bg": "#020617",
        # Text
        "text": "#E5E7EB",
        "text_disabled": "#9CA3AF",
        # Tables
        "table_bg": "#020617",
        "table_text": "#E5E7EB",
        "alternate_bg": "#0B1120",
        "selection_bg": "#1D4ED8",
        # Buttons
        "button_bg": "#020617",
        "button_hover_bg": "#111827",
        "button_active_bg": "#1D4ED8",
        # Overlays / tooltips
        "hover_label_bg": "rgba(15,23,42,220)",
        "hover_label_border": "#4B5563",
        # Lines / grids / cursors
        "grid_color": "#374151",
        "cursor_a": "#38BDF8",
        "cursor_b": "#F97316",
        "cursor_text": "#E5E7EB",
        "cursor_line": "#38BDF8",
        # Accents
        "accent": "#38BDF8",
        "accent_fill": "#0EA5E9",
        "accent_fill_secondary": "#F97316",
        "event_line": "#9CA3AF",
        "event_highlight": "#1D4ED8",
        "time_cursor": "#F97316",
        # Trace defaults
        "trace_color": "#E5E7EB",
        "trace_color_secondary": "#F97316",
        # Warnings
        "warning_bg": "#451A03",
        "warning_border": "#F97316",
        "warning_text": "#FDE68A",
    }
)

# Extra contrast styling for dark mode widgets
DARK_WIDGET_CONTRAST_QSS = """
/* Core input widgets in dark mode */
QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {
    background-color: #1b212d;
    border: 1px solid #4a5368;
    border-radius: 3px;
    padding: 2px 4px;
}

/* Focus state: make the active field obvious */
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border: 1px solid #5292e4;
}

/* Checkboxes and radio buttons: clearer indicators */
QCheckBox::indicator,
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border-radius: 2px;
    border: 1px solid #9aa2b5;
    background: #1b212d;
}

QCheckBox::indicator:checked,
QRadioButton::indicator:checked {
    background: #5292e4;
    border-color: #5292e4;
}

/* Optional: hover state for indicators */
QCheckBox::indicator:hover,
QRadioButton::indicator:hover {
    border-color: #c3cadb;
}

/* Group boxes: faint borders so sections are visible */
QGroupBox {
    border: 1px solid #343b4d;
    border-radius: 3px;
    margin-top: 6px;
    padding-top: 6px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
}
"""

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


def _apply_theme(theme: dict) -> None:
    """Internal helper to push theme to Qt + matplotlib."""
    global CURRENT_THEME
    CURRENT_THEME = theme
    apply_qt_palette(theme)

    app = QApplication.instance()
    if app is not None:
        cast(QApplication, app).setStyleSheet(apply_qt_stylesheet(theme))

    apply_matplotlib_style(theme)


def apply_light_theme() -> None:
    """Force the light theme."""
    _apply_theme(LIGHT_THEME)


def apply_dark_theme() -> None:
    """Force the dark theme."""
    _apply_theme(DARK_THEME)

    # Append dark-mode widget contrast tweaks on top of the theme stylesheet
    app = QApplication.instance()
    if app is not None:
        q_app = cast(QApplication, app)
        existing_qss = q_app.styleSheet() or ""
        q_app.setStyleSheet(existing_qss + "\n" + DARK_WIDGET_CONTRAST_QSS)


def detect_system_theme() -> str:
    """
    Try to detect the OS theme preference.

    Returns:
        "dark" or "light" (defaults to "light" on errors/unknown platforms).
    """
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and "Dark" in result.stdout:
                return "dark"
        except Exception:
            pass
        return "light"

    if sys.platform.startswith("win"):
        try:
            import winreg  # type: ignore[attr-defined]

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if value else "dark"
        except Exception:
            return "light"

    return "light"


def apply_theme_from_settings() -> str:
    """
    Apply the theme configured in QSettings and return the effective theme.

    QSettings key:
        appearance/themeMode -> "light", "dark", or "system" (default "system").

    Returns:
        "light" or "dark" depending on what was ultimately applied.
    """
    try:
        settings = QSettings("TykockiLab", "VasoAnalyzer")
        mode = settings.value("appearance/themeMode", "system", type=str)
    except Exception:
        mode = "system"

    if mode == "light":
        apply_light_theme()
        return "light"

    if mode == "dark":
        apply_dark_theme()
        return "dark"

    system_mode = detect_system_theme()
    if system_mode == "dark":
        apply_dark_theme()
    else:
        apply_light_theme()
    return system_mode
