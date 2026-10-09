"""Domain packs: inventories of the variables a domain expects, grouped into criteria."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, Field, model_validator

from scorecard.checks.base import Criterion

PACK_DIR = Path(__file__).parent
PACK_FILES = {"oncology-completeness": PACK_DIR / "oncology.yaml"}


class PackVariable(BaseModel):
    name: str
    column: str | None = None
    any_of: list[str] | None = None
    uninformative: list[str] = Field(default_factory=list)
    applies_to: list[str] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> PackVariable:
        if (self.column is None) == (self.any_of is None):
            raise ValueError(f"variable {self.name!r} needs exactly one of 'column' or 'any_of'")
        return self

    @property
    def columns(self) -> list[str]:
        return [self.column] if self.column else list(self.any_of or [])

    def applicable(self, features: pd.DataFrame) -> pd.Series:
        """Boolean mask of the patients this variable applies to."""
        if self.applies_to is None:
            return pd.Series(True, index=features.index)
        if "primary_site" not in features.columns:
            return pd.Series(False, index=features.index)
        site = features["primary_site"].astype("string").str.lower()
        mask = pd.Series(False, index=features.index)
        for prefix in self.applies_to:
            mask |= site.str.startswith(prefix.lower()).fillna(False)
        return mask

    def present(self, features: pd.DataFrame) -> pd.Series:
        """Boolean mask of patients with an informative value. Absent columns count as missing."""
        uninformative = {v.lower() for v in self.uninformative}
        mask = pd.Series(False, index=features.index)
        for column in self.columns:
            if column not in features.columns:
                continue
            values = features[column]
            informative = values.notna()
            if uninformative:
                lowered = values.astype("string").str.lower()
                informative &= ~lowered.isin(uninformative).fillna(False)
            mask |= informative
        return mask


class PackCriterion(BaseModel):
    id: str
    title: str
    description: str
    bridge2ai: list[Criterion]
    validated: bool = False
    review_note: str | None = None
    variables: list[PackVariable]


class Pack(BaseModel):
    id: str
    version: str
    criteria: list[PackCriterion]

    def criterion(self, criterion_id: str) -> PackCriterion:
        for c in self.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(f"pack {self.id!r} has no criterion {criterion_id!r}")


@cache
def load_pack(pack_id: str) -> Pack:
    try:
        path = PACK_FILES[pack_id]
    except KeyError:
        raise KeyError(f"unknown pack {pack_id!r}; available: {sorted(PACK_FILES)}") from None
    return Pack.model_validate(yaml.safe_load(path.read_text()))
