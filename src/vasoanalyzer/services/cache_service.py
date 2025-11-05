"""Local disk cache helpers for speeding up repeated data loads."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

__all__ = ["DataCache", "cache_dir_for_project", "DEFAULT_CACHE_LIMIT_GB", "get_cache_root"]

DEFAULT_CACHE_LIMIT_GB = 25


def get_cache_root(app_name: str = "VasoAnalyzer") -> Path | None:
    """Return the system cache root when ``VASO_CACHE_MODE=system`` is set."""

    mode = os.environ.get("VASO_CACHE_MODE", "").lower()
    if mode != "system":
        return None

    system = platform.system().lower()
    home = Path.home()

    if system == "darwin":
        base = home / "Library" / "Caches" / app_name
    elif system == "windows":
        base = (
            Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
            / app_name
            / "Cache"
        )
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(home / ".cache"))) / app_name

    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_dir_for_project(project_path: str | os.PathLike[str] | None) -> Path:
    """Return the cache directory associated with ``project_path``.

    When ``project_path`` points to a ``.vaso`` file the cache lives in a sibling
    directory named ``<stem>.vaso.cache``.  For directory-based projects the cache
    is ``.vaso_cache`` within that directory.  A user-scoped fallback is used
    when no project path is available.
    """

    system_root = get_cache_root()
    if system_root is not None:
        if project_path:
            candidate = Path(project_path).expanduser().resolve(strict=False)
            if candidate.is_dir():
                stem = candidate.name or "project"
                identifier_source = candidate.as_posix() + "/"
            else:
                stem = candidate.stem or "project"
                identifier_source = candidate.as_posix()
        else:
            stem = "shared"
            identifier_source = stem
        digest = hashlib.sha1(identifier_source.encode("utf-8", "ignore")).hexdigest()[:10]
        return system_root / "projects" / f"{stem}.vaso.cache-{digest}"

    if project_path:
        candidate = Path(project_path)
        candidate = candidate.expanduser().resolve(strict=False)
        if candidate.is_dir():
            return candidate / ".vaso_cache"
        stem = candidate.stem or "project"
        return candidate.parent / f"{stem}.vaso.cache"

    # Fallback to a user-level cache directory
    if sys.platform.startswith("darwin"):
        base = Path.home() / "Library" / "Application Support" / "VasoAnalyzer"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VasoAnalyzer"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "VasoAnalyzer"
    return base / "cache"


def _default_meta_path(cache_dir: Path) -> Path:
    return cache_dir / "index.json"


def _safe_read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


def _signature(path: Path, version: int) -> str:
    stat = path.stat()
    return f"{stat.st_size}-{int(stat.st_mtime)}-v{version}"


def _mirror_source(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        src_hash = (src.stat().st_size, int(src.stat().st_mtime))
        dst_hash = (dest.stat().st_size, int(dest.stat().st_mtime))
        if src_hash == dst_hash:
            return dest
    shutil.copy2(src, dest)
    return dest


@dataclass(slots=True)
class DataCache:
    """Simple disk cache that stores DataFrames derived from external files."""

    root: Path
    version: int = 1
    mirror_sources: bool = False
    _meta: dict | None = None

    def __post_init__(self) -> None:
        self.root = self.root.expanduser().resolve(strict=False)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    @property
    def meta_path(self) -> Path:
        return _default_meta_path(self.root)

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def mirror_dir(self) -> Path:
        return self.root / "sources"

    @property
    def meta(self) -> dict:
        if self._meta is None:
            self._meta = _safe_read_json(self.meta_path)
        return self._meta

    # ------------------------------------------------------------------
    def _record_entry(self, key: str, entry: dict) -> None:
        meta = self.meta
        meta[key] = entry
        _safe_write_json(self.meta_path, meta)

    def _cache_path_for(self, src: Path, suffix: str) -> Path:
        stem = src.stem
        return (self.data_dir / stem).with_suffix(suffix)

    def _should_mirror(self, src: Path) -> bool:
        return self.mirror_sources and src.exists() and src.is_file()

    # ------------------------------------------------------------------
    def read_dataframe(
        self,
        src_path: str | os.PathLike[str],
        loader: Callable[[Path], pd.DataFrame],
        *,
        preserve_columns: Iterable[str] | None = None,
        allow_parquet: bool = True,
        category_threshold: float = 0.2,
    ) -> pd.DataFrame:
        """Return a cached DataFrame or populate the cache via ``loader``."""

        src = Path(src_path).expanduser().resolve(strict=False)
        key = src.as_posix()
        sig = _signature(src, self.version)
        entry = self.meta.get(key)

        if entry and entry.get("sig") == sig:
            cached_path = Path(entry.get("cache_path", ""))
            if cached_path.exists():
                try:
                    if entry.get("format") == "parquet" and allow_parquet:
                        return pd.read_parquet(cached_path)
                    return pd.read_pickle(cached_path)
                except Exception:
                    pass  # fall through to rebuild cache

        df = loader(src)
        df = self._downcast(df, preserve_columns=preserve_columns, threshold=category_threshold)

        cache_dir = self.data_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        fmt = "pickle"
        cache_path = self._cache_path_for(src, ".pkl")

        if allow_parquet:
            try:
                import pyarrow  # noqa: F401

                cache_path = self._cache_path_for(src, ".parquet")
                df.to_parquet(cache_path)
                fmt = "parquet"
            except Exception:
                df.to_pickle(cache_path)
        else:
            df.to_pickle(cache_path)

        entry = {
            "sig": sig,
            "cache_path": cache_path.as_posix(),
            "format": fmt,
        }
        if self._should_mirror(src):
            mirrored = _mirror_source(src, self.mirror_dir / src.name)
            entry["mirrored_source"] = mirrored.as_posix()
        self._record_entry(key, entry)
        return df

    # ------------------------------------------------------------------
    def _downcast(
        self,
        df: pd.DataFrame,
        *,
        preserve_columns: Iterable[str] | None = None,
        threshold: float,
    ) -> pd.DataFrame:
        if df.empty:
            return df
        preserve = {c for c in preserve_columns or []}

        for col in df.select_dtypes(include="float64").columns:
            if col in preserve:
                continue
            df[col] = df[col].astype("float32")

        for col in df.select_dtypes(include="int64").columns:
            if col in preserve:
                continue
            df[col] = pd.to_numeric(df[col], downcast="integer")

        for col in df.select_dtypes(include="object").columns:
            if col in preserve:
                continue
            series = df[col]
            unique_ratio = series.nunique(dropna=True) / max(len(series), 1)
            if unique_ratio <= threshold:
                df[col] = series.astype("category")
        return df

    # ------------------------------------------------------------------
    def prune(self, *, limit_gb: int = DEFAULT_CACHE_LIMIT_GB) -> None:
        """Delete least-recently-updated entries when cache exceeds ``limit_gb``."""

        limit_bytes = max(limit_gb, 1) * 1024**3
        if limit_bytes <= 0:
            return

        total = 0
        entries = []
        for entry in self.meta.values():
            path = Path(entry.get("cache_path", ""))
            if not path.exists():
                continue
            size = path.stat().st_size
            total += size
            entries.append((path, entry, size))

        if total <= limit_bytes:
            return

        entries.sort(key=lambda item: item[0].stat().st_mtime if item[0].exists() else 0)

        current = total
        for path, _entry, size in entries:
            if current <= limit_bytes:
                break
            try:
                path.unlink()
            except OSError:
                continue
            current -= size

        # Rewrite metadata without missing entries
        cleaned = {k: v for k, v in self.meta.items() if Path(v.get("cache_path", "")).exists()}
        self._meta = cleaned
        _safe_write_json(self.meta_path, cleaned)
