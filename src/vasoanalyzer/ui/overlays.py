"""Compatibility forwarders for plot overlays."""

from __future__ import annotations

import warnings

from vasoanalyzer.ui.plots.overlays import (
    AnnotationLane,
    AnnotationSpec,
    EventHighlightOverlay,
    TimeCursorOverlay,
)

__all__ = [
    "AnnotationSpec",
    "AnnotationLane",
    "TimeCursorOverlay",
    "EventHighlightOverlay",
]

warnings.warn(
    "Importing from vasoanalyzer.ui.overlays is deprecated; use vasoanalyzer.ui.plots.overlays",
    DeprecationWarning,
    stacklevel=2,
)
