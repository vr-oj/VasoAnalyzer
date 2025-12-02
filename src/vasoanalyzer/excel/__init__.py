# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Excel integration for VasoAnalyzer."""

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
]
