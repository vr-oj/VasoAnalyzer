# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from importlib import import_module

__all__ = ["VasoAnalyzerApp", "CustomToolbar"]


def __getattr__(name: str):
    if name == "VasoAnalyzerApp":
        module = import_module("vasoanalyzer.ui.main_window")
        value = module.VasoAnalyzerApp
    elif name == "CustomToolbar":
        module = import_module("vasoanalyzer.ui.widgets")
        value = module.CustomToolbar
    else:
        raise AttributeError(f"module 'vasoanalyzer.ui' has no attribute {name!r}")
    globals()[name] = value
    return value
