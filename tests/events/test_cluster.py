from vasoanalyzer.core.events.cluster import cluster_events


def test_cluster_basic():
    times = [0.00, 0.006, 0.011, 0.50, 1.20]
    xlim = (0.0, 1.5)
    clusters = cluster_events(
        times,
        xlim,
        ax_width_px=300,
        min_gap_px=12,
        max_visible_per_cluster=2,
    )
    assert len(clusters) == 3
    assert len(clusters[0].times) == 2
    assert clusters[0].hidden == 1
