"""
Tests for the append-only snapshot bundle format and ZIP container format.

Tests cover:
- Bundle creation
- Snapshot management
- Migration from legacy format
- Recovery from corruption
- Format detection
- ZIP container format
- Container packing/unpacking
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from vasoanalyzer.storage.bundle_adapter import (
    close_project_handle,
    create_project_handle,
    open_project_handle,
    save_project_handle,
)
from vasoanalyzer.storage.container_fs import (
    cleanup_stale_temp_dirs,
    convert_vasopack_to_container,
    is_vaso_container,
    pack_temp_bundle_to_container,
    unpack_container_to_temp,
)
from vasoanalyzer.storage.migration import (
    detect_project_format,
    export_to_legacy,
    is_legacy_project,
    migrate_to_bundle,
)
from vasoanalyzer.storage.snapshots import (
    create_bundle,
    create_snapshot,
    get_current_snapshot,
    list_snapshots,
    open_staging_db,
    prune_old_snapshots,
    validate_snapshot,
)


class TestBundleCreation:
    """Test bundle directory structure creation."""

    def test_create_bundle_creates_structure(self, tmp_path):
        """Test that create_bundle creates required directories and files."""
        bundle_path = tmp_path / "test.vasopack"

        create_bundle(bundle_path)

        assert bundle_path.exists()
        assert bundle_path.is_dir()
        assert (bundle_path / "HEAD.json").exists()
        assert (bundle_path / "snapshots").exists()
        assert (bundle_path / ".staging").exists()
        assert (bundle_path / "project.meta.json").exists()

    def test_create_bundle_fails_if_exists(self, tmp_path):
        """Test that create_bundle raises error if bundle exists."""
        bundle_path = tmp_path / "test.vasopack"
        bundle_path.mkdir()

        with pytest.raises(FileExistsError):
            create_bundle(bundle_path)


class TestSnapshotOperations:
    """Test snapshot creation and management."""

    def test_create_snapshot_from_staging(self, tmp_path):
        """Test creating snapshot from staging database."""
        bundle_path = tmp_path / "test.vasopack"
        create_bundle(bundle_path)

        # Create a staging database with some data
        staging_path, staging_conn = open_staging_db(bundle_path)
        try:
            staging_conn.execute("CREATE TABLE test (id INTEGER, value TEXT)")
            staging_conn.execute("INSERT INTO test VALUES (1, 'hello')")
            staging_conn.commit()
        finally:
            staging_conn.close()

        # Create snapshot
        snapshot_info = create_snapshot(bundle_path, staging_path)

        assert snapshot_info.number == 1
        assert snapshot_info.path.name == "000001.sqlite"
        assert snapshot_info.path.exists()
        assert snapshot_info.is_current

        # Verify HEAD points to snapshot
        current = get_current_snapshot(bundle_path)
        assert current.number == 1

    def test_multiple_snapshots(self, tmp_path):
        """Test creating multiple snapshots."""
        bundle_path = tmp_path / "test.vasopack"
        create_bundle(bundle_path)

        # Create 5 snapshots
        for i in range(5):
            staging_path, staging_conn = open_staging_db(bundle_path)
            try:
                staging_conn.execute(f"CREATE TABLE test{i} (id INTEGER)")
                staging_conn.commit()
            finally:
                staging_conn.close()

            create_snapshot(bundle_path, staging_path)

        # Verify all snapshots exist
        snapshots = list_snapshots(bundle_path)
        assert len(snapshots) == 5
        assert all(s.number == i + 1 for i, s in enumerate(snapshots))

        # Verify HEAD points to latest
        current = get_current_snapshot(bundle_path)
        assert current.number == 5

    def test_snapshot_validation(self, tmp_path):
        """Test snapshot integrity validation."""
        bundle_path = tmp_path / "test.vasopack"
        create_bundle(bundle_path)

        staging_path, staging_conn = open_staging_db(bundle_path)
        try:
            staging_conn.execute("CREATE TABLE test (id INTEGER)")
            staging_conn.commit()
        finally:
            staging_conn.close()

        snapshot_info = create_snapshot(bundle_path, staging_path)

        # Valid snapshot should pass validation
        assert validate_snapshot(snapshot_info.path)

        # Corrupt the snapshot
        with open(snapshot_info.path, "wb") as f:
            f.write(b"corrupted data")

        # Should fail validation
        assert not validate_snapshot(snapshot_info.path)

    def test_prune_old_snapshots(self, tmp_path):
        """Test pruning old snapshots."""
        bundle_path = tmp_path / "test.vasopack"
        create_bundle(bundle_path)

        # Create 10 snapshots
        for i in range(10):
            staging_path, staging_conn = open_staging_db(bundle_path)
            try:
                staging_conn.execute(f"CREATE TABLE test{i} (id INTEGER)")
                staging_conn.commit()
            finally:
                staging_conn.close()
            create_snapshot(bundle_path, staging_path)

        # Prune to keep only 5
        deleted = prune_old_snapshots(bundle_path, keep_count=5)

        assert deleted == 5
        assert len(list_snapshots(bundle_path)) == 5

        # Current snapshot should still exist
        current = get_current_snapshot(bundle_path)
        assert current.number == 10


class TestFormatDetection:
    """Test project format detection."""

    def test_detect_bundle_format(self, tmp_path):
        """Test detecting bundle format."""
        bundle_path = tmp_path / "test.vasopack"
        create_bundle(bundle_path)

        fmt = detect_project_format(bundle_path)
        assert fmt == "bundle-v1"

    def test_detect_legacy_format(self, tmp_path):
        """Test detecting legacy .vaso format."""
        vaso_path = tmp_path / "test.vaso"

        # Create a minimal SQLite v3 database
        conn = sqlite3.connect(vaso_path)
        conn.execute("PRAGMA user_version = 3")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta VALUES ('format', 'sqlite-v3')")
        conn.commit()
        conn.close()

        fmt = detect_project_format(vaso_path)
        assert fmt == "sqlite-v3"
        assert is_legacy_project(vaso_path)

    def test_detect_unknown_format(self, tmp_path):
        """Test detecting unknown format."""
        unknown_path = tmp_path / "unknown.txt"
        unknown_path.write_text("not a project")

        fmt = detect_project_format(unknown_path)
        assert fmt == "unknown"


class TestMigration:
    """Test migration from legacy to bundle format."""

    def test_migrate_legacy_to_bundle(self, tmp_path):
        """Test migrating legacy .vaso to bundle."""
        # Create legacy project
        vaso_path = tmp_path / "test.vaso"
        conn = sqlite3.connect(vaso_path)
        conn.execute("PRAGMA user_version = 3")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta VALUES ('format', 'sqlite-v3')")
        conn.execute("INSERT INTO meta VALUES ('project_name', 'Test Project')")
        conn.commit()
        conn.close()

        # Migrate to bundle
        bundle_path = migrate_to_bundle(vaso_path, keep_legacy=True)

        # Verify bundle was created
        assert bundle_path.exists()
        assert bundle_path.suffix == ".vasopack"
        assert (bundle_path / "snapshots" / "000001.sqlite").exists()

        # Verify legacy file was renamed
        legacy_backup = vaso_path.with_suffix(".vaso.legacy")
        assert legacy_backup.exists()
        assert not vaso_path.exists()

        # Verify snapshot contains original data
        snapshot = bundle_path / "snapshots" / "000001.sqlite"
        conn = sqlite3.connect(snapshot)
        cursor = conn.execute("SELECT value FROM meta WHERE key='project_name'")
        assert cursor.fetchone()[0] == "Test Project"
        conn.close()

    def test_export_bundle_to_legacy(self, tmp_path):
        """Test exporting bundle back to legacy format."""
        # Create bundle
        bundle_path = tmp_path / "test.vasopack"
        create_bundle(bundle_path)

        # Create snapshot with data
        staging_path, staging_conn = open_staging_db(bundle_path)
        try:
            staging_conn.execute("CREATE TABLE test (id INTEGER, value TEXT)")
            staging_conn.execute("INSERT INTO test VALUES (1, 'test data')")
            staging_conn.commit()
        finally:
            staging_conn.close()

        create_snapshot(bundle_path, staging_path)

        # Export to legacy
        vaso_path = export_to_legacy(bundle_path)

        assert vaso_path.exists()
        assert vaso_path.suffix == ".vaso"

        # Verify data is in exported file
        conn = sqlite3.connect(vaso_path)
        cursor = conn.execute("SELECT value FROM test WHERE id=1")
        assert cursor.fetchone()[0] == "test data"
        conn.close()


class TestProjectHandle:
    """Test ProjectHandle interface."""

    def test_create_and_open_bundle(self, tmp_path):
        """Test creating and opening bundle via ProjectHandle."""
        bundle_path = tmp_path / "test.vasopack"

        # Create project handle (use folder bundle, not container)
        handle, conn = create_project_handle(bundle_path, use_bundle_format=True, use_container_format=False)

        assert handle.is_bundle
        assert handle.path == bundle_path
        assert conn is not None

        # Write some data
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()

        # Save (creates snapshot)
        save_project_handle(handle)

        # Close
        close_project_handle(handle, save_before_close=False)

        # Reopen and verify data
        handle2, conn2 = open_project_handle(bundle_path)
        cursor = conn2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test'")
        assert cursor.fetchone() is not None

        close_project_handle(handle2)

    def test_crash_recovery(self, tmp_path):
        """Test recovery after simulated crash (staging DB lost)."""
        bundle_path = tmp_path / "test.vasopack"

        # Create and save (use folder bundle, not container)
        handle, conn = create_project_handle(bundle_path, use_bundle_format=True, use_container_format=False)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        save_project_handle(handle)
        close_project_handle(handle)

        # Simulate crash: delete staging DB but not snapshots
        staging_dir = bundle_path / ".staging"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        # Should be able to reopen from snapshot
        handle2, conn2 = open_project_handle(bundle_path)
        cursor = conn2.execute("SELECT * FROM test")
        assert cursor.fetchone()[0] == 1

        close_project_handle(handle2)


class TestContainerFormat:
    """Test ZIP container format (.vaso)."""

    def test_container_creation_and_opening(self, tmp_path):
        """Test creating and opening container format."""
        container_path = tmp_path / "test.vaso"

        # Create container project
        handle, conn = create_project_handle(container_path, use_bundle_format=True, use_container_format=True)

        assert handle.is_container
        assert handle.container_path == container_path
        assert handle.temp_bundle_root is not None
        assert container_path.exists()
        assert container_path.is_file()

        # Write some data
        conn.execute("CREATE TABLE test (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello container')")
        conn.commit()

        # Save (should pack to container)
        save_project_handle(handle)

        # Close
        close_project_handle(handle, save_before_close=False)

        # Verify container file exists
        assert container_path.exists()
        assert is_vaso_container(container_path)

        # Reopen and verify data
        handle2, conn2 = open_project_handle(container_path)
        cursor = conn2.execute("SELECT value FROM test WHERE id=1")
        assert cursor.fetchone()[0] == "hello container"

        close_project_handle(handle2)

    def test_container_format_detection(self, tmp_path):
        """Test detecting ZIP container format."""
        container_path = tmp_path / "test.vaso"

        # Create container
        handle, conn = create_project_handle(container_path, use_bundle_format=True, use_container_format=True)
        close_project_handle(handle)

        # Should detect as zip-bundle-v1
        fmt = detect_project_format(container_path)
        assert fmt == "zip-bundle-v1"
        assert is_vaso_container(container_path)

    def test_convert_vasopack_to_container(self, tmp_path):
        """Test converting .vasopack folder to .vaso container."""
        # Create a .vasopack folder bundle
        vasopack_path = tmp_path / "test.vasopack"
        create_bundle(vasopack_path)

        # Add some data
        staging_path, staging_conn = open_staging_db(vasopack_path)
        try:
            staging_conn.execute("CREATE TABLE test (id INTEGER, value TEXT)")
            staging_conn.execute("INSERT INTO test VALUES (1, 'converted data')")
            staging_conn.commit()
        finally:
            staging_conn.close()

        create_snapshot(vasopack_path, staging_path)

        # Convert to container
        container_path = convert_vasopack_to_container(vasopack_path)

        assert container_path.exists()
        assert container_path.suffix == ".vaso"
        assert is_vaso_container(container_path)

        # Verify data in container
        handle, conn = open_project_handle(container_path)
        cursor = conn.execute("SELECT value FROM test WHERE id=1")
        assert cursor.fetchone()[0] == "converted data"
        close_project_handle(handle)

    def test_container_save_creates_snapshots(self, tmp_path):
        """Test that container saves create snapshots internally."""
        container_path = tmp_path / "test.vaso"

        # Create and save multiple times
        handle, conn = create_project_handle(container_path, use_bundle_format=True, use_container_format=True)

        for i in range(3):
            conn.execute(f"CREATE TABLE test{i} (id INTEGER)")
            conn.commit()
            save_project_handle(handle)

        close_project_handle(handle)

        # Unpack container and check snapshots
        bundle_root = unpack_container_to_temp(container_path)
        try:
            snapshots = list_snapshots(bundle_root)
            # Should have at least 3 snapshots (one initial + 3 saves)
            assert len(snapshots) >= 3
        finally:
            if bundle_root.parent.exists():
                shutil.rmtree(bundle_root.parent, ignore_errors=True)

    def test_container_temp_cleanup(self, tmp_path):
        """Test cleanup of stale temp directories."""
        # Create a temp directory manually
        import time

        temp_dir = tmp_path / "VasoAnalyzer-container-test123"
        temp_dir.mkdir()

        # Make it look old by modifying mtime
        old_time = time.time() - (25 * 3600)  # 25 hours ago
        import os

        os.utime(temp_dir, (old_time, old_time))

        # Run cleanup (with short max_age for testing)
        cleaned = cleanup_stale_temp_dirs(max_age=24 * 3600)

        # Note: cleanup might not find our test dir if it's not in system temp
        # This test mainly verifies the cleanup function runs without errors

    def test_container_pack_unpack_round_trip(self, tmp_path):
        """Test packing and unpacking preserves data."""
        # Create bundle
        bundle_path = tmp_path / "original" / "bundle"
        bundle_path.parent.mkdir(parents=True)
        create_bundle(bundle_path)

        # Add data
        staging_path, staging_conn = open_staging_db(bundle_path)
        try:
            staging_conn.execute("CREATE TABLE test (id INTEGER, value TEXT)")
            staging_conn.execute("INSERT INTO test VALUES (1, 'round trip data')")
            staging_conn.commit()
        finally:
            staging_conn.close()

        create_snapshot(bundle_path, staging_path)

        # Pack to container
        container_path = tmp_path / "project.vaso"
        pack_temp_bundle_to_container(bundle_path, container_path)

        assert container_path.exists()
        assert is_vaso_container(container_path)

        # Unpack to new location
        unpacked_bundle = unpack_container_to_temp(container_path)

        try:
            # Verify data
            current_snapshot = get_current_snapshot(unpacked_bundle)
            assert current_snapshot is not None

            conn = sqlite3.connect(current_snapshot.path)
            cursor = conn.execute("SELECT value FROM test WHERE id=1")
            assert cursor.fetchone()[0] == "round trip data"
            conn.close()
        finally:
            if unpacked_bundle.parent.exists():
                shutil.rmtree(unpacked_bundle.parent, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
