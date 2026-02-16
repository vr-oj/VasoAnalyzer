import numpy as np
import pytest

from vasoanalyzer.analysis.contract import (
    AnalysisParamsV1,
    Event,
    MyographyDataset,
    TimeSeries,
    Trace,
)
from vasoanalyzer.analysis.errors import InvalidEventError, MissingPassiveDiameterError
from vasoanalyzer.analysis.metrics import (
    analyze_pressure_myography_v1,
    compute_myogenic_tone_percent,
    compute_passive_diameter_per_step,
    compute_step_steady_state,
)
from vasoanalyzer.analysis.segmentation import extract_pressure_steps


def _make_dataset_with_events(events, metadata=None):
    time = TimeSeries(np.arange(0, 11, dtype=np.float64))
    diameter = Trace(np.ones(11, dtype=np.float64), unit="um")
    pressure = Trace(np.ones(11, dtype=np.float64), unit="mmHg")
    return MyographyDataset(
        dataset_id="events-only",
        time=time,
        diameter_inner_um=diameter,
        pressure_mmhg=pressure,
        events=events,
        metadata=metadata or {},
    )


def _make_synthetic_dataset(metadata_passive=False, include_passive_event=False):
    t = np.arange(0, 601, dtype=np.float64)
    time = TimeSeries(t)

    pressure = np.zeros_like(t)
    pressure[0:200] = 20.0
    pressure[200:400] = 60.0
    pressure[400:] = 120.0

    diameter = np.zeros_like(t)
    diameter[0:200] = 200.0
    diameter[200:400] = 180.0
    diameter[400:] = 160.0

    diameter[0:30] += 50.0
    diameter[200:230] += 50.0
    diameter[400:430] += 50.0

    events = [
        Event("PressureStep", 0.0, 200.0, payload={"target_mmhg": 20}),
        Event("PressureStep", 200.0, 400.0, payload={"target_mmhg": 60}),
        Event("PressureStep", 400.0, 600.0, payload={"target_mmhg": 120}),
    ]

    if include_passive_event:
        events.append(Event("Marker", 50.0, 80.0, payload={"condition": "passive"}))

    metadata = {"condition": "passive"} if metadata_passive else {}

    return MyographyDataset(
        dataset_id="synthetic-1",
        time=time,
        diameter_inner_um=Trace(diameter, unit="um"),
        pressure_mmhg=Trace(pressure, unit="mmHg"),
        events=tuple(events),
        metadata=metadata,
    )


def test_extract_pressure_steps_sorted_nonoverlapping():
    events_unsorted = (
        Event("PressureStep", 100.0, 200.0, payload={"target_mmhg": 60}),
        Event("PressureStep", 0.0, 50.0, payload={"target_mmhg": 20}),
    )
    dataset_unsorted = _make_dataset_with_events(events_unsorted)
    with pytest.raises(InvalidEventError):
        extract_pressure_steps(dataset_unsorted)

    events_overlap = (
        Event("PressureStep", 0.0, 100.0, payload={"target_mmhg": 20}),
        Event("PressureStep", 50.0, 150.0, payload={"target_mmhg": 60}),
    )
    dataset_overlap = _make_dataset_with_events(events_overlap)
    with pytest.raises(InvalidEventError):
        extract_pressure_steps(dataset_overlap)


def test_compute_step_steady_state_excludes_transient():
    dataset = _make_synthetic_dataset()
    params = AnalysisParamsV1()
    steps = extract_pressure_steps(dataset)
    results = compute_step_steady_state(dataset, steps, params)

    np.testing.assert_allclose(results[0].mean_diameter_inner_um, 200.0, atol=1e-6)
    np.testing.assert_allclose(results[1].mean_diameter_inner_um, 180.0, atol=1e-6)
    np.testing.assert_allclose(results[2].mean_diameter_inner_um, 160.0, atol=1e-6)


def test_passive_missing_raises():
    dataset = _make_synthetic_dataset()
    params = AnalysisParamsV1()
    steps = extract_pressure_steps(dataset)
    with pytest.raises(MissingPassiveDiameterError):
        compute_passive_diameter_per_step(dataset, steps, params)


def test_tone_computation():
    params = AnalysisParamsV1()
    active = np.array([100.0, 150.0])
    passive = np.array([200.0, 200.0])
    tone = compute_myogenic_tone_percent(active, passive, params)
    np.testing.assert_allclose(tone, np.array([50.0, 25.0]), atol=1e-6)


def test_analyze_pressure_myography_v1_end_to_end():
    dataset = _make_synthetic_dataset(metadata_passive=True)
    params = AnalysisParamsV1()
    results = analyze_pressure_myography_v1(dataset, params)

    assert len(results.steps) == 3
    assert len(results.step_results) == 3
    assert len(results.passive_diameter_um) == 3
    assert len(results.tone_percent) == 3
    assert results.provenance.dataset_id == dataset.dataset_id
    assert results.provenance.version
