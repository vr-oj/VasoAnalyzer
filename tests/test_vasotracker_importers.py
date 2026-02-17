from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from vasoanalyzer.io.importers import (
    EVENT_V2_TABLE_COLUMNS,
    TRACE_V2_COLUMNS,
    EventRow,
    TraceFrame,
    export_events_as_v2_table_csv,
    export_trace_as_v2_csv,
    guess_table_csv_for_trace,
    import_vasotracker_v1,
    import_vasotracker_v2,
)


def _write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_import_v1_normalizes_and_marks_events(tmp_path: Path) -> None:
    trace_path = tmp_path / "sample.csv"
    table_path = tmp_path / "sample - Table.csv"

    _write_csv(
        trace_path,
        [
            "Time",
            "Outer Diameter",
            "Inner Diameter",
            "Temperature (oC)",
            "Pressure 1 (mmHg)",
            "Pressure 2 (mmHg)",
            "Avg Pressure (mmHg)",
            "Caliper length",
        ],
        [
            [10.0, 100.0, 50.0, 35.0, 80.0, 85.0, 82.5, 10.0],
            [10.5, 101.0, 49.0, 35.1, 81.0, 86.0, 83.5, 10.1],
            [11.0, 102.0, -1.0, 35.2, 82.0, 87.0, 84.5, 10.2],
        ],
    )
    _write_csv(
        table_path,
        ["Event", "Time"],
        [
            ["A", 10.51],
            ["B", "bad-time"],
        ],
    )

    frames, events, report = import_vasotracker_v1(trace_path, table_csv_path=table_path)

    assert report.source_format == "vasotracker_v1"
    assert report.trace_rows == 3
    assert report.event_rows == 2
    assert report.stats["negative_inner_diameter_count"] == 1

    assert [frame.frame_number for frame in frames] == [0, 1, 2]
    assert [frame.time_s for frame in frames] == [0.0, 0.5, 1.0]
    assert frames[1].table_marker == 1

    assert events[0].label == "A"
    assert events[0].frame_number == 1
    assert events[1].label == "B"
    assert events[1].frame_number == -1


def test_import_v2_snaps_by_frame_then_time(tmp_path: Path) -> None:
    trace_path = tmp_path / "v2.csv"
    table_path = tmp_path / "v2_table.csv"

    _write_csv(
        trace_path,
        [
            "Time (s)",
            "Time (hh:mm:ss)",
            "Time_s_exact",
            "FrameNumber",
            "Saved",
            "TiffPage",
            "Outer Diameter",
            "Inner Diameter",
            "Table Marker",
            "Temperature (oC)",
            "Pressure 1 (mmHg)",
            "Pressure 2 (mmHg)",
            "Avg Pressure (mmHg)",
            "Set Pressure (mmHg)",
            "Caliper length",
        ],
        [
            [0.0, "00:00:00", 0.0, 10, 0, "", 110.0, 60.0, 0, 34.0, 70.0, 75.0, 72.5, 80.0, 9.0],
            [1.0, "00:00:01", 1.0, 11, 0, "", 111.0, 61.0, 0, 34.1, 71.0, 76.0, 73.5, 81.0, 9.1],
            [2.0, "00:00:02", 2.0, 12, 0, "", 112.0, 62.0, 0, 34.2, 72.0, 77.0, 74.5, 82.0, 9.2],
        ],
    )
    _write_csv(
        table_path,
        ["#", "Time", "Frame", "Label", "OD", "%OD ref", "ID", "Caliper", "Pavg", "P1", "P2", "Temp"],
        [
            [1, "00:00:01", 11, "Frame match", 150.0, "", 65.0, 8.8, 70.1, 68.0, 72.0, 33.0],
            [2, "00:00:02", 999, "Time match", "", "", "", "", "", "", "", ""],
        ],
    )

    frames, events, report = import_vasotracker_v2(trace_path, table_csv_path=table_path)

    assert report.source_format == "vasotracker_v2"
    assert report.trace_rows == 3
    assert report.event_rows == 2
    assert report.stats["unplaced_event_count"] == 0

    assert events[0].label == "Frame match"
    assert events[0].frame_number == 11
    assert events[0].od_um == 150.0
    assert events[0].id_um == 65.0

    assert events[1].label == "Time match"
    assert events[1].frame_number == 12
    assert events[1].od_um == 112.0
    assert events[1].id_um == 62.0

    markers = [frame.table_marker for frame in frames]
    assert markers == [0, 1, 1]


def test_guess_table_csv_for_trace_supports_v1_and_v2_patterns(tmp_path: Path) -> None:
    v1_trace = tmp_path / "foo.csv"
    v1_table = tmp_path / "foo - Table.csv"
    v1_trace.write_text("Time,Outer Diameter,Inner Diameter\n0,1,1\n", encoding="utf-8")
    v1_table.write_text("Event,Time\nA,0\n", encoding="utf-8")
    assert guess_table_csv_for_trace(v1_trace) == v1_table

    v2_trace = tmp_path / "bar.csv"
    v2_table = tmp_path / "bar_table.csv"
    v2_trace.write_text("Time (s),Outer Diameter,Inner Diameter\n0,1,1\n", encoding="utf-8")
    v2_table.write_text("#,Time,Frame,Label\n1,00:00:00,0,A\n", encoding="utf-8")
    assert guess_table_csv_for_trace(v2_trace) == v2_table


def test_v2_exports_keep_contract_column_order(tmp_path: Path) -> None:
    frames = [
        TraceFrame(
            time_s=0.0,
            time_hms="00:00:00",
            time_s_exact=0.0,
            frame_number=0,
            saved=0,
            tiff_page=None,
            outer_diameter_um=100.0,
            inner_diameter_um=50.0,
            table_marker=0,
            temperature_C=35.0,
            pressure_1_mmHg=80.0,
            pressure_2_mmHg=81.0,
            avg_pressure_mmHg=80.5,
            set_pressure_mmHg=82.0,
            caliper_length=10.0,
            outer_profiles="[]",
            inner_profiles="[]",
            outer_profiles_valid="[]",
            inner_profiles_valid="[]",
        )
    ]
    events = [
        EventRow(
            index=1,
            time_hms="00:00:00",
            frame_number=0,
            label="A",
            od_um=100.0,
            od_ref_pct=None,
            id_um=50.0,
            caliper=10.0,
            pavg_mmHg=80.5,
            p1_mmHg=80.0,
            p2_mmHg=81.0,
            temp_C=35.0,
        )
    ]

    trace_out = tmp_path / "trace_out.csv"
    events_out = tmp_path / "events_out.csv"
    export_trace_as_v2_csv(frames, trace_out)
    export_events_as_v2_table_csv(events, events_out)

    trace_df = pd.read_csv(trace_out)
    events_df = pd.read_csv(events_out)

    assert tuple(trace_df.columns) == TRACE_V2_COLUMNS
    assert tuple(events_df.columns) == EVENT_V2_TABLE_COLUMNS
