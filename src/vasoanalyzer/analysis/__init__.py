"""GUI-independent analysis core for pressure myography datasets."""

from .contract import (
    AnalysisParamsV1,
    Event,
    EventType,
    FloatArray,
    MyographyDataset,
    PassiveDefinition,
    StepWindows,
    TimeSeries,
    ToneDefinition,
    Trace,
    TrackingMetadata,
    build_dataset_from_arrays,
)
from .errors import (
    AnalysisError,
    InvalidEventError,
    InvalidTimebaseError,
    MissingPassiveDiameterError,
    MissingTraceError,
)
from .metrics import (
    AnalysisResultsV1,
    StepResult,
    analyze_pressure_myography_v1,
    compute_myogenic_tone_percent,
    compute_passive_diameter_per_step,
    compute_step_steady_state,
    slice_mask,
)
from .provenance import Provenance, resolve_analyzer_version, stable_params_hash
from .segmentation import StepSegment, extract_pressure_steps

__all__ = [
    "AnalysisError",
    "AnalysisParamsV1",
    "AnalysisResultsV1",
    "Event",
    "EventType",
    "FloatArray",
    "InvalidEventError",
    "InvalidTimebaseError",
    "MissingPassiveDiameterError",
    "MissingTraceError",
    "MyographyDataset",
    "PassiveDefinition",
    "Provenance",
    "StepResult",
    "StepSegment",
    "StepWindows",
    "TimeSeries",
    "ToneDefinition",
    "Trace",
    "TrackingMetadata",
    "analyze_pressure_myography_v1",
    "build_dataset_from_arrays",
    "compute_myogenic_tone_percent",
    "compute_passive_diameter_per_step",
    "compute_step_steady_state",
    "extract_pressure_steps",
    "resolve_analyzer_version",
    "slice_mask",
    "stable_params_hash",
]
