from __future__ import annotations

from vasoanalyzer.ui.plots.event_label_layout import choose_event_label_lod, layout_labels


def test_overlapping_labels_use_different_lanes() -> None:
    placements = layout_labels(
        events=[
            (1, 1.00, "12"),
            (2, 1.02, "34"),
        ],
        x_to_px=lambda x: x * 100.0,
        text_width_px=lambda _text: 20.0,
        max_lanes=3,
        min_gap_px=6.0,
    )

    assert len(placements) == 2
    assert placements[0].visible is True
    assert placements[1].visible is True
    assert placements[0].lane != placements[1].lane


def test_dense_labels_hide_when_lanes_exhausted() -> None:
    placements = layout_labels(
        events=[
            (1, 1.000, "1"),
            (2, 1.005, "2"),
            (3, 1.010, "3"),
        ],
        x_to_px=lambda x: x * 1000.0,
        text_width_px=lambda _text: 14.0,
        max_lanes=2,
        min_gap_px=6.0,
        hide_if_no_space=True,
    )

    visible = [item for item in placements if item.visible]
    hidden = [item for item in placements if not item.visible]

    assert len(visible) == 2
    assert len(hidden) == 1


def test_visible_labels_do_not_overlap_within_each_lane() -> None:
    min_gap = 4.0
    placements = layout_labels(
        events=[
            (1, 0.50, "A"),
            (2, 0.54, "B"),
            (3, 0.58, "C"),
            (4, 0.62, "D"),
            (5, 0.66, "E"),
            (6, 0.70, "F"),
        ],
        x_to_px=lambda x: x * 1000.0,
        text_width_px=lambda _text: 22.0,
        max_lanes=3,
        min_gap_px=min_gap,
        hide_if_no_space=True,
    )

    by_lane: dict[int, list] = {}
    for placement in placements:
        if not placement.visible:
            continue
        by_lane.setdefault(placement.lane, []).append(placement)

    for lane_items in by_lane.values():
        lane_items.sort(key=lambda placement: placement.x_px0)
        for left, right in zip(lane_items, lane_items[1:]):
            assert left.x_px1 + min_gap <= right.x_px0


def test_choose_event_label_lod_prefers_markers_when_dense() -> None:
    assert (
        choose_event_label_lod(
            visible_event_count=80,
            pixel_width=600,
            min_spacing_px=12.0,
        )
        == "markers_only"
    )
    assert (
        choose_event_label_lod(
            visible_event_count=8,
            pixel_width=600,
            min_spacing_px=12.0,
        )
        == "labels"
    )
