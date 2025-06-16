from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import pandas as pd
from .event_loader import _standardize_headers

__all__ = [
    "Project",
    "Experiment",
    "SampleN",
    "load_project",
    "save_project",
    "export_sample",
]


@dataclass
class SampleN:
    name: str
    trace_path: Optional[str] = None
    events_path: Optional[str] = None
    diameter_data: Optional[List[float]] = None
    exported: bool = False
    column: Optional[str] = None
    trace_data: Optional[pd.DataFrame] = None
    events_data: Optional[pd.DataFrame] = None


@dataclass
class Experiment:
    name: str
    excel_path: Optional[str] = None
    next_column: str = "B"
    samples: List[SampleN] = field(default_factory=list)


@dataclass
class Project:
    name: str
    experiments: List[Experiment] = field(default_factory=list)
    path: Optional[str] = None
    ui_state: Optional[dict] = None


# JSON I/O --------------------------------------------------------------


def sample_to_dict(sample: SampleN) -> dict:
    data = asdict(sample)
    if isinstance(sample.trace_data, pd.DataFrame):
        data["trace_data"] = sample.trace_data.to_dict(orient="list")
    if isinstance(sample.events_data, pd.DataFrame):
        data["events_data"] = sample.events_data.to_dict(orient="list")
    return data


def project_to_dict(project: Project) -> dict:
    proj_dict = {
        "name": project.name,
        "path": project.path,
        "experiments": [],
        "ui_state": project.ui_state,
    }
    for exp in project.experiments:
        exp_dict = {
            "name": exp.name,
            "excel_path": exp.excel_path,
            "next_column": exp.next_column,
            "samples": [sample_to_dict(s) for s in exp.samples],
        }
        proj_dict["experiments"].append(exp_dict)
    return proj_dict


def sample_from_dict(data: dict) -> SampleN:
    trace_data = data.get("trace_data")
    if isinstance(trace_data, dict):
        trace_data = pd.DataFrame(trace_data)

    events_data = data.get("events_data")
    if isinstance(events_data, dict):
        events_data = pd.DataFrame(events_data)
    if isinstance(events_data, pd.DataFrame):
        events_data = _standardize_headers(events_data)

    return SampleN(
        name=data.get("name", ""),
        trace_path=data.get("trace_path"),
        events_path=data.get("events_path"),
        diameter_data=data.get("diameter_data"),
        exported=data.get("exported", False),
        column=data.get("column"),
        trace_data=trace_data,
        events_data=events_data,
    )


def project_from_dict(data: dict) -> Project:
    experiments = []
    for exp in data.get("experiments", []):
        samples = [sample_from_dict(s) for s in exp.get("samples", [])]
        experiments.append(
            Experiment(
                name=exp.get("name", ""),
                excel_path=exp.get("excel_path"),
                next_column=exp.get("next_column", "B"),
                samples=samples,
            )
        )
    return Project(
        name=data.get("name", ""),
        experiments=experiments,
        path=data.get("path"),
        ui_state=data.get("ui_state"),
    )


def save_project(project: Project, path: str) -> None:
    """Safely save ``project`` to ``path`` with a backup."""
    import os
    import shutil

    project.path = str(path)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(project_to_dict(project), f, indent=2)

    if os.path.exists(path):
        shutil.copy2(path, f"{path}.bak")
    os.replace(tmp_path, path)


def load_project(path: str) -> Project:
    """Load a project file, falling back to ``.bak`` if needed."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        bak = f"{path}.bak"
        with open(bak, "r", encoding="utf-8") as f:
            data = json.load(f)
        path = bak
    proj = project_from_dict(data)
    proj.path = path
    return proj


# Export helpers --------------------------------------------------------


def _increment_column(col: str) -> str:
    if not col:
        return "B"
    import string

    letters = string.ascii_uppercase
    idx = letters.index(col[-1]) + 1
    if idx >= len(letters):
        return col + "A"
    return letters[idx]


def export_sample(exp: Experiment, sample: SampleN) -> None:
    sample.exported = True
    sample.column = exp.next_column
    exp.next_column = _increment_column(exp.next_column)
