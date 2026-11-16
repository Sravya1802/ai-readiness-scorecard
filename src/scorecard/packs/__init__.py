"""Domain packs: inventories of the variables a domain expects, grouped into criteria."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, Field, model_validator

from scorecard.checks.base import Criterion
from scorecard.rules import Rule, all_of

PACK_DIR = Path(__file__).parent
PACK_FILES = {"oncology-completeness": PACK_DIR / "oncology.yaml"}


class PackVariable(BaseModel):
    name: str
    column: str | None = None
    any_of: list[str] | None = None
    # Alternatively, a modality: present when the patient has that kind of file.
    modality: str | None = None
    uninformative: list[str] = Field(default_factory=list)
    applies_to: list[str] | None = None
    # The value is only expected for patients who meet every rule here, for
    # example HER2 FISH only when HER2 IHC is equivocal.
    expected_when: list[Rule] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> PackVariable:
        given = sum(x is not None for x in (self.column, self.any_of, self.modality))
        if given != 1:
            raise ValueError(
                f"variable {self.name!r} needs exactly one of 'column', 'any_of' or 'modality'"
            )
        return self

    @property
    def columns(self) -> list[str]:
        return [self.column] if self.column else list(self.any_of or [])

    def applicable(self, features: pd.DataFrame) -> pd.Series:
        """Boolean mask of the patients this variable is expected for."""
        mask = pd.Series(True, index=features.index)
        if self.applies_to is not None:
            if "primary_site" not in features.columns:
                return pd.Series(False, index=features.index)
            site = features["primary_site"].astype("string").str.lower()
            mask = pd.Series(False, index=features.index)
            for prefix in self.applies_to:
                mask |= site.str.startswith(prefix.lower()).fillna(False)
        if self.expected_when:
            # A rule that cannot be evaluated counts as "expected", so a missing
            # value in the condition never hides a missing value in the variable.
            mask &= all_of(self.expected_when, features).fillna(True).astype(bool)
        return mask

    def present(self, features: pd.DataFrame, modalities: pd.DataFrame | None = None) -> pd.Series:
        """Boolean mask of patients with an informative value. Absent columns count as missing."""
        if self.modality is not None:
            if modalities is None or self.modality not in modalities.columns:
                return pd.Series(False, index=features.index)
            return modalities[self.modality].astype(bool)
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
