"""Simple VA feature flag parser using the ``VA_FEATURES`` environment variable."""

from __future__ import annotations

import os
from collections.abc import Iterable
from functools import lru_cache

_FALSE_VALUES = {"0", "false", "off", "no", "disable", "disabled"}
_TRUE_VALUES = {"1", "true", "on", "yes", "enable", "enabled"}


def _normalise(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _tokenise(raw: str) -> Iterable[str]:
    for token in raw.split(","):
        clean = token.strip()
        if clean:
            yield clean


def _parse_bool(value: str) -> bool | None:
    normalised = value.strip().lower()
    if normalised in _TRUE_VALUES:
        return True
    if normalised in _FALSE_VALUES:
        return False
    return None


def _parse_tokens(raw: str) -> dict[str, bool]:
    features: dict[str, bool] = {}
    for token in _tokenise(raw):
        if token.startswith(("!", "-")):
            features[_normalise(token[1:])] = False
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            parsed = _parse_bool(value)
            if parsed is None:
                continue
            features[_normalise(key)] = parsed
            continue
        features[_normalise(token)] = True
    return features


@lru_cache(maxsize=1)
def _cached_flags(env_value: str | None = None) -> dict[str, bool]:
    raw = env_value if env_value is not None else os.environ.get("VA_FEATURES", "")
    return _parse_tokens(raw)


def reload() -> None:
    """Clear the cached feature map (useful for tests)."""

    _cached_flags.cache_clear()


def all_enabled(env_value: str | None = None) -> dict[str, bool]:
    """Return a copy of the parsed feature map."""

    return dict(_cached_flags(env_value))


def is_enabled(flag: str, *, default: bool = False) -> bool:
    """Return whether ``flag`` is active."""

    if not flag:
        raise ValueError("Flag name must be a non-empty string")
    key = _normalise(flag)
    features = _cached_flags()
    if key not in features:
        return default
    return features[key]
