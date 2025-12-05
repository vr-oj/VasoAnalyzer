"""Trace persistence utilities for SQLite projects."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Sequence

import pandas as pd

log = logging.getLogger(__name__)

__all__ = [
    "normalize_label",
    "match_trace_columns",
    "nullable_float",
    "prepare_trace_rows",
    "fetch_trace_dataframe",
]


def normalize_label(label: str) -> str:
    """Normalize free-form column labels for fuzzy matching."""

    return "".join(ch for ch in str(label).lower() if ch.isalnum())


def match_trace_columns(columns: Sequence[str]) -> dict[str, str]:
    """
    Best-effort mapping from arbitrary column names to the canonical schema.
    """

    def _unitless(norm: str) -> str:
        """Helper that strips unit suffixes like ``mmhg`` for easier matching."""
        return norm.replace("mmhg", "")

    def _missing(target: str, current: dict[str, str]) -> bool:
        return target not in current.values()

    mapping: dict[str, str] = {}
    for col in columns:
        norm = normalize_label(col)
        unitless = _unitless(norm)

        # Priority 1: VasoTracker high-precision time column
        if norm == "timesexact" and _missing("t_seconds", mapping):
            mapping[col] = "t_seconds"
        # Priority 2: Standard time columns
        elif (
            unitless in {"times", "tseconds", "t", "time", "timestamp"}
            or unitless.startswith("time")
        ) and _missing("t_seconds", mapping):
            mapping[col] = "t_seconds"
        elif (
            ("inner" in unitless and "diam" in unitless)
            or unitless in {"innerdiameter", "innerdiam"}
        ) and _missing("inner_diam", mapping):
            mapping[col] = "inner_diam"
        elif (
            ("outer" in unitless and "diam" in unitless)
            or unitless in {"outerdiameter", "outerdiam"}
        ) and _missing("outer_diam", mapping):
            mapping[col] = "outer_diam"
        elif (
            ("avg" in unitless and "press" in unitless)
            or unitless in {"pressureavg", "avgpressure", "pavg"}
        ) and _missing("p_avg", mapping):
            mapping[col] = "p_avg"
        elif (
            ("press" in unitless and "1" in unitless) or unitless in {"pressure1", "p1"}
        ) and _missing("p1", mapping):
            mapping[col] = "p1"
        elif (
            (("set" in unitless and "press" in unitless) or unitless in {"setpressure", "setpress"})
            and _missing("p2", mapping)
        ) or (
            (("press" in unitless and "2" in unitless) or unitless in {"pressure2", "p2"})
            and _missing("p2", mapping)
        ):
            mapping[col] = "p2"
        # VasoTracker-specific columns
        elif norm == "framenumber" and _missing("frame_number", mapping):
            mapping[col] = "frame_number"
        elif norm == "tiffpage" and _missing("tiff_page", mapping):
            mapping[col] = "tiff_page"
        elif (
            norm in {"temperature", "temperaturec", "temp"} or ("temp" in norm and "c" in norm)
        ) and _missing("temp", mapping):
            mapping[col] = "temp"
        elif norm in {"tablemarker", "marker"} and _missing("table_marker", mapping):
            mapping[col] = "table_marker"
        elif (
            norm in {"caliper", "caliperlength"} or ("caliper" in norm and "length" in norm)
        ) and _missing("caliper_length", mapping):
            mapping[col] = "caliper_length"
    if mapping:
        log.debug("TRACE COLUMN MAP: %s", mapping)
        return mapping

    defaults: dict[str, str] = {}
    for col in columns:
        lower = col.lower()
        if lower.startswith("time") and "t_seconds" not in defaults.values():
            defaults[col] = "t_seconds"
        elif "inner" in lower and "diam" in lower and "inner_diam" not in defaults.values():
            defaults[col] = "inner_diam"
        elif "outer" in lower and "diam" in lower and "outer_diam" not in defaults.values():
            defaults[col] = "outer_diam"
    if defaults:
        log.debug("TRACE COLUMN MAP (defaults): %s", defaults)
    return defaults


def nullable_float(value) -> float | None:
    """Return a float or ``None`` while tolerating NaN-like values."""

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        # Non-numeric values fall back to conversion attempt below.
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def prepare_trace_rows(dataset_id: int, df: pd.DataFrame | None) -> Iterable[tuple]:
    """Normalize ``df`` into rows suitable for the trace table."""

    if df is None or df.empty:
        log.debug("prepare_trace_rows: empty DataFrame for dataset %s", dataset_id)
        return []

    df_local = df.copy()
    rename_map = match_trace_columns(df_local.columns)
    if rename_map:
        df_local = df_local.rename(columns=rename_map)

    if "t_seconds" not in df_local.columns:
        raise ValueError("Trace DataFrame must contain a time column")

    df_local["t_seconds"] = pd.to_numeric(df_local["t_seconds"], errors="coerce")
    for col in ("inner_diam", "outer_diam", "p_avg", "p1", "p2"):
        if col in df_local.columns:
            df_local[col] = pd.to_numeric(df_local[col], errors="coerce")
            if col in ("inner_diam", "outer_diam"):
                df_local.loc[df_local[col] < 0, col] = pd.NA

    df_local = df_local.dropna(subset=["t_seconds"])

    set_pressure_source = None
    for candidate in ("Set Pressure (mmHg)", "Set P (mmHg)"):
        if candidate in df.columns:
            set_pressure_source = pd.to_numeric(df[candidate], errors="coerce")
            source_label = candidate
            break
    if set_pressure_source is None and "Pressure 2 (mmHg)" in df.columns:
        set_pressure_source = pd.to_numeric(df["Pressure 2 (mmHg)"], errors="coerce")
        source_label = "Pressure 2 (mmHg)"
        log.info(
            "prepare_trace_rows: falling back to '%s' for dataset_id=%s",
            source_label,
            dataset_id,
        )
    if set_pressure_source is not None:
        current = df_local.get("p2")
        current_non_null = int(current.notna().sum()) if isinstance(current, pd.Series) else 0
        source_non_null = int(set_pressure_source.notna().sum())
        if current is None or source_non_null > current_non_null:
            df_local["p2"] = set_pressure_source
            log.info(
                "prepare_trace_rows: injected dense set-pressure from '%s' (non_null=%d of %d) for dataset_id=%s",
                source_label,
                source_non_null,
                len(set_pressure_source),
                dataset_id,
            )

    rows = []
    for _, row in df_local.iterrows():
        rows.append(
            (
                dataset_id,
                float(row.get("t_seconds")),
                nullable_float(row.get("inner_diam")),
                nullable_float(row.get("outer_diam")),
                nullable_float(row.get("p_avg")),
                nullable_float(row.get("p1")),
                nullable_float(row.get("p2")),
            )
        )
    log.debug(
        "prepare_trace_rows: dataset=%s rows=%s columns=%s",
        dataset_id,
        len(rows),
        list(df_local.columns),
    )
    if "p2" in df_local.columns:
        p2_series = df_local["p2"]
        log.info(
            "Embed: canonical p2 for dataset_id=%s -> non_null=%d of %d, head=%s",
            dataset_id,
            int(p2_series.notna().sum()),
            len(p2_series),
            p2_series.head(5).tolist(),
        )
    else:
        log.info(
            "Embed: no canonical p2 column for dataset_id=%s; available=%s",
            dataset_id,
            list(df_local.columns),
        )
    return rows


def fetch_trace_dataframe(
    conn: sqlite3.Connection,
    dataset_id: int,
    t0: float | None = None,
    t1: float | None = None,
) -> pd.DataFrame:
    """
    Load trace samples for ``dataset_id`` optionally filtered to ``[t0, t1]``.
    """

    query = [
        "SELECT t_seconds, inner_diam, outer_diam, p_avg, p1, p2",
        "FROM trace",
        "WHERE dataset_id = ?",
    ]
    params: list[object] = [dataset_id]
    if t0 is not None:
        query.append("AND t_seconds >= ?")
        params.append(float(t0))
    if t1 is not None:
        query.append("AND t_seconds <= ?")
        params.append(float(t1))
    query.append("ORDER BY t_seconds ASC")
    df = pd.read_sql_query(" ".join(query), conn, params=params)
    log.debug(
        "fetch_trace_dataframe: dataset=%s rows=%s columns=%s",
        dataset_id,
        len(df.index),
        list(df.columns),
    )
    if "p2" in df.columns:
        p2_series = df["p2"]
        log.info(
            "Reopen: canonical p2 from storage dataset_id=%s -> non_null=%d of %d, head=%s",
            dataset_id,
            int(p2_series.notna().sum()),
            len(p2_series),
            p2_series.head(5).tolist(),
        )
    else:
        log.info(
            "Reopen: no canonical p2 in fetched trace for dataset_id=%s; columns=%s",
            dataset_id,
            list(df.columns),
        )
    return df
