from pathlib import Path

import pandas as pd

from vasoanalyzer.core.project import Experiment, Project, SampleN, load_project, save_project


def _make_trace_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Time (s)": [0.0, 1.0],
            "Inner Diameter": [50.0, 50.5],
            "Outer Diameter": [60.0, 60.5],
            "Avg Pressure (mmHg)": [80.0, 80.2],
            "Set Pressure (mmHg)": [90.0, 90.0],
        }
    )


def test_composer_state_ignored_on_save_reload(tmp_path: Path) -> None:
    sample = SampleN(
        name="SampleA",
        trace_data=_make_trace_df(),
        ui_state={
            "axis_xlim": (0.0, 1.0),
            "figure_slides": [{"id": "legacy-1", "name": "Legacy"}],
        },
    )
    project = Project(name="TestProject", experiments=[Experiment(name="ExpA", samples=[sample])])
    vaso_path = tmp_path / "legacy_composer.vaso"

    save_project(project, vaso_path.as_posix())
    project.close()

    loaded = load_project(vaso_path.as_posix())
    try:
        loaded_sample = loaded.experiments[0].samples[0]
        assert loaded_sample.ui_state is not None
        axis_xlim = loaded_sample.ui_state.get("axis_xlim")
        assert axis_xlim is not None
        assert tuple(axis_xlim) == (0.0, 1.0)
        assert "figure_slides" not in loaded_sample.ui_state
        save_project(loaded, vaso_path.as_posix())
    finally:
        loaded.close()

    reopened = load_project(vaso_path.as_posix())
    try:
        reopened_sample = reopened.experiments[0].samples[0]
        assert "figure_slides" not in (reopened_sample.ui_state or {})
    finally:
        reopened.close()
