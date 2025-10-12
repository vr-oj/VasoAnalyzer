import sqlite3
from pathlib import Path

from vasoanalyzer.storage.sqlite_utils import connect_rw
from vasoanalyzer.tools.portable_export import export_single_file


def _pragma(conn: sqlite3.Connection, query: str) -> str:
    return conn.execute(query).fetchone()[0]


def test_export_is_delete_mode(tmp_path):
    src = tmp_path / "src.vaso"
    with sqlite3.connect(src) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t(v) VALUES ('x')")
        conn.commit()

    out = tmp_path / "out.vaso"
    export_single_file(str(src), str(out))

    assert out.exists()
    assert not (Path(str(out) + "-wal").exists())
    assert not (Path(str(out) + "-shm").exists())

    with connect_rw(str(out)) as conn:
        mode = _pragma(conn, "PRAGMA journal_mode;").lower()
        assert mode == "delete"


def test_tiff_externalization(tmp_path):
    src = tmp_path / "src2.vaso"
    with sqlite3.connect(src) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE assets(
                id INTEGER PRIMARY KEY,
                media_type TEXT,
                is_embedded INT,
                blob BLOB,
                sha256 TEXT,
                path_hint TEXT
            )
            """
        )
        blob = b"TIFF89" + b"0" * 20
        conn.execute(
            "INSERT INTO assets(media_type, is_embedded, blob, sha256, path_hint) VALUES (?, ?, ?, ?, ?)",
            ("image/tiff", 1, blob, None, None),
        )
        conn.commit()

    assets_dir = tmp_path / "assets_out"
    out = tmp_path / "shareable.vaso"
    export_single_file(str(src), str(out), link_snapshot_tiffs=True, extract_tiffs_dir=str(assets_dir))

    with sqlite3.connect(out) as conn:
        row = conn.execute("SELECT is_embedded, blob, sha256, path_hint FROM assets").fetchone()
        assert row[0] == 0
        assert row[1] is None
        assert row[2] is not None and len(row[2]) == 64
        assert row[3].startswith("assets/") and row[3].endswith(".tif")

    tif_files = list((assets_dir / "assets").glob("*.tif"))
    assert len(tif_files) == 1
    assert tif_files[0].exists()
