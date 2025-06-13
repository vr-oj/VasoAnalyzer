import json

import pandas as pd

from vasoanalyzer.event_loader import load_events
from vasoanalyzer.project import (
    Experiment,
    Project,
    SampleN,
    export_sample,
    load_project,
    save_project,
)
from vasoanalyzer.trace_loader import load_trace


def test_project_save_load(tmp_path):
    proj = Project(name="P")
    exp = Experiment(name="E")
    exp.samples.append(SampleN(name="N1"))
    proj.experiments.append(exp)
    path = tmp_path / "proj.vaso"
    save_project(proj, path)
    loaded = load_project(path)
    assert loaded.name == "P"
    assert loaded.experiments[0].samples[0].name == "N1"


def test_export_sample():
    exp = Experiment(name="E", next_column="B", samples=[SampleN(name="N1")])
    s = exp.samples[0]
    export_sample(exp, s)
    assert s.exported is True
    assert s.column == "B"
    assert exp.next_column == "C"


def test_trace_event_paths_persist(tmp_path):
    proj = Project(name="P")
    exp = Experiment(name="E")
    s = SampleN(name="N1", trace_path="trace.csv", events_path="events.csv")
    exp.samples.append(s)
    proj.experiments.append(exp)
    path = tmp_path / "proj.vaso"
    save_project(proj, path)

    loaded = load_project(path)
    loaded_s = loaded.experiments[0].samples[0]
    assert loaded_s.trace_path == "trace.csv"
    assert loaded_s.events_path == "events.csv"


def test_embedded_data_persistence(tmp_path):
    trace_path = tmp_path / "trace.csv"
    df_trace = pd.DataFrame({"Time (s)": [0, 1], "Inner Diameter": [10, 11]})
    df_trace.to_csv(trace_path, index=False)

    events_path = tmp_path / "events.csv"
    df_events = pd.DataFrame({"label": ["A"], "time": [0.5], "frame": [5]})
    df_events.to_csv(events_path, index=False)

    loaded_trace = load_trace(str(trace_path))
    labels, times, frames = load_events(str(events_path))
    events_df = pd.DataFrame({"label": labels, "time": times, "frame": frames})

    sample = SampleN(
        name="N1",
        trace_path=str(trace_path),
        events_path=str(events_path),
        trace_data=loaded_trace,
        events_data=events_df,
    )
    exp = Experiment(name="E", samples=[sample])
    proj = Project(name="P", experiments=[exp])

    save_path = tmp_path / "proj.vaso"
    save_project(proj, save_path)

    trace_path.unlink()
    events_path.unlink()

    loaded_proj = load_project(save_path)
    ls = loaded_proj.experiments[0].samples[0]

    pd.testing.assert_frame_equal(ls.trace_data, loaded_trace)
    pd.testing.assert_frame_equal(ls.events_data, events_df)

def test_ui_state_persistence(tmp_path):
    proj = Project(name="P", ui_state={"geometry": "abcd"})
    path = tmp_path / "proj.vaso"
    save_project(proj, path)
    loaded = load_project(path)
    assert loaded.ui_state == {"geometry": "abcd"}
