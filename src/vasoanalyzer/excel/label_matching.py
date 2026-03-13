# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Shared label-matching utilities for Excel mapping.

Provides normalisation and fuzzy-matching functions used by both the
Excel Map Wizard and the Excel Template Export Dialog to align session
event labels with template row labels.
"""

from __future__ import annotations

import re

__all__ = ["normalize_label", "best_match"]

# Characters stripped during normalisation (separators, brackets, etc.)
_NORM_SUBS = re.compile(r"[:\-–—•+/\\()\[\]{}=,;]")


def normalize_label(label: str) -> str:
    """Normalize a label for fuzzy comparison.

    Transformations applied:
    - Lowercase
    - Micro-sign variants (µ, μ) → ``u``
    - Dash-type characters (–, —) → ``-`` (before stripping)
    - Separator / bracket characters stripped
    - Digit/letter boundaries split (``20mmHg`` → ``20 mmhg``)
    - Whitespace collapsed to single spaces

    Examples::

        normalize_label("20 mmHg: Max")  →  "20 mmhg max"
        normalize_label("+ 1 µM CCh")   →  "1 um cch"
        normalize_label("1 µM PE")       →  "1 um pe"
    """
    s = label.strip().lower()
    s = s.replace("µ", "u").replace("μ", "u")  # micro sign variants
    s = _NORM_SUBS.sub(" ", s)
    # Split digit/letter boundaries (e.g. "20mmhg" → "20 mmhg", "1um" → "1 um")
    s = re.sub(r"(\d)([a-z])", r"\1 \2", s)
    s = re.sub(r"([a-z])(\d)", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _token_overlap_score(a: str, b: str) -> float:
    """Jaccard similarity between word-token sets of two normalized labels."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def best_match(
    template_label: str,
    candidates: list[str],
    *,
    threshold: float = 0.5,
) -> str | None:
    """Return the best-matching candidate label for *template_label*.

    Matching cascade:

    1. **Exact normalized** – normalised forms are identical.
    2. **Substring containment** – one normalised form contains the other.
    3. **Token-overlap (Jaccard)** – word-token overlap ≥ *threshold*.

    Returns the first match found (earliest cascade level wins).  Within
    the token-overlap pass the candidate with the highest score is chosen.
    Returns ``None`` if no candidate meets any criterion.
    """
    norm_tpl = normalize_label(template_label)

    # Pass 1 – exact normalised match
    for c in candidates:
        if normalize_label(c) == norm_tpl:
            return c

    # Pass 2 – substring containment
    for c in candidates:
        norm_c = normalize_label(c)
        if norm_tpl in norm_c or norm_c in norm_tpl:
            return c

    # Pass 3 – token-overlap scoring
    best_score = 0.0
    best_candidate: str | None = None
    for c in candidates:
        score = _token_overlap_score(norm_tpl, normalize_label(c))
        if score > best_score:
            best_score = score
            best_candidate = c
    if best_score >= threshold:
        return best_candidate

    return None
