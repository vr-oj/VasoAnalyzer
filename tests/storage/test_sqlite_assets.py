from pathlib import Path

from vasoanalyzer.storage.sqlite_store import (
    ProjectStore,
    add_or_update_asset,
    create_project,
    get_asset_bytes,
    list_assets,
)


def _open_temp_store(tmp_path: Path) -> ProjectStore:
    db_path = tmp_path / "project.vaso"
    store = create_project(db_path, app_version="test", timezone="UTC")
    return store


def test_add_or_update_asset_embedded(tmp_path):
    store = _open_temp_store(tmp_path)
    try:
        # Minimal dataset
        store.conn.execute(
            """
            INSERT INTO dataset(id, name, created_utc)
            VALUES (1, 'sample', '2000-01-01T00:00:00Z')
            """
        )
        payload = b"hello"
        asset_id = add_or_update_asset(
            store,
            dataset_id=1,
            role="test",
            path_or_bytes=payload,
            embed=True,
        )
        assets = list_assets(store, 1)
        assert len(assets) == 1
        asset = assets[0]
        assert asset["id"] == asset_id
        assert asset["role"] == "test"
        assert asset["sha256"]
        assert asset["size_bytes"] == len(payload)
        assert asset["compressed"] is True
        assert asset["chunk_size"] > 0
        data = get_asset_bytes(store, asset_id)
        assert data == payload
    finally:
        store.close()


def test_add_or_update_asset_deduplicates(tmp_path):
    store = _open_temp_store(tmp_path)
    try:
        store.conn.execute(
            """
            INSERT INTO dataset(id, name, created_utc)
            VALUES (1, 'sample', '2000-01-01T00:00:00Z')
            """
        )
        payload = b"abc123"
        asset_id = add_or_update_asset(
            store,
            dataset_id=1,
            role="test",
            path_or_bytes=payload,
            embed=True,
        )
        second_id = add_or_update_asset(
            store,
            dataset_id=1,
            role="test",
            path_or_bytes=payload,
            embed=True,
        )
        assets = list_assets(store, 1)
        assert len(assets) == 1
        assert assets[0]["id"] == second_id == asset_id
        assert get_asset_bytes(store, asset_id) == payload
    finally:
        store.close()


def test_add_or_update_asset_rejects_external(tmp_path):
    store = _open_temp_store(tmp_path)
    try:
        store.conn.execute(
            """
            INSERT INTO dataset(id, name, created_utc)
            VALUES (1, 'sample', '2000-01-01T00:00:00Z')
            """
        )
        try:
            add_or_update_asset(
                store,
                dataset_id=1,
                role="test",
                path_or_bytes=b"x",
                embed=False,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Expected ValueError for non-embedded asset")
    finally:
        store.close()
