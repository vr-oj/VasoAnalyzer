"""
Trace persistence utilities for SQLite projects.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence

import pandas as pd

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

    mapping: dict[str, str] = {}
    for col in columns:
        norm = normalize_label(col)
        if (
            norm in {"times", "tseconds", "t", "time", "timestamp"}
            and "t_seconds" not in mapping.values()
        ):
            mapping[col] = "t_seconds"
        elif norm in {"innerdiameter", "innerdiam"} and "inner_diam" not in mapping.values():
            mapping[col] = "inner_diam"
        elif norm in {"outerdiameter", "outerdiam"} and "outer_diam" not in mapping.values():
            mapping[col] = "outer_diam"
        elif norm in {"pressureavg", "pavg"} and "p_avg" not in mapping.values():
            mapping[col] = "p_avg"
        elif norm in {"pressure1", "p1"} and "p1" not in mapping.values():
            mapping[col] = "p1"
        elif norm in {"pressure2", "p2"} and "p2" not in mapping.values():
            mapping[col] = "p2"
    if mapping:
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
    return pd.read_sql_query(" ".join(query), conn, params=params)
