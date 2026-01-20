import csv
import io

from vasoanalyzer.export.clipboard import render_tsv, write_csv
from vasoanalyzer.export.generator import build_export_table, events_from_rows
from vasoanalyzer.export.profiles import (
    EVENT_TABLE_ROW_PER_EVENT,
    EVENT_VALUES_SINGLE_COLUMN,
    PRESSURE_CURVE_STANDARD,
)


def _parse_delimited(text: str, delimiter: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def test_deterministic_row_per_event():
    rows = [
        ("B", 2.0, 110.1234, None, None, None, None),
        ("A", 1.0, 100.5, None, None, None, None),
    ]
    events = events_from_rows(rows)
    table = build_export_table(EVENT_TABLE_ROW_PER_EVENT, events)

    tsv = render_tsv(table, include_header=True)
    expected = (
        "Time (s)\tEvent Label\tValue\n"
        "1.00\tA\t100.50\n"
        "2.00\tB\t110.12\n"
    )
    assert tsv == expected


def test_single_column_paste():
    rows = [
        ("First", 1.0, 5.5, None, None, None, None),
        ("Second", 2.0, 6.0, None, None, None, None),
    ]
    events = events_from_rows(rows)
    table = build_export_table(EVENT_VALUES_SINGLE_COLUMN, events)

    tsv = render_tsv(table, include_header=False)
    parsed = _parse_delimited(tsv, "\t")

    assert parsed == [["5.50"], ["6.00"]]
    assert all(len(row) == 1 for row in parsed)
    assert "." in parsed[0][0]


def test_pressure_curve_profile_order_and_missing():
    rows = [
        ("60 mmHg – Tone", 3.0, 70.0, None, None, None, None),
        ("20 mmHg – Max", 1.0, 90.0, None, None, None, None),
        ("60 mmHg – Max", 2.0, 80.0, None, None, None, None),
    ]
    events = events_from_rows(rows)
    table = build_export_table(PRESSURE_CURVE_STANDARD, events)

    present = {row[0] for row in rows}
    expected_labels = [
        label
        for label in PRESSURE_CURVE_STANDARD.requires_event_labels
        if label in present
    ]
    output_labels = [row[0] for row in table.rows]
    assert output_labels == expected_labels

    missing = [
        label
        for label in PRESSURE_CURVE_STANDARD.requires_event_labels
        if label not in present
    ]
    if missing:
        warning_text = "\n".join(table.warnings)
        for label in missing:
            assert label in warning_text


def test_clipboard_csv_parity(tmp_path):
    rows = [
        ("A", 1.0, 100.5, None, None, None, None),
        ("B", 2.0, 110.1234, None, None, None, None),
    ]
    events = events_from_rows(rows)
    table = build_export_table(EVENT_TABLE_ROW_PER_EVENT, events)

    tsv = render_tsv(table, include_header=True)
    csv_path = tmp_path / "export.csv"
    write_csv(csv_path, table, include_header=True)

    parsed_tsv = _parse_delimited(tsv, "\t")
    parsed_csv = _parse_delimited(csv_path.read_text(), ",")
    assert parsed_tsv == parsed_csv
