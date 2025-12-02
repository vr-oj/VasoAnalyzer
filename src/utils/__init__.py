# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Utility helpers for the VasoAnalyzer package."""

import os
import sys


def resource_path(*parts: str) -> str:
    """Return absolute path to a bundled resource.

    When running from a PyInstaller bundle, data files are extracted to a
    temporary directory available via ``sys._MEIPASS``. During normal
    development, resources live in the project root. This helper constructs a
    path that works in both cases.
    """

    base = getattr(
        sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    )
    return os.path.join(base, *parts)
