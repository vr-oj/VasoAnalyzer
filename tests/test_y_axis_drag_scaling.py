from __future__ import annotations

import pytest

from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
from vasoanalyzer.ui.plots.pyqtgraph_trace_view import y_axis_scale_factor_for_drag_delta


def test_y_axis_drag_scale_factor_directionality() -> None:
    assert y_axis_scale_factor_for_drag_delta(10.0) > 1.0
    assert y_axis_scale_factor_for_drag_delta(-10.0) < 1.0
    assert y_axis_scale_factor_for_drag_delta(0.0) == pytest.approx(1.0, abs=1e-12)


def test_scale_y_about_disables_continuous_autoscale_and_preserves_center(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    try:
        track.set_ylim(0.0, 100.0)
        track._set_continuous_autoscale(True)
        assert track.view.is_autoscale_enabled() is True

        before_min, before_max = track.get_ylim()
        before_span = before_max - before_min
        track.scale_y_about(50.0, 1.25)
        ymin, ymax = track.get_ylim()
        assert track.view.is_autoscale_enabled() is False
        assert (ymax - ymin) == pytest.approx(before_span * 1.25, rel=1e-6)
        assert ((ymin + ymax) * 0.5) == pytest.approx(50.0, abs=1e-6)

        center_before = (ymin + ymax) * 0.5
        track.scale_y_about(None, 0.8)
        ymin2, ymax2 = track.get_ylim()
        center_after = (ymin2 + ymax2) * 0.5
        assert center_after == pytest.approx(center_before, abs=1e-6)
    finally:
        track.widget.close()
        qt_app.processEvents()
