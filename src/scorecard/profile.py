"""DatasetProfile: the intermediate representation (IR).

Every adapter produces one DatasetProfile and every check consumes one. Nothing
downstream of an adapter may know which repository the data came from.

Changing anything in this file changes the contract for the whole team, so
changes go through the project lead (see docs/TECHNICAL_PLAN.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd
from pydantic import BaseModel, Field

IR_VERSION = "0.2.0"
# All times in the IR are days; reports convert with this.
DAYS_PER_YEAR = 365.25


class ProfileError(ValueError):
    """The profile breaks an IR invariant."""


class Role(str, Enum):
    FEATURE = "feature"
    # Outcome columns a task derives its label from. Kept out of the feature
    # set so checks never treat the answer as an input.
    TARGET = "target"
    IDENTIFIER = "identifier"
    SITE = "site"


class Availability(str, Enum):
    """Whether the source carries a variable at all, as opposed to missing values in it.

    Every adapter declares the full shared vocabulary. A variable the source
    does not have is still a column, left empty and marked here, so a check can
    tell "absent from the dataset" from "missing for some patients".
    """

    LOADED = "loaded"
    # The source has it, but the file that holds it was not given to the adapter.
    NOT_LOADED = "not_loaded"
    NOT_IN_SOURCE = "not_in_source"


# FeatureMeta.caveats code: the source reports "no" and "unknown" as one value,
# so the adapter cannot emit a trustworthy "no".
NO_UNKNOWN_MERGED = "no_unknown_merged"


class FeatureMeta(BaseModel):
    """What one column of `DatasetProfile.features` is and where it came from."""

    name: str
    modality: str
    role: Role = Role.FEATURE
    source_field: str | None = None
    description: str | None = None
    availability: Availability = Availability.LOADED
    caveats: list[str] = Field(default_factory=list)
    # Plain-language reason for the availability or caveat, quoted on the data card.
    note: str | None = None


def _default_min_cell() -> int | None:
    value = os.environ.get("SCORECARD_MIN_CELL")
    return int(value) if value else None


class PrivacyPolicy(BaseModel):
    """What a report built on this profile may show.

    patient_level_output  False for sources whose data use agreement covers
                          case-level rows (SEER): reports then carry counts and
                          percentages only, never patient ids or example rows.
    min_cell_count        counts from 1 up to this number minus one are shown
                          as "<N". None turns suppression off.
    """

    patient_level_output: bool = True
    min_cell_count: int | None = Field(default_factory=_default_min_cell)
    basis: str | None = None

    def count(self, n: int) -> int | str:
        """A count as it may be shown: the number, or "<N" when it is a small cell."""
        if self.min_cell_count and 0 < n < self.min_cell_count:
            return f"<{self.min_cell_count}"
        return int(n)

    def is_small(self, n: int) -> bool:
        return bool(self.min_cell_count) and 0 < n < self.min_cell_count


class Provenance(BaseModel):
    """Enough to reproduce the profile: who built it, from what, and when."""

    adapter: str
    adapter_version: str
    repository: str
    query: dict = Field(default_factory=dict)
    retrieved_at: str
    data_release: str | None = None
    content_sha256: str
    n_source_records: int
    source_files: dict[str, int] = Field(default_factory=dict)
    # Strings such as "Not Reported" that the adapter turned into missing values.
    sentinels_normalized: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ModalityCoverage(BaseModel):
    modality: str
    n_patients: int
    fraction: float


class ProfileSummary(BaseModel):
    """JSON-serializable view of a profile (everything except the table itself)."""

    ir_version: str = IR_VERSION
    dataset_id: str
    title: str
    description: str
    n_patients: int
    n_features: int
    site_column: str | None
    n_sites: int | None
    modality_coverage: list[ModalityCoverage]
    n_patients_all_modalities: int
    features: list[FeatureMeta]
    provenance: Provenance
    linkable: bool = True
    privacy: PrivacyPolicy = Field(default_factory=PrivacyPolicy)


@dataclass
class DatasetProfile:
    """One dataset in the shared shape.

    features      one row per patient, indexed by patient id
    feature_meta  one entry per column of `features`
    modalities    boolean table, same index as `features`, one column per
                  modality: True where the patient has that modality in the
                  repository. Presence does not mean the modality's features
                  are loaded into `features`.
    site_column   the column of `features` holding the site/batch label
    linkable      False for sources that are never joined per patient (SEER)
    privacy       what reports built on this profile may show
    reference     aggregate summary of a reference population (counts and
                  shares only), set by the pipeline for the representativeness check
    """

    dataset_id: str
    title: str
    description: str
    features: pd.DataFrame
    feature_meta: dict[str, FeatureMeta]
    modalities: pd.DataFrame
    provenance: Provenance
    site_column: str | None = None
    linkable: bool = True
    privacy: PrivacyPolicy = field(default_factory=PrivacyPolicy)
    reference: dict | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.features.index.is_unique:
            dupes = self.features.index[self.features.index.duplicated()].unique()[:5].tolist()
            raise ProfileError(f"features must have one row per patient; duplicated ids: {dupes}")
        missing_meta = set(self.features.columns) - set(self.feature_meta)
        extra_meta = set(self.feature_meta) - set(self.features.columns)
        if missing_meta or extra_meta:
            raise ProfileError(
                "feature_meta must describe exactly the columns of features; "
                f"undescribed: {sorted(missing_meta)}, unknown: {sorted(extra_meta)}"
            )
        if not self.modalities.index.equals(self.features.index):
            raise ProfileError("modalities must have the same patient index as features")
        non_bool = [c for c in self.modalities.columns if self.modalities[c].dtype != bool]
        if non_bool:
            raise ProfileError(f"modalities columns must be boolean; got non-boolean: {non_bool}")
        if self.site_column is not None:
            if self.site_column not in self.features.columns:
                raise ProfileError(f"site_column {self.site_column!r} is not a column of features")
            if self.feature_meta[self.site_column].role is not Role.SITE:
                raise ProfileError(f"site_column {self.site_column!r} must have role 'site'")

    @property
    def n_patients(self) -> int:
        return len(self.features)

    @property
    def site(self) -> pd.Series | None:
        return None if self.site_column is None else self.features[self.site_column]

    def columns_with_role(self, role: Role, *, loaded_only: bool = False) -> list[str]:
        return [
            c
            for c in self.features.columns
            if self.feature_meta[c].role is role and (not loaded_only or self.carries(c))
        ]

    def availability(self, column: str) -> Availability:
        """How the source stands on a column. Undeclared columns are not in the source."""
        meta = self.feature_meta.get(column)
        return Availability.NOT_IN_SOURCE if meta is None else meta.availability

    def carries(self, column: str) -> bool:
        return self.availability(column) is Availability.LOADED

    def has_caveat(self, column: str, caveat: str) -> bool:
        meta = self.feature_meta.get(column)
        return meta is not None and caveat in meta.caveats

    def modality_coverage(self) -> list[ModalityCoverage]:
        n = max(self.n_patients, 1)
        return [
            ModalityCoverage(
                modality=m,
                n_patients=int(self.modalities[m].sum()),
                fraction=float(self.modalities[m].sum()) / n,
            )
            for m in self.modalities.columns
        ]

    def summary(self) -> ProfileSummary:
        site = self.site
        return ProfileSummary(
            dataset_id=self.dataset_id,
            title=self.title,
            description=self.description,
            n_patients=self.n_patients,
            n_features=len(self.columns_with_role(Role.FEATURE)),
            site_column=self.site_column,
            n_sites=None if site is None else int(site.nunique(dropna=True)),
            modality_coverage=self.modality_coverage(),
            n_patients_all_modalities=int(self.modalities.all(axis=1).sum()),
            features=[self.feature_meta[c] for c in self.features.columns],
            provenance=self.provenance,
            linkable=self.linkable,
            privacy=self.privacy,
        )
