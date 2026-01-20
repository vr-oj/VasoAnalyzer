# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Snapshot data source adapters for the canonical viewer."""

from __future__ import annotations

import math
from typing import Any, Protocol, Sequence, runtime_checkable

import numpy as np


@runtime_checkable
class SnapshotDataSource(Protocol):
    """Interface for retrieving frames from a snapshot stack."""

    def index_for_time(self, t_seconds: float) -> int | None:
        ...

    def get_frame_at_time(self, t_seconds: float):
        ...

    def get_frame_at_index(self, index: int):
        ...


class SnapshotStackDataSource:
    """Adapter for in-memory snapshot stacks with optional frame times."""

    def __init__(
        self,
        frames: Sequence[Any],
        frame_times: Sequence[float] | None = None,
    ) -> None:
        self._frames = list(frames)
        self._frame_times = (
            np.asarray(frame_times, dtype=float) if frame_times is not None else None
        )
        self._source_kind = "in-memory"

    def get_frame_at_time(self, t_seconds: float):
        idx = self.index_for_time(t_seconds)
        if idx is None:
            return None
        return self.get_frame_at_index(idx)

    def get_frame_at_index(self, index: int):
        if not self._frames:
            return None
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return None
        if idx < 0 or idx >= len(self._frames):
            return None
        return self._frames[idx]

    def index_for_time(self, t_seconds: float) -> int | None:
        if not self._frames:
            return None
        if self._frame_times is None or self._frame_times.size == 0:
            return None
        try:
            t_val = float(t_seconds)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(t_val):
            return None
        return int(np.argmin(np.abs(self._frame_times - t_val)))

    @property
    def frame_times(self) -> np.ndarray | None:
        return self._frame_times

    @property
    def source_kind(self) -> str:
        return self._source_kind

    def __len__(self) -> int:
        return len(self._frames)
