"""Deterministic TSV/CSV serialization for export tables."""

from __future__ import annotations

import csv
import math
import numbers
from io import StringIO
from pathlib import Path

from .generator import ExportTable


def _format_cell(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, numbers.Integral):
        return str(int(value))
    if isinstance(value, numbers.Real):
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return ""
        return f"{num:.2f}"
    return str(value)


def _render_delimited(table: ExportTable, *, delimiter: str, include_header: bool = True) -> str:
    output = StringIO()
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
    if include_header and table.headers:
        writer.writerow([_format_cell(header) for header in table.headers])
    for row in table.rows:
        writer.writerow([_format_cell(cell) for cell in row])
    return output.getvalue()


def render_tsv(table: ExportTable, *, include_header: bool = True) -> str:
    return _render_delimited(table, delimiter="\t", include_header=include_header)


def render_csv(table: ExportTable, *, include_header: bool = True) -> str:
    return _render_delimited(table, delimiter=",", include_header=include_header)


def write_csv(path: str | Path, table: ExportTable, *, include_header: bool = True) -> None:
    text = render_csv(table, include_header=include_header)
    Path(path).write_text(text, encoding="utf-8")
