from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .contract import AnalysisParamsV1, MyographyDataset, TimeSeries
from .errors import AnalysisError, MissingPassiveDiameterError
from .provenance import Provenance, resolve_analyzer_version, stable_params_hash
from .segmentation import StepSegment, extract_pressure_steps


def slice_mask(time: TimeSeries, start_s: float, end_s: float) -> np.ndarray:
    if end_s <= start_s:
        raise AnalysisError("slice_mask end_s must be greater than start_s.")
    return (time.t_s >= start_s) & (time.t_s < end_s)


@dataclass(frozen=True)
class StepResult:
    step_index: int
    start_s: float
    end_s: float
    target_mmhg: float | None
    mean_diameter_inner_um: float
    mean_pressure_mmhg: float | None


def compute_step_steady_state(
    dataset: MyographyDataset,
    steps: Sequence[StepSegment],
    params: AnalysisParamsV1,
) -> tuple[StepResult, ...]:
    results: list[StepResult] = []
    transient_exclude = params.step_windows.transient_exclude_s
    steady_window = params.step_windows.steady_state_window_s

    for step in steps:
        window_start = step.start_s + transient_exclude
        window_start = max(window_start, step.end_s - steady_window)
        mask = slice_mask(dataset.time, window_start, step.end_s)
        if not np.any(mask):
            raise AnalysisError(
                f"Empty steady-state window for step {step.index} ({step.start_s}-{step.end_s}s)."
            )
        mean_diameter = float(np.mean(dataset.diameter_inner_um.values[mask]))
        mean_pressure: float | None = None
        if dataset.pressure_mmhg is not None:
            mean_pressure = float(np.mean(dataset.pressure_mmhg.values[mask]))

        results.append(
            StepResult(
                step_index=step.index,
                start_s=step.start_s,
                end_s=step.end_s,
                target_mmhg=step.target_mmhg,
                mean_diameter_inner_um=mean_diameter,
                mean_pressure_mmhg=mean_pressure,
            )
        )

    return tuple(results)


def compute_passive_diameter_per_step(
    dataset: MyographyDataset,
    steps: Sequence[StepSegment],
    params: AnalysisParamsV1,
) -> np.ndarray:
    """returns array length = len(steps) with passive diameters in um"""

    if params.passive.mode != "event_tagged":
        raise AnalysisError("Only passive mode 'event_tagged' is supported in v1.")
    if not steps:
        return np.asarray([], dtype=np.float64)

    passive_key = params.passive.passive_event_key
    passive_value = params.passive.passive_event_value

    if dataset.metadata.get(passive_key) == passive_value:
        mean_passive = float(np.mean(dataset.diameter_inner_um.values))
        return np.full(len(steps), mean_passive, dtype=np.float64)

    matching_events = [
        event
        for event in dataset.events
        if isinstance(event.payload, dict) and event.payload.get(passive_key) == passive_value
    ]
    if not matching_events:
        raise MissingPassiveDiameterError("No passive markers found in dataset.")

    selected = min(matching_events, key=lambda event: event.start_s)
    if selected.end_s is not None:
        start_s = selected.start_s
        end_s = selected.end_s
    else:
        start_s = selected.start_s
        end_s = selected.start_s + params.step_windows.steady_state_window_s

    mask = slice_mask(dataset.time, start_s, end_s)
    if not np.any(mask):
        raise AnalysisError("Passive marker interval contains no samples.")
    mean_passive = float(np.mean(dataset.diameter_inner_um.values[mask]))
    return np.full(len(steps), mean_passive, dtype=np.float64)


def compute_myogenic_tone_percent(
    active_um: np.ndarray,
    passive_um: np.ndarray,
    params: AnalysisParamsV1,
) -> np.ndarray:
    active = np.asarray(active_um, dtype=np.float64)
    passive = np.asarray(passive_um, dtype=np.float64)
    if active.shape != passive.shape:
        raise AnalysisError("active_um and passive_um must have the same shape.")
    if np.any(passive <= 0):
        raise AnalysisError("Passive diameter must be > 0 for tone computation.")

    tone = (passive - active) / passive * 100.0
    if params.tone.clamp_negative_to_zero:
        tone = np.maximum(tone, 0.0)
    return tone


@dataclass(frozen=True)
class AnalysisResultsV1:
    provenance: Provenance
    steps: tuple[StepSegment, ...]
    step_results: tuple[StepResult, ...]
    passive_diameter_um: tuple[float, ...]
    tone_percent: tuple[float, ...]


def analyze_pressure_myography_v1(
    dataset: MyographyDataset,
    params: AnalysisParamsV1,
) -> AnalysisResultsV1:
    """
    Orchestrates: extract steps -> compute steady state -> passive -> tone.
    """

    steps = extract_pressure_steps(dataset)
    step_results = compute_step_steady_state(dataset, steps, params)
    active_um = np.asarray([result.mean_diameter_inner_um for result in step_results])
    passive_um = compute_passive_diameter_per_step(dataset, steps, params)
    tone_percent = compute_myogenic_tone_percent(active_um, passive_um, params)

    provenance = Provenance(
        analyzer="VasoAnalyzer",
        version=resolve_analyzer_version(),
        params_hash=stable_params_hash(params),
        dataset_id=dataset.dataset_id,
    )

    return AnalysisResultsV1(
        provenance=provenance,
        steps=tuple(steps),
        step_results=tuple(step_results),
        passive_diameter_um=tuple(float(value) for value in passive_um),
        tone_percent=tuple(float(value) for value in tone_percent),
    )
