import sqlite3

from vasoanalyzer.storage.sqlite import projects as _projects
from vasoanalyzer.storage.sqlite_store import create_project, save_project


def test_save_project_updates_metadata(tmp_path):
    project_path = tmp_path / "pipeline.vaso"
    store = create_project(project_path, app_version="test", timezone="UTC")
    try:
        initial_meta = _projects.read_meta(store.conn)
        assert initial_meta["format"] == "sqlite-v3"
        save_project(store)
        assert project_path.exists()
        # Connection remains usable after the save cycle.
        count_row = store.conn.execute("SELECT COUNT(*) FROM dataset").fetchone()
        assert count_row[0] == 0

        with sqlite3.connect(project_path.as_posix()) as conn:
            meta = dict(conn.execute("SELECT key, value FROM meta"))

        assert meta["format"] == "sqlite-v3"
        assert meta["modified_at"] == meta["modified_utc"]
        assert meta["modified_at"] >= initial_meta["modified_at"]
    finally:
        store.close()
