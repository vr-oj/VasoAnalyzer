from __future__ import annotations

from collections.abc import Iterable

from matplotlib.axes import Axes

from vasoanalyzer.core.events.cluster import Cluster
from vasoanalyzer.core.events.summary import format_cluster_label

__all__ = ["draw_event_labels"]


def draw_event_labels(
    ax: Axes,
    clusters: Iterable[Cluster],
    xlim: tuple[float, float],
    *,
    mode: str = "horizontal",
) -> list:
    """Draw minimal labels for clustered events on ``ax`` and return artists."""

    xmin, xmax = xlim
    span = max(xmax - xmin, 1e-12)
    width = ax.bbox.width or 1.0
    scale = width / span  # px per second

    mode = (mode or "horizontal").lower()
    if mode == "horizontal_outside":
        transform = ax.get_xaxis_transform()
        y_pos = 1.02
        valign = "bottom"
        clip = False
    elif mode == "vertical":
        transform = ax.get_xaxis_transform()
        y_pos = 0.98
        valign = "top"
        clip = True
    else:  # horizontal inside
        transform = ax.get_xaxis_transform()
        y_pos = 0.98
        valign = "top"
        clip = True

    artists: list = []
    for cluster in clusters:
        xdata = xmin + (cluster.x_px / scale)
        line = ax.axvline(xdata, linewidth=0.8, alpha=0.35)
        artists.append(line)
        label = format_cluster_label(cluster)
        text = ax.text(
            xdata,
            y_pos,
            label,
            transform=transform,
            ha="center",
            va=valign,
            clip_on=clip,
        )
        artists.append(text)
    return artists
