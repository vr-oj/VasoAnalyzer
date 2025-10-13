from __future__ import annotations

import os
from pathlib import Path

import pytest

from vasoanalyzer.app.flags import is_enabled, reload as reload_flags

from tests.plots.test_golden import (
    GOLDEN_DIR,
    _render_zoom_event_labels,
    _fig_to_array,
    _load_golden,
    _assert_images_close,
)

GOLDEN_NAME = "event_labels_v2.png"


def _golden_path() -> Path:
    path = GOLDEN_DIR / GOLDEN_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.skipif(not is_enabled("event_labels_v2", default=True), reason="event_labels_v2 disabled")
def test_event_labels_v2_golden(monkeypatch):
    reload_flags()
    if not is_enabled("event_labels_v2", default=True):
        pytest.skip("event_labels_v2 disabled")

    fig = _render_zoom_event_labels()

    update = os.environ.get("UPDATE_GOLDENS")
    if update:
        fig.savefig(_golden_path(), format="png", dpi=200, bbox_inches="tight")

    actual = _fig_to_array(fig)
    expected = _load_golden(GOLDEN_NAME)
    max_diff, mean_diff = _assert_images_close(actual, expected)
    assert max_diff <= 4, f"{GOLDEN_NAME}: max diff {max_diff}, mean diff {mean_diff:.2f}"
