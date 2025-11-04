from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class DatasetEntry:
    dataset_id: str
    title: str
    has_embedded_blobs: bool = False
    ref_count: int = 0


@dataclass(slots=True)
class DatasetCatalog:
    datasets: dict[str, DatasetEntry] = field(default_factory=dict)

    def register(self, entry: DatasetEntry) -> None:
        self.datasets[entry.dataset_id] = entry

    def mark_embedded(self, dataset_id: str, has_embedded: bool) -> None:
        entry = self.datasets.get(dataset_id)
        if entry is None:
            entry = DatasetEntry(dataset_id=dataset_id, title=dataset_id)
            self.datasets[dataset_id] = entry
        entry.has_embedded_blobs = has_embedded

    def mark_ref_count(self, dataset_id: str, ref_count: int) -> None:
        entry = self.datasets.get(dataset_id)
        if entry is None:
            entry = DatasetEntry(dataset_id=dataset_id, title=dataset_id)
            self.datasets[dataset_id] = entry
        entry.ref_count = ref_count

    def to_bytes(self) -> bytes:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "catalog.sqlite"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=OFF")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS datasets (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        has_embedded INTEGER NOT NULL,
                        ref_count INTEGER NOT NULL
                    )
                    """
                )
                conn.execute("DELETE FROM datasets")
                for entry in self.datasets.values():
                    conn.execute(
                        (
                            "INSERT OR REPLACE INTO datasets(id, title, has_embedded, ref_count) "
                            "VALUES (?, ?, ?, ?)"
                        ),
                        (
                            entry.dataset_id,
                            entry.title,
                            1 if entry.has_embedded_blobs else 0,
                            entry.ref_count,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()
            return Path(db_path).read_bytes()

    @classmethod
    def from_bytes(cls, payload: bytes) -> DatasetCatalog:
        catalog = cls()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "catalog.sqlite"
            db_path.write_bytes(payload)
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.execute(
                    "SELECT id, title, has_embedded, ref_count FROM datasets ORDER BY id"
                )
                for dataset_id, title, has_embedded, ref_count in cursor:
                    catalog.datasets[dataset_id] = DatasetEntry(
                        dataset_id=dataset_id,
                        title=title,
                        has_embedded_blobs=bool(has_embedded),
                        ref_count=int(ref_count),
                    )
            finally:
                conn.close()
        return catalog
