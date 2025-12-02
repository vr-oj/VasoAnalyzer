from __future__ import annotations

from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

TEXT_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml", ".md", ".csv"}


def write_bytes(z: ZipFile, arcname: str, data: bytes, stored: bool = False) -> None:
    compress = ZIP_STORED if stored else ZIP_DEFLATED
    z.writestr(arcname, data, compress_type=compress)


def write_text(z: ZipFile, arcname: str, text: str) -> None:
    z.writestr(arcname, text.encode("utf-8"), compress_type=ZIP_DEFLATED)


def read_bytes(z: ZipFile, arcname: str) -> bytes:
    with z.open(arcname, "r") as handle:
        return handle.read()


def exists(z: ZipFile, arcname: str) -> bool:
    try:
        z.getinfo(arcname)
        return True
    except KeyError:
        return False
