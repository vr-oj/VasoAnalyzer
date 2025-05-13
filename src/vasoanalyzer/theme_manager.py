from PyQt5.QtGui import QPalette, QColor, QFont
from PyQt5.QtWidgets import QApplication
from matplotlib import rcParams

# -----------------------------------------------------------------------------
# Centralized Theme Definitions for VasoAnalyzer
# -----------------------------------------------------------------------------
# Define color tokens for light and dark themes
LIGHT_THEME = {
    'window_bg': '#F5F5F5',
    'text': '#000000',
    'button_bg': '#FFFFFF',
    'button_hover_bg': '#E6F0FF',
    'toolbar_bg': '#F0F0F0',
    'table_bg': '#FFFFFF',
    'table_text': '#000000',
    'selection_bg': '#E6F0FF',
    'alternate_bg': '#F5F5F5',
    'hover_label_bg': 'rgba(255,255,255,220)',
    'hover_label_border': '#888888',
    'grid_color': '#CCCCCC',
}

DARK_THEME = {
    'window_bg': '#2E2E2E',
    'text': '#FFFFFF',
    'button_bg': '#3C3C3C',
    'button_hover_bg': '#505050',
    'toolbar_bg': '#333333',
    'table_bg': '#3C3C3C',
    'table_text': '#FFFFFF',
    'selection_bg': '#505470',
    'alternate_bg': '#2A2A2A',
    'hover_label_bg': 'rgba(60,60,60,220)',
    'hover_label_border': '#AAAAAA',
    'grid_color': '#444444',
}

# Font settings
FONTS = {
    'family': 'Arial',
    'axis_size': 14,
    'tick_size': 12,
    'event_size': 10,
    'pin_size': 10,
    'header_size': 13,
    'category_size': 15,
    'description_size': 17,
}

# -----------------------------------------------------------------------------
# Qt Palette & Stylesheet Application
# -----------------------------------------------------------------------------

def apply_qt_palette(theme: dict):
    """
    Create and apply a QPalette based on the provided theme dict.
    """
    palette = QPalette()
    # Window backgrounds and text
    palette.setColor(QPalette.Window, QColor(theme['window_bg']))
    palette.setColor(QPalette.WindowText, QColor(theme['text']))
    # Base (e.g., table background) and alternate
    palette.setColor(QPalette.Base, QColor(theme['table_bg']))
    palette.setColor(QPalette.AlternateBase, QColor(theme['alternate_bg']))
    # Buttons
    palette.setColor(QPalette.Button, QColor(theme['button_bg']))
    palette.setColor(QPalette.ButtonText, QColor(theme['text']))
    # Selections
    palette.setColor(QPalette.Highlight, QColor(theme['selection_bg']))
    palette.setColor(QPalette.HighlightedText, QColor(theme['text']))
    # Tooltips / hover labels
    palette.setColor(QPalette.ToolTipBase, QColor(theme['hover_label_bg']))
    palette.setColor(QPalette.ToolTipText, QColor(theme['text']))
    # Apply globally
    QApplication.setPalette(palette)


def apply_qt_stylesheet(theme: dict):
    """
    Return a stylesheet string using theme tokens and font settings.
    """
    return f"""
QWidget {{
    background-color: {theme['window_bg']};
    color: {theme['text']};
    font-family: {FONTS['family']};
}}
QPushButton {{
    background-color: {theme['button_bg']};
    color: {theme['text']};
    border: 1px solid {theme['grid_color']};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background-color: {theme['button_hover_bg']};
}}
QToolButton {{
    background-color: {theme['button_bg']};
    color: {theme['text']};
    border: 1px solid {theme['grid_color']};
    border-radius: 6px;
    padding: 6px;
}}
QToolButton:hover {{
    background-color: {theme['button_hover_bg']};
}}
QTableWidget {{
    background-color: {theme['table_bg']};
    color: {theme['table_text']};
    alternate-background-color: {theme['alternate_bg']};
}}
QTableWidget::item:selected {{
    background-color: {theme['selection_bg']};
}}
QHeaderView::section {{
    background-color: {theme['button_bg']};
    color: {theme['text']};
    font-weight: bold;
}}
QSlider::groove:horizontal, QSlider::groove:vertical {{
    background: {theme['grid_color']};
}}
"""

# -----------------------------------------------------------------------------
# Matplotlib Style Application
# -----------------------------------------------------------------------------

def apply_matplotlib_style(theme: dict):
    """
    Update matplotlib rcParams according to the theme.
    """
    rcParams.update({
        'axes.labelcolor': theme['text'],
        'xtick.color': theme['text'],
        'ytick.color': theme['text'],
        'text.color': theme['text'],
        'figure.facecolor': theme['window_bg'],
        'figure.edgecolor': theme['window_bg'],
        'grid.color': theme['grid_color'],
        'savefig.facecolor': theme['window_bg'],
        'savefig.edgecolor': theme['window_bg'],
    })

# -----------------------------------------------------------------------------
# Convenience functions
# -----------------------------------------------------------------------------

def apply_light_theme():
    apply_qt_palette(LIGHT_THEME)
    QApplication.setStyleSheet(apply_qt_stylesheet(LIGHT_THEME))
    apply_matplotlib_style(LIGHT_THEME)


def apply_dark_theme():
    apply_qt_palette(DARK_THEME)
    QApplication.setStyleSheet(apply_qt_stylesheet(DARK_THEME))
    apply_matplotlib_style(DARK_THEME)
