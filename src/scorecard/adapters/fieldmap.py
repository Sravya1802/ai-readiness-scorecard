"""Field maps: YAML files that say which source column feeds each shared variable.

Keeping the names in YAML means a wrong column name is fixed by editing the
map, not the adapter. The helpers here are shared by the GDC supplement reader
and the SEER adapter.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

FIELDMAP_DIR = Path(__file__).parent / "fieldmaps"


@cache
def load_fieldmap(name: str) -> dict:
    return yaml.safe_load((FIELDMAP_DIR / f"{name}.yaml").read_text())


def loose(name: str) -> str:
    """A column name with case, punctuation and bracketed parts removed."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\([^)]*\)", "", str(name).lower()))


def find_columns(frame: pd.DataFrame, candidates: list[str]) -> list[str]:
    """Columns of `frame` matching the candidates, in candidate order. Exact match first."""
    exact = {str(c).strip().lower(): c for c in frame.columns}
    fuzzy = {loose(c): c for c in frame.columns}
    found: list[str] = []
    for candidate in candidates:
        hit = exact.get(candidate.strip().lower()) or fuzzy.get(loose(candidate))
        if hit is not None and hit not in found:
            found.append(hit)
    return found


def clean(values: pd.Series, sentinels: list[str], counts: dict[str, int]) -> pd.Series:
    """Strip text, and turn the source's missing-value strings into real missing values."""
    text = values.astype("string").str.strip()
    lowered = text.str.lower()
    is_sentinel = lowered.isin({s.strip().lower() for s in sentinels}) | (text == "")
    for value, n in text[is_sentinel.fillna(False)].value_counts().items():
        key = value or "(empty string)"
        counts[key] = counts.get(key, 0) + int(n)
    return text.mask(is_sentinel.fillna(False)).astype(object).where(text.notna(), None)


def _number(values: pd.Series, spec: dict) -> pd.Series:
    kind = spec.get("type")
    if kind == "leading_number":
        values = values.astype("string").str.extract(r"(\d+)", expand=False)
    numeric = pd.to_numeric(values, errors="coerce")
    if "valid" in spec:
        low, high = spec["valid"]
        numeric = numeric.where((numeric >= low) & (numeric <= high))
    return numeric


def _surgery(values: pd.Series) -> pd.Series:
    """SEER surgery of primary site code -> yes / no / missing."""
    text = values.astype("string").str.strip()
    lettered = text.str.match(r"^[A-Za-z]\d{3}$").fillna(False)
    code = pd.to_numeric(text.where(~lettered, text.str[1:]), errors="coerce")
    code = code.where(~lettered, code // 10)
    out = pd.Series(None, index=values.index, dtype=object)
    out[code == 0] = "no"
    out[(code >= 10) & (code <= 80)] = "yes"
    return out


def _recode(values: pd.Series, spec: dict) -> pd.Series:
    exact = {str(k).strip().lower(): v for k, v in (spec.get("map") or {}).items()}
    contains = [(str(k).lower(), v) for k, v in (spec.get("contains") or [])]
    keep_unmapped = "else" not in spec

    def one(value: Any) -> Any:
        if value is None or pd.isna(value):
            return None
        low = str(value).strip().lower()
        if low in exact:
            return exact[low]
        for needle, out in contains:
            if needle in low:
                return out
        return value if keep_unmapped else spec["else"]

    return values.map(one).astype(object)


def convert(values: pd.Series, spec: dict) -> pd.Series:
    """Apply a field map entry's type and recoding to already-cleaned values."""
    kind = spec.get("type")
    if kind in ("number", "leading_number"):
        return _number(values, spec)
    if kind == "surgery_code":
        return _surgery(values)
    out = _recode(values, spec) if ("map" in spec or "contains" in spec) else values
    if spec.get("prefix"):
        out = out.map(lambda v: None if v is None or pd.isna(v) else f"{spec['prefix']}{v}")
    return out.astype(object).where(out.notna(), None)


def extract(
    frame: pd.DataFrame, spec: dict, sentinels: list[str], counts: dict[str, int]
) -> tuple[pd.Series | None, list[str]]:
    """One shared variable from a source table: (values, source columns used)."""
    columns = find_columns(frame, spec.get("candidates") or [])
    if not columns:
        return None, []
    if not spec.get("coalesce"):
        columns = columns[:1]
    merged = None
    for column in columns:
        values = convert(clean(frame[column], sentinels, counts), spec)
        merged = values if merged is None else merged.where(merged.notna(), values)
    return merged, columns
