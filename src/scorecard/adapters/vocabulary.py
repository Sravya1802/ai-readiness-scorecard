"""The shared variable vocabulary beyond the original GDC columns, and derived variables.

Every adapter emits every column listed here. A column the source lacks is
left empty and marked as not in the source, or not loaded, in its FeatureMeta.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from scorecard.profile import Role

F, T = Role.FEATURE, Role.TARGET

# (name, role, description, numeric)
EXTRA_COLUMNS: list[tuple[str, Role, str, bool]] = [
    ("stage_group", F, "Stage group without substage: 0, I, II, III or IV (derived)", False),
    ("metastatic_at_diagnosis", F, "Distant metastasis at diagnosis: yes or no (derived)", False),
    ("nodes_positive", F, "Number of positive regional lymph nodes", True),
    ("nodes_examined", F, "Number of regional lymph nodes examined", True),
    ("tumor_size_mm", F, "Tumor size in millimetres", True),
    ("margin_status", F, "Surgical margin status", False),
    ("menopausal_status", F, "premenopausal, perimenopausal or postmenopausal", False),
    ("family_history_breast_cancer", F, "Family history of breast or ovarian cancer", False),
    ("first_primary", F, "First malignant primary: yes or no", False),
    ("her2_ihc_status", F, "HER2 by immunohistochemistry: Positive, Negative, Equivocal", False),
    ("her2_ihc_score", F, "HER2 immunohistochemistry score (0, 1+, 2+, 3+)", False),
    ("her2_fish_status", F, "HER2 by in situ hybridization: Positive, Negative, Equivocal", False),
    ("breast_subtype", F, "Receptor-based subtype (registry recode)", False),
    ("surgery", F, "Surgery of the primary site: yes or no", False),
    ("surgery_type", F, "Surgical procedure", False),
    ("chemotherapy", F, "Chemotherapy: yes, no, or empty when not recorded", False),
    ("endocrine_therapy", F, "Endocrine therapy: yes, no, or empty when not recorded", False),
    ("radiation_therapy", F, "Radiation therapy: yes, no, or empty when not recorded", False),
    ("targeted_therapy", F, "Targeted therapy: yes, no, or empty when not recorded", False),
    ("immunotherapy", F, "Immunotherapy: yes, no, or empty when not recorded", False),
    ("ovarian_suppression", F, "Ovarian suppression drug recorded: yes or empty", False),
    ("neoadjuvant_therapy", F, "Systemic therapy before surgery: yes or no", False),
    ("drug_names", F, "Drug names recorded, '; '-joined", False),
    ("endocrine_therapy_start_days", F, "Days from diagnosis to first endocrine therapy", True),
    ("endocrine_therapy_end_days", F, "Days from diagnosis to last endocrine therapy end", True),
    ("endocrine_therapy_duration_days", F, "Endocrine therapy end minus start (derived)", True),
    ("radiation_sequence", F, "Order of radiation and surgery", False),
    ("time_to_treatment_days", F, "Days from diagnosis to first treatment", True),
    ("genomic_risk_score", F, "Commercial genomic recurrence score (Oncotype DX, 0-100)", True),
    ("genomic_risk_reason_no_score", F, "Why no genomic recurrence score was linked", False),
    ("pam50_subtype", F, "PAM50 intrinsic subtype (published table)", False),
    ("germline_brca_status", F, "Germline BRCA1/2 pathogenic variant status", False),
    ("hrd_score", T, "Homologous recombination deficiency score from tumor data", True),
    ("os_event", T, "Death from any cause: 1 or 0 (derived)", True),
    ("os_time_days", T, "Days to death or last follow-up (derived)", True),
    ("dss_event", T, "Death from this cancer: 1 or 0", True),
    ("dss_time_days", T, "Days to death from this cancer or censoring", True),
    ("pfi_event", T, "Progression-free interval event: 1 or 0", True),
    ("pfi_time_days", T, "Progression-free interval, days", True),
    ("dfi_event", T, "Disease-free interval event: 1 or 0", True),
    ("dfi_time_days", T, "Disease-free interval, days", True),
    ("distant_recurrence_event", T, "Distant recurrence: 1 or 0", True),
    ("distant_recurrence_time_days", T, "Days to distant recurrence or censoring", True),
]
EXTRA_NAMES = [name for name, *_ in EXTRA_COLUMNS]
# Filled in by derive() from other columns, so they are loaded whenever their inputs are.
DERIVED = {
    "stage_group": ["ajcc_pathologic_stage"],
    "metastatic_at_diagnosis": ["ajcc_pathologic_m", "ajcc_pathologic_stage"],
    "os_event": ["vital_status"],
    "os_time_days": ["vital_status"],
    "endocrine_therapy_duration_days": [
        "endocrine_therapy_start_days",
        "endocrine_therapy_end_days",
    ],
    "surgery": ["surgery_type"],
}

_STAGE = re.compile(r"^(?:STAGE\s*)?(IV|III|II|I|0|[0-4])")
_ARABIC = {"0": "0", "1": "I", "2": "II", "3": "III", "4": "IV"}


def stage_group(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    match = _STAGE.match(str(value).strip().upper())
    if not match:
        return None
    return _ARABIC.get(match.group(1), match.group(1))


def _metastatic(m_value, stage) -> str | None:
    if m_value is not None and not pd.isna(m_value):
        text = str(m_value).upper()
        if "M1" in text:
            return "yes"
        if "M0" in text:
            return "no"
    if stage is not None and not pd.isna(stage):
        return "yes" if stage == "IV" else "no"
    return None


def _fill(features: pd.DataFrame, column: str, values: pd.Series) -> None:
    """Fill gaps in `column` with derived values; never overwrite what the source gave."""
    current = features[column]
    features[column] = current.where(current.notna(), values)


def derive(features: pd.DataFrame) -> pd.DataFrame:
    """Add the derived variables. Expects every EXTRA column to exist already."""
    f = features
    _fill(f, "stage_group", f["ajcc_pathologic_stage"].map(stage_group).astype(object))
    _fill(
        f,
        "metastatic_at_diagnosis",
        pd.Series(
            [
                _metastatic(m, s)
                for m, s in zip(f["ajcc_pathologic_m"], f["stage_group"], strict=True)
            ],
            index=f.index,
            dtype=object,
        ),
    )
    dead, alive = f["vital_status"] == "Dead", f["vital_status"] == "Alive"
    event = pd.Series(np.nan, index=f.index)
    event[dead], event[alive] = 1.0, 0.0
    time = pd.Series(np.nan, index=f.index)
    time[dead] = pd.to_numeric(f.loc[dead, "days_to_death"], errors="coerce")
    time[alive] = pd.to_numeric(f.loc[alive, "days_to_last_follow_up"], errors="coerce")
    _fill(f, "os_event", event)
    _fill(f, "os_time_days", time)
    duration = pd.to_numeric(f["endocrine_therapy_end_days"], errors="coerce") - pd.to_numeric(
        f["endocrine_therapy_start_days"], errors="coerce"
    )
    _fill(f, "endocrine_therapy_duration_days", duration.where(duration >= 0))
    has_surgery = pd.Series(None, index=f.index, dtype=object)
    has_surgery[f["surgery_type"].notna()] = "yes"
    _fill(f, "surgery", has_surgery)
    for name, _, _, numeric in EXTRA_COLUMNS:
        if numeric:
            f[name] = pd.to_numeric(f[name], errors="coerce")
    return f
