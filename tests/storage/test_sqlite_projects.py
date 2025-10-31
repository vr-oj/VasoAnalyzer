from vasoanalyzer.storage.sqlite import projects
from vasoanalyzer.storage.sqlite.utils import open_db
from vasoanalyzer.storage.sqlite_store import SCHEMA_VERSION


def test_meta_roundtrip(tmp_path):
    db_path = tmp_path / "proj.db"
    conn = open_db(db_path.as_posix())
    try:
        projects.apply_default_pragmas(conn)
        projects.ensure_schema(
            conn,
            schema_version=SCHEMA_VERSION,
            now="2000-01-01T00:00:00Z",
        )
        initial_meta = projects.read_meta(conn)
        assert "created_utc" in initial_meta
        assert "modified_utc" in initial_meta
        assert initial_meta["format"] == "sqlite-v3"
        assert initial_meta["project_version"] == str(SCHEMA_VERSION)

        projects.write_meta(conn, {"title": "Test"})
        conn.commit()

        updated_meta = projects.read_meta(conn)
        assert updated_meta["title"] == "Test"
    finally:
        conn.close()
