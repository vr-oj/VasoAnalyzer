# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Helper routines for loading diameter trace CSV files."""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

try:
    from vasoanalyzer.services.cache_service import DataCache
except ImportError:  # pragma: no cover - optional during bootstrap
    DataCache = None

log = logging.getLogger(__name__)


def load_trace(file_path, *, cache: Any | None = None):
    """Load a trace CSV and return a standardized DataFrame.

    Args:
        file_path (str or Path): Path to the CSV file.

    Returns:
        pandas.DataFrame: Data with ``"Time (s)"`` and ``"Inner Diameter"``
        columns converted to numeric types. Files with multiple header rows
        are supported.

    Raises:
        ValueError: If no time or inner diameter column can be found.
        pandas.errors.ParserError: If the CSV cannot be parsed.
    """

    log.debug("Loading trace from %s", file_path)

    # Auto-detect delimiter using the CSV sniffer
    with open(file_path, encoding="utf-8-sig") as f:
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

    def _load_csv(path):
        return pd.read_csv(path, delimiter=delimiter, encoding="utf-8-sig", header=0)

    if cache is not None and DataCache is not None:
        df = cache.read_dataframe(
            file_path,
            loader=_load_csv,
        )
    else:
        df = _load_csv(file_path)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(part) for part in col if pd.notna(part)) for col in df.columns]

    # Drop any entirely empty columns that may appear due to malformed files
    df = df.dropna(axis=1, how="all")

    if len(df) > 1:
        numeric_preview = df.apply(pd.to_numeric, errors="coerce")
        header_row = df.iloc[0]
        textual_mask = header_row.apply(lambda v: isinstance(v, str) and v.strip() != "")
        if numeric_preview.iloc[0].isna().all() and numeric_preview.iloc[1:].notna().any().any():
            if textual_mask.any():
                new_columns = []
                for col, extra, is_textual in zip(
                    df.columns, header_row, textual_mask, strict=False
                ):
                    if is_textual:
                        combined = f"{col} {extra}".strip()
                        new_columns.append(combined)
                    else:
                        new_columns.append(col)
                df = df.iloc[1:].reset_index(drop=True)
                df.columns = new_columns
            else:
                df = df.iloc[1:].reset_index(drop=True)

    def _normalize(col):
        return re.sub(r"[^a-z0-9]", "", col.lower())

    # Locate time and diameter columns using flexible matching for legacy files
    # VasoTracker files have Time_s_exact (high precision) - prioritize it!
    time_s_exact_col = None
    time_s_col = None
    time_col = None  # Generic fallback
    diam_col = None
    outer_col = None
    avg_pressure_col = None
    set_pressure_col = None
    inner_candidates = []
    diam_candidates = []
    outer_candidates = []
    avg_pressure_candidates = []
    set_pressure_candidates: list[str] = []

    for c in df.columns:
        norm = _normalize(c)

        # Priority 1: Look for Time_s_exact (VasoTracker high-precision time)
        if norm == "timesexact":
            time_s_exact_col = c
        # Priority 2: Look for Time (s) or similar
        elif norm in ("times", "timeseconds") or c == "Time (s)":
            time_s_col = c
        # Priority 3: Generic time column
        elif time_col is None and ("time" in norm or "sec" in norm or norm in {"t", "ts"}):
            time_col = c

        if "inner" in norm and "diam" in norm:
            inner_candidates.append(c)
        elif ("outer" in norm and "diam" in norm) or norm.startswith("od"):
            outer_candidates.append(c)
        elif "diam" in norm or norm in {"id", "diameter"}:
            diam_candidates.append(c)

        # Detect pressure columns
        if "avg" in norm and "pressure" in norm:
            avg_pressure_candidates.append(c)
        elif "set" in norm and "pressure" in norm:
            if c in ("Set Pressure (mmHg)", "Set P (mmHg)"):
                set_pressure_candidates.insert(0, c)
            else:
                set_pressure_candidates.append(c)

    if inner_candidates:
        diam_col = inner_candidates[0]
    elif diam_candidates:
        diam_col = diam_candidates[0]

    if outer_candidates:
        outer_col = outer_candidates[0]

    if avg_pressure_candidates:
        avg_pressure_col = avg_pressure_candidates[0]

    if set_pressure_candidates:
        set_pressure_col = set_pressure_candidates[0]

    # Use Time_s_exact if available (VasoTracker), fall back to Time (s), then generic
    canonical_time_col = time_s_exact_col or time_s_col or time_col

    if canonical_time_col is None or diam_col is None or canonical_time_col == diam_col:
        raise ValueError("Trace file must contain Time and Inner Diameter columns")

    # Log warning for legacy files missing Time_s_exact
    if time_s_exact_col:
        log.info(f"Using high-precision time column '{time_s_exact_col}' as canonical")
    elif time_s_col or time_col:
        log.warning(
            f"Using legacy time column '{canonical_time_col}' (Time_s_exact not found). "
            "Sub-millisecond precision may be lost."
        )

    # If using Time_s_exact, drop the old "Time (s)" column to avoid conflict
    if time_s_exact_col and "Time (s)" in df.columns and time_s_exact_col != "Time (s)":
        df = df.drop(columns=["Time (s)"])
        log.info("Dropped rounded 'Time (s)' column in favor of high-precision 'Time_s_exact'")

    # Rename to standardized column names (canonical_time_col → "Time (s)")
    rename_map = {canonical_time_col: "Time (s)", diam_col: "Inner Diameter"}
    if outer_col:
        rename_map[outer_col] = "Outer Diameter"
    if avg_pressure_col:
        rename_map[avg_pressure_col] = "Avg Pressure (mmHg)"
    if set_pressure_col:
        rename_map[set_pressure_col] = "Set Pressure (mmHg)"
    df = df.rename(columns=rename_map)
    df = df.loc[:, ~df.columns.duplicated()]

    # Store provenance: which column was used as canonical time
    df.attrs["canonical_time_source"] = canonical_time_col

    # Ensure numeric types
    df["Time (s)"] = pd.to_numeric(df["Time (s)"], errors="coerce")
    df["Inner Diameter"] = pd.to_numeric(df["Inner Diameter"], errors="coerce")
    if "Outer Diameter" in df.columns:
        df["Outer Diameter"] = pd.to_numeric(df["Outer Diameter"], errors="coerce")
    if "Avg Pressure (mmHg)" in df.columns:
        df["Avg Pressure (mmHg)"] = pd.to_numeric(df["Avg Pressure (mmHg)"], errors="coerce")
    if "Set Pressure (mmHg)" in df.columns:
        df["Set Pressure (mmHg)"] = pd.to_numeric(df["Set Pressure (mmHg)"], errors="coerce")

    neg_inner = int((df["Inner Diameter"] < 0).sum())
    if neg_inner:
        df.loc[df["Inner Diameter"] < 0, "Inner Diameter"] = np.nan
        log.warning("Replaced %d negative inner diameter values with NaN", neg_inner)
    df.attrs["negative_inner_diameters"] = neg_inner

    if "Outer Diameter" in df.columns:
        neg_outer = int((df["Outer Diameter"] < 0).sum())
        if neg_outer:
            df.loc[df["Outer Diameter"] < 0, "Outer Diameter"] = np.nan
            log.warning("Replaced %d negative outer diameter values with NaN", neg_outer)
        df.attrs["negative_outer_diameters"] = neg_outer
    else:
        df.attrs["negative_outer_diameters"] = 0

    # Pressure values can be negative (e.g., vacuum), so we don't filter them out
    # Just log if pressure columns were found
    if "Avg Pressure (mmHg)" in df.columns:
        log.debug(
            "Loaded Avg Pressure column with %d valid values",
            df["Avg Pressure (mmHg)"].notna().sum(),
        )
    if "Set Pressure (mmHg)" in df.columns:
        log.debug(
            "Loaded Set Pressure column with %d valid values",
            df["Set Pressure (mmHg)"].notna().sum(),
        )

    log.debug("Loaded trace with %d rows", len(df))
    return df


def merge_traces(
    trace_paths: Sequence[str],
    *,
    cache: Any | None = None,
) -> pd.DataFrame:
    """Merge multiple trace CSVs into one continuous dataset.

    Files are appended in the provided order with time, frame, and TIFF indices
    offset so they remain strictly increasing across segments.

    Args:
        trace_paths: Ordered collection of CSV paths to merge.
        cache: Optional cache for faster repeated reads.

    Returns:
        Merged trace dataframe with provenance stored in ``attrs``:
        ``merged_from_paths`` and ``merged_segments`` (per-segment offsets).
    """

    if not trace_paths:
        raise ValueError("trace_paths must contain at least one file")

    normalized_paths = [str(p) for p in trace_paths]
    merged_frames: list[pd.DataFrame] = []
    merged_paths: list[str] = []
    segments: list[dict[str, object]] = []
    merge_warnings: list[str] = []
    skipped: list[dict[str, str]] = []

    time_offset = 0.0
    frame_offset: float | None = None
    tiff_offset: float | None = None
    canonical_source: str | None = None
    total_neg_inner = 0
    total_neg_outer = 0

    def _estimate_dt(values: pd.Series | np.ndarray) -> float:
        arr = pd.to_numeric(values, errors="coerce")
        diffs = np.diff(arr[np.isfinite(arr)])
        diffs = diffs[diffs > 0]
        if diffs.size:
            return float(np.nanmedian(diffs))
        return 0.0

    for idx, path in enumerate(normalized_paths):
        try:
            df = load_trace(path, cache=cache).copy()
        except Exception as exc:  # Skip malformed files but record why
            msg = f"Skipped {os.path.basename(path)}: {exc}"
            log.warning(msg, exc_info=True)
            merge_warnings.append(msg)
            skipped.append({"path": path, "reason": str(exc)})
            continue

        merged_paths.append(path)

        if canonical_source is None:
            canonical_source = df.attrs.get("canonical_time_source", "Time (s)")

        time_values = pd.to_numeric(df["Time (s)"], errors="coerce")
        dt = _estimate_dt(time_values)
        t_start = float(np.nanmin(time_values)) if np.isfinite(np.nanmin(time_values)) else 0.0
        shift = 0.0
        if idx > 0:
            shift = time_offset - t_start
            if dt > 0:
                shift += dt
            df["Time (s)"] = time_values + shift

        frame_shift = 0
        if "FrameNumber" in df.columns:
            frame_vals = pd.to_numeric(df["FrameNumber"], errors="coerce")
            f_start = float(np.nanmin(frame_vals)) if np.isfinite(np.nanmin(frame_vals)) else 0.0
            if idx > 0 and frame_offset is not None and np.isfinite(frame_offset):
                frame_shift = int(frame_offset - f_start + 1)
            df["FrameNumber"] = frame_vals + frame_shift
            frame_offset_candidate = float(np.nanmax(df["FrameNumber"])) if np.isfinite(
                np.nanmax(df["FrameNumber"])
            ) else None
            if frame_offset_candidate is not None and np.isfinite(frame_offset_candidate):
                frame_offset = frame_offset_candidate

        tiff_shift = 0
        if "TiffPage" in df.columns:
            tiff_vals = pd.to_numeric(df["TiffPage"], errors="coerce")
            tp_start = float(np.nanmin(tiff_vals)) if np.isfinite(np.nanmin(tiff_vals)) else 0.0
            if idx > 0 and tiff_offset is not None and np.isfinite(tiff_offset):
                tiff_shift = int(tiff_offset - tp_start + 1)
            df["TiffPage"] = tiff_vals + tiff_shift
            tiff_offset_candidate = float(np.nanmax(df["TiffPage"])) if np.isfinite(
                np.nanmax(df["TiffPage"])
            ) else None
            if tiff_offset_candidate is not None and np.isfinite(tiff_offset_candidate):
                tiff_offset = tiff_offset_candidate

        merged_frames.append(df)

        t_end = float(np.nanmax(df["Time (s)"])) if np.isfinite(np.nanmax(df["Time (s)"])) else time_offset
        time_offset = max(time_offset, t_end)

        total_neg_inner += int(df.attrs.get("negative_inner_diameters", 0) or 0)
        total_neg_outer += int(df.attrs.get("negative_outer_diameters", 0) or 0)

        segments.append(
            {
                "path": path,
                "rows": int(len(df.index)),
                "applied_time_offset": float(shift),
                "applied_frame_offset": int(frame_shift) if frame_shift else 0,
                "applied_tiff_offset": int(tiff_shift) if tiff_shift else 0,
                "t_start": float(t_start),
                "t_end": float(t_end),
                "dt_median": float(dt),
            }
        )

    if not merged_frames:
        raise ValueError("No valid trace files found to merge")

    merged_df = pd.concat(merged_frames, ignore_index=True, sort=False)
    merged_df.attrs["canonical_time_source"] = canonical_source or "Time (s)"
    merged_df.attrs["merged_requested_paths"] = normalized_paths
    merged_df.attrs["merged_from_paths"] = merged_paths
    merged_df.attrs["merged_segments"] = segments
    merged_df.attrs["negative_inner_diameters"] = total_neg_inner
    merged_df.attrs["negative_outer_diameters"] = total_neg_outer
    if merge_warnings:
        merged_df.attrs["merge_warnings"] = merge_warnings
    if skipped:
        merged_df.attrs["merged_skipped_paths"] = skipped
    return merged_df
