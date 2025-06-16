import os
import csv
import re
import logging
import pandas as pd

log = logging.getLogger(__name__)


def is_legacy_trace(path: str) -> bool:
    """Return True if ``path`` appears to be a legacy trace file."""
    name = os.path.basename(path).lower()
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            header = f.readline().lower()
    except Exception:
        header = ""
    if "inner diameter" in header:
        return False
    if "id" in header or "i.d" in header:
        return True
    if "mbfa" in name:
        return True
    return False


def load_trace(file_path: str) -> pd.DataFrame:
    """Load a legacy trace CSV into a DataFrame."""
    log.info("Loading legacy trace from %s", file_path)
    with open(file_path, "r", encoding="utf-8-sig") as f:
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
    df = pd.read_csv(file_path, delimiter=delimiter, encoding="utf-8-sig", header=0)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(part) for part in col if pd.notna(part)) for col in df.columns]

    df = df.dropna(axis=1, how="all")

    def _norm(c: str) -> str:
        return re.sub(r"[^a-z0-9]", "", c.lower())

    time_col = None
    diam_col = None
    for c in df.columns:
        n = _norm(c)
        if time_col is None and ("time" in n or n in {"t", "ts"}):
            time_col = c
        if diam_col is None and (n == "id" or "diam" in n):
            diam_col = c

    if time_col is None or diam_col is None:
        raise ValueError("Legacy trace file missing Time or Diameter columns")

    df = df.rename(columns={time_col: "Time (s)", diam_col: "Inner Diameter"})
    df = df.loc[:, ["Time (s)", "Inner Diameter"]]
    df["Time (s)"] = pd.to_numeric(df["Time (s)"], errors="coerce")
    df["Inner Diameter"] = pd.to_numeric(df["Inner Diameter"], errors="coerce")

    log.info("Loaded legacy trace with %d rows", len(df))
    return df


__all__ = ["load_trace", "is_legacy_trace"]
