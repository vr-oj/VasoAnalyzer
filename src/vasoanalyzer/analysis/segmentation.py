from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .contract import MyographyDataset
from .errors import InvalidEventError


@dataclass(frozen=True)
class StepSegment:
    index: int
    start_s: float
    end_s: float
    target_mmhg: Optional[float] = None
    label: str = ""


def extract_pressure_steps(dataset: MyographyDataset) -> Tuple[StepSegment, ...]:
    """
    Uses dataset.events of type PressureStep.
    Requires each PressureStep to have end_s (step is an interval).
    target pressure should be in payload under 'target_mmhg' if present.
    """

    pressure_events = [event for event in dataset.events if event.type == "PressureStep"]
    steps: list[StepSegment] = []
    prev_start: Optional[float] = None
    prev_end: Optional[float] = None

    for index, event in enumerate(pressure_events):
        if event.end_s is None:
            raise InvalidEventError("PressureStep event must define end_s.")
        if prev_start is not None and event.start_s < prev_start:
            raise InvalidEventError("PressureStep events must be sorted by start_s.")
        if prev_end is not None and event.start_s < prev_end:
            raise InvalidEventError("PressureStep events must be non-overlapping.")

        target = None
        if isinstance(event.payload, dict) and "target_mmhg" in event.payload:
            try:
                target = float(event.payload["target_mmhg"])
            except (TypeError, ValueError) as exc:
                raise InvalidEventError("PressureStep target_mmhg must be numeric.") from exc

        steps.append(
            StepSegment(
                index=index,
                start_s=event.start_s,
                end_s=event.end_s,
                target_mmhg=target,
                label=event.label,
            )
        )
        prev_start = event.start_s
        prev_end = event.end_s

    return tuple(steps)
