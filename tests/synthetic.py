"""Invented patients for tests. Nothing here comes from a real dataset."""

from __future__ import annotations

import pandas as pd

from scorecard.adapters.gdc import COLUMNS
from scorecard.adapters.vocabulary import derive
from scorecard.profile import (
    Availability,
    DatasetProfile,
    FeatureMeta,
    PrivacyPolicy,
    Provenance,
)

NAMES = [name for name, *_ in COLUMNS]


def make_profile(
    n: int,
    columns: dict[str, list],
    *,
    absent: tuple[str, ...] = (),
    caveats: dict[str, list[str]] | None = None,
    modalities: dict[str, list[bool]] | None = None,
    privacy: PrivacyPolicy | None = None,
    linkable: bool = True,
) -> DatasetProfile:
    """A profile of n invented patients. Columns not given are empty but loaded."""
    index = pd.Index([f"FAKE-{i:04d}" for i in range(n)], name="patient_id")
    features = pd.DataFrame(None, index=index, columns=NAMES, dtype=object)
    for name, values in columns.items():
        features[name] = values
    features = derive(features)
    meta = {
        name: FeatureMeta(
            name=name,
            modality="clinical",
            role=role,
            availability=Availability.NOT_IN_SOURCE if name in absent else Availability.LOADED,
            caveats=(caveats or {}).get(name, []),
            note="Invented note." if name in (caveats or {}) else None,
        )
        for name, role, *_ in COLUMNS
    }
    return DatasetProfile(
        dataset_id="FAKE",
        title="Invented cohort",
        description="Invented rows for tests.",
        features=features,
        feature_meta=meta,
        modalities=pd.DataFrame({"clinical": True, **(modalities or {})}, index=index),
        provenance=Provenance(
            adapter="fake",
            adapter_version="0",
            repository="fake",
            retrieved_at="2026-01-01T00:00:00+00:00",
            content_sha256="0" * 64,
            n_source_records=n,
        ),
        site_column="tissue_source_site",
        privacy=privacy or PrivacyPolicy(),
        linkable=linkable,
    )


def chemo_cohort(n: int = 400, *, untreated_every: int = 2) -> dict[str, list]:
    """n invented patients who all meet the chemo-benefit population rules."""
    i = range(n)
    j = [k // 2 for k in i]  # varies independently of the treatment, which alternates
    return {
        "tissue_source_site": ["A" if k % 2 else "B" for k in j],
        "sex": ["female"] * n,
        "er_status": ["Positive"] * n,
        "pr_status": ["Positive" if k % 3 else "Negative" for k in j],
        "her2_status": ["Negative"] * n,
        "ajcc_pathologic_stage": ["Stage IIA" if k % 2 else "Stage IA" for k in i],
        "ajcc_pathologic_m": ["M0"] * n,
        "nodes_positive": [k % 4 for k in j],
        "surgery": ["yes"] * n,
        "neoadjuvant_therapy": ["no"] * n,
        "chemotherapy": ["no" if k % untreated_every == 0 else "yes" for k in i],
        "endocrine_therapy": ["yes"] * n,
        "menopausal_status": ["postmenopausal" if k % 2 else "premenopausal" for k in j],
        "tumor_grade": ["G2"] * n,
        "age_at_index": [40 + k % 40 for k in j],
        "race": ["white" if k % 4 else "black or african american" for k in j],
        "genomic_risk_score": [10 + k % 30 for k in j],
        "primary_diagnosis": ["Infiltrating duct carcinoma, NOS"] * n,
        "vital_status": ["Alive"] * n,
        "days_to_last_follow_up": [3650] * n,
        # Every third patient has the event at 2 years; the rest are followed 10 years.
        "distant_recurrence_event": [1 if k % 3 == 0 else 0 for k in i],
        "distant_recurrence_time_days": [730 if k % 3 == 0 else 3650 for k in i],
    }
