# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import os

from utils.style_defaults import (
    STYLE_DEFAULTS,
    STYLE_SCHEMA_VERSION,
    flatten_style_defaults,
    load_factory_defaults,
    load_flat_factory_defaults,
)

PREVIOUS_PLOT_PATH = os.path.join(os.path.expanduser("~"), ".vasoanalyzer_last_plot.json")

# Flattened snapshot for legacy consumers; use helper functions for copies.
DEFAULT_STYLE = load_flat_factory_defaults()

# Re-export for convenience within the UI package.
FACTORY_STYLE_DEFAULTS = STYLE_DEFAULTS
FACTORY_STYLE_VERSION = STYLE_SCHEMA_VERSION
get_factory_style = load_factory_defaults
get_flat_factory_style = flatten_style_defaults
