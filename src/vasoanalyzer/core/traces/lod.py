from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .window import TraceWindow

__all__ = ["LODLevel"]


@dataclass
class LODLevel:
    """Single level of the level-of-detail pyramid."""

    factor: int
    bucket_size: int
    time_centers: np.ndarray
    inner_mean: np.ndarray
    inner_min: np.ndarray
    inner_max: np.ndarray
    outer_mean: np.ndarray | None
    outer_min: np.ndarray | None
    outer_max: np.ndarray | None
    avg_pressure_mean: np.ndarray | None = None
    avg_pressure_min: np.ndarray | None = None
    avg_pressure_max: np.ndarray | None = None
    set_pressure_mean: np.ndarray | None = None
    set_pressure_min: np.ndarray | None = None
    set_pressure_max: np.ndarray | None = None

    def window(self, x0: float, x1: float, margin: int = 1) -> TraceWindow:
        """Return a slice of this level covering ``[x0, x1]``."""

        lo = max(int(np.searchsorted(self.time_centers, x0, side="left")) - margin, 0)
        hi = min(
            int(np.searchsorted(self.time_centers, x1, side="right")) + margin,
            len(self.time_centers),
        )
        return TraceWindow(
            time=self.time_centers[lo:hi],
            inner_mean=self.inner_mean[lo:hi],
            inner_min=self.inner_min[lo:hi],
            inner_max=self.inner_max[lo:hi],
            outer_mean=None if self.outer_mean is None else self.outer_mean[lo:hi],
            outer_min=None if self.outer_min is None else self.outer_min[lo:hi],
            outer_max=None if self.outer_max is None else self.outer_max[lo:hi],
            avg_pressure_mean=None if self.avg_pressure_mean is None else self.avg_pressure_mean[lo:hi],
            avg_pressure_min=None if self.avg_pressure_min is None else self.avg_pressure_min[lo:hi],
            avg_pressure_max=None if self.avg_pressure_max is None else self.avg_pressure_max[lo:hi],
            set_pressure_mean=None if self.set_pressure_mean is None else self.set_pressure_mean[lo:hi],
            set_pressure_min=None if self.set_pressure_min is None else self.set_pressure_min[lo:hi],
            set_pressure_max=None if self.set_pressure_max is None else self.set_pressure_max[lo:hi],
        )

    def count_in_range(self, x0: float, x1: float) -> int:
        lo = int(np.searchsorted(self.time_centers, x0, side="left"))
        hi = int(np.searchsorted(self.time_centers, x1, side="right"))
        return max(hi - lo, 1)
