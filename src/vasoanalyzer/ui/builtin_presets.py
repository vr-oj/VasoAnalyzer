"""Built-in style presets for publication-ready figures."""

from __future__ import annotations

from copy import deepcopy

from vasoanalyzer.ui.constants import FACTORY_STYLE_DEFAULTS, get_factory_style
from utils.style_defaults import flatten_style_defaults

__all__ = ["BUILTIN_PRESETS", "get_builtin_presets"]


def _create_nature_preset() -> dict:
    """
    Nature journal preset.

    Nature figure guidelines:
    - Single column: 89mm (3.5")
    - Double column: 183mm (7.2")
    - Font: Arial or Helvetica, 5-7pt minimum
    - Line width: 0.5-1pt
    - Black/grayscale for lines
    """
    base = deepcopy(get_factory_style())

    # Compact fonts for space efficiency
    base["axis"]["font_family"] = "Arial"
    base["axis"]["font_size"] = 8
    base["axis"]["bold"] = False

    base["ticks"]["font_size"] = 7

    base["events"]["font_family"] = "Arial"
    base["events"]["font_size"] = 7
    base["events"]["bold"] = False

    # Thin lines (Nature prefers subtle)
    base["lines"]["inner_width"] = 0.75
    base["lines"]["outer_width"] = 0.75

    return {
        "name": "Nature",
        "description": "Nature journal style (89mm single column, compact fonts, thin lines)",
        "tags": ["journal", "nature", "single-column"],
        "style": flatten_style_defaults(base),
    }


def _create_cell_preset() -> dict:
    """
    Cell journal preset.

    Cell figure guidelines:
    - Full width: 185mm (7.3")
    - Half width: 89mm (3.5")
    - Font: Arial or Helvetica, 6-8pt minimum
    - High contrast, clear labels
    """
    base = deepcopy(get_factory_style())

    # Clear, readable fonts
    base["axis"]["font_family"] = "Arial"
    base["axis"]["font_size"] = 10
    base["axis"]["bold"] = True

    base["ticks"]["font_size"] = 9

    base["events"]["font_family"] = "Arial"
    base["events"]["font_size"] = 9
    base["events"]["bold"] = True

    # Medium line weights for clarity
    base["lines"]["inner_width"] = 1.5
    base["lines"]["outer_width"] = 1.5

    return {
        "name": "Cell",
        "description": "Cell journal style (high contrast, bold labels, medium lines)",
        "tags": ["journal", "cell"],
        "style": flatten_style_defaults(base),
    }


def _create_jphysiol_preset() -> dict:
    """
    Journal of Physiology preset.

    J Physiol guidelines:
    - Width: 82mm (single) or 173mm (double)
    - Font: Times New Roman or Arial, minimum 8pt after reduction
    - Clear, professional appearance
    """
    base = deepcopy(get_factory_style())

    # Professional serif font
    base["axis"]["font_family"] = "Times New Roman"
    base["axis"]["font_size"] = 11
    base["axis"]["bold"] = False
    base["axis"]["italic"] = True  # Italic for axis labels

    base["ticks"]["font_size"] = 10

    base["events"]["font_family"] = "Arial"
    base["events"]["font_size"] = 10
    base["events"]["bold"] = False

    # Standard line weights
    base["lines"]["inner_width"] = 1.25
    base["lines"]["outer_width"] = 1.25

    return {
        "name": "J Physiol",
        "description": "Journal of Physiology style (serif fonts, italic axis labels)",
        "tags": ["journal", "jphysiol", "physiology"],
        "style": flatten_style_defaults(base),
    }


def _create_presentation_preset() -> dict:
    """
    Presentation preset.

    Optimized for:
    - Projected slides (1920x1080, 16:9)
    - Large auditorium viewing
    - High contrast, bold elements
    """
    base = deepcopy(get_factory_style())

    # Large, bold fonts for visibility
    base["axis"]["font_family"] = "Arial"
    base["axis"]["font_size"] = 28
    base["axis"]["bold"] = True

    base["ticks"]["font_size"] = 24

    base["events"]["font_family"] = "Arial"
    base["events"]["font_size"] = 20
    base["events"]["bold"] = True

    # Thick lines for projection
    base["lines"]["inner_width"] = 3.5
    base["lines"]["outer_width"] = 3.5

    # Increased tick visibility
    base["ticks"]["length"] = 8.0
    base["ticks"]["width"] = 2.0

    return {
        "name": "Presentation",
        "description": "Presentation style (large fonts, thick lines, high visibility)",
        "tags": ["presentation", "slides", "conference"],
        "style": flatten_style_defaults(base),
    }


def _create_minimal_preset() -> dict:
    """
    Minimal/clean preset.

    For:
    - Supplementary figures
    - Internal reports
    - Draft figures
    """
    base = deepcopy(get_factory_style())

    # Clean sans-serif
    base["axis"]["font_family"] = "Helvetica"
    base["axis"]["font_size"] = 12
    base["axis"]["bold"] = False

    base["ticks"]["font_size"] = 10

    base["events"]["font_family"] = "Helvetica"
    base["events"]["font_size"] = 10
    base["events"]["bold"] = False

    # Subtle lines
    base["lines"]["inner_width"] = 1.0
    base["lines"]["outer_width"] = 1.0

    # Disable event label outline for cleaner look
    base["events"]["outline_enabled"] = False

    return {
        "name": "Minimal",
        "description": "Minimal/clean style (subtle styling, no outlines)",
        "tags": ["minimal", "clean", "draft"],
        "style": flatten_style_defaults(base),
    }


def _create_plos_preset() -> dict:
    """
    PLOS ONE preset.

    PLOS ONE guidelines:
    - Width: 83mm (single) or 173mm (double)
    - Font: Arial, Helvetica, or Times, minimum 6pt
    - Sans-serif preferred
    """
    base = deepcopy(get_factory_style())

    base["axis"]["font_family"] = "Arial"
    base["axis"]["font_size"] = 9
    base["axis"]["bold"] = False

    base["ticks"]["font_size"] = 8

    base["events"]["font_family"] = "Arial"
    base["events"]["font_size"] = 8
    base["events"]["bold"] = False

    base["lines"]["inner_width"] = 1.0
    base["lines"]["outer_width"] = 1.0

    return {
        "name": "PLOS ONE",
        "description": "PLOS ONE journal style (sans-serif, moderate sizing)",
        "tags": ["journal", "plos", "open-access"],
        "style": flatten_style_defaults(base),
    }


# Collection of all built-in presets
BUILTIN_PRESETS = [
    _create_nature_preset(),
    _create_cell_preset(),
    _create_jphysiol_preset(),
    _create_presentation_preset(),
    _create_minimal_preset(),
    _create_plos_preset(),
]


def get_builtin_presets() -> list[dict]:
    """
    Get a copy of all built-in presets.

    Returns:
        List of preset dictionaries
    """
    return deepcopy(BUILTIN_PRESETS)


def get_preset_by_name(name: str) -> dict | None:
    """
    Get a specific built-in preset by name.

    Args:
        name: Preset name (case-insensitive)

    Returns:
        Preset dictionary or None if not found
    """
    name_lower = name.lower()
    for preset in BUILTIN_PRESETS:
        if preset["name"].lower() == name_lower:
            return deepcopy(preset)
    return None
