import sqlite3
from pathlib import Path

from vasoanalyzer.storage import sqlite_store
from vasoanalyzer.storage.sqlite_store import LegacyProjectError


def _create_legacy_project(path: Path) -> None:
    with sqlite3.connect(path.as_posix()) as conn:
        conn.executescript(
            """
            PRAGMA user_version = 1;
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta(key, value) VALUES('created_utc', '2000-01-01T00:00:00Z');
            INSERT INTO meta(key, value) VALUES('modified_utc', '2000-01-01T00:00:00Z');

            CREATE TABLE dataset(
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                notes TEXT,
                fps REAL,
                pixel_size_um REAL,
                t0_seconds REAL DEFAULT 0,
                extra_json TEXT
            );

            CREATE TABLE trace(
                dataset_id INTEGER NOT NULL,
                t_seconds REAL NOT NULL,
                inner_diam REAL,
                outer_diam REAL,
                p_avg REAL,
                p1 REAL,
                p2 REAL,
                PRIMARY KEY(dataset_id, t_seconds)
            ) WITHOUT ROWID;

            CREATE TABLE event(
                id INTEGER PRIMARY KEY,
                dataset_id INTEGER NOT NULL,
                t_seconds REAL NOT NULL,
                label TEXT NOT NULL,
                frame INTEGER,
                p_avg REAL,
                p1 REAL,
                p2 REAL,
                temp REAL,
                extra_json TEXT
            );

            CREATE TABLE asset(
                id INTEGER PRIMARY KEY,
                dataset_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                storage TEXT NOT NULL,
                rel_path TEXT,
                sha256 TEXT NOT NULL,
                bytes INTEGER,
                mime TEXT
            );

            CREATE TABLE blob_chunk(
                asset_id INTEGER NOT NULL,
                seq INTEGER NOT NULL,
                data BLOB NOT NULL,
                PRIMARY KEY(asset_id, seq)
            ) WITHOUT ROWID;
            """
        )
        conn.execute(
            "INSERT INTO dataset(id, name, created_utc) VALUES(1, 'legacy', '2000-01-01T00:00:00Z')"
        )
        payload = b"legacy-payload"
        conn.execute(
            """
            INSERT INTO asset(id, dataset_id, role, storage, rel_path, sha256, bytes, mime)
            VALUES(1, 1, 'legacy_blob', 'embedded', NULL, 'deadbeef', ?, 'application/octet-stream')
            """,
            (len(payload),),
        )
        conn.execute(
            "INSERT INTO blob_chunk(asset_id, seq, data) VALUES(1, 0, ?)",
            (payload,),
        )
        conn.commit()


def test_convert_legacy_project(tmp_path):
    project_path = tmp_path / "legacy.vaso"
    _create_legacy_project(project_path)

    try:
        sqlite_store.open_project(project_path)
    except LegacyProjectError:
        pass
    else:
        raise AssertionError("Expected LegacyProjectError for legacy schema")

    store = sqlite_store.convert_legacy_project(project_path)
    try:
        assets = sqlite_store.list_assets(store, 1)
        assert len(assets) == 1
        asset = assets[0]
        assert asset["role"] == "legacy_blob"
        assert asset["compressed"] is True
        data = sqlite_store.get_asset_bytes(store, asset["id"])
        assert data == b"legacy-payload"

        meta = sqlite_store.get_dataset_meta(store, 1)
        assert meta is not None

        backup_path = project_path.with_suffix(project_path.suffix + ".bak1")
        assert backup_path.exists()
    finally:
        store.close()
