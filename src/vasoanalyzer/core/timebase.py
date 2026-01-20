# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Canonical timebase resolution and validation utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Sequence
from typing import Any, Mapping

import logging
import math
import bisect

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TIME_EPS_S = 1e-3
RANGE_TOL_S = 0.05


class TimebaseSource(str, Enum):
    TIME_S_EXACT = "time_s_exact"
    TIME_SECONDS = "time_seconds"
    TIMESTAMP = "timestamp"
    SAMPLE_RATE = "sample_rate"
    UNKNOWN = "unknown"


class FrameTimeSource(str, Enum):
    TRACE_TIFF_PAGE = "tiff_page"
    TIFF_METADATA = "tiff_metadata"
    EXPLICIT = "explicit"
    FPS = "fps"
    UNIFORM_WINDOW = "uniform_window"
    UNKNOWN = "unknown"


@dataclass
class TimebaseResult:
    time_s: np.ndarray
    source: TimebaseSource
    warnings: list[str] = field(default_factory=list)
    source_column: str | None = None
    t0_s: float | None = None


@dataclass
class EventTimeReport:
    total: int
    valid: int
    invalid: int
    clamped: int
    clamped_low: int
    clamped_high: int
    out_of_range: int
    warnings: list[str] = field(default_factory=list)
    range_min_s: float | None = None
    range_max_s: float | None = None


@dataclass
class FrameTimeResult:
    frame_times_s: np.ndarray
    source: FrameTimeSource
    warnings: list[str] = field(default_factory=list)
    fps: float | None = None
    frame_to_trace_idx: np.ndarray | None = None
    mapping_coverage: float | None = None


@dataclass
class TiffPageTimeResult:
    tiff_page_times: list[float]
    warnings: list[str] = field(default_factory=list)
    valid: bool = False
    page_count: int | None = None
    median_interval_s: float | None = None
    time_column: str | None = None


def _normalize_name(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _extract_metadata(metadata: Mapping[str, Any] | None, attrs: Any | None) -> dict[str, Any]:
    if metadata is not None:
        return dict(metadata)
    if isinstance(attrs, dict):
        return dict(attrs)
    return {}


def _extract_sample_rate_hz(meta: Mapping[str, Any]) -> float | None:
    for key in ("sample_rate_hz", "sampling_rate_hz", "sample_rate", "sampling_rate", "fps"):
        if key in meta:
            try:
                rate = float(meta[key])
            except (TypeError, ValueError):
                continue
            if rate > 0:
                return rate
    return None


def _time_units_from_meta(meta: Mapping[str, Any]) -> str | None:
    for key in ("time_units", "time_unit", "time_unit_s"):
        if key in meta and meta[key] is not None:
            return str(meta[key]).strip().lower()
    return None


def resolve_trace_timebase(
    trace_df: pd.DataFrame,
    metadata: Mapping[str, Any] | None = None,
) -> TimebaseResult:
    """Resolve and normalize the trace timebase to seconds starting at 0."""

    meta = _extract_metadata(metadata, getattr(trace_df, "attrs", None))
    warnings: list[str] = []

    normalized = {col: _normalize_name(col) for col in trace_df.columns}

    exact_col = next((c for c, n in normalized.items() if n == "timesexact"), None)

    seconds_candidates = {
        "times",
        "timeseconds",
        "timesec",
        "timesecs",
        "timesecond",
        "timeinsecs",
        "tseconds",
        "tsec",
        "tseconds",
        "tseconds",
    }
    seconds_col = None
    for col, norm in normalized.items():
        if norm in seconds_candidates:
            seconds_col = col
            break
        if "time" in norm and ("sec" in norm or "second" in norm) and "stamp" not in norm:
            seconds_col = col
            break

    time_unit = _time_units_from_meta(meta)
    time_col = None
    if seconds_col is None:
        for col, norm in normalized.items():
            if norm == "time":
                if time_unit in {"s", "sec", "secs", "second", "seconds"}:
                    seconds_col = col
                    warnings.append(
                        f"Using '{col}' as seconds because metadata specifies time units '{time_unit}'."
                    )
                else:
                    time_col = col
                break

    timestamp_col = next(
        (c for c, n in normalized.items() if n in {"timestamp", "datetime", "dateTime".lower()}),
        None,
    )

    source = TimebaseSource.UNKNOWN
    source_column = None
    if exact_col is not None:
        source = TimebaseSource.TIME_S_EXACT
        source_column = exact_col
    elif seconds_col is not None:
        source = TimebaseSource.TIME_SECONDS
        source_column = seconds_col
        if exact_col is None and "Time_s_exact" not in trace_df.columns:
            warnings.append("Time_s_exact not found; using seconds column as canonical.")
    elif timestamp_col is not None:
        source = TimebaseSource.TIMESTAMP
        source_column = timestamp_col
    elif time_col is not None:
        raise ValueError(
            f"Trace time column '{time_col}' is ambiguous. "
            "Rename to 'Time (s)' or provide metadata time units or sample_rate_hz."
        )
    else:
        sample_rate = _extract_sample_rate_hz(meta)
        if sample_rate is None:
            raise ValueError(
                "No explicit time column found. Provide 'Time_s_exact', 'Time (s)', "
                "'Timestamp'/'Datetime', or an explicit sample_rate_hz."
            )
        source = TimebaseSource.SAMPLE_RATE
        source_column = None

    if source == TimebaseSource.SAMPLE_RATE:
        sample_rate = _extract_sample_rate_hz(meta)
        if sample_rate is None:
            raise ValueError("sample_rate_hz must be provided for index-based time.")
        time_values = np.arange(len(trace_df), dtype=float) / float(sample_rate)
    elif source == TimebaseSource.TIMESTAMP:
        series = trace_df[source_column]
        dt = pd.to_datetime(series, errors="coerce")
        valid = dt.notna()
        if not valid.any():
            raise ValueError(f"Timestamp column '{source_column}' has no valid values.")
        t0 = dt.loc[valid].iloc[0]
        delta = (dt - t0).dt.total_seconds()
        time_values = delta.to_numpy(dtype=float)
    else:
        series = trace_df[source_column]
        numeric = pd.to_numeric(series, errors="coerce")
        if not numeric.notna().any():
            raise ValueError(f"Time column '{source_column}' has no numeric values.")
        time_values = numeric.to_numpy(dtype=float)

    finite_mask = np.isfinite(time_values)
    if not finite_mask.any():
        raise ValueError("Resolved trace timebase has no finite values.")

    t0 = float(time_values[finite_mask][0])
    time_values = time_values - t0

    finite_vals = time_values[finite_mask]
    if finite_vals.size >= 2:
        diffs = np.diff(finite_vals)
        if np.any(diffs < -TIME_EPS_S):
            warnings.append("Trace timebase is not monotonic increasing.")
        if np.any(diffs <= 0):
            warnings.append("Trace timebase has non-positive time steps.")

    if np.any(time_values < -TIME_EPS_S):
        warnings.append("Trace timebase contains negative values after normalization.")

    return TimebaseResult(
        time_s=np.asarray(time_values, dtype=np.float64),
        source=source,
        warnings=warnings,
        source_column=source_column,
        t0_s=t0,
    )


def _coerce_event_time_series(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        missing = numeric.isna()
        if missing.any():
            td = pd.to_timedelta(series[missing], errors="coerce")
            numeric.loc[missing] = td.dt.total_seconds()
        return numeric.astype(float)
    td = pd.to_timedelta(series, errors="coerce")
    return td.dt.total_seconds().astype(float)


def validate_and_normalize_events(
    events_df: pd.DataFrame,
    time_s: np.ndarray | list[float] | None,
    *,
    range_tol_s: float = RANGE_TOL_S,
    eps_s: float = TIME_EPS_S,
    time_col: str | None = None,
) -> tuple[pd.DataFrame, EventTimeReport]:
    """Validate event times against a trace timebase and clamp within tolerance."""

    df = events_df.copy()
    warnings: list[str] = []

    if "_time_seconds" in df.columns:
        raw_times = pd.to_numeric(df["_time_seconds"], errors="coerce").astype(float)
    else:
        if time_col is None:
            for col in df.columns:
                norm = _normalize_name(col)
                if norm.startswith("time"):
                    time_col = col
                    break
        if time_col is None:
            raise ValueError("Could not determine event time column.")
        raw_times = _coerce_event_time_series(df[time_col])
        if "__time_offset_seconds" in df.columns:
            offsets = pd.to_numeric(df["__time_offset_seconds"], errors="coerce").fillna(0.0)
            raw_times = raw_times.add(offsets, fill_value=0.0)

    if "_time_seconds_raw" not in df.columns:
        df["_time_seconds_raw"] = raw_times

    normalized_times = raw_times.to_numpy(dtype=float)
    status = np.full(len(df.index), "ok", dtype=object)
    valid_mask = np.isfinite(normalized_times)

    trace_min = None
    trace_max = None
    if time_s is not None:
        trace_arr = np.asarray(time_s, dtype=float)
        trace_valid = np.isfinite(trace_arr)
        if trace_valid.any():
            trace_min = float(trace_arr[trace_valid].min())
            trace_max = float(trace_arr[trace_valid].max())

    clamp_low = np.zeros_like(valid_mask, dtype=bool)
    clamp_high = np.zeros_like(valid_mask, dtype=bool)
    out_of_range = np.zeros_like(valid_mask, dtype=bool)

    if trace_min is not None and trace_max is not None:
        too_low = valid_mask & (normalized_times < trace_min - range_tol_s)
        too_high = valid_mask & (normalized_times > trace_max + range_tol_s)
        out_of_range = too_low | too_high

        clamp_low = valid_mask & (~out_of_range) & (normalized_times < trace_min - eps_s)
        clamp_high = valid_mask & (~out_of_range) & (normalized_times > trace_max + eps_s)

        normalized_times = normalized_times.copy()
        normalized_times[clamp_low] = trace_min
        normalized_times[clamp_high] = trace_max

        status[clamp_low] = "clamped_low"
        status[clamp_high] = "clamped_high"
        status[out_of_range] = "out_of_range"

    status[~valid_mask] = "invalid_time"

    df["_time_seconds"] = normalized_times
    df["_time_status"] = status
    df["_time_valid"] = valid_mask & ~out_of_range

    total = len(df.index)
    clamped_low_count = int(clamp_low.sum())
    clamped_high_count = int(clamp_high.sum())
    clamped_count = clamped_low_count + clamped_high_count
    out_of_range_count = int(out_of_range.sum())
    invalid_time_count = int((~valid_mask).sum())
    valid_count = total - out_of_range_count - invalid_time_count

    if clamped_count:
        warnings.append(
            f"Clamped {clamped_count} event time(s) to trace range using tolerance {range_tol_s:.3f}s."
        )
    if out_of_range_count:
        warnings.append(
            f"Flagged {out_of_range_count} event time(s) outside trace range beyond tolerance."
        )
    if invalid_time_count:
        warnings.append(f"Found {invalid_time_count} event time(s) with invalid values.")

    report = EventTimeReport(
        total=total,
        valid=valid_count,
        invalid=invalid_time_count,
        clamped=clamped_count,
        clamped_low=clamped_low_count,
        clamped_high=clamped_high_count,
        out_of_range=out_of_range_count,
        warnings=warnings,
        range_min_s=trace_min,
        range_max_s=trace_max,
    )
    return df, report


def _parse_time_value(value: Any) -> tuple[float | None, bool]:
    """Return (seconds, assumed_units)."""

    if value is None:
        return None, False
    raw = str(value).strip()
    if not raw:
        return None, False
    has_ms = "ms" in raw.lower()
    has_s = "s" in raw.lower()
    try:
        numeric = float(raw.replace("ms", "").replace("MS", "").replace("s", ""))
    except (TypeError, ValueError):
        return None, False
    if has_ms:
        return numeric / 1000.0, False
    if has_s:
        return numeric, False
    # Ambiguous numeric value: assume seconds but flag as assumed.
    return numeric, True


def resolve_tiff_frame_times(
    tiff_info: Mapping[str, Any],
    *,
    fps: float | None = None,
    trace_time_s: np.ndarray | None = None,
    tiff_page_to_trace_idx: Mapping[int, int] | None = None,
    uniform_time_window_s: tuple[float, float] | None = None,
    time_offset_s: float | None = None,
    allow_fallback: bool = True,
) -> FrameTimeResult:
    """Resolve deterministic TIFF frame times for snapshot sync."""

    warnings: list[str] = []
    n_frames = tiff_info.get("n_frames")
    frame_indices = tiff_info.get("frame_indices")
    explicit_times = tiff_info.get("frame_times_s")
    frames_metadata = tiff_info.get("frames_metadata") or tiff_info.get("frame_metadata")

    if explicit_times is not None:
        times = np.asarray(explicit_times, dtype=float)
        if n_frames is not None and len(times) != int(n_frames):
            raise ValueError("Explicit frame_times_s length does not match n_frames.")
        n_frames = len(times)
        source = FrameTimeSource.EXPLICIT
        frame_times = times
        return _finalize_frame_times(
            frame_times,
            source=source,
            warnings=warnings,
            fps=fps,
            time_offset_s=time_offset_s,
            normalize_to_zero=False,
        )

    if n_frames is None:
        if frames_metadata is not None:
            n_frames = len(frames_metadata)
        elif frame_indices is not None:
            n_frames = len(frame_indices)
        else:
            raise ValueError("tiff_info is missing n_frames and frame metadata.")

    n_frames = int(n_frames)
    if frame_indices is None or len(frame_indices) != n_frames:
        frame_indices = list(range(n_frames))

    trace_time = trace_time_s if trace_time_s is not None else tiff_info.get("trace_time_s")
    mapping = (
        tiff_page_to_trace_idx if tiff_page_to_trace_idx is not None else tiff_info.get("tiff_page_to_trace_idx")
    )

    if trace_time is not None and mapping:
        trace_arr = np.asarray(trace_time, dtype=float)
        frame_to_trace_idx = np.full(n_frames, -1, dtype=int)
        frame_times = np.full(n_frames, np.nan, dtype=float)
        missing = 0
        for frame_idx, page_idx in enumerate(frame_indices):
            try:
                page_int = int(page_idx)
            except Exception:
                page_int = page_idx
            trace_idx = mapping.get(page_int)
            if trace_idx is None or trace_idx < 0 or trace_idx >= len(trace_arr):
                missing += 1
                continue
            frame_to_trace_idx[frame_idx] = int(trace_idx)
            frame_times[frame_idx] = float(trace_arr[int(trace_idx)])
        if missing == 0 and np.isfinite(frame_times).all():
            coverage = 1.0
            return _finalize_frame_times(
                frame_times,
                source=FrameTimeSource.TRACE_TIFF_PAGE,
                warnings=warnings,
                fps=fps,
                frame_to_trace_idx=frame_to_trace_idx,
                mapping_coverage=coverage,
                time_offset_s=time_offset_s,
                normalize_to_zero=False,
            )
        warnings.append(
            f"Trace TIFF mapping missing {missing} frame(s); falling back to other timing sources."
        )
        if not allow_fallback:
            raise ValueError("Trace TIFF mapping incomplete; fallback disabled.")

    if frames_metadata:
        frame_times = []
        assumed_units = 0
        for meta in frames_metadata:
            value = None
            if isinstance(meta, Mapping):
                if "FrameTime" in meta:
                    value = meta.get("FrameTime")
                elif "FrameTime" in meta.keys():
                    value = meta.get("FrameTime")
            seconds, assumed = _parse_time_value(value)
            if seconds is None:
                frame_times.append(np.nan)
            else:
                frame_times.append(float(seconds))
                if assumed:
                    assumed_units += 1

        frame_times = np.asarray(frame_times, dtype=float)
        if np.isfinite(frame_times).all():
            if assumed_units:
                warnings.append(
                    f"Assumed seconds for {assumed_units} FrameTime value(s) without units."
                )
            return _finalize_frame_times(
                frame_times,
                source=FrameTimeSource.TIFF_METADATA,
                warnings=warnings,
                fps=fps,
                time_offset_s=time_offset_s,
            )

        interval_s = None
        if isinstance(frames_metadata[0], Mapping):
            for key in ("Rec_intvl", "FrameInterval"):
                if key in frames_metadata[0]:
                    interval_s, assumed = _parse_time_value(frames_metadata[0].get(key))
                    if interval_s is not None:
                        if assumed:
                            warnings.append(
                                f"Assumed seconds for '{key}' interval without units."
                            )
                        break
        if interval_s is not None and interval_s > 0:
            first_idx = int(np.flatnonzero(np.isfinite(frame_times))[0]) if np.isfinite(frame_times).any() else 0
            first_val = float(frame_times[first_idx]) if np.isfinite(frame_times).any() else 0.0
            filled = first_val + interval_s * (np.arange(n_frames) - first_idx)
            warnings.append(
                "Filled missing FrameTime values using explicit interval metadata."
            )
            return _finalize_frame_times(
                filled,
                source=FrameTimeSource.TIFF_METADATA,
                warnings=warnings,
                fps=fps,
                time_offset_s=time_offset_s,
            )

    if fps is not None and fps > 0:
        frame_times = np.arange(n_frames, dtype=float) / float(fps)
        return _finalize_frame_times(
            frame_times,
            source=FrameTimeSource.FPS,
            warnings=warnings,
            fps=fps,
            time_offset_s=time_offset_s,
        )

    if uniform_time_window_s is not None:
        start, end = uniform_time_window_s
        if n_frames <= 1:
            frame_times = np.asarray([float(start)], dtype=float)
        else:
            frame_times = np.linspace(float(start), float(end), n_frames)
        return _finalize_frame_times(
            frame_times,
            source=FrameTimeSource.UNIFORM_WINDOW,
            warnings=warnings,
            fps=fps,
            time_offset_s=time_offset_s,
            normalize_to_zero=False,
        )

    raise ValueError("Unable to resolve TIFF frame times; provide metadata or fps.")


def _finalize_frame_times(
    frame_times: np.ndarray,
    *,
    source: FrameTimeSource,
    warnings: list[str],
    fps: float | None = None,
    frame_to_trace_idx: np.ndarray | None = None,
    mapping_coverage: float | None = None,
    time_offset_s: float | None = None,
    normalize_to_zero: bool = True,
) -> FrameTimeResult:
    finite = np.isfinite(frame_times)
    if not finite.any():
        raise ValueError("Resolved frame times are all invalid.")
    t0 = float(frame_times[finite][0])
    offset = float(time_offset_s) if time_offset_s is not None else 0.0
    if normalize_to_zero:
        normalized = frame_times - t0 + offset
    else:
        normalized = frame_times + offset
    if normalized.size >= 2:
        diffs = np.diff(normalized[np.isfinite(normalized)])
        if np.any(diffs < -TIME_EPS_S):
            warnings.append("Frame times are not monotonic increasing.")
    return FrameTimeResult(
        frame_times_s=np.asarray(normalized, dtype=np.float64),
        source=source,
        warnings=warnings,
        fps=fps,
        frame_to_trace_idx=frame_to_trace_idx,
        mapping_coverage=mapping_coverage,
    )


def derive_tiff_page_times(
    trace_df: pd.DataFrame | None,
    *,
    expected_page_count: int | None = None,
    time_columns: Sequence[str] = ("Time_s_exact", "Time (s)", "t_seconds"),
    saved_column: str = "Saved",
    tiff_page_column: str = "TiffPage",
) -> TiffPageTimeResult:
    """Derive canonical TIFF page times from trace metadata."""

    warnings: list[str] = []
    if trace_df is None or trace_df.empty:
        warnings.append("Trace DataFrame unavailable; cannot derive TIFF page times.")
        return TiffPageTimeResult([], warnings=warnings)

    time_col = None
    for candidate in time_columns:
        if candidate in trace_df.columns:
            time_col = candidate
            break
    if time_col is None:
        warnings.append("No canonical time column found for TIFF page timing.")
        return TiffPageTimeResult([], warnings=warnings)

    tiff_col = tiff_page_column
    if tiff_col not in trace_df.columns and "tiff_page" in trace_df.columns:
        tiff_col = "tiff_page"
    if tiff_col not in trace_df.columns:
        warnings.append("No TiffPage column found for TIFF page timing.")
        return TiffPageTimeResult([], warnings=warnings, time_column=time_col)

    df_local = trace_df
    if saved_column in trace_df.columns:
        saved_series = pd.to_numeric(trace_df[saved_column], errors="coerce").fillna(0)
        saved_mask = saved_series > 0
        if saved_mask.any():
            df_local = trace_df.loc[saved_mask]
        else:
            warnings.append("Saved column present but no saved rows; using all rows.")

    pages = pd.to_numeric(df_local[tiff_col], errors="coerce")
    times = pd.to_numeric(df_local[time_col], errors="coerce")
    mask = pages.notna() & times.notna()
    if not mask.any():
        warnings.append("No valid TiffPage/time pairs found.")
        return TiffPageTimeResult([], warnings=warnings, time_column=time_col)

    pages = pages.loc[mask].astype(int)
    times = times.loc[mask].astype(float)

    mapping: dict[int, float] = {}
    duplicates: set[int] = set()
    for page_val, time_val in zip(pages.to_numpy(), times.to_numpy(), strict=False):
        page_int = int(page_val)
        if page_int in mapping:
            duplicates.add(page_int)
            continue
        mapping[page_int] = float(time_val)

    if duplicates:
        warnings.append(
            f"Duplicate TiffPage entries detected (count={len(duplicates)}); "
            "using first occurrence."
        )

    if not mapping:
        warnings.append("No usable TiffPage mappings after filtering.")
        return TiffPageTimeResult([], warnings=warnings, time_column=time_col)

    max_page = max(mapping.keys())
    if expected_page_count is not None and expected_page_count > 0:
        page_count = int(expected_page_count)
    else:
        page_count = int(max_page + 1)

    if page_count <= 0:
        warnings.append("Expected TIFF page count is invalid.")
        return TiffPageTimeResult([], warnings=warnings, time_column=time_col)

    times_list: list[float] = [float("nan")] * page_count
    out_of_range = 0
    for page_int, time_val in mapping.items():
        if page_int < 0 or page_int >= page_count:
            out_of_range += 1
            continue
        times_list[page_int] = float(time_val)
    if out_of_range:
        warnings.append(
            f"TiffPage entries out of expected range: {out_of_range}."
        )

    missing_pages = [i for i, val in enumerate(times_list) if not math.isfinite(val)]
    if missing_pages:
        warnings.append(
            f"Missing TIFF page time(s): {len(missing_pages)} of {page_count}."
        )

    valid = not missing_pages and out_of_range == 0
    median_interval = None
    if any(math.isfinite(val) for val in times_list):
        finite_vals = np.asarray([val for val in times_list if math.isfinite(val)], dtype=float)
        if finite_vals.size >= 2:
            diffs = np.diff(finite_vals)
            if np.any(diffs <= TIME_EPS_S):
                warnings.append("TIFF page times are not strictly increasing.")
                valid = False
            else:
                median_interval = float(np.median(diffs))

    if min(mapping.keys()) != 0:
        warnings.append("TiffPage indices do not start at 0.")
        valid = False

    if expected_page_count is not None and expected_page_count > 0:
        expected_set = set(range(int(expected_page_count)))
        if set(mapping.keys()) != expected_set:
            warnings.append("TiffPage coverage does not match expected range.")
            valid = False

    return TiffPageTimeResult(
        tiff_page_times=times_list,
        warnings=warnings,
        valid=valid,
        page_count=page_count,
        median_interval_s=median_interval,
        time_column=time_col,
    )


def page_for_time(
    t: float,
    tiff_page_times: Sequence[float],
    *,
    mode: str = "nearest",
) -> int | None:
    """Return the deterministic page index for a time value."""

    try:
        if len(tiff_page_times) == 0:
            return None
    except Exception:
        return None
    try:
        t_val = float(t)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(t_val):
        return None

    times = [float(v) for v in tiff_page_times]
    finite_indices = [i for i, v in enumerate(times) if math.isfinite(v)]
    if not finite_indices:
        return None

    if len(finite_indices) != len(times):
        return min(finite_indices, key=lambda i: abs(times[i] - t_val))

    for idx in range(1, len(times)):
        if times[idx] < times[idx - 1] - TIME_EPS_S:
            return min(range(len(times)), key=lambda i: abs(times[i] - t_val))

    if mode == "floor":
        pos = bisect.bisect_right(times, t_val) - 1
        return max(0, min(int(pos), len(times) - 1))

    pos = bisect.bisect_left(times, t_val)
    if pos <= 0:
        return 0
    if pos >= len(times):
        return len(times) - 1
    prev_idx = pos - 1
    next_idx = pos
    if abs(times[next_idx] - t_val) < abs(t_val - times[prev_idx]):
        return int(next_idx)
    return int(prev_idx)


__all__ = [
    "TIME_EPS_S",
    "RANGE_TOL_S",
    "TimebaseSource",
    "FrameTimeSource",
    "TimebaseResult",
    "EventTimeReport",
    "FrameTimeResult",
    "TiffPageTimeResult",
    "resolve_trace_timebase",
    "validate_and_normalize_events",
    "resolve_tiff_frame_times",
    "derive_tiff_page_times",
    "page_for_time",
]
