import pandas as pd

from vasoanalyzer.services.project_service import create_project_repository
from vasoanalyzer.storage import sqlite_store


def test_sqlite_project_repository_roundtrip(tmp_path):
    repo_path = tmp_path / "repo.vaso"
    repo = create_project_repository(
        repo_path.as_posix(),
        app_version="test",
        timezone="UTC",
    )
    try:
        store = repo.store
        sqlite_store.add_dataset(
            store,
            name="sample",
            trace_df=pd.DataFrame({"t_seconds": [0.0, 1.0], "inner_diam": [10.0, 11.0]}),
            events_df=pd.DataFrame({"t_seconds": [0.0], "label": ["start"]}),
            metadata={},
        )
        repo.commit()

        trace = repo.get_trace(1)
        assert list(trace["t_seconds"]) == [0.0, 1.0]

        events = repo.get_events(1)
        assert list(events["label"]) == ["start"]

        assert repo.list_assets(1) == []
        asset_id = sqlite_store.add_or_update_asset(
            store,
            dataset_id=1,
            role="blob",
            path_or_bytes=b"data",
            embed=True,
        )
        assert repo.get_asset_bytes(asset_id) == b"data"
    finally:
        repo.close()
