from vasoanalyzer.core.events.cluster import cluster_events


def test_cluster_ignores_nan_and_outside():
    times = [None, float("nan"), -1.0, 0.1, 0.11, 9.9, 10.1, float("inf"), -float("inf")]
    clusters = cluster_events(times, (0.0, 10.0), ax_width_px=300, min_gap_px=12, max_visible_per_cluster=2)
    # Only 0.1, 0.11, and 9.9 should remain (3 events total)
    assert sum(len(c.times) + c.hidden for c in clusters) == 3


def test_cluster_empty_when_axis_unready():
    assert cluster_events([0.5, 1.5], (0.0, 2.0), ax_width_px=0) == []
    assert cluster_events([0.5, 1.5], (2.0, 2.0), ax_width_px=200) == []
