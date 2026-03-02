from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TRACE_V2_COLUMNS: tuple[str, ...] = (
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
    "Outer Profiles",
    "Inner Profiles",
    "Outer Profiles Valid",
    "Inner Profiles Valid",
)

EVENT_V2_TABLE_COLUMNS: tuple[str, ...] = (
    "#",
    "Time",
    "Frame",
    "Label",
    "OD",
    "%OD ref",
    "ID",
    "Caliper",
    "Pavg",
    "P1",
    "P2",
    "Temp",
)


@dataclass(frozen=True)
class TraceFrame:
    time_s: float
    time_hms: str
    time_s_exact: float
    frame_number: int
    saved: int
    tiff_page: int | None
    outer_diameter_um: float | None
    inner_diameter_um: float | None
    table_marker: int
    temperature_C: float | None
    pressure_1_mmHg: float | None
    pressure_2_mmHg: float | None
    avg_pressure_mmHg: float | None
    set_pressure_mmHg: float | None
    caliper_length: float | None
    outer_profiles: str | None
    inner_profiles: str | None
    outer_profiles_valid: str | None
    inner_profiles_valid: str | None


@dataclass(frozen=True)
class EventRow:
    index: int
    time_hms: str
    frame_number: int
    label: str
    od_um: float | None
    od_ref_pct: float | None
    id_um: float | None
    caliper: float | None
    pavg_mmHg: float | None
    p1_mmHg: float | None
    p2_mmHg: float | None
    temp_C: float | None
    raw_time_s: float | None = None
    snap_delta_s: float | None = None


@dataclass(frozen=True)
class ImportReport:
    source_format: Literal["vasotracker_v1", "vasotracker_v2"]
    trace_rows: int
    event_rows: int
    warnings: list[str]
    errors: list[str]
    stats: dict[str, float | int | str]


__all__ = [
    "EVENT_V2_TABLE_COLUMNS",
    "TRACE_V2_COLUMNS",
    "EventRow",
    "ImportReport",
    "TraceFrame",
]
