# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Page-to-time mapping helpers for the TIFF viewer v2."""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from vasoanalyzer.core.timebase import page_for_time

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageTimeMap:
    """Validated page time mapping with status messaging."""

    page_times: tuple[float, ...]
    valid: bool
    status: str

    @classmethod
    def invalid(cls, reason: str) -> PageTimeMap:
        return cls(tuple(), False, reason)

    @classmethod
    def from_times(cls, times: Iterable[float]) -> PageTimeMap:
        page_times = tuple(float(v) for v in times)
        if not page_times:
            return cls.invalid("Sync unavailable: no mapped pages")
        for idx, value in enumerate(page_times):
            if not math.isfinite(value):
                return cls.invalid("Sync unavailable: non-finite times")
            if idx > 0 and value < page_times[idx - 1]:
                return cls.invalid("Sync unavailable: non-monotonic times")
            if idx > 0 and value == page_times[idx - 1]:
                log.warning("TIFF page times are not strictly increasing.")
        return cls(page_times, True, f"Sync available ({len(page_times)} pages mapped)")

    @property
    def page_count(self) -> int:
        return len(self.page_times)

    def time_for_page(self, page_index: int) -> float | None:
        if not self.valid:
            return None
        try:
            idx = int(page_index)
        except (TypeError, ValueError):
            return None
        if idx < 0 or idx >= len(self.page_times):
            return None
        value = float(self.page_times[idx])
        if not math.isfinite(value):
            return None
        return value

    def page_for_time(self, t_seconds: float) -> int | None:
        if not self.valid:
            return None
        return page_for_time(t_seconds, self.page_times, mode="nearest")


def _normalize_column_name(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


def _column_map(df) -> dict[str, str]:
    return {_normalize_column_name(col): col for col in df.columns}


def _find_column(df, candidates: Sequence[str]) -> str | None:
    col_map = _column_map(df)
    for candidate in candidates:
        key = _normalize_column_name(candidate)
        if key in col_map:
            return col_map[key]
    return None


def _sync_debug_enabled() -> bool:
    value = os.environ.get("VA_SNAPSHOT_VIEWER_V2_SYNC_DEBUG", "").strip().lower()
    if not value:
        return False
    return value not in {"0", "false", "no", "off"}


def resolve_time_column(df) -> tuple[str | None, object | None, str | None]:
    """Return (column_name, values, error_reason)."""

    time_candidates = ("Time_s_exact", "Time (s)", "Time (hh:mm:ss)")
    time_col = _find_column(df, time_candidates)
    if time_col is None:
        return (
            None,
            None,
            "Sync unavailable: missing time column (Time_s_exact / Time (s) / Time (hh:mm:ss))",
        )

    normalized = _normalize_column_name(time_col)
    import pandas as pd  # type: ignore

    if normalized == _normalize_column_name("Time (hh:mm:ss)"):
        values = pd.to_timedelta(df[time_col], errors="coerce").dt.total_seconds()
    else:
        values = pd.to_numeric(df[time_col], errors="coerce")
    return time_col, values, None


def resolve_saved_rows(df, *, tiff_col: str) -> object:
    """Return a boolean mask for saved rows based on Saved/TiffPage."""

    import pandas as pd  # type: ignore

    tiff_pages = pd.to_numeric(df[tiff_col], errors="coerce")
    saved_col = _find_column(df, ("Saved",))
    if saved_col is not None:
        saved_series = pd.to_numeric(df[saved_col], errors="coerce").fillna(0)
        saved_mask = saved_series > 0
        if saved_mask.any():
            return saved_mask & tiff_pages.notna()
    return tiff_pages.notna()


def derive_page_time_map_from_trace(
    trace_df, *, expected_page_count: int | None = None
) -> PageTimeMap:
    """Derive a page time map from a VasoTracker trace DataFrame."""

    if trace_df is None:
        return PageTimeMap.invalid("Sync unavailable: missing trace data")

    try:
        import pandas as pd  # type: ignore
    except Exception:
        return PageTimeMap.invalid("Sync unavailable: pandas not available")

    tiff_col = _find_column(trace_df, ("TiffPage", "tiff_page"))
    if tiff_col is None:
        return PageTimeMap.invalid("Sync unavailable: missing TiffPage column")

    time_col, time_values, time_error = resolve_time_column(trace_df)
    if time_error:
        return PageTimeMap.invalid(time_error)

    df = trace_df.copy()
    mask = resolve_saved_rows(df, tiff_col=tiff_col)
    df = df.loc[mask].copy()
    if df.empty:
        return PageTimeMap.invalid("Sync unavailable: no TiffPage mappings")

    df[tiff_col] = pd.to_numeric(df[tiff_col], errors="coerce")
    df = df.dropna(subset=[tiff_col])
    df["_v2_time"] = pd.to_numeric(time_values, errors="coerce")
    df = df.dropna(subset=["_v2_time"])
    if df.empty:
        return PageTimeMap.invalid("Sync unavailable: no valid TiffPage/time pairs")

    df = df.sort_values("_v2_time")
    duplicates = df[tiff_col].duplicated(keep="first")
    if duplicates.any():
        dup_pages = sorted(df.loc[duplicates, tiff_col].astype(int).unique().tolist())
        log.warning(
            "Duplicate TiffPage values found; keeping earliest time for pages: %s",
            dup_pages,
        )
    df = df.drop_duplicates(subset=[tiff_col], keep="first")

    df[tiff_col] = df[tiff_col].astype(int)
    df = df.sort_values(tiff_col)

    pages: list[int] = df[tiff_col].tolist()
    times: list[float] = df["_v2_time"].astype(float).tolist()

    if not pages:
        return PageTimeMap.invalid("Sync unavailable: no mapped pages")

    expected_size = (
        int(expected_page_count)
        if expected_page_count is not None and expected_page_count > 0
        else pages[-1] + 1
    )
    expected = list(range(expected_size))
    if pages != expected:
        missing_pages = sorted(set(expected) - set(pages))
        if missing_pages:
            log.warning("Missing TIFF pages in trace mapping: %s", missing_pages)
        return PageTimeMap.invalid("Sync unavailable: TiffPage coverage mismatch (expected 0..N-1)")

    for idx in range(1, len(times)):
        if not math.isfinite(times[idx]):
            return PageTimeMap.invalid("Sync unavailable: non-finite times")
        if times[idx] < times[idx - 1]:
            return PageTimeMap.invalid("Sync unavailable: non-monotonic times")
        if times[idx] == times[idx - 1]:
            log.warning("TIFF page times are not strictly increasing.")

    if _sync_debug_enabled():
        log.info(
            "V2 sync: time_col=%s mapped_pages=%d first_time=%.3f last_time=%.3f",
            time_col,
            len(times),
            times[0],
            times[-1],
        )

    return PageTimeMap.from_times(times)


__all__ = ["PageTimeMap", "derive_page_time_map_from_trace"]
