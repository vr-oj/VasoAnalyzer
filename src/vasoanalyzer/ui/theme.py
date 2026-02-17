# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import base64
import contextlib
import inspect
import logging
import re
from pathlib import Path
from typing import cast

from matplotlib import rcParams
from PyQt5.QtCore import QObject, QSettings, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

log = logging.getLogger(__name__)

try:  # Optional helper used for locating packaged resources
    from utils import resource_path
except Exception:  # pragma: no cover - resource helper missing or not packaged
    resource_path = None

# -----------------------------------------------------------------------------
# Color Derivation Helpers / Presets
# -----------------------------------------------------------------------------

# Complete theme presets - no OS palette dependency
LIGHT_THEME = {
    # Surfaces
    "window_bg": "#F3F4F6",  # Gray chrome (toolbars, status bar)
    "plot_bg": "#FFFFFF",  # White content area
    "toolbar_bg": "#F3F4F6",
    "table_bg": "#FFFFFF",
    "alternate_bg": "#F9FAFB",
    "panel_bg": "#FFFFFF",
    # Text
    "text": "#111827",
    "text_disabled": "#9CA3AF",
    "table_text": "#111827",
    # Buttons
    "button_bg": "#F3F4F6",
    "button_hover_bg": "#E5E7EB",
    "button_active_bg": "#3B82F6",
    # Grids and borders
    "grid_color": "#E5E7EB",
    "table_header_border": "#D1D5DB",
    "panel_border": "#D1D5DB",
    "hover_label_bg": "rgba(243, 244, 246, 0.9)",
    "hover_label_border": "#D1D5DB",
    # Selection
    "selection_bg": "#3B82F6",
    "highlighted_text": "#FFFFFF",
    # Lines / cursors / semantic colors
    "cursor_a": "#3366FF",
    "cursor_b": "#FF6B3D",
    "cursor_text": "#111827",
    "cursor_line": "#3366FF",
    "accent": "#3B82F6",
    "accent_fill": "#2563EB",
    "accent_fill_secondary": "#FF6B3D",
    "event_line": "#9CA3AF",
    "event_highlight": "#3B82F6",
    "time_cursor": "#FF6B3D",
    "trace_color": "#111827",
    "trace_color_secondary": "#FF6B3D",
    # Warnings
    "warning_bg": "#FEF3C7",
    "warning_border": "#F59E0B",
    "warning_text": "#78350F",
    # Snapshot
    "snapshot_bg": "#F3F4F6",
    "table_hover": "#F3F4F6",
    "table_editable_hover": "#DBEAFE",
    "table_focused_border": "#3366FF",
    "panel_radius": 6,
}

DARK_THEME = {
    # Surfaces
    "window_bg": "#1E242D",  # Dark gray chrome
    "plot_bg": "#0D1117",  # Dark content area
    "toolbar_bg": "#1E242D",
    "table_bg": "#0D1117",
    "alternate_bg": "#161B22",
    "panel_bg": "#0D1117",
    # Text
    "text": "#E6EDF3",
    "text_disabled": "#7D8590",
    "table_text": "#E6EDF3",
    # Buttons
    "button_bg": "#21262D",
    "button_hover_bg": "#30363D",
    "button_active_bg": "#388BFD",
    # Grids and borders
    "grid_color": "#30363D",
    "table_header_border": "#373E47",
    "panel_border": "#373E47",
    "hover_label_bg": "rgba(30, 36, 45, 0.9)",
    "hover_label_border": "#30363D",
    # Selection
    "selection_bg": "#1F6FEB",
    "highlighted_text": "#FFFFFF",
    # Lines / cursors / semantic colors
    "cursor_a": "#58A6FF",
    "cursor_b": "#F97316",
    "cursor_text": "#E6EDF3",
    "cursor_line": "#58A6FF",
    "accent": "#58A6FF",
    "accent_fill": "#1F6FEB",
    "accent_fill_secondary": "#F97316",
    "event_line": "#6E7681",
    "event_highlight": "#1F6FEB",
    "time_cursor": "#F97316",
    "trace_color": "#E6EDF3",
    "trace_color_secondary": "#F97316",
    # Warnings
    "warning_bg": "#451A03",
    "warning_border": "#F97316",
    "warning_text": "#FDE68A",
    # Snapshot
    "snapshot_bg": "#0D1117",
    "table_hover": "#21262D",
    "table_editable_hover": "#1C3D5A",
    "table_focused_border": "#3B82F6",
    "panel_radius": 6,
}


def hex_to_pyqtgraph_color(hex_color: str) -> tuple[int, int, int]:
    """Convert CSS hex color to RGB tuple for PyQtGraph.

    PyQtGraph's setBackground() requires RGB tuple, not CSS hex strings.

    Args:
        hex_color: CSS hex color like "#FFFFFF" or "#FFF"

    Returns:
        RGB tuple like (255, 255, 255)
    """
    qcolor = QColor(hex_color)
    if not qcolor.isValid():
        qcolor = QColor("#FFFFFF")  # Fallback to white

    return (qcolor.red(), qcolor.green(), qcolor.blue())


def _lighten_color(color: QColor, factor: float) -> str:
    """Lighten a color by increasing value in HSV space."""
    h, s, v, a = color.getHsvF()
    v = min(1.0, v + factor)
    return QColor.fromHsvF(h, s, v, a).name()


def _darken_color(color: QColor, factor: float) -> str:
    """Darken a color by decreasing value in HSV space."""
    h, s, v, a = color.getHsvF()
    v = max(0.0, v - factor)
    return QColor.fromHsvF(h, s, v, a).name()


def _derive_grid_color(base: QColor, is_dark: bool) -> str:
    """Derive grid color: 15% lighter (dark) or darker (light) than base."""
    return _lighten_color(base, 0.15) if is_dark else _darken_color(base, 0.15)


def _derive_hover_color(base: QColor, is_dark: bool) -> str:
    """Derive hover state: 10% lighter (dark) or darker (light)."""
    return _lighten_color(base, 0.10) if is_dark else _darken_color(base, 0.10)


def _derive_border_color(text_color: QColor) -> str:
    """Derive border color: text color at 40% opacity."""
    r, g, b = text_color.red(), text_color.green(), text_color.blue()
    return f"rgba({r}, {g}, {b}, 0.4)"


def _derive_tooltip_bg(window_bg: QColor, is_dark: bool) -> str:
    """Derive tooltip background with transparency."""
    r, g, b = window_bg.red(), window_bg.green(), window_bg.blue()
    alpha = 220  # Semi-transparent
    return f"rgba({r}, {g}, {b}, {alpha})"


def _pick_contrast_color(color_str: str, *, light: str = "#FFFFFF", dark: str = "#111827") -> str:
    """Pick a high-contrast color for a given background."""
    color = QColor(color_str)
    if not color.isValid():
        return light
    return light if color.lightness() < 128 else dark


def _svg_data_uri(svg: str) -> str:
    """Return a data URI for an SVG payload."""
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


# -----------------------------------------------------------------------------
# OS Palette Extraction
# -----------------------------------------------------------------------------


def _build_theme_from_palette(force_dark: bool | None = None) -> dict:
    """
    Build theme dictionary from OS palette with optional dark mode override.

    Args:
        force_dark: If None, auto-detect from palette. If True/False, force that mode.

    Returns:
        Theme dict with colors derived from OS palette.
    """
    app = QApplication.instance()
    palette = app.palette() if app else QPalette()

    # Extract base colors from OS palette
    window_bg = palette.color(QPalette.Window)
    window_text = palette.color(QPalette.WindowText)
    base = palette.color(QPalette.Base)
    alternate_base = palette.color(QPalette.AlternateBase)
    button = palette.color(QPalette.Button)
    highlight = palette.color(QPalette.Highlight)
    highlighted_text = palette.color(QPalette.HighlightedText)
    mid = palette.color(QPalette.Mid)

    # Detect or override dark mode
    if force_dark is None:
        is_dark = window_bg.lightness() < 128
    else:
        is_dark = force_dark

    # Build comprehensive theme dict with OS colors + derived states
    theme = {
        # Surfaces
        "window_bg": window_bg.name(),
        "plot_bg": base.name(),  # Use Base for plot backgrounds
        "toolbar_bg": window_bg.name(),
        "is_dark": bool(is_dark),
        # Text
        "text": window_text.name(),
        "text_disabled": mid.name(),  # Mid palette role for disabled text
        # Tables
        "table_bg": base.name(),
        "table_text": window_text.name(),
        "alternate_bg": alternate_base.name(),
        "selection_bg": highlight.name(),
        # Buttons
        "button_bg": button.name(),
        "button_hover_bg": _derive_hover_color(button, is_dark),
        "button_active_bg": highlight.name(),
        # Overlays / tooltips
        "hover_label_bg": _derive_tooltip_bg(window_bg, is_dark),
        "hover_label_border": mid.name(),
        # Lines / grids / cursors
        "grid_color": _derive_grid_color(base, is_dark),
        "cursor_a": "#38BDF8" if is_dark else "#3366FF",  # Blue - semantic
        "cursor_b": "#F97316" if is_dark else "#FF6B3D",  # Orange - semantic
        "cursor_text": window_text.name(),
        "cursor_line": "#38BDF8" if is_dark else "#3366FF",
        # Accents (semantic colors for data visualization)
        "accent": "#38BDF8" if is_dark else "#3366FF",
        "accent_fill": "#0EA5E9" if is_dark else "#2563EB",
        "accent_fill_secondary": "#F97316" if is_dark else "#FF6B3D",
        "event_line": mid.name(),
        "event_highlight": highlight.name(),
        "time_cursor": "#F97316" if is_dark else "#FF6B3D",
        # Trace defaults (semantic)
        "trace_color": window_text.name(),
        "trace_color_secondary": "#F97316" if is_dark else "#FF6B3D",
        # Warnings (semantic - keep consistent)
        "warning_bg": "#451A03" if is_dark else "#FEF3C7",
        "warning_border": "#F97316" if is_dark else "#F59E0B",
        "warning_text": "#FDE68A" if is_dark else "#78350F",
        # Snapshot (for matplotlib snapshots)
        "snapshot_bg": "#0F141B" if is_dark else "#F3F4F6",
        # Table-specific
        "table_hover": _derive_hover_color(base, is_dark),
        "table_editable_hover": _derive_hover_color(highlight, is_dark),
        "table_focused_border": "#3B82F6" if is_dark else "#3366FF",
        "table_header_border": _derive_grid_color(base, is_dark),
    }

    # For backwards compatibility, just return the preset directly
    # We no longer derive from OS palette - use complete presets instead
    return DARK_THEME.copy() if is_dark else LIGHT_THEME.copy()


def extract_os_palette() -> dict:
    """
    Deprecated: Returns light theme preset for backwards compatibility.

    We no longer follow OS theme. Use LIGHT_THEME or DARK_THEME directly instead.
    """
    return LIGHT_THEME.copy()


def refresh_theme_from_os() -> None:
    """
    Deprecated: Sets light theme for backwards compatibility.

    We no longer follow OS theme. Use set_theme_mode() instead.
    """
    global CURRENT_THEME
    # Update in place so all imported references stay valid
    CURRENT_THEME.clear()
    CURRENT_THEME.update(LIGHT_THEME)

    # Apply to matplotlib
    apply_matplotlib_style(CURRENT_THEME)


# Extra contrast styling using OS palette
# No longer uses hardcoded colors - adapts to OS theme automatically
DARK_WIDGET_CONTRAST_QSS = """
/* Core input widgets - use OS palette colors */
QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {
    background-color: palette(base);
    border: 1px solid palette(mid);
    border-radius: 3px;
    padding: 2px 4px;
}

/* Focus state: make the active field obvious */
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border: 1px solid palette(highlight);
}

/* Indicator visuals are applied in the theme-aware indicator stylesheet. */

/* Group boxes: use OS palette borders */
QGroupBox {
    border: 1px solid palette(mid);
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

UI_INTERACTION_CONTRACT_QSS = """
/* UI interaction contract: menus, tooltips, disabled, focus */
QMenu {
    background-color: palette(base);
    border: 1px solid palette(mid);
    padding: 4px;
}

QMenu::item {
    padding: 6px 18px 6px 24px;
    color: palette(text);
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: palette(highlight);
    color: palette(highlighted-text);
}

QMenu::item:disabled {
    color: palette(mid);
}

QMenu::separator {
    height: 1px;
    background: palette(mid);
    margin: 6px 6px;
}

QToolTip {
    background-color: palette(tool-tip-base);
    color: palette(tool-tip-text);
    border: 1px solid palette(mid);
    padding: 6px 8px;
    border-radius: 4px;
}

QPushButton:focus,
QToolButton:focus,
QLineEdit:focus,
QComboBox:focus,
QTreeWidget:focus,
QTableWidget:focus {
    outline: none;
    border: 1px solid palette(highlight);
}

QPushButton:disabled,
QToolButton:disabled {
    color: palette(mid);
}
"""


def _build_indicator_qss(theme: dict) -> str:
    """Build theme-aware QSS for checkbox and radio indicators."""
    indicator_size = 16
    base_bg = theme.get("plot_bg", theme.get("table_bg", "#FFFFFF"))
    hover_bg = theme.get("table_hover", theme.get("alternate_bg", base_bg))
    border_color = theme.get("panel_border", theme.get("grid_color", "#D1D5DB"))
    accent_bg = theme.get("accent_fill", theme.get("selection_bg", "#2563EB"))
    accent_border = theme.get("accent", accent_bg)
    disabled_bg = theme.get("grid_color", border_color)
    disabled_border = theme.get("grid_color", border_color)
    text_color = theme.get("text", "#111827")
    disabled_check = theme.get("text_disabled", _pick_contrast_color(disabled_bg))

    check_color = _pick_contrast_color(accent_bg)
    check_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        'viewBox="0 0 16 16">'
        f'<path d="M12.2 4.3L6.7 11.7L3.8 8.8" fill="none" '
        f'stroke="{check_color}" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round"/></svg>'
    )
    check_disabled_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        'viewBox="0 0 16 16">'
        f'<path d="M12.2 4.3L6.7 11.7L3.8 8.8" fill="none" '
        f'stroke="{disabled_check}" stroke-width="2.4" stroke-linecap="round" '
        'stroke-linejoin="round"/></svg>'
    )
    dash_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        'viewBox="0 0 16 16">'
        f'<path d="M4 8H12" fill="none" stroke="{check_color}" '
        'stroke-width="2.6" stroke-linecap="round"/></svg>'
    )
    dash_disabled_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        'viewBox="0 0 16 16">'
        f'<path d="M4 8H12" fill="none" stroke="{disabled_check}" '
        'stroke-width="2.6" stroke-linecap="round"/></svg>'
    )

    check_url = _svg_data_uri(check_svg)
    check_disabled_url = _svg_data_uri(check_disabled_svg)
    dash_url = _svg_data_uri(dash_svg)
    dash_disabled_url = _svg_data_uri(dash_disabled_svg)

    return f"""
QCheckBox,
QRadioButton {{
    spacing: 6px;
    color: {text_color};
}}

QCheckBox::indicator,
QRadioButton::indicator,
QTreeView::indicator,
QTableView::indicator,
QListView::indicator {{
    width: {indicator_size}px;
    height: {indicator_size}px;
    border: 2px solid {border_color};
    background-color: {base_bg};
}}

QCheckBox::indicator {{
    border-radius: 3px;
}}

QRadioButton::indicator {{
    border-radius: {indicator_size // 2}px;
}}

QCheckBox::indicator:hover,
QRadioButton::indicator:hover,
QTreeView::indicator:hover,
QTableView::indicator:hover,
QListView::indicator:hover {{
    border-color: {accent_border};
    background-color: {hover_bg};
}}

QCheckBox::indicator:checked,
QRadioButton::indicator:checked,
QTreeView::indicator:checked,
QTableView::indicator:checked,
QListView::indicator:checked {{
    background-color: {accent_bg};
    border-color: {accent_border};
    image: url("{check_url}");
}}

QCheckBox::indicator:checked:hover,
QRadioButton::indicator:checked:hover,
QTreeView::indicator:checked:hover,
QTableView::indicator:checked:hover,
QListView::indicator:checked:hover {{
    background-color: {accent_bg};
    border-color: {accent_border};
    image: url("{check_url}");
}}

QCheckBox::indicator:indeterminate,
QTreeView::indicator:indeterminate,
QTableView::indicator:indeterminate,
QListView::indicator:indeterminate {{
    background-color: {accent_bg};
    border-color: {accent_border};
    image: url("{dash_url}");
}}

QCheckBox::indicator:disabled,
QRadioButton::indicator:disabled,
QTreeView::indicator:disabled,
QTableView::indicator:disabled,
QListView::indicator:disabled {{
    background-color: {disabled_bg};
    border-color: {disabled_border};
}}

QCheckBox::indicator:checked:disabled,
QRadioButton::indicator:checked:disabled,
QTreeView::indicator:checked:disabled,
QTableView::indicator:checked:disabled,
QListView::indicator:checked:disabled {{
    background-color: {disabled_bg};
    border-color: {disabled_border};
    image: url("{check_disabled_url}");
}}

QCheckBox::indicator:indeterminate:disabled,
QTreeView::indicator:indeterminate:disabled,
QTableView::indicator:indeterminate:disabled,
QListView::indicator:indeterminate:disabled {{
    background-color: {disabled_bg};
    border-color: {disabled_border};
    image: url("{dash_disabled_url}");
}}
"""


LIGHT_THEME = {
    # Surfaces
    "window_bg": "#F3F4F6",
    "plot_bg": "#FFFFFF",
    "toolbar_bg": "#F3F4F6",
    "is_dark": False,
    # Text
    "text": "#111827",
    "text_disabled": "#9CA3AF",
    # Tables
    "table_bg": "#FFFFFF",
    "table_text": "#111827",
    "alternate_bg": "#F3F6FB",
    "selection_bg": "#E6F0FF",
    "panel_bg": "#FFFFFF",
    # Buttons
    "button_bg": "#FFFFFF",
    "button_hover_bg": "#EAF2FF",
    "button_active_bg": "#D7E5FF",
    # Overlays / tooltips
    "hover_label_bg": "rgba(255,255,255,220)",
    "hover_label_border": "#CBD5E1",
    # Lines / grids / cursors
    "grid_color": "#D1D5DB",
    "cursor_a": "#3366FF",
    "cursor_b": "#FF6B3D",
    "cursor_text": "#222222",
    "cursor_line": "#3366FF",
    # Accents
    "accent": "#3366FF",
    "accent_fill": "#2563EB",
    "accent_fill_secondary": "#FF6B3D",
    "event_line": "#9CA3AF",
    "event_highlight": "#1D4ED8",
    "time_cursor": "#FF6B3D",
    # Trace defaults
    "trace_color": "#000000",
    "trace_color_secondary": "#FF6B3D",
    # Warnings
    "warning_bg": "#FEF3C7",
    "warning_border": "#F59E0B",
    "warning_text": "#78350F",
    # Snapshot
    "snapshot_bg": "#F3F4F6",
    # Table-specific
    "table_hover": "#F0F0F0",
    "table_editable_hover": "#E6F0FF",
    "table_focused_border": "#3366FF",
    "table_header_border": "#CBD5E1",
    "panel_border": "#CBD5E1",
    "panel_radius": 6,
}

DARK_THEME = {
    # Surfaces
    "window_bg": "#1E242D",
    "plot_bg": "#10141C",
    "toolbar_bg": "#1E242D",
    "is_dark": True,
    # Text
    "text": "#E5E7EB",
    "text_disabled": "#9CA3AF",
    # Tables
    "table_bg": "#0F141B",
    "table_text": "#E5E7EB",
    "alternate_bg": "#161C25",
    "selection_bg": "#263248",
    "panel_bg": "#0F141B",
    # Buttons
    "button_bg": "#1A212B",
    "button_hover_bg": "#232E3C",
    "button_active_bg": "#2F3F55",
    # Overlays / tooltips
    "hover_label_bg": "rgba(30,36,45,230)",
    "hover_label_border": "#364659",
    # Lines / grids / cursors
    "grid_color": "#2E3A49",
    "cursor_a": "#38BDF8",
    "cursor_b": "#F97316",
    "cursor_text": "#E5E7EB",
    "cursor_line": "#38BDF8",
    # Accents
    "accent": "#38BDF8",
    "accent_fill": "#0EA5E9",
    "accent_fill_secondary": "#F97316",
    "event_line": "#4B5563",
    "event_highlight": "#2563EB",
    "time_cursor": "#F97316",
    # Trace defaults
    "trace_color": "#FFFFFF",
    "trace_color_secondary": "#F97316",
    # Warnings
    "warning_bg": "#451A03",
    "warning_border": "#F59E0B",
    "warning_text": "#FDE68A",
    # Snapshot
    "snapshot_bg": "#0F141B",
    # Table-specific
    "table_hover": "#1F2835",
    "table_editable_hover": "#2F3F55",
    "table_focused_border": "#38BDF8",
    "table_header_border": "#364659",
    "panel_border": "#364659",
    "panel_radius": 6,
}

# Currently applied theme; initialized from light preset to avoid KeyErrors
CURRENT_THEME = dict(LIGHT_THEME)

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
    Apply theme colors to Qt's application palette.

    When forcing light/dark mode (not "system"), this ensures that
    palette() CSS references use the forced theme colors instead of OS defaults.

    Args:
        theme: Theme dictionary with color values
    """
    app = QApplication.instance()
    if app is None:
        return

    # Create a new palette based on theme colors
    palette = QPalette()

    # Parse colors from theme
    def parse_color(color_str: str) -> QColor:
        return QColor(color_str) if color_str else QColor()

    # Window colors (toolbars, status bar, chrome)
    window_bg = parse_color(theme.get("window_bg", "#F3F4F6"))
    window_text = parse_color(theme.get("text", "#111827"))

    # Base colors (content areas - plots, tables, etc.)
    base_bg = parse_color(theme.get("plot_bg", "#FFFFFF"))
    alternate_bg = parse_color(theme.get("alternate_bg", "#F9FAFB"))

    # Button colors
    button_bg = parse_color(theme.get("button_bg", "#E5E7EB"))

    # Highlight colors
    highlight_bg = parse_color(theme.get("selection_bg", "#3B82F6"))
    highlight_text = parse_color(theme.get("highlighted_text", "#FFFFFF"))

    # Mid/border colors
    mid_color = parse_color(theme.get("grid_color", "#D1D5DB"))
    is_dark = bool(theme.get("is_dark", window_bg.lightness() < 128))

    # Tooltip colors for palette(tool-tip-base) / palette(tool-tip-text)
    tooltip_bg = window_bg.lighter(115) if is_dark else window_bg.darker(105)
    tooltip_text = window_text

    # Apply to all color groups (Active, Inactive, Disabled)
    for group in [QPalette.Active, QPalette.Inactive, QPalette.Disabled]:
        # Window (toolbars, status bar - gray chrome)
        palette.setColor(group, QPalette.Window, window_bg)
        palette.setColor(group, QPalette.WindowText, window_text)

        # Base (content areas - white/dark backgrounds)
        palette.setColor(group, QPalette.Base, base_bg)
        palette.setColor(group, QPalette.AlternateBase, alternate_bg)
        palette.setColor(group, QPalette.Text, window_text)

        # Buttons
        palette.setColor(group, QPalette.Button, button_bg)
        palette.setColor(group, QPalette.ButtonText, window_text)

        # Highlight (selections)
        palette.setColor(group, QPalette.Highlight, highlight_bg)
        palette.setColor(group, QPalette.HighlightedText, highlight_text)
        palette.setColor(group, QPalette.ToolTipBase, tooltip_bg)
        palette.setColor(group, QPalette.ToolTipText, tooltip_text)

        # Mid/borders
        palette.setColor(group, QPalette.Mid, mid_color)
        palette.setColor(group, QPalette.Dark, mid_color.darker(120))
        palette.setColor(group, QPalette.Light, window_bg.lighter(150))
        palette.setColor(group, QPalette.Midlight, window_bg.lighter(125))

    # Apply the palette to the application
    app.setPalette(palette)


def apply_qt_stylesheet(theme: dict):
    """
    Return a minimal stylesheet with structural styles only.

    Colors are inherited from OS palette automatically.
    This stylesheet only sets layout properties (padding, borders, border-radius).
    """
    return f"""
QWidget {{
    font-family: {FONTS["family"]};
}}
QPushButton {{
    border-radius: 6px;
    padding: 6px 12px;
}}
QToolButton {{
    border-radius: 6px;
    padding: 6px;
}}
QHeaderView::section {{
    font-weight: bold;
}}
QSlider::groove:horizontal, QSlider::groove:vertical {{
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal, QSlider::handle:vertical {{
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
    Update matplotlib rcParams to match OS theme.

    Uses Base palette role (table_bg) for plot backgrounds,
    WindowText for all text elements, and derived grid colors.
    """
    rcParams.update(
        {
            # All text colors from WindowText
            "axes.labelcolor": theme["text"],
            "xtick.color": theme["text"],
            "ytick.color": theme["text"],
            "text.color": theme["text"],
            # Plot backgrounds from Base (table_bg), not Window
            "figure.facecolor": theme.get("plot_bg", theme["table_bg"]),
            "figure.edgecolor": theme.get("plot_bg", theme["table_bg"]),
            "axes.facecolor": theme.get("plot_bg", theme["table_bg"]),
            # Grid from derived color
            "grid.color": theme["grid_color"],
            # Export backgrounds use window_bg
            "savefig.facecolor": theme["window_bg"],
            "savefig.edgecolor": theme["window_bg"],
        }
    )


# -----------------------------------------------------------------------------
# Convenience functions
# -----------------------------------------------------------------------------


def get_theme_mode() -> str:
    """Return the active theme mode: 'light' or 'dark'."""
    theme = CURRENT_THEME if isinstance(CURRENT_THEME, dict) else {}
    window_bg = None
    if isinstance(theme, dict):
        window_bg = theme.get("window_bg") or theme.get("plot_bg")
    if window_bg:
        color = QColor(window_bg)
        if color.isValid():
            return "dark" if color.lightness() < 128 else "light"

    app = QApplication.instance()
    palette = app.palette() if app else QPalette()
    return "dark" if palette.color(QPalette.Window).lightness() < 128 else "light"


def _apply_theme(theme: dict) -> None:
    """
    Internal helper to apply theme to Qt palette, stylesheet, and matplotlib.

    This function updates Qt's palette to match the theme (important for forced
    light/dark modes), then applies stylesheets and matplotlib settings.
    """
    global CURRENT_THEME
    # Update in place so all imported references stay valid
    CURRENT_THEME.clear()
    CURRENT_THEME.update(theme)

    # Update Qt's palette with theme colors (critical for forced light/dark modes)
    apply_qt_palette(theme)

    # Apply stylesheet and matplotlib
    app = QApplication.instance()
    if app is not None:
        q_app = cast(QApplication, app)
        q_app.setStyleSheet(_build_complete_stylesheet(theme))

    apply_matplotlib_style(theme)


def _append_stylesheet(q_app: QApplication, stylesheet: str) -> None:
    """Append extra QSS to the existing application stylesheet."""

    existing = q_app.styleSheet() or ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    q_app.setStyleSheet(existing + (stylesheet or ""))


def _load_light_stylesheet() -> str:
    """Load the optional light-mode stylesheet if present."""

    candidates: list[Path] = []
    if resource_path is not None:
        with contextlib.suppress(Exception):
            candidates.append(Path(resource_path("style.qss")))

    # Fallbacks: source root and project root
    resolved = Path(__file__).resolve()
    with contextlib.suppress(IndexError):
        candidates.append(resolved.parents[2] / "style.qss")
    with contextlib.suppress(IndexError):
        candidates.append(resolved.parents[3] / "style.qss")

    for path in candidates:
        try:
            if path.exists():
                return path.read_text()
        except Exception:
            continue
    return ""


def _build_complete_stylesheet(theme: dict) -> str:
    """Build the full application stylesheet from all global sources."""
    complete_qss = apply_qt_stylesheet(theme)

    main_stylesheet = _load_light_stylesheet()
    if main_stylesheet:
        complete_qss += "\n" + main_stylesheet

    complete_qss += "\n" + DARK_WIDGET_CONTRAST_QSS
    complete_qss += "\n" + UI_INTERACTION_CONTRACT_QSS
    complete_qss += "\n" + _build_indicator_qss(theme)
    return complete_qss


def set_theme_mode(mode: str, *, persist: bool = True) -> str:
    """
    Apply theme mode: light or dark.

    Args:
        mode: "light" or "dark". Defaults to "light" if invalid.
        persist: Whether to persist the mode to QSettings.

    Returns:
        The mode that was set: "light" or "dark".
    """
    requested = (mode or "light").lower()

    # Map old "system"/"auto" to light for backwards compatibility
    if requested in ("system", "auto"):
        requested = "light"

    if requested not in {"light", "dark"}:
        requested = "light"

    try:
        if persist:
            settings = QSettings("TykockiLab", "VasoAnalyzer")
            settings.setValue("appearance/themeMode", requested)
    except Exception:
        pass

    # Use complete theme presets (no OS palette dependency)
    global CURRENT_THEME
    # Update in place so all imported references stay valid
    CURRENT_THEME.clear()
    CURRENT_THEME.update(DARK_THEME if requested == "dark" else LIGHT_THEME)

    # Update Qt's palette and matplotlib
    apply_qt_palette(CURRENT_THEME)
    apply_matplotlib_style(CURRENT_THEME)

    # Build complete stylesheet with all components
    app = QApplication.instance()
    if app is not None:
        q_app = cast(QApplication, app)

        complete_qss = _build_complete_stylesheet(CURRENT_THEME)

        # Apply complete stylesheet (this forces re-evaluation of palette() refs)
        q_app.setStyleSheet(complete_qss)

    return requested


def apply_theme_from_settings() -> str:
    """
    Apply theme from QSettings.

    QSettings key: appearance/themeMode -> "light", "dark", or "system" (default).

    Returns:
        The mode that was applied: "light", "dark", or "system".
    """
    try:
        settings = QSettings("TykockiLab", "VasoAnalyzer")
        mode = settings.value("appearance/themeMode", "system", type=str)
    except Exception:
        mode = "system"

    try:
        return set_theme_mode(mode, persist=False)
    except Exception:
        # Fallback: refresh from OS directly
        refresh_theme_from_os()
        _apply_theme(CURRENT_THEME)
        return "system"


# -----------------------------------------------------------------------------
# Theme Broadcast + Refresh
# -----------------------------------------------------------------------------


class ThemeManager(QObject):
    """Central theme broadcaster for runtime theme changes."""

    themeChanged = pyqtSignal(str)


_THEME_MANAGER: ThemeManager | None = None


def get_theme_manager() -> ThemeManager:
    """Return the singleton ThemeManager instance."""
    global _THEME_MANAGER
    if _THEME_MANAGER is None:
        _THEME_MANAGER = ThemeManager()
    return _THEME_MANAGER


def _call_apply_theme_hook(widget, mode: str) -> None:
    apply_hook = getattr(widget, "apply_theme", None)
    if not callable(apply_hook):
        return

    try:
        signature = inspect.signature(apply_hook)
    except (TypeError, ValueError):
        try:
            apply_hook(mode)
        except Exception:
            with contextlib.suppress(Exception):
                apply_hook()
        return

    params = list(signature.parameters.values())
    try:
        if not params:
            apply_hook()
            return

        first = params[0]
        if first.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            apply_hook(mode)
        elif first.kind == inspect.Parameter.KEYWORD_ONLY:
            if "mode" in signature.parameters:
                apply_hook(mode=mode)
            else:
                apply_hook()
        else:
            apply_hook()
    except Exception:
        log.exception("Theme apply hook failed for %r", widget)


def _refresh_top_level_widgets(mode: str) -> int:
    app = QApplication.instance()
    if app is None:
        return 0

    widgets = app.topLevelWidgets()
    log.info(
        "Theme changed: %s - refreshing %d top-level widgets",
        mode,
        len(widgets),
    )

    for widget in widgets:
        with contextlib.suppress(Exception):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        _call_apply_theme_hook(widget, mode)

    with contextlib.suppress(Exception):
        app.processEvents()
    return len(widgets)


def apply_theme(mode: str, *, persist: bool = True) -> str:
    """Apply theme mode and refresh all visible widgets."""
    scheme = set_theme_mode(mode, persist=persist)

    _refresh_top_level_widgets(scheme)

    manager = get_theme_manager()
    with contextlib.suppress(Exception):
        manager.themeChanged.emit(scheme)

    return scheme
