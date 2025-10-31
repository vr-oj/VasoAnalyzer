from __future__ import annotations

from collections.abc import Iterable

from .cluster import Cluster

__all__ = ["format_cluster_label", "total_count"]


def format_cluster_label(cluster: Cluster) -> str:
    """Return a compact label for a cluster (e.g. "3" or "3+2")."""

    visible = len(cluster.times)
    return f"{visible}+{cluster.hidden}" if cluster.hidden else f"{visible}"


def total_count(clusters: Iterable[Cluster]) -> int:
    """Return total visible + hidden events across clusters."""

    total = 0
    for cluster in clusters:
        total += len(cluster.times) + cluster.hidden
    return total
