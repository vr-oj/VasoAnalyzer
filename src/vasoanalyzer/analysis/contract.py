from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Literal

import numpy as np

from .errors import AnalysisError, InvalidEventError, InvalidTimebaseError, MissingTraceError

FloatArray = np.ndarray  # must be 1D float64
EventType = Literal["PressureStep", "DrugAdd", "TempChange", "FlowChange", "Marker"]


def _as_float_array(values: FloatArray) -> FloatArray:
    return np.asarray(values, dtype=np.float64)


def _validate_1d(
    values: FloatArray,
    name: str,
    *,
    error_type: type[Exception] = AnalysisError,
) -> None:
    if values.ndim != 1:
        raise error_type(f"{name} must be 1D float64.")
    if values.size == 0:
        raise error_type(f"{name} must be non-empty.")


def _normalize_unit(unit: str, mapping: Dict[str, str], field_name: str) -> str:
    if not isinstance(unit, str):
        raise AnalysisError(f"{field_name} unit must be a string.")
    normal = unit.strip()
    normalized = mapping.get(normal)
    if normalized is None:
        allowed = ", ".join(sorted(mapping.keys()))
        raise AnalysisError(f"{field_name} unit must be one of: {allowed}.")
    return normalized


@dataclass(frozen=True)
class TimeSeries:
    """
    Canonical uniform-time base.
    t_s: seconds, monotonically increasing, 1D float64, length N.
    """

    t_s: FloatArray

    def __post_init__(self) -> None:
        values = _as_float_array(self.t_s)
        _validate_1d(values, "t_s", error_type=InvalidTimebaseError)
        if not np.all(np.isfinite(values)):
            raise InvalidTimebaseError("t_s must be finite with no NaNs.")
        if values.size > 1 and not np.all(np.diff(values) > 0):
            raise InvalidTimebaseError("t_s must be strictly increasing.")
        object.__setattr__(self, "t_s", values)


@dataclass(frozen=True)
class Trace:
    """
    A trace aligned to TimeSeries.t_s.
    values: 1D float64, length N, no NaNs by default (allow NaNs only if allow_nans=True).
    unit: explicit string ("um", "mmHg", "C", etc).
    """

    values: FloatArray
    unit: str
    allow_nans: bool = False

    def __post_init__(self) -> None:
        values = _as_float_array(self.values)
        _validate_1d(values, "values")
        if self.allow_nans:
            if np.isinf(values).any():
                raise AnalysisError("Trace values must not contain infinities.")
        else:
            if not np.all(np.isfinite(values)):
                raise AnalysisError("Trace values must be finite with no NaNs.")
        if not isinstance(self.unit, str) or not self.unit:
            raise AnalysisError("Trace unit must be a non-empty string.")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True)
class Event:
    """
    Events are time-based and reference TimeSeries.t_s (seconds).
    start_s required, end_s optional (None for point markers).
    payload contains strongly recommended keys per event type.
    """

    type: EventType
    start_s: float
    end_s: Optional[float] = None
    label: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            start = float(self.start_s)
        except (TypeError, ValueError) as exc:
            raise InvalidEventError("Event start_s must be a finite float.") from exc
        if not np.isfinite(start):
            raise InvalidEventError("Event start_s must be finite.")
        end = self.end_s
        if end is not None:
            try:
                end = float(end)
            except (TypeError, ValueError) as exc:
                raise InvalidEventError("Event end_s must be a finite float.") from exc
            if not np.isfinite(end):
                raise InvalidEventError("Event end_s must be finite.")
            if end < start:
                raise InvalidEventError("Event end_s must be >= start_s.")
        if not isinstance(self.payload, dict):
            raise InvalidEventError("Event payload must be a dict.")
        object.__setattr__(self, "start_s", start)
        object.__setattr__(self, "end_s", end)


@dataclass(frozen=True)
class TrackingMetadata:
    """
    Records how diameter was produced (if available).
    No analysis logic depends on this; it's provenance-only.
    """

    algorithm: str = ""
    rois: Tuple[Dict[str, Any], ...] = ()
    filters: Tuple[Dict[str, Any], ...] = ()
    rejected_frame_fraction: Optional[float] = None


@dataclass(frozen=True)
class MyographyDataset:
    """
    Canonical dataset container for analysis.
    diameter_inner_um: required
    pressure_mmhg: optional but required for step detection
    temperature_c: optional
    diameter_outer_um: optional
    events: optional but strongly recommended
    """

    dataset_id: str
    time: TimeSeries

    diameter_inner_um: Trace
    pressure_mmhg: Optional[Trace] = None
    temperature_c: Optional[Trace] = None
    diameter_outer_um: Optional[Trace] = None

    events: Tuple[Event, ...] = ()
    tracking: TrackingMetadata = field(default_factory=TrackingMetadata)

    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not self.dataset_id:
            raise AnalysisError("dataset_id must be a non-empty string.")
        if not isinstance(self.time, TimeSeries):
            raise InvalidTimebaseError("time must be a TimeSeries.")
        if self.diameter_inner_um is None:
            raise MissingTraceError("diameter_inner_um is required.")
        if not isinstance(self.diameter_inner_um, Trace):
            raise AnalysisError("diameter_inner_um must be a Trace.")

        events = tuple(self.events)
        for event in events:
            if not isinstance(event, Event):
                raise InvalidEventError("All events must be Event instances.")
        object.__setattr__(self, "events", events)

        if not isinstance(self.tracking, TrackingMetadata):
            raise AnalysisError("tracking must be TrackingMetadata.")
        if not isinstance(self.metadata, dict):
            raise AnalysisError("metadata must be a dict.")
        object.__setattr__(self, "metadata", dict(self.metadata))

        self._validate_trace_alignment(self.diameter_inner_um, "diameter_inner_um")
        self._validate_trace_alignment(self.pressure_mmhg, "pressure_mmhg")
        self._validate_trace_alignment(self.temperature_c, "temperature_c")
        self._validate_trace_alignment(self.diameter_outer_um, "diameter_outer_um")

        self._normalize_units()

    def _validate_trace_alignment(self, trace: Optional[Trace], name: str) -> None:
        if trace is None:
            return
        if not isinstance(trace, Trace):
            raise AnalysisError(f"{name} must be a Trace.")
        if trace.values.shape[0] != self.time.t_s.shape[0]:
            raise InvalidTimebaseError(f"{name} length must match time base.")

    def _normalize_units(self) -> None:
        diameter_units = {"um": "um", "\u00b5m": "um"}
        temp_units = {"C": "C", "\u00b0C": "C"}
        pressure_units = {"mmHg": "mmHg"}

        diameter_unit = _normalize_unit(
            self.diameter_inner_um.unit, diameter_units, "diameter_inner_um"
        )
        if diameter_unit != self.diameter_inner_um.unit:
            object.__setattr__(
                self,
                "diameter_inner_um",
                Trace(
                    values=self.diameter_inner_um.values,
                    unit=diameter_unit,
                    allow_nans=self.diameter_inner_um.allow_nans,
                ),
            )

        if self.diameter_outer_um is not None:
            outer_unit = _normalize_unit(
                self.diameter_outer_um.unit, diameter_units, "diameter_outer_um"
            )
            if outer_unit != self.diameter_outer_um.unit:
                object.__setattr__(
                    self,
                    "diameter_outer_um",
                    Trace(
                        values=self.diameter_outer_um.values,
                        unit=outer_unit,
                        allow_nans=self.diameter_outer_um.allow_nans,
                    ),
                )

        if self.pressure_mmhg is not None:
            pressure_unit = _normalize_unit(
                self.pressure_mmhg.unit, pressure_units, "pressure_mmhg"
            )
            if pressure_unit != self.pressure_mmhg.unit:
                object.__setattr__(
                    self,
                    "pressure_mmhg",
                    Trace(
                        values=self.pressure_mmhg.values,
                        unit=pressure_unit,
                        allow_nans=self.pressure_mmhg.allow_nans,
                    ),
                )

        if self.temperature_c is not None:
            temp_unit = _normalize_unit(self.temperature_c.unit, temp_units, "temperature_c")
            if temp_unit != self.temperature_c.unit:
                object.__setattr__(
                    self,
                    "temperature_c",
                    Trace(
                        values=self.temperature_c.values,
                        unit=temp_unit,
                        allow_nans=self.temperature_c.allow_nans,
                    ),
                )


@dataclass(frozen=True)
class StepWindows:
    """
    Defines how we compute per-step values.
    transient_exclude_s: time to ignore after step start
    steady_state_window_s: duration at end of step to average; if step shorter, clamp.
    """

    transient_exclude_s: float = 30.0
    steady_state_window_s: float = 30.0

    def __post_init__(self) -> None:
        if self.transient_exclude_s < 0:
            raise AnalysisError("transient_exclude_s must be >= 0.")
        if self.steady_state_window_s <= 0:
            raise AnalysisError("steady_state_window_s must be > 0.")


@dataclass(frozen=True)
class PassiveDefinition:
    """
    Defines how passive diameter is obtained.
    mode:
      - "event_tagged": passive comes from events payload (e.g., condition="passive")
      - "separate_dataset": passive comes from another dataset analyzed alongside
    """

    mode: Literal["event_tagged", "separate_dataset"] = "event_tagged"
    passive_event_key: str = "condition"
    passive_event_value: str = "passive"


@dataclass(frozen=True)
class ToneDefinition:
    """
    tone% = (D_passive - D_active) / D_passive * 100
    """

    clamp_negative_to_zero: bool = False


@dataclass(frozen=True)
class AnalysisParamsV1:
    step_windows: StepWindows = field(default_factory=StepWindows)
    passive: PassiveDefinition = field(default_factory=PassiveDefinition)
    tone: ToneDefinition = field(default_factory=ToneDefinition)


def build_dataset_from_arrays(
    *,
    dataset_id: str,
    time_s: FloatArray,
    diameter_inner_um: FloatArray,
    pressure_mmhg: Optional[FloatArray] = None,
    temperature_c: Optional[FloatArray] = None,
    diameter_outer_um: Optional[FloatArray] = None,
    events: Optional[Tuple[Event, ...]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> MyographyDataset:
    """
    Minimal adapter to build a MyographyDataset from raw arrays.
    """

    time = TimeSeries(time_s)
    diameter_trace = Trace(diameter_inner_um, unit="um")
    pressure_trace = Trace(pressure_mmhg, unit="mmHg") if pressure_mmhg is not None else None
    temperature_trace = Trace(temperature_c, unit="C") if temperature_c is not None else None
    outer_trace = Trace(diameter_outer_um, unit="um") if diameter_outer_um is not None else None
    return MyographyDataset(
        dataset_id=dataset_id,
        time=time,
        diameter_inner_um=diameter_trace,
        pressure_mmhg=pressure_trace,
        temperature_c=temperature_trace,
        diameter_outer_um=outer_trace,
        events=events or (),
        metadata=metadata or {},
    )
