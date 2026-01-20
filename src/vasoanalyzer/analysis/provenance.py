from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
from typing import Any

from importlib.metadata import PackageNotFoundError, version as pkg_version

from .contract import AnalysisParamsV1


@dataclass(frozen=True)
class Provenance:
    analyzer: str  # "VasoAnalyzer"
    version: str  # pull from package __version__ if available, else "dev"
    params_hash: str
    dataset_id: str


def _to_builtin(obj: Any) -> Any:
    if is_dataclass(obj):
        return {field.name: _to_builtin(getattr(obj, field.name)) for field in fields(obj)}
    if isinstance(obj, dict):
        return {str(key): _to_builtin(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_builtin(value) for value in obj]
    return obj


def stable_params_hash(params: AnalysisParamsV1) -> str:
    """
    Canonical JSON dump of params dataclasses then SHA256 hex digest.
    Must be stable across runs and platforms.
    """

    payload = _to_builtin(params)
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_analyzer_version() -> str:
    """
    Return package __version__ if available, else "dev".
    """

    try:
        version = pkg_version("vasoanalyzer")
    except PackageNotFoundError:
        return "dev"
    if isinstance(version, str) and version:
        return version
    return "dev"
