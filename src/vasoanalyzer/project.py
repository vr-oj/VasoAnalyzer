from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional

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


# JSON I/O --------------------------------------------------------------


def project_to_dict(project: Project) -> dict:
    return asdict(project)


def project_from_dict(data: dict) -> Project:
    experiments = []
    for exp in data.get("experiments", []):
        samples = [SampleN(**s) for s in exp.get("samples", [])]
        experiments.append(
            Experiment(
                name=exp.get("name", ""),
                excel_path=exp.get("excel_path"),
                next_column=exp.get("next_column", "B"),
                samples=samples,
            )
        )
    return Project(
        name=data.get("name", ""), experiments=experiments, path=data.get("path")
    )


def save_project(project: Project, path: str) -> None:
    project.path = path
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project_to_dict(project), f, indent=2)


def load_project(path: str) -> Project:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
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
