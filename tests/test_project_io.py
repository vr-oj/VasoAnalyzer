import json
from vasoanalyzer.project import (
    Project,
    Experiment,
    SampleN,
    save_project,
    load_project,
    export_sample,
)


def test_project_save_load(tmp_path):
    proj = Project(name="P")
    exp = Experiment(name="E")
    exp.samples.append(SampleN(name="N1"))
    proj.experiments.append(exp)
    path = tmp_path / "proj.vasoproj"
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
    path = tmp_path / "proj.vasoproj"
    save_project(proj, path)

    loaded = load_project(path)
    loaded_s = loaded.experiments[0].samples[0]
    assert loaded_s.trace_path == "trace.csv"
    assert loaded_s.events_path == "events.csv"
