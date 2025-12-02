# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar


class CustomToolbar(NavigationToolbar):
    """Navigation toolbar that resets using stored full limits."""

    def __init__(self, canvas, parent, reset_callback):
        super().__init__(canvas, parent)
        self._reset_callback = reset_callback

    def home(self):
        self._reset_callback()
