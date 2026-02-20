from __future__ import annotations

import time

from vasoanalyzer.ui.plots.pyqtgraph_event_strip import EventLodDebouncer


def test_lod_debouncer_delays_downgrade_and_upgrades_immediately() -> None:
    debouncer = EventLodDebouncer(delay_ms=150)
    assert debouncer.update("labels") == "labels"

    assert debouncer.update("markers_only") == "labels"
    time.sleep(0.06)
    assert debouncer.update("markers_only") == "labels"
    time.sleep(0.11)
    assert debouncer.update("markers_only") == "markers_only"

    assert debouncer.update("labels") == "labels"
