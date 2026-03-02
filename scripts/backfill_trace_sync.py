#!/usr/bin/env python3
"""Backfill trace frame_number/tiff_page from the original trace CSV.

This updates only the trace table's sync columns and leaves edited diameter
values untouched.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vasoanalyzer.storage.project_storage import open_unified_project  # noqa: E402


def _sniff_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig") as handle:
        sample = handle.read(2048)
    try:
        return csv.Sniffer().sniff(sample).delimiter
    except csv.Error:
        if "," in sample:
            return ","
        if "\t" in sample:
            return "\t"
        return ";"


def _normalize_label(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _read_trace_csv(path: Path) -> pd.DataFrame:
    delimiter = _sniff_delimiter(path)
    df = pd.read_csv(path, delimiter=delimiter, encoding="utf-8-sig", header=0)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(part) for part in col if pd.notna(part)) for col in df.columns
        ]

    df = df.dropna(axis=1, how="all")

    if len(df) > 1:
        numeric_preview = df.apply(pd.to_numeric, errors="coerce")
        header_row = df.iloc[0]
        textual_mask = header_row.apply(
            lambda v: isinstance(v, str) and v.strip() != ""
        )
        if (
            numeric_preview.iloc[0].isna().all()
            and numeric_preview.iloc[1:].notna().any().any()
        ):
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

    return df


def _pick_time_column(df: pd.DataFrame) -> str | None:
    norm_map = {_normalize_label(c): c for c in df.columns}
    for key in ("timesexact", "timeseconds", "times"):
        if key in norm_map:
            return norm_map[key]
    for col in df.columns:
        if "time" in _normalize_label(col):
            return col
    return None


def _pick_exact_column(df: pd.DataFrame, keys: tuple[str, ...]) -> str | None:
    norm_map = {_normalize_label(c): c for c in df.columns}
    for key in keys:
        if key in norm_map:
            return norm_map[key]
    return None


def _coerce_time(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().all():
        td = pd.to_timedelta(series.astype(str), errors="coerce")
        if not td.isna().all():
            return td.dt.total_seconds()
        return numeric
    if numeric.isna().any():
        td = pd.to_timedelta(series.astype(str), errors="coerce")
        numeric = numeric.copy()
        numeric.loc[numeric.isna()] = td.dt.total_seconds()
    return numeric


def _coerce_int(value: object) -> int | None:
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(str(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _list_datasets(conn) -> list[tuple[int, str]]:
    rows = conn.execute("SELECT id, name FROM dataset ORDER BY id").fetchall()
    return [(int(r[0]), str(r[1])) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill trace frame_number/tiff_page from original trace CSV."
    )
    parser.add_argument("--project", required=True, help="Path to .vaso or .vasopack")
    parser.add_argument("--trace-csv", required=True, help="Original trace CSV path")
    parser.add_argument("--dataset-id", type=int, help="Dataset id to update")
    parser.add_argument("--sample-name", help="Sample name (matches dataset.name)")
    parser.add_argument(
        "--precision", type=int, default=6, help="Rounding decimals for time match"
    )
    parser.add_argument(
        "--min-match", type=float, default=0.9, help="Minimum match ratio required"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing non-null values"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show summary without writing"
    )
    parser.add_argument("--list", action="store_true", help="List datasets and exit")
    parser.add_argument(
        "--time-column",
        help="Explicit time column name from the trace CSV (overrides auto-detect)",
    )

    args = parser.parse_args()

    project_path = Path(args.project).expanduser()
    trace_csv = Path(args.trace_csv).expanduser()

    if not project_path.exists():
        print(f"Project not found: {project_path}")
        return 2
    if not trace_csv.exists():
        print(f"Trace CSV not found: {trace_csv}")
        return 2

    store = open_unified_project(project_path, readonly=False)
    try:
        datasets = _list_datasets(store.conn)
        if args.list:
            for ds_id, name in datasets:
                print(f"{ds_id}\t{name}")
            return 0

        dataset_id = args.dataset_id
        if dataset_id is None:
            if args.sample_name:
                matches = [row for row in datasets if row[1] == args.sample_name]
                if len(matches) == 1:
                    dataset_id = matches[0][0]
                elif len(matches) > 1:
                    print(f"Multiple datasets named '{args.sample_name}':")
                    for ds_id, name in matches:
                        print(f"{ds_id}\t{name}")
                    return 2
                else:
                    print(f"No dataset named '{args.sample_name}'. Available datasets:")
                    for ds_id, name in datasets:
                        print(f"{ds_id}\t{name}")
                    return 2
            else:
                print("Specify --dataset-id or --sample-name. Available datasets:")
                for ds_id, name in datasets:
                    print(f"{ds_id}\t{name}")
                return 2

        df_csv = _read_trace_csv(trace_csv)
        tiff_col = _pick_exact_column(df_csv, ("tiffpage",))
        frame_col = _pick_exact_column(df_csv, ("framenumber", "frame"))

        if tiff_col is None and frame_col is None:
            print("Could not detect TiffPage or FrameNumber columns in the trace CSV.")
            return 2

        df_db = pd.read_sql_query(
            "SELECT t_seconds, tiff_page, frame_number FROM trace WHERE dataset_id = ? ORDER BY t_seconds",
            store.conn,
            params=[dataset_id],
        )
        if df_db.empty:
            print(f"No trace rows found for dataset_id={dataset_id}")
            return 2

        if args.time_column:
            time_col = args.time_column
        else:
            time_col = _pick_time_column(df_csv)

        if time_col is None or time_col not in df_csv.columns:
            print("Could not detect a usable time column in the trace CSV.")
            return 2

        candidate_cols = [time_col]
        if not args.time_column:
            for candidate in ("Time (s)", "Time_s_exact"):
                if candidate in df_csv.columns and candidate not in candidate_cols:
                    candidate_cols.append(candidate)

        best_col = None
        best_match = -1
        db_keys = set(df_db["t_seconds"].round(args.precision).tolist())
        for candidate in candidate_cols:
            candidate_series = _coerce_time(df_csv[candidate]).round(args.precision)
            match = candidate_series.isin(db_keys).sum()
            if match > best_match:
                best_match = match
                best_col = candidate

        if best_col is None:
            print("Failed to select a time column from the trace CSV.")
            return 2

        if best_col != time_col:
            time_col = best_col

        time_values = _coerce_time(df_csv[time_col])
        df_map = pd.DataFrame({"t_seconds": time_values})
        if tiff_col is not None:
            df_map["tiff_page_new"] = pd.to_numeric(df_csv[tiff_col], errors="coerce")
        if frame_col is not None:
            df_map["frame_number_new"] = pd.to_numeric(
                df_csv[frame_col], errors="coerce"
            )
        df_map = df_map.dropna(subset=["t_seconds"])
        df_map["t_key"] = df_map["t_seconds"].round(args.precision)
        df_map = df_map.drop_duplicates(subset=["t_key"], keep="first")

        df_db["t_key"] = df_db["t_seconds"].round(args.precision)
        merged = df_db.merge(df_map, on="t_key", how="left", suffixes=("", "_csv"))

        matched = (
            merged["t_seconds_csv"].notna().sum() if "t_seconds_csv" in merged else 0
        )
        match_rate = matched / max(len(merged), 1)
        print(f"Time column: {time_col}")
        print(f"Match rate: {matched}/{len(merged)} ({match_rate:.1%})")
        if match_rate < args.min_match and not args.dry_run:
            print(
                f"Match rate below threshold ({args.min_match:.0%}). "
                "Use --dry-run to inspect or increase --min-match/--overwrite."
            )
            return 2

        updates = []
        updated_tiff = 0
        updated_frame = 0
        for row in merged.itertuples(index=False):
            existing_tiff = row.tiff_page
            existing_frame = row.frame_number
            new_tiff_raw = getattr(row, "tiff_page_new", None)
            new_frame_raw = getattr(row, "frame_number_new", None)

            new_tiff = _coerce_int(new_tiff_raw) if new_tiff_raw is not None else None
            new_frame = (
                _coerce_int(new_frame_raw) if new_frame_raw is not None else None
            )

            if new_tiff is None and new_frame is None:
                continue

            tiff_value = existing_tiff
            frame_value = existing_frame

            if new_tiff is not None:
                if existing_tiff is None or pd.isna(existing_tiff) or args.overwrite:
                    tiff_value = new_tiff
            if new_frame is not None:
                if existing_frame is None or pd.isna(existing_frame) or args.overwrite:
                    frame_value = new_frame

            if tiff_value != existing_tiff or frame_value != existing_frame:
                updates.append((tiff_value, frame_value, dataset_id, row.t_seconds))
                if tiff_value != existing_tiff:
                    updated_tiff += 1
                if frame_value != existing_frame:
                    updated_frame += 1

        print(
            f"Planned updates: tiff_page={updated_tiff}, frame_number={updated_frame}"
        )
        if args.dry_run:
            return 0

        if updates:
            with store.conn:
                store.conn.executemany(
                    """
                    UPDATE trace
                    SET tiff_page = ?, frame_number = ?
                    WHERE dataset_id = ? AND t_seconds = ?
                    """,
                    updates,
                )
            store.mark_dirty()
            store.save()
            print("Backfill complete.")
        else:
            print("No updates needed.")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
