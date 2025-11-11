"""Trace data model with manual edit tracking and LOD rendering."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np

from .audit import EditAction, deserialize_edit_log
from .traces.actions import bridge_segment, find_neighbor
from .traces.lod import LODLevel
from .traces.window import TraceWindow, ensure_float_array


def _prefer_column(frame, names: Sequence[str]) -> str | None:
    for candidate in names:
        if candidate in frame.columns:
            return candidate
    return None


class TraceModel:
    """Expose trace data with fast level-of-detail windowing and edit replay."""

    _CACHE_LIMIT = 8

    def __init__(
        self,
        time: np.ndarray,
        inner: np.ndarray,
        outer: np.ndarray | None = None,
        *,
        inner_raw: np.ndarray | None = None,
        outer_raw: np.ndarray | None = None,
        avg_pressure: np.ndarray | None = None,
        set_pressure: np.ndarray | None = None,
        base_factor: int = 4,
        max_points_per_level: int = 4096,
        edit_actions: Sequence[EditAction] | None = None,
    ) -> None:
        if time.ndim != 1 or inner.ndim != 1:
            raise ValueError("time and inner arrays must be 1-D")
        if time.size != inner.size:
            raise ValueError("time and inner arrays must have the same length")
        if outer is not None and outer.shape != inner.shape:
            raise ValueError("outer array must match inner shape")
        if avg_pressure is not None and avg_pressure.shape != inner.shape:
            raise ValueError("avg_pressure array must match inner shape")
        if set_pressure is not None and set_pressure.shape != inner.shape:
            raise ValueError("set_pressure array must match inner shape")

        order = np.argsort(time)
        self._time_full = np.ascontiguousarray(time[order])

        inner_clean = ensure_float_array(inner)[order]
        raw_candidate = inner_raw if inner_raw is not None else inner
        inner_raw_sorted = ensure_float_array(raw_candidate)[order]

        self._inner_raw = inner_raw_sorted
        self._inner_clean = inner_clean if inner_clean is not None else inner_raw_sorted.copy()

        if outer is None:
            self._outer_clean = None
            self._outer_raw = None if outer_raw is None else ensure_float_array(outer_raw)[order]
        else:
            outer_clean_sorted = ensure_float_array(outer)[order]
            if outer_raw is None:
                outer_raw_sorted = outer_clean_sorted.copy()
            else:
                outer_raw_sorted = ensure_float_array(outer_raw)[order]
            self._outer_clean = outer_clean_sorted
            self._outer_raw = outer_raw_sorted

        if self._outer_clean is None and self._outer_raw is not None:
            # Raw provided but no active outer channel -> treat raw as clean baseline.
            self._outer_clean = self._outer_raw.copy()

        # Store pressure data (not editable, so no raw/clean distinction needed)
        self._avg_pressure = None if avg_pressure is None else ensure_float_array(avg_pressure)[order]
        self._set_pressure = None if set_pressure is None else ensure_float_array(set_pressure)[order]

        self._base_factor = max(int(base_factor), 2)
        self._max_points_per_level = max(int(max_points_per_level), 64)
        self._window_cache: dict[tuple[int, float, float], TraceWindow] = {}
        self._levels: tuple[LODLevel, ...] = ()
        self._edit_log: list[EditAction] = []

        if edit_actions:
            self.replay_actions(edit_actions, rebuild=True)
        else:
            self._rebuild_levels()

    # ------------------------------------------------------------------ properties
    @property
    def levels(self) -> tuple[LODLevel, ...]:
        return self._levels

    @property
    def time_full(self) -> np.ndarray:
        return self._time_full

    @property
    def inner_full(self) -> np.ndarray:
        return self._inner_clean

    @property
    def inner_raw(self) -> np.ndarray:
        return self._inner_raw

    @property
    def outer_full(self) -> np.ndarray | None:
        return self._outer_clean

    @property
    def outer_raw(self) -> np.ndarray | None:
        return self._outer_raw

    @property
    def avg_pressure_full(self) -> np.ndarray | None:
        return self._avg_pressure

    @property
    def set_pressure_full(self) -> np.ndarray | None:
        return self._set_pressure

    @property
    def full_range(self) -> tuple[float, float]:
        return float(self._time_full[0]), float(self._time_full[-1])

    @property
    def edit_log(self) -> tuple[EditAction, ...]:
        return tuple(self._edit_log)

    def edited_point_count(self) -> int:
        return sum(action.count for action in self._edit_log)

    def edited_fraction(self) -> float:
        total = max(len(self._inner_raw), 1)
        return float(self.edited_point_count()) / total

    # ------------------------------------------------------------------ LOD helpers
    def _rebuild_levels(self) -> None:
        self._levels = self._build_levels()
        self.clear_cache()

    def clear_cache(self) -> None:
        self._window_cache.clear()

    def _build_levels(self) -> tuple[LODLevel, ...]:
        levels: list[LODLevel] = []
        bucket_size = 1
        factor = 1
        total = self._time_full.size
        while True:
            level = self._build_level(bucket_size=bucket_size, factor=factor)
            levels.append(level)
            if level.time_centers.size <= self._max_points_per_level or bucket_size >= total:
                break
            bucket_size = min(bucket_size * self._base_factor, total)
            factor *= self._base_factor
            if bucket_size == total:
                break
        return tuple(levels)

    def _build_level(self, *, bucket_size: int, factor: int) -> LODLevel:
        time = self._time_full
        inner = self._inner_clean
        outer = self._outer_clean
        avg_pressure = self._avg_pressure
        set_pressure = self._set_pressure
        n = time.size
        if bucket_size <= 1:
            return LODLevel(
                factor=factor,
                bucket_size=1,
                time_centers=time.copy(),
                inner_mean=inner.copy(),
                inner_min=inner.copy(),
                inner_max=inner.copy(),
                outer_mean=None if outer is None else outer.copy(),
                outer_min=None if outer is None else outer.copy(),
                outer_max=None if outer is None else outer.copy(),
                avg_pressure_mean=None if avg_pressure is None else avg_pressure.copy(),
                avg_pressure_min=None if avg_pressure is None else avg_pressure.copy(),
                avg_pressure_max=None if avg_pressure is None else avg_pressure.copy(),
                set_pressure_mean=None if set_pressure is None else set_pressure.copy(),
                set_pressure_min=None if set_pressure is None else set_pressure.copy(),
                set_pressure_max=None if set_pressure is None else set_pressure.copy(),
            )

        starts = np.arange(0, n, bucket_size, dtype=int)
        ends = np.append(starts[1:], n)
        centers = (time[starts] + time[np.maximum(ends - 1, starts)]) * 0.5

        def reduce_series(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
            counts = ends - starts
            sums = np.add.reduceat(values, starts)
            means = sums / counts
            mins = np.minimum.reduceat(values, starts)
            maxs = np.maximum.reduceat(values, starts)
            return means, mins, maxs

        inner_mean, inner_min, inner_max = reduce_series(inner)
        outer_mean: np.ndarray | None
        outer_min: np.ndarray | None
        outer_max: np.ndarray | None
        if outer is not None:
            outer_mean, outer_min, outer_max = reduce_series(outer)
        else:
            outer_mean = outer_min = outer_max = None

        avg_pressure_mean: np.ndarray | None
        avg_pressure_min: np.ndarray | None
        avg_pressure_max: np.ndarray | None
        if avg_pressure is not None:
            avg_pressure_mean, avg_pressure_min, avg_pressure_max = reduce_series(avg_pressure)
        else:
            avg_pressure_mean = avg_pressure_min = avg_pressure_max = None

        set_pressure_mean: np.ndarray | None
        set_pressure_min: np.ndarray | None
        set_pressure_max: np.ndarray | None
        if set_pressure is not None:
            set_pressure_mean, set_pressure_min, set_pressure_max = reduce_series(set_pressure)
        else:
            set_pressure_mean = set_pressure_min = set_pressure_max = None

        return LODLevel(
            factor=factor,
            bucket_size=bucket_size,
            time_centers=centers,
            inner_mean=inner_mean,
            inner_min=inner_min,
            inner_max=inner_max,
            outer_mean=outer_mean,
            outer_min=outer_min,
            outer_max=outer_max,
            avg_pressure_mean=avg_pressure_mean,
            avg_pressure_min=avg_pressure_min,
            avg_pressure_max=avg_pressure_max,
            set_pressure_mean=set_pressure_mean,
            set_pressure_min=set_pressure_min,
            set_pressure_max=set_pressure_max,
        )

    def best_level_for_window(self, x0: float, x1: float, pixel_width: int) -> int:
        """Select LOD level to ensure ~2-3 points per pixel for optimal rendering.

        This balances visual quality (shows all features) with performance
        (doesn't render invisible detail). The min/max envelope ensures no
        data is lost even when downsampled.
        """
        if pixel_width <= 0 or not self._levels:
            return 0

        # Calculate approximate points in window from full dataset
        time = self._time_full
        mask = (time >= x0) & (time <= x1)
        points_in_window = np.count_nonzero(mask)

        # If very few points, always use raw data
        if points_in_window < pixel_width:
            return 0

        # Target: 2.5 points per pixel for smooth rendering without overdraw
        # This provides good visual quality while avoiding wasted GPU/CPU work
        target_points = pixel_width * 2.5

        # Select the coarsest LOD level that still meets our target
        for i, level in enumerate(self._levels):
            if level.time_centers.size <= target_points:
                return i

        # If all levels have too many points, use the coarsest available
        return len(self._levels) - 1

    def window(self, level_index: int, x0: float, x1: float) -> TraceWindow:
        key = (level_index, float(x0), float(x1))
        cached = self._window_cache.get(key)
        if cached is not None:
            return cached

        level_index = max(0, min(level_index, len(self._levels) - 1))
        level = self._levels[level_index]
        window = level.window(x0, x1)
        self._window_cache[key] = window
        if len(self._window_cache) > self._CACHE_LIMIT:
            oldest = next(iter(self._window_cache))
            if oldest != key:
                self._window_cache.pop(oldest, None)
        return window

    # ------------------------------------------------------------------ editing
    def apply_actions(self, actions: Sequence[EditAction], *, rebuild: bool = True) -> None:
        if not actions:
            return
        for action in actions:
            self._apply_action(action, record=True)
        if rebuild:
            self._rebuild_levels()
        else:
            self.clear_cache()

    def replay_actions(self, actions: Sequence[EditAction], *, rebuild: bool = True) -> None:
        self._inner_clean = self._inner_raw.copy()
        if self._outer_raw is not None:
            self._outer_clean = self._outer_raw.copy()
        elif self._outer_clean is not None:
            self._outer_clean = self._outer_clean.copy()
        self._edit_log = list(actions)
        for action in self._edit_log:
            self._apply_action(action, record=False)
        if rebuild:
            self._rebuild_levels()
        else:
            self.clear_cache()

    def clear_actions(self, *, rebuild: bool = True) -> None:
        self._edit_log.clear()
        self._inner_clean = self._inner_raw.copy()
        if self._outer_raw is not None:
            self._outer_clean = self._outer_raw.copy()
        elif self._outer_clean is not None:
            self._outer_clean = self._outer_clean.copy()
        if rebuild:
            self._rebuild_levels()
        else:
            self.clear_cache()

    def pop_actions(self, count: int = 1, *, rebuild: bool = True) -> list[EditAction]:
        if count <= 0 or not self._edit_log:
            return []
        remove_count = min(count, len(self._edit_log))
        removed = self._edit_log[-remove_count:]
        remaining = self._edit_log[:-remove_count]
        self.replay_actions(remaining, rebuild=rebuild)
        return list(removed)

    # ------------------------------------------------------------------ internal editing helpers
    def _select_series(self, channel: str, *, raw: bool = False) -> np.ndarray | None:
        channel_key = channel.strip().lower()
        if channel_key == "inner":
            return self._inner_raw if raw else self._inner_clean
        if channel_key == "outer":
            series = self._outer_raw if raw else self._outer_clean
            if series is None:
                raise ValueError("Trace does not include an outer diameter channel")
            return series
        raise ValueError(f"Unsupported channel: {channel}")

    def _apply_action(self, action: EditAction, *, record: bool) -> None:
        target = self._select_series(action.channel, raw=False)
        raw_series = self._select_series(action.channel, raw=True)
        if target is None or raw_series is None:
            raise ValueError(f"Channel {action.channel} not available for editing")

        if not action.indices:
            if record:
                self._edit_log.append(action)
            return

        indices = tuple(sorted(dict.fromkeys(int(i) for i in action.indices)))
        arr_idx = np.fromiter(indices, dtype=int)
        if arr_idx.min() < 0 or arr_idx.max() >= len(target):
            raise IndexError("Edit indices out of bounds")

        if action.op == "delete_points":
            target[arr_idx] = np.nan
        elif action.op == "restore_points":
            target[arr_idx] = raw_series[arr_idx]
        elif action.op == "connect_across":
            self._apply_connect(target, raw_series, arr_idx, action)
        else:
            raise ValueError(f"Unsupported edit operation: {action.op}")

        if record:
            self._edit_log.append(action)
        self.clear_cache()

    def _apply_connect(
        self,
        target: np.ndarray,
        raw_series: np.ndarray,
        indices: np.ndarray,
        action: EditAction,
    ) -> None:
        forbidden = {int(i) for i in indices.tolist()}
        first = int(indices[0])
        last = int(indices[-1])
        left_idx = find_neighbor(target, start=first - 1, step=-1, forbidden=forbidden)
        right_idx = find_neighbor(target, start=last + 1, step=+1, forbidden=forbidden)

        if left_idx is None or right_idx is None:
            target[indices] = np.nan
            return

        method = str(action.params.get("method", "linear")).lower()
        bridged = bridge_segment(
            self._time_full,
            target,
            raw_series,
            indices,
            left_idx=left_idx,
            right_idx=right_idx,
            method=method,
            forbidden=forbidden,
        )
        target[indices] = bridged

    # ------------------------------------------------------------------ construction helpers
    @classmethod
    def from_dataframe(
        cls,
        df,
        *,
        base_factor: int = 4,
        max_points_per_level: int = 4096,
        edit_actions: Sequence[EditAction] | None = None,
    ) -> TraceModel:
        time = df["Time (s)"].to_numpy(dtype=float)

        inner_col = _prefer_column(df, ("Inner Diameter (clean)", "Inner Diameter"))
        if inner_col is None:
            raise ValueError("Dataframe missing Inner Diameter column")
        inner_clean = df[inner_col].to_numpy(dtype=float)

        raw_inner_col = _prefer_column(
            df,
            (
                "Inner Diameter (raw)",
                "Inner Diameter Raw",
                "Inner Diameter (original)",
            ),
        )
        inner_raw = df[raw_inner_col].to_numpy(dtype=float) if raw_inner_col else None

        outer_clean = None
        outer_raw = None
        outer_col = _prefer_column(
            df,
            (
                "Outer Diameter (clean)",
                "Outer Diameter",
            ),
        )
        if outer_col is not None:
            outer_clean = df[outer_col].to_numpy(dtype=float)
            outer_raw_col = _prefer_column(
                df,
                (
                    "Outer Diameter (raw)",
                    "Outer Diameter Raw",
                    "Outer Diameter (original)",
                ),
            )
            outer_raw = df[outer_raw_col].to_numpy(dtype=float) if outer_raw_col else None

        # Extract pressure columns if available
        avg_pressure = None
        avg_pressure_col = _prefer_column(df, ("Avg Pressure (mmHg)",))
        if avg_pressure_col is not None:
            avg_pressure = df[avg_pressure_col].to_numpy(dtype=float)

        set_pressure = None
        set_pressure_col = _prefer_column(df, ("Set Pressure (mmHg)",))
        if set_pressure_col is not None:
            set_pressure = df[set_pressure_col].to_numpy(dtype=float)

        if edit_actions is None:
            attrs = getattr(df, "attrs", None)
            if isinstance(attrs, dict):
                payload = attrs.get("edit_log")
                if isinstance(payload, Iterable):
                    edit_actions = deserialize_edit_log(payload)

        return cls(
            time,
            inner_clean,
            outer_clean,
            inner_raw=inner_raw,
            outer_raw=outer_raw,
            avg_pressure=avg_pressure,
            set_pressure=set_pressure,
            base_factor=base_factor,
            max_points_per_level=max_points_per_level,
            edit_actions=edit_actions,
        )


def lod_sidecar_path(trace_path: Path) -> Path:
    """Return the default path for a cached LOD pyramid file."""

    return trace_path.with_suffix(trace_path.suffix + ".lod.npz")


def _signature(time: np.ndarray, inner: np.ndarray) -> np.ndarray:
    if time.size == 0:
        return np.zeros(6, dtype=np.float64)
    return np.array(
        [
            float(time.size),
            float(time[0]),
            float(time[-1]),
            float(np.nanmean(time)),
            float(np.nanmean(inner)),
            float(np.nanstd(inner)),
        ],
        dtype=np.float64,
    )


def save_lod(path: Path, model: TraceModel) -> None:
    """Persist LOD levels for later reuse."""

    path = Path(path)
    payload = {
        "signature": _signature(model.time_full, model.inner_full),
        "has_outer": np.array([model.outer_full is not None], dtype=np.int8),
        "has_avg_pressure": np.array([model.avg_pressure_full is not None], dtype=np.int8),
        "has_set_pressure": np.array([model.set_pressure_full is not None], dtype=np.int8),
        "level_count": np.array([len(model.levels)], dtype=np.int64),
    }
    for idx, level in enumerate(model.levels):
        prefix = f"l{idx}_"
        payload[f"{prefix}meta"] = np.array([level.factor, level.bucket_size], dtype=np.int64)
        payload[f"{prefix}time"] = level.time_centers
        payload[f"{prefix}inner_mean"] = level.inner_mean
        payload[f"{prefix}inner_min"] = level.inner_min
        payload[f"{prefix}inner_max"] = level.inner_max
        if level.outer_mean is not None:
            payload[f"{prefix}outer_mean"] = level.outer_mean
        if level.outer_min is not None:
            payload[f"{prefix}outer_min"] = level.outer_min
        if level.outer_max is not None:
            payload[f"{prefix}outer_max"] = level.outer_max
        if level.avg_pressure_mean is not None:
            payload[f"{prefix}avg_pressure_mean"] = level.avg_pressure_mean
        if level.avg_pressure_min is not None:
            payload[f"{prefix}avg_pressure_min"] = level.avg_pressure_min
        if level.avg_pressure_max is not None:
            payload[f"{prefix}avg_pressure_max"] = level.avg_pressure_max
        if level.set_pressure_mean is not None:
            payload[f"{prefix}set_pressure_mean"] = level.set_pressure_mean
        if level.set_pressure_min is not None:
            payload[f"{prefix}set_pressure_min"] = level.set_pressure_min
        if level.set_pressure_max is not None:
            payload[f"{prefix}set_pressure_max"] = level.set_pressure_max
    np.savez_compressed(path, **cast(dict[str, Any], payload))


def load_lod(
    path: Path,
    *,
    time: np.ndarray,
    inner: np.ndarray,
    outer: np.ndarray | None = None,
) -> tuple[LODLevel, ...] | None:
    """Load cached LOD levels if they match the provided trace."""

    path = Path(path)
    if not path.exists():
        return None

    with np.load(path, allow_pickle=False) as data:
        signature = data.get("signature")
        if signature is None:
            return None
        expected = _signature(time, inner)
        if signature.shape != expected.shape or not np.allclose(signature, expected, atol=1e-6):
            return None
        level_count_arr = data.get("level_count")
        if level_count_arr is None:
            return None
        level_count = int(level_count_arr[0])
        has_outer = bool(data.get("has_outer", np.array([0]))[0])
        has_avg_pressure = bool(data.get("has_avg_pressure", np.array([0]))[0])
        has_set_pressure = bool(data.get("has_set_pressure", np.array([0]))[0])
        levels = []
        for idx in range(level_count):
            prefix = f"l{idx}_"
            meta = data.get(f"{prefix}meta")
            time_centers = data.get(f"{prefix}time")
            inner_mean = data.get(f"{prefix}inner_mean")
            inner_min = data.get(f"{prefix}inner_min")
            inner_max = data.get(f"{prefix}inner_max")
            if meta is None or time_centers is None or inner_mean is None:
                return None
            factor = int(meta[0])
            bucket_size = int(meta[1])
            outer_mean = outer_min = outer_max = None
            if has_outer:
                outer_mean = data.get(f"{prefix}outer_mean")
                outer_min = data.get(f"{prefix}outer_min")
                outer_max = data.get(f"{prefix}outer_max")
                if outer_mean is None:
                    return None
            avg_pressure_mean = avg_pressure_min = avg_pressure_max = None
            if has_avg_pressure:
                avg_pressure_mean = data.get(f"{prefix}avg_pressure_mean")
                avg_pressure_min = data.get(f"{prefix}avg_pressure_min")
                avg_pressure_max = data.get(f"{prefix}avg_pressure_max")
            set_pressure_mean = set_pressure_min = set_pressure_max = None
            if has_set_pressure:
                set_pressure_mean = data.get(f"{prefix}set_pressure_mean")
                set_pressure_min = data.get(f"{prefix}set_pressure_min")
                set_pressure_max = data.get(f"{prefix}set_pressure_max")
            levels.append(
                LODLevel(
                    factor=factor,
                    bucket_size=bucket_size,
                    time_centers=time_centers,
                    inner_mean=inner_mean,
                    inner_min=inner_min,
                    inner_max=inner_max,
                    outer_mean=outer_mean,
                    outer_min=outer_min,
                    outer_max=outer_max,
                    avg_pressure_mean=avg_pressure_mean,
                    avg_pressure_min=avg_pressure_min,
                    avg_pressure_max=avg_pressure_max,
                    set_pressure_mean=set_pressure_mean,
                    set_pressure_min=set_pressure_min,
                    set_pressure_max=set_pressure_max,
                )
            )
    if not levels:
        return None
    return tuple(levels)


__all__ = [
    "TraceModel",
    "TraceWindow",
    "EditAction",
    "bridge_segment",
    "find_neighbor",
    "lod_sidecar_path",
    "save_lod",
    "load_lod",
]
