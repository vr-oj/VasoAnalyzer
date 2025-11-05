from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from .io_zip import write_bytes


def compute_sha256(fs_path: Path) -> str:
    hasher = sha256()
    with fs_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def add_blob_file(z: ZipFile, fs_path: Path) -> str:
    digest = compute_sha256(fs_path)
    arc = f"datasets/_shared/blobs/{digest}"
    if not any(info.filename == arc for info in z.infolist()):
        write_bytes(z, arc, Path(fs_path).read_bytes(), stored=True)
    return digest
