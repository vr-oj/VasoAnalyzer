# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from vasoanalyzer.services.cache_service import DataCache
except ImportError:  # pragma: no cover - optional during bootstrap
    DataCache = None

from vasoanalyzer.io.events import _standardize_headers, find_matching_event_file
from vasoanalyzer.io.traces import load_trace


def _read_event_dataframe(path: str, *, cache: Any | None = None) -> pd.DataFrame:
    """Return ``path`` loaded into a DataFrame with normalized headers."""
    with open(path, encoding="utf-8-sig") as f:
        sample = f.read(1024)
        try:
            delimiter = csv.Sniffer().sniff(sample).delimiter
        except csv.Error:
            if "," in sample:
                delimiter = ","
            elif "\t" in sample:
                delimiter = "\t"
            else:
                delimiter = ";"

    def _load_csv(p: str | Path) -> pd.DataFrame:
        return pd.read_csv(p, delimiter=delimiter)

    if cache is not None and DataCache is not None:
        df = cache.read_dataframe(path, loader=_load_csv)
    else:
        df = _load_csv(path)
    return _standardize_headers(df)


log = logging.getLogger(__name__)


def load_trace_and_events(
    trace_path: str,
    events_path: str | pd.DataFrame | None = None,
    *,
    cache: Any | None = None,
):
    """Load a trace CSV and its matching event table.

    Parameters
    ----------
    trace_path:
        Path to the trace CSV file.
    events_path:
        Optional explicit path to the event file. If ``None``, a matching
        file is searched next to ``trace_path`` using
        :func:`find_matching_event_file`.

    Returns
    -------
    tuple[
        pandas.DataFrame,
        list[str],
        list[float],
        list[int] | None,
        list[float],
        list[float],
        dict[str, object],
    ]
        The trace DataFrame followed by event labels, times, frame indices (or
        ``None`` if unavailable), the inner and outer diameter at each event time,
        and a metadata dictionary describing any adjustments applied during import.
    """
    log.debug("Loading trace and events for %s", trace_path)
    df = load_trace(trace_path, cache=cache)
    log.info(
        "Import: Loaded trace CSV %s with %d rows and columns=%s",
        trace_path,
        len(df.index),
        list(df.columns),
    )

    extras: dict[str, object] = {
        "event_file": None,
        "auto_detected": False,
        "frame_fallback_used": False,
        "frame_fallback_rows": 0,
        "dropped_missing_time": 0,
        "ignored_out_of_range": 0,
        "time_source": None,
    }

    events_df: pd.DataFrame | None = None
    ev_path: str | None = None

    event_source_label: str | None = None
    if isinstance(events_path, pd.DataFrame):
        events_df = _standardize_headers(events_path.copy())
        event_source_label = "<DataFrame>"
    else:
        ev_path = events_path
        if ev_path:
            event_source_label = ev_path

    if ev_path is None and events_df is None:
        ev_path = find_matching_event_file(trace_path)
        if ev_path:
            extras["auto_detected"] = True
            event_source_label = ev_path

    if ev_path and os.path.exists(ev_path):
        extras["event_file"] = ev_path
        events_df = _read_event_dataframe(ev_path, cache=cache)
        log.info(
            "Import: Loaded events CSV %s with %d rows (columns=%s)",
            ev_path,
            len(events_df.index),
            list(events_df.columns),
        )
    elif events_df is None:
        log.info("Import: No separate events file for %s (using trace-only)", trace_path)
        return df, [], [], None, [], [], extras
    else:
        log.info(
            "Import: Loaded inline events table %s with %d rows (columns=%s)",
            event_source_label or "(embedded)",
            len(events_df.index),
            list(events_df.columns),
        )

    labels: list[str] = []
    times: list[float] = []
    raw_frames: list[int | None] | None = None
    diam: list[float] = []
    od_diam: list[float] = []

    trace_time = df["Time (s)"].to_numpy(dtype=float)
    frame_number_to_trace_idx: dict[int, int] = {}
    if "FrameNumber" in df.columns:
        frame_numbers = pd.to_numeric(df["FrameNumber"], errors="coerce")
        frame_number_to_trace_idx = {
            int(fn): int(i)
            for i, fn in enumerate(frame_numbers.to_numpy())
            if pd.notna(fn)
        }
        log.info(
            "Import: Prepared %d frame→trace index mappings from trace CSV",
            len(frame_number_to_trace_idx),
        )

    def _coerce_time_values(series: pd.Series) -> pd.Series:
        """Return ``series`` converted to seconds where possible."""

        numeric = pd.to_numeric(series, errors="coerce")
        mask = numeric.isna()
        if mask.any():
            td = pd.to_timedelta(series.loc[mask], errors="coerce")
            numeric.loc[mask] = td.dt.total_seconds()
        return numeric.astype(float)

    def _map_frames_to_trace_time(frame_series: pd.Series) -> pd.Series:
        """Legacy: approximate mapping from frame order onto trace time."""

        numeric = pd.to_numeric(frame_series, errors="coerce")
        result = pd.Series(np.nan, index=frame_series.index, dtype=float)
        valid_mask = numeric.notna()
        if not valid_mask.any():
            return result

        arr_t = df["Time (s)"].to_numpy(dtype=float)
        if arr_t.size == 0:
            return result

        values = numeric.loc[valid_mask].to_numpy(dtype=float)
        v_min = values.min()
        v_max = values.max()
        if v_max == v_min:
            idx = np.zeros_like(values, dtype=int)
        else:
            scaled = (values - v_min) / (v_max - v_min)
            idx = np.round(scaled * (len(arr_t) - 1)).astype(int)
        idx = np.clip(idx, 0, len(arr_t) - 1)

        mapped = arr_t[idx]
        result.loc[numeric.loc[valid_mask].index] = mapped
        return result

    def _nearest_trace_index(target: float) -> int:
        arr_t = df["Time (s)"].to_numpy(dtype=float)
        valid_mask = np.isfinite(arr_t)
        if not valid_mask.any():
            return 0
        indices = np.flatnonzero(valid_mask)
        arr_valid = arr_t[indices]
        pos = int(np.argmin(np.abs(arr_valid - target)))
        return int(indices[pos])

    working_df = events_df.copy()

    label_col = "EventLabel" if "EventLabel" in working_df.columns else working_df.columns[0]
    frame_col = "Frame" if "Frame" in working_df.columns else None
    time_col = None
    for candidate in ("Time", "Time (s)"):
        if candidate in working_df.columns:
            time_col = candidate
            break
    if time_col is None:
        for col in working_df.columns[1:]:
            if col.lower().startswith("time"):
                time_col = col
                break
    extras["time_source"] = time_col or "frame"

    frame_series = None
    if frame_col:
        frame_series = pd.to_numeric(working_df[frame_col], errors="coerce")

    time_series = (
        _coerce_time_values(working_df[time_col])
        if time_col
        else pd.Series(np.nan, index=working_df.index, dtype=float)
    )

    approx_frame_times = None
    if frame_series is not None and not frame_number_to_trace_idx:
        approx_frame_times = _map_frames_to_trace_time(frame_series)
        if approx_frame_times.notna().any():
            extras["frame_fallback_used"] = True
            extras["frame_fallback_rows"] = int(approx_frame_times.notna().sum())

    resolved_times = pd.Series(np.nan, index=working_df.index, dtype=float)
    if frame_series is not None and frame_number_to_trace_idx:
        mapped_idx: list[int | None] = []
        for val in frame_series.to_numpy():
            idx = None
            if pd.notna(val):
                idx = frame_number_to_trace_idx.get(int(round(float(val))))
            mapped_idx.append(idx)
        mapped_idx_series = pd.Series(mapped_idx, index=working_df.index, dtype="Int64")
        extras["frame_map_used"] = True
        extras["frame_map_rows"] = int(mapped_idx_series.notna().sum())
        extras["frame_map_missing"] = int(mapped_idx_series.isna().sum())
        if trace_time.size:
            mapped_times = []
            for idx_val in mapped_idx_series.tolist():
                if idx_val is None or idx_val < 0 or idx_val >= len(trace_time):
                    mapped_times.append(np.nan)
                else:
                    mapped_times.append(float(trace_time[idx_val]))
            resolved_times.loc[mapped_idx_series.notna()] = mapped_times
    else:
        resolved_times = resolved_times.combine_first(time_series)
        if approx_frame_times is not None:
            resolved_times = resolved_times.combine_first(approx_frame_times)

    working_df = working_df.assign(_time_seconds=resolved_times)
    valid_mask_series = working_df["_time_seconds"].notna()
    dropped_missing_time = int((~valid_mask_series).sum())
    if dropped_missing_time:
        extras["dropped_missing_time"] = dropped_missing_time
        working_df = working_df.loc[valid_mask_series].reset_index(drop=True)
        if frame_series is not None:
            frame_series = frame_series.loc[valid_mask_series].reset_index(drop=True)

    if working_df.empty:
        log.info("Events table became empty after dropping invalid times")
        return df, [], [], None, [], [], extras

    times_series = working_df["_time_seconds"].astype(float)

    arr_t = df["Time (s)"].to_numpy(dtype=float)
    if arr_t.size:
        finite_trace_mask = np.isfinite(arr_t)
        if finite_trace_mask.any():
            t_min = float(arr_t[finite_trace_mask].min())
            t_max = float(arr_t[finite_trace_mask].max())
            in_range_mask = (times_series >= t_min) & (times_series <= t_max)
            ignored_out_of_range = int((~in_range_mask).sum())
            if ignored_out_of_range:
                extras["ignored_out_of_range"] = ignored_out_of_range
                working_df = working_df.loc[in_range_mask].reset_index(drop=True)
                times_series = times_series.loc[in_range_mask].reset_index(drop=True)
                if frame_series is not None:
                    frame_series = frame_series.loc[in_range_mask].reset_index(drop=True)

    if working_df.empty:
        log.info("No events remain within trace time range")
        return df, [], [], None, [], [], extras

    labels = working_df[label_col].astype(str).tolist()
    times = times_series.astype(float).tolist()

    if frame_series is not None:
        raw_frames = [
            int(val) if pd.notna(val) else None
            for val in frame_series.round().astype("Int64").tolist()
        ]
    else:
        raw_frames = None

    arr_id = df["Inner Diameter"].to_numpy(dtype=float)
    if "DiamBefore" in working_df.columns:
        diam_series = pd.to_numeric(working_df["DiamBefore"], errors="coerce")
        diam = diam_series.astype(float).tolist()
    else:
        diam = []
        for tv in times:
            idx = _nearest_trace_index(tv)
            diam.append(float(arr_id[idx]))

    if "OuterDiamBefore" in working_df.columns:
        od_series = pd.to_numeric(working_df["OuterDiamBefore"], errors="coerce")
        od_diam = od_series.astype(float).tolist()
    elif "Outer Diameter" in df.columns:
        arr_od = df["Outer Diameter"].to_numpy(dtype=float)
        if arr_od.size == len(arr_id):
            for tv in times:
                idx = _nearest_trace_index(tv)
                od_diam.append(float(arr_od[idx]))

    resolved_frames = [_nearest_trace_index(tv) for tv in times]
    if raw_frames is None:
        frames = resolved_frames
    else:
        frames = [
            resolved_frames[idx] if frame is None else int(frame)
            for idx, frame in enumerate(raw_frames)
        ]

    set_p_col = None
    for candidate in ("Set Pressure (mmHg)", "Set P (mmHg)", "Pressure 2 (mmHg)"):
        if candidate in df.columns:
            set_p_col = candidate
            break
    if set_p_col is not None:
        col = df[set_p_col]
        log.info(
            "Import: Set-pressure snapshot (%s) non_null=%d of %d, head=%s",
            set_p_col,
            int(col.notna().sum()),
            len(col),
            col.head(5).tolist(),
        )
    else:
        log.info(
            "Import: No set-pressure-like column found in trace_df columns=%s", list(df.columns)
        )
    log.info(
        "Import: Prepared %d normalised events for %s (source=%s)",
        len(labels),
        trace_path,
        extras.get("event_file") or "trace-only",
    )
    return df, labels, times, frames, diam, od_diam, extras


__all__ = ["load_trace_and_events"]
