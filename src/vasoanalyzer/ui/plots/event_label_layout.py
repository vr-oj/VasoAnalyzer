"""Collision-aware event label placement in pixel space."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class PlacedLabel:
    """Label placement for one event in the current view."""

    event_id: int
    x_data: float
    lane: int
    visible: bool
    x_px0: float
    x_px1: float


def _overlaps(a0: float, a1: float, b0: float, b1: float, *, gap: float) -> bool:
    return not (a1 + gap <= b0 or b1 + gap <= a0)


def choose_event_label_lod(
    *,
    visible_event_count: int,
    pixel_width: int,
    min_spacing_px: float = 18.0,
) -> str:
    """Return ``labels`` when text can fit, otherwise ``markers_only``."""
    count = max(int(visible_event_count), 0)
    width_px = max(int(pixel_width), 1)
    if count <= 0:
        return "markers_only"
    average_spacing_px = float(width_px) / float(count)
    if average_spacing_px < float(min_spacing_px):
        return "markers_only"
    return "labels"


def layout_labels(
    *,
    events: list[tuple[int, float, str]],
    x_to_px: Callable[[float], float],
    text_width_px: Callable[[str], float],
    max_lanes: int = 3,
    min_gap_px: float = 6.0,
    hide_if_no_space: bool = True,
) -> list[PlacedLabel]:
    """Place labels into non-overlapping lanes from left-to-right.

    Args:
        events: (event_id, x_data, text) payloads.
        x_to_px: data-to-pixel mapper for x coordinates.
        text_width_px: callback returning text width in pixels.
        max_lanes: max number of lanes to use.
        min_gap_px: required gap between neighboring labels.
        hide_if_no_space: hide labels that cannot be placed.
    """

    if max_lanes <= 0:
        return [
            PlacedLabel(
                event_id=int(event_id),
                x_data=float(x_data),
                lane=0,
                visible=False,
                x_px0=float(x_to_px(float(x_data))),
                x_px1=float(x_to_px(float(x_data))),
            )
            for event_id, x_data, _text in events
        ]

    indexed: list[tuple[int, int, float, str, float, float, float]] = []
    for idx, (event_id, x_data, text) in enumerate(events):
        x_data_f = float(x_data)
        x_px = float(x_to_px(x_data_f))
        width = max(0.0, float(text_width_px(str(text))))
        x0 = x_px - (width * 0.5)
        x1 = x_px + (width * 0.5)
        indexed.append((idx, int(event_id), x_data_f, str(text), x_px, x0, x1))

    indexed.sort(key=lambda row: (row[4], row[1], row[0]))

    lanes: list[list[tuple[float, float, int]]] = [[] for _ in range(int(max_lanes))]
    results: dict[int, PlacedLabel] = {}

    for original_idx, event_id, x_data_f, _text, x_px, x0, x1 in indexed:
        lane_idx = -1
        for candidate in range(int(max_lanes)):
            occupied = lanes[candidate]
            if not occupied:
                lane_idx = candidate
                break
            last_x0, last_x1, _last_id = occupied[-1]
            if not _overlaps(last_x0, last_x1, x0, x1, gap=float(min_gap_px)):
                lane_idx = candidate
                break

        visible = True
        if lane_idx < 0:
            if hide_if_no_space:
                lane_idx = int(max_lanes) - 1
                visible = False
            else:
                lane_idx = int(max_lanes) - 1

        if visible:
            lanes[lane_idx].append((x0, x1, event_id))

        results[original_idx] = PlacedLabel(
            event_id=event_id,
            x_data=x_data_f,
            lane=lane_idx,
            visible=visible,
            x_px0=x0,
            x_px1=x1,
        )

    return [results[i] for i in range(len(events))]
