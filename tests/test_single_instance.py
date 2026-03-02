from __future__ import annotations

import json

from vasoanalyzer.core.single_instance import collect_vaso_paths, parse_ipc_message


def test_collect_vaso_paths_filters_and_normalizes(tmp_path):
    existing = tmp_path / "demo.vaso"
    existing.write_text("ok")
    missing = tmp_path / "missing.vaso"
    other = tmp_path / "notes.txt"

    argv = ["VasoAnalyzer", str(existing), str(missing), str(other)]
    paths = collect_vaso_paths(argv)

    assert paths == [str(existing.resolve())]


def test_parse_ipc_message_extracts_vaso_paths(tmp_path):
    target = str((tmp_path / "project.vaso").resolve())
    payload = json.dumps({"open": [target, str(tmp_path / "ignore.txt"), 123]})

    paths = parse_ipc_message(payload)

    assert paths == [target]
