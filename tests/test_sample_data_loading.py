import pytest
from pathlib import Path

pytest.importorskip("pandas")

from vasoanalyzer.trace_loader import load_trace
from vasoanalyzer.event_loader import load_events

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample data"


def _trace_files():
    for p in SAMPLE_DIR.rglob("*.csv"):
        name = p.name.lower()
        if "table" in name or "profile" in name or "output" in name:
            continue
        yield p


def _event_files():
    for p in SAMPLE_DIR.rglob("*.csv"):
        name = p.name.lower()
        if "table" in name and "profile" not in name:
            yield p


def test_load_sample_traces():
    for fpath in _trace_files():
        df = load_trace(str(fpath))
        assert not df.empty
        assert "Time (s)" in df.columns
        assert "Inner Diameter" in df.columns


def test_load_sample_events():
    for fpath in _event_files():
        labels, times, frames = load_events(str(fpath))
        assert isinstance(labels, list)
        assert isinstance(times, list)
        assert frames is None or isinstance(frames, list)
