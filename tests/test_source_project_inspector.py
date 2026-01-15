from pathlib import Path

import pandas as pd

from vasoanalyzer.core.project import Experiment, Project, SampleN, save_project
from vasoanalyzer.ui.dialogs.source_project_browser import inspect_source_project


def _build_project(tmp_path: Path) -> Path:
    trace_df = pd.DataFrame({"t_seconds": [0.0, 1.0], "inner_diam": [10.0, 10.5]})
    events_df = pd.DataFrame({"t_seconds": [0.0, 1.0], "label": ["start", "stop"]})
    sample_a = SampleN(name="A1", trace_data=trace_df, events_data=events_df)
    sample_b = SampleN(name="B1", trace_data=trace_df, events_data=events_df)
    project = Project(
        name="InspectorProj",
        experiments=[
            Experiment(name="Exp1", samples=[sample_a]),
            Experiment(name="Exp2", samples=[sample_b]),
        ],
    )
    path = tmp_path / "inspector.vaso"
    save_project(project, path.as_posix())
    project.close()
    return path


def test_inspector_lists_experiments_and_datasets(tmp_path: Path):
    proj_path = _build_project(tmp_path)
    info = inspect_source_project(proj_path)

    exp_names = {exp.name for exp in info.experiments}
    assert exp_names == {"Exp1", "Exp2"}

    total_datasets = sum(len(exp.datasets) for exp in info.experiments)
    assert total_datasets == 2

    # Validate event counts were read
    counts = {ds.dataset_name: ds.event_count for exp in info.experiments for ds in exp.datasets}
    assert counts["A1"] == 2
    assert counts["B1"] == 2
