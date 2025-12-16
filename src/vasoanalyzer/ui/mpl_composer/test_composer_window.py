"""Test script for the Pure Matplotlib Figure Composer window.

This script launches the composer window with dummy data to test the UI.

Usage:
    python -m vasoanalyzer.ui.mpl_composer.test_composer_window
"""

from __future__ import annotations

import logging
import sys

import numpy as np
from PyQt5.QtWidgets import QApplication

from vasoanalyzer.core.trace_model import TraceModel

from .composer_window import PureMplFigureComposer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def create_dummy_trace_model() -> TraceModel:
    """Create a dummy TraceModel for testing."""
    # Generate synthetic vessel data
    time = np.linspace(0, 60, 600)  # 60 seconds, 10 Hz
    inner = 100 + 10 * np.sin(2 * np.pi * 0.1 * time) + np.random.normal(0, 1, len(time))
    outer = 120 + 10 * np.sin(2 * np.pi * 0.1 * time) + np.random.normal(0, 1, len(time))
    avg_pressure = 80 + 20 * np.sin(2 * np.pi * 0.05 * time) + np.random.normal(0, 2, len(time))
    set_pressure = 100 + 0 * time  # Constant set pressure

    return TraceModel(
        time=time,
        inner=inner,
        outer=outer,
        avg_pressure=avg_pressure,
        set_pressure=set_pressure,
    )


def main():
    """Launch the composer window for testing."""
    log.info("Launching Pure Matplotlib Figure Composer test window...")

    # Create Qt application
    app = QApplication(sys.argv)

    # Create dummy data
    trace_model = create_dummy_trace_model()
    event_times = [10.0, 30.0, 50.0]
    event_labels = ["Start", "Peak", "End"]
    event_colors = ["#00aa00", "#ff0000", "#0000ff"]

    # Create and show composer window
    composer = PureMplFigureComposer(
        trace_model=trace_model,
        event_times=event_times,
        event_labels=event_labels,
        event_colors=event_colors,
    )
    composer.show()

    log.info("Composer window launched. Close the window to exit.")

    # Run event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
