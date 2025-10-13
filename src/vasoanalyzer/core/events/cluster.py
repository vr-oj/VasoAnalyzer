from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

__all__ = ["Cluster", "cluster_events"]

@dataclass(frozen=True)
class Cluster:
    """One visual cluster of events occupying roughly the same x pixels."""

    x_px: float
    times: Tuple[float, ...]
    hidden: int


def cluster_events(
    times: Sequence[float],
    xlim: Tuple[float, float],
    ax_width_px: int,
    *,
    min_gap_px: int = 12,
    max_visible_per_cluster: int = 3,
) -> List[Cluster]:
    """Group events by pixel proximity along the x axis."""

    if not times:
        return []

    xmin, xmax = xlim
    span = max(xmax - xmin, 1e-12)
    scale = float(ax_width_px) / span

    xs = [(t - xmin) * scale for t in times]
    order = sorted(range(len(times)), key=lambda i: xs[i])

    groups: List[List[int]] = []
    current: List[int] = []
    for idx in order:
        if current and xs[idx] - xs[current[-1]] > min_gap_px:
            groups.append(current)
            current = [idx]
        else:
            current.append(idx)
    if current:
        groups.append(current)

    clusters: List[Cluster] = []
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
