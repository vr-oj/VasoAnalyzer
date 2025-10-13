from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
    outer_mean: Optional[np.ndarray]
    outer_min: Optional[np.ndarray]
    outer_max: Optional[np.ndarray]

    def window(self, x0: float, x1: float, margin: int = 1) -> TraceWindow:
        """Return a slice of this level covering ``[x0, x1]``."""

        lo = max(np.searchsorted(self.time_centers, x0, side="left") - margin, 0)
        hi = min(np.searchsorted(self.time_centers, x1, side="right") + margin, len(self.time_centers))
        return TraceWindow(
            time=self.time_centers[lo:hi],
            inner_mean=self.inner_mean[lo:hi],
            inner_min=self.inner_min[lo:hi],
            inner_max=self.inner_max[lo:hi],
            outer_mean=None if self.outer_mean is None else self.outer_mean[lo:hi],
            outer_min=None if self.outer_min is None else self.outer_min[lo:hi],
            outer_max=None if self.outer_max is None else self.outer_max[lo:hi],
        )

    def count_in_range(self, x0: float, x1: float) -> int:
        lo = np.searchsorted(self.time_centers, x0, side="left")
        hi = np.searchsorted(self.time_centers, x1, side="right")
        return max(hi - lo, 1)
