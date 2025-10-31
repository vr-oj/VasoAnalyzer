from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import numpy as np

from vasoanalyzer.core.interpolation import cubic_hermite_bridge, linear_bridge

__all__ = ["find_neighbor", "bridge_segment"]


def find_neighbor(
    values: np.ndarray,
    *,
    start: int,
    step: int,
    forbidden: Iterable[int],
) -> int | None:
    idx = start
    n = len(values)
    forbidden_set = {int(i) for i in forbidden}
    while 0 <= idx < n:
        if idx not in forbidden_set and np.isfinite(values[idx]):
            return idx
        idx += step
    return None


def bridge_segment(
    time: np.ndarray,
    clean_series: np.ndarray,
    raw_series: np.ndarray,
    indices: np.ndarray,
    *,
    left_idx: int,
    right_idx: int,
    method: str,
    forbidden: Iterable[int],
) -> np.ndarray:
    method = method.lower()
    if method == "cubic":
        bridged = cubic_hermite_bridge(
            time,
            clean_series,
            raw_series,
            indices,
            left_idx=left_idx,
            right_idx=right_idx,
            forbidden=forbidden,
        )
        if np.any(~np.isfinite(bridged)):
            return cast(
                np.ndarray,
                linear_bridge(
                    time,
                    clean_series,
                    indices,
                    left_idx=left_idx,
                    right_idx=right_idx,
                ),
            )
        return cast(np.ndarray, bridged)
    return cast(
        np.ndarray,
        linear_bridge(
            time,
            clean_series,
            indices,
            left_idx=left_idx,
            right_idx=right_idx,
        ),
    )
