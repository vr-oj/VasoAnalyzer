# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import contextlib
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

from matplotlib import rcParams
from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

try:  # Optional helper used for locating packaged resources
    from utils import resource_path
except Exception:  # pragma: no cover - resource helper missing or not packaged
    resource_path = None

# -----------------------------------------------------------------------------
# Color Derivation Helpers
# -----------------------------------------------------------------------------


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
        "snapshot_bg": "#1F2933" if is_dark else "#2B2B2B",

        # Table-specific
        "table_hover": _derive_hover_color(base, is_dark),
        "table_editable_hover": _derive_hover_color(highlight, is_dark),
        "table_focused_border": "#3B82F6" if is_dark else "#3366FF",
        "table_header_border": _derive_grid_color(base, is_dark),
    }

    return theme


def extract_os_palette() -> dict:
    """
    Extract colors from OS-native QPalette and build theme dictionary.

    Returns:
        Theme dict with colors derived from OS system palette (auto-detect light/dark).
    """
    return _build_theme_from_palette(force_dark=None)


def refresh_theme_from_os() -> None:
    """
    Refresh CURRENT_THEME from OS palette and apply to Qt + matplotlib.

    This should be called when:
    - Application starts
    - OS theme changes (via PaletteChange event)
    - User requests theme refresh
    """
    global CURRENT_THEME
    CURRENT_THEME = extract_os_palette()

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

/* Checkboxes and radio buttons: clearer indicators */
QCheckBox::indicator,
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border-radius: 2px;
    border: 1px solid palette(mid);
    background-color: palette(base);
}

QCheckBox::indicator:checked,
QRadioButton::indicator:checked {
    background-color: palette(highlight);
    border-color: palette(highlight);
}

/* Hover state for indicators */
QCheckBox::indicator:hover,
QRadioButton::indicator:hover {
    border-color: palette(dark);
}

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

# Currently applied theme; initialized from OS palette
# Starts with comprehensive fallback values, will be replaced by refresh_theme_from_os()
# This prevents KeyErrors if CURRENT_THEME is accessed before refresh_theme_from_os() is called
CURRENT_THEME = {
    # Surfaces
    "window_bg": "#FFFFFF",
    "plot_bg": "#FFFFFF",
    "toolbar_bg": "#F0F0F0",
    # Text
    "text": "#000000",
    "text_disabled": "#888888",
    # Tables
    "table_bg": "#FFFFFF",
    "table_text": "#000000",
    "alternate_bg": "#F5F5F5",
    "selection_bg": "#E6F0FF",
    # Buttons
    "button_bg": "#FFFFFF",
    "button_hover_bg": "#E6F0FF",
    "button_active_bg": "#CCE0FF",
    # Overlays / tooltips
    "hover_label_bg": "rgba(255,255,255,220)",
    "hover_label_border": "#888888",
    # Lines / grids / cursors
    "grid_color": "#CCCCCC",
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
    "snapshot_bg": "#2B2B2B",
    # Table-specific
    "table_hover": "#F0F0F0",
    "table_editable_hover": "#E6F0FF",
    "table_focused_border": "#3366FF",
    "table_header_border": "#CCCCCC",
}

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
    No-op function kept for compatibility.

    The OS palette is already applied by Qt automatically.
    This function exists to maintain backward compatibility with code
    that calls apply_qt_palette(), but it no longer modifies the palette.
    """
    # OS native palette is already applied by Qt
    # No need to override it
    pass


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
QToolTip {{
    padding: 2px 6px;
    border-radius: 5px;
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


def _apply_theme(theme: dict) -> None:
    """
    Internal helper to apply theme to Qt stylesheet + matplotlib.

    Note: QPalette is not modified here as it comes from OS.
    This function only applies stylesheets and matplotlib settings.
    """
    global CURRENT_THEME
    CURRENT_THEME = theme

    # No need to call apply_qt_palette - OS palette is already set
    # Just apply stylesheet and matplotlib
    app = QApplication.instance()
    if app is not None:
        cast(QApplication, app).setStyleSheet(apply_qt_stylesheet(theme))

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


def set_theme_mode(mode: str, *, persist: bool = True) -> str:
    """
    Apply theme mode: light, dark, or system.

    Args:
        mode: "light" (force light), "dark" (force dark), or "system" (follow OS).
        persist: Whether to persist the mode to QSettings.

    Returns:
        The mode that was set: "light", "dark", or "system".
    """
    requested = (mode or "system").lower()
    if requested == "auto":
        requested = "system"

    if requested not in {"light", "dark", "system"}:
        requested = "system"

    try:
        if persist:
            settings = QSettings("TykockiLab", "VasoAnalyzer")
            settings.setValue("appearance/themeMode", requested)
    except Exception:
        pass

    # Refresh theme from OS palette or override
    if requested == "system":
        refresh_theme_from_os()
    else:
        # Force light or dark by overriding is_dark in palette extraction
        global CURRENT_THEME
        CURRENT_THEME = extract_os_palette()
        # Override the is_dark detection
        is_dark = requested == "dark"
        # Re-derive colors with forced mode
        CURRENT_THEME = _build_theme_from_palette(force_dark=is_dark if requested != "system" else None)
        apply_matplotlib_style(CURRENT_THEME)

    # Apply stylesheet and matplotlib
    _apply_theme(CURRENT_THEME)

    # Load optional stylesheets (all use palette() refs, work for both light/dark)
    app = QApplication.instance()
    if app is not None:
        q_app = cast(QApplication, app)

        # Load main stylesheet
        stylesheet = _load_light_stylesheet()
        if stylesheet:
            _append_stylesheet(q_app, stylesheet)

        # Always apply widget contrast styles (now uses palette(), works for both themes)
        existing_qss = q_app.styleSheet() or ""
        if DARK_WIDGET_CONTRAST_QSS not in existing_qss:
            q_app.setStyleSheet(existing_qss + "\n" + DARK_WIDGET_CONTRAST_QSS)

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
