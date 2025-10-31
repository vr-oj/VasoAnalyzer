from pathlib import Path

from vasoanalyzer.storage.sqlite_store import (
    ProjectStore,
    create_project,
    add_or_update_asset,
    list_assets,
    get_asset_bytes,
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
        assert assets[0]["id"] == asset_id
        data = get_asset_bytes(store, asset_id)
        assert data == payload
    finally:
        store.close()


def test_add_or_update_asset_external(tmp_path):
    store = _open_temp_store(tmp_path)
    try:
        store.conn.execute(
            """
            INSERT INTO dataset(id, name, created_utc)
            VALUES (1, 'sample', '2000-01-01T00:00:00Z')
            """
        )
        file_path = tmp_path / "asset.bin"
        file_path.write_bytes(b"abc")
        asset_id = add_or_update_asset(
            store,
            dataset_id=1,
            role="test",
            path_or_bytes=file_path,
            embed=False,
        )
        assets = list_assets(store, 1)
        assert assets[0]["storage"] == "external"
        assert get_asset_bytes(store, asset_id) == b"abc"
    finally:
        store.close()
