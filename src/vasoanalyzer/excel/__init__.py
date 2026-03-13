# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Excel integration for VasoAnalyzer."""

from .flexible_writer import (
    FlexibleWritePlan,
    apply_flexible_write_plan,
    build_flexible_write_plan,
)
from .label_matching import best_match, normalize_label
from .template_metadata import (
    DateColumnMetadata,
    EventRowMetadata,
    TemplateMetadata,
    has_vaso_metadata,
    read_template_metadata,
)

__all__ = [
    "TemplateMetadata",
    "EventRowMetadata",
    "DateColumnMetadata",
    "read_template_metadata",
    "has_vaso_metadata",
    "FlexibleWritePlan",
    "build_flexible_write_plan",
    "apply_flexible_write_plan",
    "normalize_label",
    "best_match",
]
