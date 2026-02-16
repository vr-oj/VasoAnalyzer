# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import csv
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from vasoanalyzer.services.cache_service import DataCache
except ImportError:  # pragma: no cover - optional during bootstrap
    DataCache = None

from vasoanalyzer.core.timebase import (
    RANGE_TOL_S,
    TIME_EPS_S,
    derive_tiff_page_times,
    validate_and_normalize_events,
)
from vasoanalyzer.io.events import _standardize_headers, find_matching_event_file
from vasoanalyzer.io.traces import load_trace, merge_traces


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
    trace_path: str | Sequence[str],
    events_path: str | Sequence[str] | pd.DataFrame | None = None,
    *,
    cache: Any | None = None,
):
    """Load a trace CSV and its matching event table.

    Parameters
    ----------
    trace_path:
        Path to the trace CSV file, or an ordered list of CSVs to merge.
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
    multi_paths: list[str] | None = None
    if isinstance(trace_path, Sequence) and not isinstance(trace_path, (str, os.PathLike)):
        multi_paths = [str(p) for p in trace_path]
        if not multi_paths:
            raise ValueError("trace_path must include at least one file")
        df = merge_traces(multi_paths, cache=cache)
        log.info(
            "Import: Merged %d trace CSVs into %d rows; columns=%s",
            len(df.attrs.get("merged_from_paths", multi_paths)),
            len(df.index),
            list(df.columns),
        )
        primary_trace_path = df.attrs.get("merged_from_paths", multi_paths)[0]
    else:
        primary_trace_path = str(trace_path)
        df = load_trace(primary_trace_path, cache=cache)
        log.info(
            "Import: Loaded trace CSV %s with %d rows and columns=%s",
            primary_trace_path,
            len(df.index),
            list(df.columns),
        )

    from datetime import datetime, timezone
    from pathlib import Path

    extras: dict[str, object] = {
        "event_file": None,
        "auto_detected": False,
        "frame_fallback_used": False,
        "frame_fallback_rows": 0,
        "dropped_missing_time": 0,
        "ignored_out_of_range": 0,
        "time_source": None,
        # Provenance metadata
        "import_timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_original_filename": Path(primary_trace_path).name,
        "trace_original_directory": str(Path(primary_trace_path).parent),
        "canonical_time_source": df.attrs.get("canonical_time_source", "Time (s)"),
        "schema_version": 3,
    }
    if multi_paths:
        extras["trace_original_filenames"] = [Path(p).name for p in multi_paths]
        extras["merged_traces"] = multi_paths
        extras["merged_segments"] = df.attrs.get("merged_segments", [])
        extras["merge_warnings"] = df.attrs.get("merge_warnings", [])
        extras["merged_skipped_paths"] = df.attrs.get("merged_skipped_paths", [])
        extras["merged_from_paths"] = df.attrs.get("merged_from_paths", multi_paths)
        extras["merged_requested_paths"] = df.attrs.get("merged_requested_paths", multi_paths)

    # Segment map for merge-aware offsets
    segment_map: dict[str, dict[str, object]] = {}
    for seg in df.attrs.get("merged_segments", []) or []:
        path = seg.get("path")
        if path:
            segment_map[str(path)] = seg

    events_df: pd.DataFrame | None = None
    ev_path: str | None = None

    event_source_label: str | None = None
    event_merge_warnings: list[str] = []
    event_skipped: list[dict[str, str]] = []
    event_files: list[str] = []
    # Tuples of (event_path, originating_trace_path|None)
    candidate_event_paths: list[tuple[str, str | None]] = []

    if isinstance(events_path, pd.DataFrame):
        events_df = _standardize_headers(events_path.copy())
        event_source_label = "<DataFrame>"
    elif isinstance(events_path, Sequence) and not isinstance(events_path, (str, os.PathLike)):
        user_paths = [str(p) for p in events_path]
        if multi_paths and len(user_paths) == len(multi_paths):
            candidate_event_paths = list(zip(user_paths, multi_paths, strict=False))
        else:
            candidate_event_paths = [(p, None) for p in user_paths]
    else:
        ev_path = events_path
        if ev_path:
            candidate_event_paths = [(str(ev_path), None)]

    if events_df is None and not candidate_event_paths:
        # Auto-discover per trace segment (merge-aware)
        if multi_paths:
            for path in multi_paths:
                match = find_matching_event_file(path)
                if match:
                    candidate_event_paths.append((match, path))
            if candidate_event_paths:
                extras["auto_detected"] = True
        else:
            ev_path = find_matching_event_file(primary_trace_path)
            if ev_path:
                candidate_event_paths.append((ev_path, primary_trace_path))
                extras["auto_detected"] = True

    if candidate_event_paths:
        event_frames: list[pd.DataFrame] = []
        for ev, trace_origin in candidate_event_paths:
            if not os.path.exists(ev):
                msg = f"Events file not found: {os.path.basename(ev)}"
                event_merge_warnings.append(msg)
                event_skipped.append({"path": ev, "reason": "missing file"})
                log.warning(msg)
                continue
            try:
                frame = _read_event_dataframe(ev, cache=cache)
            except Exception as exc:
                msg = f"Skipped events {os.path.basename(ev)}: {exc}"
                event_merge_warnings.append(msg)
                event_skipped.append({"path": ev, "reason": str(exc)})
                log.warning(msg, exc_info=True)
                continue

            seg = (
                segment_map.get(trace_origin or "")
                or segment_map.get(ev)
                or segment_map.get((trace_origin or "").replace("\\", "/"))
            )
            time_offset = float(seg.get("applied_time_offset", 0.0)) if seg else 0.0
            frame_offset = int(seg.get("applied_frame_offset", 0)) if seg else 0
            if "Frame" in frame.columns:
                frame["Frame"] = pd.to_numeric(frame["Frame"], errors="coerce") + frame_offset
            frame["__time_offset_seconds"] = time_offset
            frame["__event_source"] = ev
            event_frames.append(frame)
            event_files.append(ev)

        if event_frames:
            events_df = pd.concat(event_frames, ignore_index=True, sort=False)
            event_source_label = ", ".join(os.path.basename(p) for p in event_files)
            ev_path = event_files[0]

    if events_df is None:
        log.info("Import: No separate events file for %s (using trace-only)", primary_trace_path)
        return df, [], [], None, [], [], extras

    if event_files and not ev_path:
        ev_path = event_files[0]

    extras["event_file"] = ev_path if isinstance(ev_path, str) else None
    extras["event_files"] = event_files or ([ev_path] if ev_path else [])
    extras["events_original_filename"] = Path(ev_path).name if isinstance(ev_path, str) else None
    extras["event_merge_warnings"] = event_merge_warnings
    extras["event_skipped_paths"] = event_skipped

    log.info(
        "Import: Loaded events table %s with %d rows (columns=%s)",
        event_source_label or "(embedded)",
        len(events_df.index),
        list(events_df.columns),
    )

    labels: list[str] = []
    times: list[float] = []
    raw_frames: list[int | None] | None = None
    diam: list[float] = []
    od_diam: list[float] = []

    # trace["Time (s)"] is the canonical experiment clock (sourced from Time_s_exact
    # if available, else Time (s) for legacy files). All other time views
    # (event CSV strings, TIFF metadata) map back onto this column.
    trace_time = df["Time (s)"].to_numpy(dtype=float)
    frame_number_to_trace_idx: dict[int, int] = {}
    tiff_page_to_trace_idx: dict[int, int] = {}
    if "FrameNumber" in df.columns:
        # FrameNumber values in the trace CSV align with the events CSV "Frame" column.
        frame_numbers = pd.to_numeric(df["FrameNumber"], errors="coerce")
        frame_number_to_trace_idx = {
            int(fn): int(i) for i, fn in enumerate(frame_numbers.to_numpy()) if pd.notna(fn)
        }
        log.info(
            "Import: Prepared %d frame→trace index mappings from trace CSV",
            len(frame_number_to_trace_idx),
        )
    if "TiffPage" in df.columns:
        # TiffPage values come from the VasoTracker TIFF stack (0-based frame indices).
        tiff_pages = pd.to_numeric(df["TiffPage"], errors="coerce")
        if "Saved" in df.columns:
            saved_mask = pd.to_numeric(df["Saved"], errors="coerce").fillna(0) > 0
            tiff_pages = tiff_pages.where(saved_mask)
        tiff_page_to_trace_idx = {
            int(tp): int(i) for i, tp in enumerate(tiff_pages.to_numpy()) if pd.notna(tp)
        }
        log.info(
            "Import: Prepared %d TIFF-page→trace index mappings from trace CSV",
            len(tiff_page_to_trace_idx),
        )

    extras["frame_number_to_trace_idx"] = frame_number_to_trace_idx
    extras["tiff_page_to_trace_idx"] = tiff_page_to_trace_idx
    df.attrs["frame_number_to_trace_idx"] = frame_number_to_trace_idx
    df.attrs["tiff_page_to_trace_idx"] = tiff_page_to_trace_idx

    tiff_result = derive_tiff_page_times(df)
    extras["tiff_page_times"] = tiff_result.tiff_page_times
    extras["tiff_page_times_valid"] = tiff_result.valid
    extras["tiff_page_times_warnings"] = tiff_result.warnings
    extras["snapshot_interval_median_s"] = tiff_result.median_interval_s
    df.attrs["tiff_page_times"] = tiff_result.tiff_page_times
    df.attrs["tiff_page_times_valid"] = tiff_result.valid

    def _coerce_time_values(series: pd.Series, *, offsets: pd.Series | None = None) -> pd.Series:
        """Return ``series`` converted to seconds where possible."""

        numeric = pd.to_numeric(series, errors="coerce")
        mask = numeric.isna()
        if mask.any():
            td = pd.to_timedelta(series.loc[mask], errors="coerce")
            numeric.loc[mask] = td.dt.total_seconds()
        if offsets is not None:
            try:
                offsets_series = pd.to_numeric(offsets, errors="coerce").fillna(0.0)
                numeric = numeric.add(offsets_series, fill_value=0.0)
            except Exception:
                pass
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
        _coerce_time_values(
            working_df[time_col],
            offsets=working_df.get("__time_offset_seconds"),
        )
        if time_col
        else pd.Series(np.nan, index=working_df.index, dtype=float)
    )
    trace_t0_s = None
    if isinstance(df.attrs, dict):
        trace_t0_s = df.attrs.get("timebase", {}).get("trace", {}).get("t0_s")
    if trace_t0_s is not None and time_col:
        try:
            trace_t0_s = float(trace_t0_s)
        except (TypeError, ValueError):
            trace_t0_s = None
    if trace_t0_s is not None and abs(trace_t0_s) > TIME_EPS_S:
        time_series = time_series - float(trace_t0_s)

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
    try:
        working_df, report = validate_and_normalize_events(
            working_df,
            trace_time,
            range_tol_s=RANGE_TOL_S,
            eps_s=TIME_EPS_S,
            time_col=time_col,
        )
    except ValueError as exc:
        log.warning("Event time validation failed: %s", exc)
        return df, [], [], None, [], [], extras

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

    extras["ignored_out_of_range"] = 0
    extras["flagged_out_of_range"] = int(report.out_of_range)
    extras["clamped_out_of_range"] = int(report.clamped)
    extras["event_time_invalid"] = int(report.invalid)

    timebase_meta = df.attrs.get("timebase") if isinstance(df.attrs, dict) else None
    if not isinstance(timebase_meta, dict):
        timebase_meta = {}
    event_warnings = list(report.warnings)
    if trace_t0_s is not None and abs(float(trace_t0_s)) > TIME_EPS_S:
        event_warnings.append(
            f"Applied trace t0 offset of {float(trace_t0_s):.6f}s to event times."
        )
    timebase_meta["events"] = {
        "range_tol_s": float(RANGE_TOL_S),
        "eps_s": float(TIME_EPS_S),
        "total": int(report.total),
        "valid": int(report.valid),
        "invalid": int(report.invalid),
        "clamped": int(report.clamped),
        "out_of_range": int(report.out_of_range),
        "trace_t0_s": float(trace_t0_s) if trace_t0_s is not None else None,
        "warnings": event_warnings,
    }
    extras["timebase"] = timebase_meta

    times_series = working_df["_time_seconds"].astype(float)

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
        primary_trace_path,
        extras.get("event_file") or "trace-only",
    )
    return df, labels, times, frames, diam, od_diam, extras


__all__ = ["load_trace_and_events"]
