"""Theme tokens for the Pure Matplotlib Figure Composer.

This module integrates with the main VasoAnalyzer theme system to ensure
the composer window follows the app's light/dark mode setting.
"""

from vasoanalyzer.ui.theme import CURRENT_THEME


def get_composer_theme() -> dict:
    """
    Generate composer theme from the current app theme.

    Maps the main app's theme tokens to the composer's expected structure.
    This ensures the composer automatically follows light/dark mode changes.

    Returns:
        Dictionary with composer-specific theme tokens.
    """
    return {
        "bg_window": CURRENT_THEME["window_bg"],
        "bg_primary": CURRENT_THEME["window_bg"],
        "bg_secondary": CURRENT_THEME["alternate_bg"],
        "bg_control": CURRENT_THEME["button_bg"],
        "panel_border": CURRENT_THEME["grid_color"],
        "page_bg": CURRENT_THEME["table_bg"],
        "border": CURRENT_THEME["grid_color"],
        "text_primary": CURRENT_THEME["text"],
        "text_secondary": CURRENT_THEME.get("text_disabled", CURRENT_THEME["text"]),
        "accent_blue": CURRENT_THEME.get("accent", "#0d6efd"),
        "accent_green": "#198754",
        "accent_red": "#dc3545",
        "accent_yellow": "#f4c542",
    }


# Dynamic theme that updates with the app's theme
THEME = get_composer_theme()
PAGE_BG_COLOR = THEME["page_bg"]


def refresh_theme():
    """
    Refresh the composer theme from the current app theme.

    Call this when the app's theme changes to update the composer.
    """
    global THEME, PAGE_BG_COLOR
    THEME = get_composer_theme()
    PAGE_BG_COLOR = THEME["page_bg"]
