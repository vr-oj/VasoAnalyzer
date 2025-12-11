#!/usr/bin/env python3
"""Test script to run the Single Figure Studio composer with DEBUG logging enabled."""

import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from PyQt5.QtWidgets import QApplication
import numpy as np

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.mpl_composer import PureMplFigureComposer

# Enable DEBUG logging for the composer
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set composer module to DEBUG to see memory verification logs
logging.getLogger("vasoanalyzer.ui.mpl_composer.composer_window").setLevel(logging.DEBUG)

def create_test_trace_model():
    """Create a test trace model with sample data."""
    time = np.linspace(0, 10, 200)
    inner = 50 + 5 * np.sin(2 * np.pi * 0.2 * time)
    outer = 60 + 5 * np.cos(2 * np.pi * 0.1 * time)
    avg_pressure = 80 + 10 * np.sin(2 * np.pi * 0.05 * time)
    set_pressure = 90 + 0 * time

    return TraceModel(
        time=time,
        inner=inner,
        outer=outer,
        avg_pressure=avg_pressure,
        set_pressure=set_pressure,
    )

def main():
    print("\n" + "="*80)
    print("Single Figure Studio - DEBUG Test")
    print("="*80)
    print("\nExpected behavior:")
    print("  ✓ Window opens at 1400x900 size")
    print("  ✓ Preview shows clean, properly scaled figure")
    print("  ✓ Zoom slider at appropriate initial level")
    print("  ✓ Event labels hidden by default")
    print("  ✓ Debug logs show '0→1' axes count on refresh")
    print("\nActions to test:")
    print("  1. Verify window size on open")
    print("  2. Zoom in/out - should be smooth with no flicker")
    print("  3. Type in event label - should update on Enter/Tab only")
    print("  4. Hold dimension spin box arrow - should be smooth")
    print("  5. Enter invalid color 'xyz' - should show red border")
    print("  6. Watch console for debug logs showing axes count")
    print("="*80 + "\n")

    app = QApplication(sys.argv)

    # Create test data
    trace_model = create_test_trace_model()

    # Create sample events
    event_times = [2.0, 5.0, 8.0]
    event_labels = ["Start", "Middle", "End"]
    event_colors = ["#ff0000", "#00ff00", "#0000ff"]

    # Create composer window
    window = PureMplFigureComposer(
        trace_model=trace_model,
        event_times=event_times,
        event_labels=event_labels,
        event_colors=event_colors,
    )

    window.show()

    print(f"Window size on open: {window.width()}x{window.height()}")
    print(f"Preview initialized: {window._preview_initialized}")
    print(f"Initial zoom level: {window._preview_zoom:.2f}")
    print(f"\nWatching for debug logs...\n")

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
