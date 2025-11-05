from __future__ import annotations

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.text import Text

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, EventLabelerV3, LayoutOptionsV3


def _make_entries(times: list[float], texts: list[str], *, meta=None) -> list[EventEntryV3]:
    meta = meta or [{} for _ in texts]
    entries: list[EventEntryV3] = []
    for t, label, payload in zip(times, texts, meta, strict=False):
        payload_dict = dict(payload or {})
        priority = int(payload_dict.get("priority", 0) or 0)
        category = payload_dict.get("category")
        pinned = bool(payload_dict.get("pinned", False))
        entries.append(
            EventEntryV3(
                t=float(t),
                text=label,
                meta=payload_dict,
                priority=priority,
                category=category if isinstance(category, str) else None,
                pinned=pinned,
            )
        )
    return entries


def test_event_labels_v3_pixel_clustering_merges_close_events():
    fig, ax = plt.subplots(figsize=(3, 2), dpi=100)
    ax.set_xlim(99.9, 100.4)
    ax.set_ylim(0, 1)
    times = [100.0, 100.01, 100.03, 100.25]
    entries = _make_entries(times, ["A", "B", "C", "D"])
    opts = LayoutOptionsV3(mode="vertical", min_px=40, max_labels_per_cluster=2)
    helper = EventLabelerV3(ax, [ax], opts)
    renderer = fig.canvas.get_renderer()
    clusters = helper._cluster(entries, ax, fig.dpi, renderer)
    assert len(clusters) == 2
    assert any(len(cluster.items) == 3 for cluster in clusters)

    opts_split = LayoutOptionsV3(mode="vertical", min_px=1)
    helper_split = EventLabelerV3(ax, [ax], opts_split)
    clusters_split = helper_split._cluster(entries, ax, fig.dpi, renderer)
    assert len(clusters_split) == len(entries)
    plt.close(fig)


def test_event_labels_v3_clustering_is_deterministic():
    fig, ax = plt.subplots(figsize=(3, 2), dpi=100)
    ax.set_xlim(0, 10)
    entries = _make_entries(
        [1.0, 1.05, 1.1, 2.0],
        ["L1", "L2", "L3", "L4"],
    )
    shuffled = list(entries)
    rng = np.random.default_rng(seed=42)
    rng.shuffle(shuffled)
    opts = LayoutOptionsV3(mode="vertical", min_px=30, max_labels_per_cluster=2)
    helper = EventLabelerV3(ax, [ax], opts)
    renderer = fig.canvas.get_renderer()
    clusters_a = helper._cluster(entries, ax, fig.dpi, renderer)
    clusters_b = helper._cluster(shuffled, ax, fig.dpi, renderer)
    summary_a = [(round(c.x, 8), c.text) for c in clusters_a]
    summary_b = [(round(c.x, 8), c.text) for c in clusters_b]
    assert summary_a == summary_b
    plt.close(fig)


def test_event_labels_v3_style_policy_selection():
    fig, ax = plt.subplots(figsize=(3, 2), dpi=100)
    ax.set_xlim(0, 5)
    meta = [
        {"color": (1.0, 0.0, 0.0, 1.0), "fontweight": "bold"},
        {"color": (0.0, 1.0, 0.0, 1.0), "fontweight": "bold"},
        {"color": (0.0, 1.0, 0.0, 1.0), "fontweight": "bold"},
    ]
    entries = _make_entries([1.0, 1.02, 1.04], ["a", "b", "c"], meta=meta)
    opts_common = LayoutOptionsV3(style_policy="most_common")
    helper_common = EventLabelerV3(ax, [ax], opts_common)
    text_common, style_common = helper_common._compose_cluster_label(entries, fig.dpi, None)
    assert style_common.get("color") == (0.0, 1.0, 0.0, 1.0)
    assert text_common.startswith("a")

    priority_meta = [
        {"priority": 1, "color": (1, 0, 0, 1)},
        {"priority": 5, "color": (0, 0, 1, 1)},
    ]
    pr_entries = _make_entries([2.0, 2.02], ["p1", "p2"], meta=priority_meta)
    opts_priority = LayoutOptionsV3(style_policy="priority")
    helper_priority = EventLabelerV3(ax, [ax], opts_priority)
    _, style_priority = helper_priority._compose_cluster_label(pr_entries, fig.dpi, None)
    assert style_priority.get("color") == (0, 0, 1, 1)
    plt.close(fig)


def test_event_labels_v3_horizontal_laneing_separates_overlaps():
    fig, ax = plt.subplots(figsize=(3, 2), dpi=100)
    ax.set_xlim(0, 3)
    entries = _make_entries(
        [1.0, 1.05],
        ["Wide Label Example", "S"],
        meta=[{"pinned": True}, {"pinned": True}],
    )
    opts = LayoutOptionsV3(mode="h_inside", lanes=2, min_px=1)
    helper = EventLabelerV3(ax, [ax], opts)
    fig.canvas.draw()
    helper.draw(entries)
    texts = [artist for artist in helper._artists if hasattr(artist, "get_position")]
    assert len(texts) == 2
    y_coords = {round(text.get_position()[1], 3) for text in texts}
    assert len(y_coords) == 2
    helper.clear()
    plt.close(fig)


def test_event_labels_v3_draw_avoids_canvas_draw_calls():
    fig, ax = plt.subplots(figsize=(3, 2), dpi=120)
    ax.set_xlim(0, 2)
    entries = _make_entries([0.5, 1.5], ["Alpha", "Beta"])
    opts = LayoutOptionsV3(mode="vertical", min_px=15)
    helper = EventLabelerV3(ax, [ax], opts)
    fig.canvas.draw()  # ensure renderer ready before patching
    original_draw = fig.canvas.draw

    def _boom(*args, **kwargs):
        raise AssertionError("canvas.draw should not be called by EventLabelerV3.draw")

    fig.canvas.draw = _boom
    try:
        helper.draw(entries)
    finally:
        fig.canvas.draw = original_draw
        helper.clear()
        plt.close(fig)


def test_event_labels_v3_outline_path_effect():
    fig, ax = plt.subplots(figsize=(2, 2), dpi=100)
    ax.set_xlim(0, 1)
    entries = _make_entries([0.5], ["Outlined"])
    opts = LayoutOptionsV3(
        mode="vertical",
        outline_enabled=True,
        outline_width=2.0,
        outline_color=(1.0, 1.0, 1.0, 1.0),
    )
    helper = EventLabelerV3(ax, [ax], opts)
    fig.canvas.draw()
    helper.draw(entries)
    outlines = [artist for artist in helper._artists if isinstance(artist, Text)]
    assert outlines, "Expected at least one text artist"
    assert outlines[0].get_path_effects(), "Outline path effect not applied"
    helper.clear()
    plt.close(fig)


def test_event_labels_v3_weighted_selection_respects_pinned():
    fig, ax = plt.subplots(figsize=(3, 2), dpi=100)
    ax.set_xlim(0, 3)
    entries = _make_entries(
        [1.0, 1.02, 1.2],
        ["Pinned", "A", "B"],
        meta=[{"pinned": True}, {}, {}],
    )
    opts = LayoutOptionsV3(mode="h_inside", lanes=1, min_px=40, max_labels_per_cluster=1)
    helper = EventLabelerV3(ax, [ax], opts)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    clusters = helper._cluster(entries, ax, fig.dpi, renderer)
    selected = helper._select_clusters_for_horizontal(clusters, fig.dpi, renderer)
    assert any(cluster.pinned for cluster in selected)
    helper.clear()
    plt.close(fig)


def test_event_labels_v3_compact_counts_text():
    fig, ax = plt.subplots(figsize=(2, 2), dpi=100)
    members = _make_entries([0.0, 0.1, 0.2], ["E1", "E2", "E3"])
    opts = LayoutOptionsV3(compact_counts=True, max_labels_per_cluster=0)
    helper = EventLabelerV3(ax, [ax], opts)
    text, _ = helper._compose_cluster_label(members, fig.dpi, None)
    assert text == "3"
    pinned_members = _make_entries(
        [0.0, 0.1, 0.2],
        ["Pinned", "Other", "Extra"],
        meta=[{"pinned": True}, {}, {}],
    )
    text_pinned, _ = helper._compose_cluster_label(pinned_members, fig.dpi, None)
    assert text_pinned.startswith("Pinned")
    helper.clear()
    plt.close(fig)


def test_event_labels_v3_horizontal_inside_stays_within_axes():
    fig, ax = plt.subplots(figsize=(4, 2), dpi=100)
    ax.set_xlim(0, 10)
    entries = _make_entries(
        [2.0, 5.0],
        ["Stimulus", "Washout"],
    )
    opts = LayoutOptionsV3(mode="h_inside", lanes=2)
    helper = EventLabelerV3(ax, [ax], opts)
    fig.canvas.draw()
    helper.draw(entries)
    renderer = fig.canvas.get_renderer()
    axis_bbox = ax.get_window_extent(renderer=renderer)

    texts, mapping = helper.annotation_text_objects()
    assert texts, "Expected horizontal labels to be drawn"
    for text in texts:
        cluster = mapping[text]
        x_anchor, _ = text.get_position()
        # Allow small tolerance for floating conversion.
        assert x_anchor >= cluster.x - 1e-6
        bbox = text.get_window_extent(renderer=renderer)
        assert bbox.x0 >= axis_bbox.x0 - 0.5
        assert bbox.x1 <= axis_bbox.x1 + 0.5
        assert text.get_ha() == "left"
    helper.clear()
    plt.close(fig)


def test_event_labels_v3_horizontal_belt_respects_bounds():
    fig, ax = plt.subplots(figsize=(4, 2), dpi=100)
    ax.set_xlim(0, 10)
    entries = _make_entries(
        [1.5, 7.5],
        ["Dose", "Recovery"],
    )
    opts = LayoutOptionsV3(mode="h_belt", lanes=2)
    helper = EventLabelerV3(ax, [ax], opts)
    fig.canvas.draw()
    helper.draw(entries)
    renderer = fig.canvas.get_renderer()

    texts, mapping = helper.annotation_text_objects()
    assert texts, "Expected belt labels to be drawn"
    for text in texts:
        cluster = mapping[text]
        x_anchor, _ = text.get_position()
        assert x_anchor >= cluster.x - 1e-6
        axis_bbox = text.axes.get_window_extent(renderer=renderer)
        bbox = text.get_window_extent(renderer=renderer)
        assert bbox.x0 >= axis_bbox.x0 - 0.5
        assert bbox.x1 <= axis_bbox.x1 + 0.5
        assert text.get_ha() == "left"
    helper.clear()
    plt.close(fig)


def test_annotation_text_objects_mapping_contains_clusters():
    fig, ax = plt.subplots(figsize=(2, 2), dpi=100)
    entries = _make_entries([0.5], ["Single"])
    helper = EventLabelerV3(ax, [ax], LayoutOptionsV3(mode="vertical"))
    fig.canvas.draw()
    helper.draw(entries)
    texts, mapping = helper.annotation_text_objects()
    assert len(texts) == 1
    assert mapping[texts[0]].items[0].text == "Single"
    helper.clear()
    plt.close(fig)


def test_draw_compact_legend_creates_artists():
    fig, ax = plt.subplots(figsize=(2, 2), dpi=100)
    helper = EventLabelerV3(ax, [ax], LayoutOptionsV3(mode="vertical"))
    categories = {"Cat": (2, (1.0, 0.0, 0.0, 1.0))}
    helper.draw_compact_legend(ax, categories)
    assert helper._legend_artists, "Legend artists were not created"
    helper.draw_compact_legend(ax, {})
    assert not helper._legend_artists, "Legend artists should be cleared"
    plt.close(fig)
