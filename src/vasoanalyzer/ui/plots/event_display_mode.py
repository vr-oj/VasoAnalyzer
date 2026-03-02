"""Display modes for event labels in PyQtGraph views."""

from __future__ import annotations

from enum import Enum

__all__ = ["EventDisplayMode", "coerce_event_display_mode"]


class EventDisplayMode(str, Enum):
    OFF = "off"
    INDICES = "indices"
    NAMES_ON_HOVER = "names_on_hover"
    NAMES_ALWAYS = "names_always"


def coerce_event_display_mode(value: object) -> EventDisplayMode:
    if isinstance(value, EventDisplayMode):
        return value
    raw = str(value or "").strip().lower()
    aliases = {
        "off": EventDisplayMode.OFF,
        "none": EventDisplayMode.OFF,
        "hide": EventDisplayMode.OFF,
        "hidden": EventDisplayMode.OFF,
        "indices": EventDisplayMode.INDICES,
        "index": EventDisplayMode.INDICES,
        "numbers": EventDisplayMode.INDICES,
        "numbers_only": EventDisplayMode.INDICES,
        "names_on_hover": EventDisplayMode.NAMES_ON_HOVER,
        "hover": EventDisplayMode.NAMES_ON_HOVER,
        "names": EventDisplayMode.NAMES_ALWAYS,
        "names_always": EventDisplayMode.NAMES_ALWAYS,
        "always": EventDisplayMode.NAMES_ALWAYS,
    }
    return aliases.get(raw, EventDisplayMode.INDICES)
