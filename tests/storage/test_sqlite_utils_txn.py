from vasoanalyzer.storage.sqlite.utils import open_db, transaction, db_cursor


def test_transaction_commits_and_rolls_back(tmp_path):
    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))

    with db_cursor(conn) as cur:
        cur.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")

    # Commit path
    with transaction(conn):
        with db_cursor(conn) as cur:
            cur.execute("INSERT INTO t (v) VALUES (1)")

    with db_cursor(conn) as cur:
        cur.execute("SELECT COUNT(*) FROM t")
        assert cur.fetchone()[0] == 1

    # Rollback path
    try:
        with transaction(conn):
            with db_cursor(conn) as cur:
                cur.execute("INSERT INTO t (v) VALUES (2)")
                raise RuntimeError("boom")
    except RuntimeError:
        pass

    with db_cursor(conn) as cur:
        cur.execute("SELECT COUNT(*) FROM t")
        assert cur.fetchone()[0] == 1

    conn.close()
