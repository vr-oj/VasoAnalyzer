from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["Cluster", "cluster_events"]


@dataclass(frozen=True)
class Cluster:
    """One visual cluster of events occupying roughly the same x pixels."""

    x_px: float
    times: tuple[float, ...]
    hidden: int


def cluster_events(
    times: Sequence[float],
    xlim: tuple[float, float],
    ax_width_px: int,
    *,
    min_gap_px: int = 12,
    max_visible_per_cluster: int = 3,
) -> list[Cluster]:
    """Group events by pixel proximity along the x axis."""

    if not times or ax_width_px <= 1:
        return []

    xmin, xmax = xlim
    if not (xmax > xmin):
        return []

    filtered: list[float] = []
    for value in times:
        if value is None:
            continue
        try:
            t = float(value)
        except Exception:
            continue
        if not math.isfinite(t):
            continue
        if xmin <= t <= xmax:
            filtered.append(t)

    if not filtered:
        return []

    times = filtered
    span = xmax - xmin
    scale = float(ax_width_px) / span

    xs = [(t - xmin) * scale for t in times]
    order = sorted(range(len(times)), key=lambda i: xs[i])

    min_gap_px = max(int(min_gap_px), 1)

    groups: list[list[int]] = []
    current: list[int] = []
    for idx in order:
        if current and xs[idx] - xs[current[-1]] > min_gap_px:
            groups.append(current)
            current = [idx]
        else:
            current.append(idx)
    if current:
        groups.append(current)

    clusters: list[Cluster] = []
    for group in groups:
        visible_idx = group[:max_visible_per_cluster]
        hidden = max(0, len(group) - len(visible_idx))
        xmid = 0.5 * (xs[group[0]] + xs[group[-1]])
        clusters.append(
            Cluster(
                x_px=xmid,
                times=tuple(times[i] for i in visible_idx),
                hidden=hidden,
            )
        )
    return clusters
