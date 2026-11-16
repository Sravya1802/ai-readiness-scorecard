"""GDC adapter: open-access clinical records from the Genomic Data Commons.

What is real today
  - clinical data for every case in a project, one row per patient
  - per-patient presence of open gene expression and somatic mutation files
    (presence only; see the TODO at the bottom for loading the matrices)

Three things about GDC clinical data that this adapter handles and that anyone
extending it should know:
  1. A case can carry several diagnosis records (prior primaries and so on).
     We keep the one flagged as the primary disease.
  2. Missing values arrive as strings such as "Not Reported". They are turned
     into real missing values and counted in the provenance record.
  3. Follow-up time lives in two places: on the diagnosis and in the separate
     follow_ups records. We take the latest of both.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from scorecard.adapters.base import Adapter, register_adapter
from scorecard.adapters.fieldmap import load_fieldmap
from scorecard.adapters.tcga_supplement import apply_supplement, read_supplement
from scorecard.adapters.vocabulary import DERIVED, EXTRA_COLUMNS, EXTRA_NAMES, derive
from scorecard.profile import Availability, DatasetProfile, FeatureMeta, Provenance, Role

API = "https://api.gdc.cancer.gov"
PAGE_SIZE = 500
TIMEOUT_SECONDS = 120

# Strings GDC uses where a value is absent. Compared case-insensitively.
SENTINELS = frozenset({"not reported", "unknown", "not allowed to collect", "--", ""})

# Open-access file types whose presence defines a modality for a patient.
MODALITY_DATA_TYPES = {
    "gene_expression": "Gene Expression Quantification",
    "somatic_mutation": "Masked Somatic Mutation",
    "copy_number": "Gene Level Copy Number",
}

_DX_FIELDS = [
    "diagnosis_is_primary_disease",
    "classification_of_tumor",
    "age_at_diagnosis",
    "year_of_diagnosis",
    "tissue_or_organ_of_origin",
    "site_of_resection_or_biopsy",
    "primary_diagnosis",
    "morphology",
    "icd_10_code",
    "tumor_grade",
    "laterality",
    "ajcc_pathologic_stage",
    "ajcc_pathologic_t",
    "ajcc_pathologic_n",
    "ajcc_pathologic_m",
    "ajcc_staging_system_edition",
    "prior_malignancy",
    "progression_or_recurrence",
    "days_to_last_follow_up",
]

CASE_FIELDS = [
    "submitter_id",
    "case_id",
    "tissue_source_site.code",
    "tissue_source_site.name",
    "demographic.vital_status",
    "demographic.days_to_death",
    "demographic.sex_at_birth",
    "demographic.gender",
    "demographic.race",
    "demographic.ethnicity",
    "demographic.age_at_index",
    *[f"diagnoses.{f}" for f in _DX_FIELDS],
    "diagnoses.treatments.treatment_type",
    "diagnoses.treatments.treatment_or_therapy",
    "follow_ups.days_to_follow_up",
    "follow_ups.molecular_tests.gene_symbol",
    "follow_ups.molecular_tests.test_result",
]

# Extra fields that let the API alone fill drug names, treatment timing and intent, and
# split HER2 by test method. The names are from the GDC data dictionary but have not
# been checked against the live API, so they are requested only when
# SCORECARD_GDC_EXTENDED_FIELDS=1. build_profile uses them when a snapshot has them.
OPTIONAL_CASE_FIELDS = [
    "diagnoses.treatments.therapeutic_agents",
    "diagnoses.treatments.days_to_treatment_start",
    "diagnoses.treatments.days_to_treatment_end",
    "diagnoses.treatments.treatment_intent_type",
    "follow_ups.molecular_tests.molecular_analysis_method",
]

# Receptor status genes recorded in follow_ups.molecular_tests, keyed by IR column.
BIOMARKER_GENES = {"er_status": "ESR1", "pr_status": "PGR", "her2_status": "ERBB2"}
# When a patient has several tests for one gene (for example HER2 by IHC and then
# FISH), the first of these results found wins. Other results ("Test Value
# Reported", "Copy Number Reported") carry no status and are ignored.
_RESULT_PRIORITY = ("Positive", "Negative", "Equivocal")

# The IR columns this adapter emits: (name, role, GDC source field, description).
# Names here are the canonical vocabulary that packs and task specs refer to.
COLUMNS: list[tuple[str, Role, str, str]] = [
    ("gdc_case_id", Role.IDENTIFIER, "case_id", "GDC case UUID"),
    ("tissue_source_site", Role.SITE, "tissue_source_site.code", "TCGA tissue source site code"),
    ("sex", Role.FEATURE, "demographic.sex_at_birth", "Sex at birth (falls back to gender)"),
    ("race", Role.FEATURE, "demographic.race", "Race"),
    ("ethnicity", Role.FEATURE, "demographic.ethnicity", "Ethnicity"),
    ("age_at_index", Role.FEATURE, "demographic.age_at_index", "Age at index date, years"),
    ("age_at_diagnosis_days", Role.FEATURE, "diagnoses.age_at_diagnosis", "Age at diagnosis, days"),
    ("year_of_diagnosis", Role.FEATURE, "diagnoses.year_of_diagnosis", "Year of diagnosis"),
    ("primary_site", Role.FEATURE, "diagnoses.tissue_or_organ_of_origin", "Primary site"),
    (
        "site_of_resection_or_biopsy",
        Role.FEATURE,
        "diagnoses.site_of_resection_or_biopsy",
        "Site of resection or biopsy",
    ),
    ("primary_diagnosis", Role.FEATURE, "diagnoses.primary_diagnosis", "Histologic diagnosis"),
    ("morphology", Role.FEATURE, "diagnoses.morphology", "ICD-O-3 morphology code"),
    ("icd_10_code", Role.FEATURE, "diagnoses.icd_10_code", "ICD-10 code"),
    ("tumor_grade", Role.FEATURE, "diagnoses.tumor_grade", "Tumor grade"),
    ("laterality", Role.FEATURE, "diagnoses.laterality", "Laterality"),
    ("ajcc_pathologic_stage", Role.FEATURE, "diagnoses.ajcc_pathologic_stage", "AJCC stage group"),
    ("ajcc_pathologic_t", Role.FEATURE, "diagnoses.ajcc_pathologic_t", "AJCC pathologic T"),
    ("ajcc_pathologic_n", Role.FEATURE, "diagnoses.ajcc_pathologic_n", "AJCC pathologic N"),
    ("ajcc_pathologic_m", Role.FEATURE, "diagnoses.ajcc_pathologic_m", "AJCC pathologic M"),
    (
        "ajcc_staging_system_edition",
        Role.FEATURE,
        "diagnoses.ajcc_staging_system_edition",
        "AJCC staging manual edition",
    ),
    ("prior_malignancy", Role.FEATURE, "diagnoses.prior_malignancy", "Prior malignancy"),
    (
        "treatment_types",
        Role.FEATURE,
        "diagnoses.treatments.treatment_type",
        "Treatment types recorded as given for the primary diagnosis, '; '-joined; "
        "'none' when every record says no",
    ),
    ("er_status", Role.FEATURE, "follow_ups.molecular_tests[ESR1].test_result", "ER status"),
    ("pr_status", Role.FEATURE, "follow_ups.molecular_tests[PGR].test_result", "PR status"),
    ("her2_status", Role.FEATURE, "follow_ups.molecular_tests[ERBB2].test_result", "HER2 status"),
    (
        "progression_or_recurrence",
        Role.TARGET,
        "diagnoses.progression_or_recurrence",
        "Progression or recurrence",
    ),
    ("vital_status", Role.TARGET, "demographic.vital_status", "Vital status"),
    ("days_to_death", Role.TARGET, "demographic.days_to_death", "Days from index to death"),
    (
        "days_to_last_follow_up",
        Role.TARGET,
        "diagnoses.days_to_last_follow_up, follow_ups.days_to_follow_up",
        "Days from index to last follow-up (latest of the diagnosis and follow-up records)",
    ),
]

BASE_NAMES = [name for name, *_ in COLUMNS]
# The shared vocabulary beyond the original columns (adapters/vocabulary.py).
COLUMNS += [(name, role, "", description) for name, role, description, _ in EXTRA_COLUMNS]
_API_TREATMENT = "diagnoses.treatments.treatment_type + treatment_or_therapy"

_NUMERIC = [
    "age_at_index",
    "age_at_diagnosis_days",
    "year_of_diagnosis",
    "days_to_death",
    "days_to_last_follow_up",
]


def _in(field: str, values: list[str]) -> dict:
    return {"op": "in", "content": {"field": field, "value": values}}


def _post(endpoint: str, payload: dict, *, attempts: int = 3) -> dict:
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(f"{API}/{endpoint}", json=payload, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()["data"]
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def _paginate(
    endpoint: str,
    filters: dict,
    fields: list[str],
    *,
    limit: int | None = None,
    sort: str | None = None,
) -> list[dict]:
    hits: list[dict] = []
    while True:
        size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(hits))
        payload = {
            "filters": filters,
            "fields": ",".join(fields),
            "size": size,
            "from": len(hits),
            "format": "json",
        }
        if sort:
            payload["sort"] = sort
        data = _post(endpoint, payload)
        hits.extend(data["hits"])
        total = data["pagination"]["total"]
        if not data["hits"] or len(hits) >= total or (limit is not None and len(hits) >= limit):
            return hits


def _data_release() -> str | None:
    try:
        response = requests.get(f"{API}/status", timeout=30)
        response.raise_for_status()
        return response.json().get("data_release")
    except requests.RequestException:
        return None


def _clean(value, counts: dict[str, int]):
    """Return None for a GDC missing-value sentinel (and count it), else the value."""
    if isinstance(value, str) and value.strip().lower() in SENTINELS:
        key = value.strip() or "(empty string)"
        counts[key] = counts.get(key, 0) + 1
        return None
    return value


def _primary_diagnosis(diagnoses: list[dict]) -> dict | None:
    if not diagnoses:
        return None
    for dx in diagnoses:
        if dx.get("diagnosis_is_primary_disease") is True:
            return dx
    for dx in diagnoses:
        if str(dx.get("classification_of_tumor", "")).lower() == "primary":
            return dx
    return max(diagnoses, key=lambda dx: sum(v is not None for v in dx.values()))


def _treatment_types(dx: dict, counts: dict[str, int]) -> str | None:
    given: set[str] = set()
    answered = False
    for treatment in dx.get("treatments") or []:
        answer = _clean(treatment.get("treatment_or_therapy"), counts)
        kind = _clean(treatment.get("treatment_type"), counts)
        if answer is None:
            continue
        answered = True
        if str(answer).lower() == "yes" and kind:
            given.add(kind)
    if not answered:
        return None
    return "; ".join(sorted(given)) if given else "none"


def _api_extras(case: dict, dx: dict, counts: dict[str, int], fieldmap: dict) -> dict:
    """Treatment yes/no per class and HER2 by method, from the API records alone.

    "no" is only ever set from a record that says no. A patient with no record
    for a treatment class is left empty: not recorded is not the same as not given.
    """
    out: dict = {}
    answers: dict[str, set[str]] = {}
    agents: set[str] = set()
    neoadjuvant = None
    endocrine_start, endocrine_end = [], []
    for treatment in dx.get("treatments") or []:
        kind = str(_clean(treatment.get("treatment_type"), counts) or "").lower()
        answer = str(_clean(treatment.get("treatment_or_therapy"), counts) or "").lower()
        classes = [
            name
            for name, keywords in fieldmap["gdc_treatment_types"].items()
            if any(keyword in kind for keyword in keywords)
        ]
        for name in classes:
            if answer in ("yes", "no"):
                answers.setdefault(name, set()).add(answer)
        if answer != "yes":
            continue
        agent = _clean(treatment.get("therapeutic_agents"), counts)
        if agent:
            agents.add(str(agent).lower())
        intent = str(treatment.get("treatment_intent_type") or "").lower()
        if intent:
            is_neo = any(word in intent for word in fieldmap["gdc_neoadjuvant_intents"])
            neoadjuvant = "yes" if is_neo or neoadjuvant == "yes" else "no"
        if "endocrine_therapy" in classes:
            if treatment.get("days_to_treatment_start") is not None:
                endocrine_start.append(treatment["days_to_treatment_start"])
            if treatment.get("days_to_treatment_end") is not None:
                endocrine_end.append(treatment["days_to_treatment_end"])
    for name in fieldmap["gdc_treatment_types"]:
        found = answers.get(name, set())
        out[name] = "yes" if "yes" in found else ("no" if "no" in found else None)
    out["neoadjuvant_therapy"] = neoadjuvant
    out["drug_names"] = "; ".join(sorted(agents)) if agents else None
    out["endocrine_therapy_start_days"] = min(endocrine_start) if endocrine_start else None
    out["endocrine_therapy_end_days"] = max(endocrine_end) if endocrine_end else None

    # HER2 by method, so an equivocal IHC with no FISH follow-up stays visible.
    by_method: dict[str, set] = {"her2_ihc_status": set(), "her2_fish_status": set()}
    for follow_up in case.get("follow_ups") or []:
        for test in follow_up.get("molecular_tests") or []:
            if test.get("gene_symbol") != BIOMARKER_GENES["her2_status"]:
                continue
            method = str(test.get("molecular_analysis_method") or "").lower()
            if "ihc" in method or "immunohisto" in method:
                by_method["her2_ihc_status"].add(test.get("test_result"))
            elif "ish" in method or "in situ" in method:
                by_method["her2_fish_status"].add(test.get("test_result"))
    for column, results in by_method.items():
        out[column] = next((r for r in _RESULT_PRIORITY if r in results), None)
    return out


def _biomarker_status(case: dict, gene: str) -> str | None:
    results = {
        test.get("test_result")
        for follow_up in case.get("follow_ups") or []
        for test in follow_up.get("molecular_tests") or []
        if test.get("gene_symbol") == gene
    }
    return next((r for r in _RESULT_PRIORITY if r in results), None)


def _flatten_case(case: dict, counts: dict[str, int], fieldmap: dict | None = None) -> dict:
    demographic = case.get("demographic") or {}
    dx = _primary_diagnosis(case.get("diagnoses") or []) or {}

    def demo(field: str):
        return _clean(demographic.get(field), counts)

    def diag(field: str):
        return _clean(dx.get(field), counts)

    follow_up_days = [dx.get("days_to_last_follow_up")]
    follow_up_days += [f.get("days_to_follow_up") for f in case.get("follow_ups") or []]
    follow_up_days = [d for d in follow_up_days if d is not None]

    return {
        "patient_id": case["submitter_id"],
        "gdc_case_id": case.get("case_id") or case.get("id"),
        "tissue_source_site": _clean((case.get("tissue_source_site") or {}).get("code"), counts),
        "sex": demo("sex_at_birth") or demo("gender"),
        "race": demo("race"),
        "ethnicity": demo("ethnicity"),
        "age_at_index": demo("age_at_index"),
        "age_at_diagnosis_days": diag("age_at_diagnosis"),
        "year_of_diagnosis": diag("year_of_diagnosis"),
        "primary_site": diag("tissue_or_organ_of_origin"),
        "site_of_resection_or_biopsy": diag("site_of_resection_or_biopsy"),
        "primary_diagnosis": diag("primary_diagnosis"),
        "morphology": diag("morphology"),
        "icd_10_code": diag("icd_10_code"),
        "tumor_grade": diag("tumor_grade"),
        "laterality": diag("laterality"),
        "ajcc_pathologic_stage": diag("ajcc_pathologic_stage"),
        "ajcc_pathologic_t": diag("ajcc_pathologic_t"),
        "ajcc_pathologic_n": diag("ajcc_pathologic_n"),
        "ajcc_pathologic_m": diag("ajcc_pathologic_m"),
        "ajcc_staging_system_edition": diag("ajcc_staging_system_edition"),
        "prior_malignancy": diag("prior_malignancy"),
        "treatment_types": _treatment_types(dx, counts),
        **{column: _biomarker_status(case, gene) for column, gene in BIOMARKER_GENES.items()},
        "progression_or_recurrence": diag("progression_or_recurrence"),
        "vital_status": demo("vital_status"),
        "days_to_death": demo("days_to_death"),
        "days_to_last_follow_up": max(follow_up_days) if follow_up_days else None,
        **(_api_extras(case, dx, counts, fieldmap) if fieldmap else {}),
    }


def _feature_meta(name, role, source, description, sources, has_method) -> FeatureMeta:
    """Describe one column, including whether TCGA carries it and whether it was loaded."""
    availability, note, field = Availability.LOADED, None, source or None
    if name in sources:
        availability, note, supplement_field = sources[name]
        field = supplement_field or field
    elif name in ("her2_ihc_status", "her2_fish_status") and not has_method:
        availability = Availability.NOT_LOADED
        note = "Needs the patient table (--supplement) or the API test method field."
    elif name in DERIVED:
        field = "derived from " + ", ".join(DERIVED[name])
    elif name in EXTRA_NAMES:
        field = _API_TREATMENT
    if name in ("drug_names", "endocrine_therapy_start_days", "endocrine_therapy_end_days"):
        # Loaded from the API only when the optional treatment fields were fetched.
        field = field or "diagnoses.treatments (optional fields)"
    return FeatureMeta(
        name=name,
        modality="clinical",
        role=role,
        source_field=field,
        description=description,
        availability=availability,
        note=note,
    )


@register_adapter
class GDCAdapter(Adapter):
    name = "gdc"
    repository = "GDC"
    modalities = ("clinical", *MODALITY_DATA_TYPES)

    def fetch_raw(self, dataset: str, *, limit: int | None = None) -> dict:
        cases = _paginate(
            "cases",
            _in("project.project_id", [dataset]),
            CASE_FIELDS
            + (OPTIONAL_CASE_FIELDS if os.environ.get("SCORECARD_GDC_EXTENDED_FIELDS") else []),
            limit=limit,
            sort="submitter_id:asc",
        )
        if not cases:
            raise ValueError(f"GDC returned no cases for project {dataset!r}")

        modality_files: dict[str, list[dict]] = {}
        for modality, data_type in MODALITY_DATA_TYPES.items():
            clauses = [
                _in("cases.project.project_id", [dataset]),
                _in("data_type", [data_type]),
                _in("access", ["open"]),
            ]
            if limit is not None:
                clauses.append(_in("cases.submitter_id", [c["submitter_id"] for c in cases]))
            hits = _paginate(
                "files", {"op": "and", "content": clauses}, ["file_id", "cases.submitter_id"]
            )
            modality_files[modality] = [
                {
                    "file_id": hit["file_id"],
                    "cases": sorted({c["submitter_id"] for c in hit.get("cases", [])}),
                }
                for hit in hits
            ]

        return {
            "snapshot_version": 1,
            "adapter": self.name,
            "dataset": dataset,
            "limit": limit,
            "api": API,
            "data_release": _data_release(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cases": cases,
            "modality_files": modality_files,
        }

    def build_profile(self, raw: dict) -> DatasetProfile:
        cases = raw["cases"]
        dataset = raw["dataset"]
        sentinel_counts: dict[str, int] = {}

        fieldmap = load_fieldmap("tcga_brca")
        rows = [_flatten_case(case, sentinel_counts, fieldmap) for case in cases]
        features = pd.DataFrame.from_records(rows).set_index("patient_id").sort_index()
        features = features.reindex(columns=[name for name, *_ in COLUMNS]).astype(
            {name: object for name in EXTRA_NAMES}
        )
        for column in _NUMERIC:
            features[column] = pd.to_numeric(features[column], errors="coerce")

        # Local supplement files (never downloaded here): Biotab tables, TCGA-CDR,
        # published subtype and HRD tables.
        supplement = raw.get("supplement")
        if supplement is None and self.supplement_dir is not None:
            supplement = read_supplement(self.supplement_dir, fieldmap)
        sources = apply_supplement(features, supplement, fieldmap, sentinel_counts)
        features = derive(features)
        has_method = any(
            "molecular_analysis_method" in test
            for case in cases
            for follow_up in case.get("follow_ups") or []
            for test in follow_up.get("molecular_tests") or []
        )

        modalities = pd.DataFrame({"clinical": True}, index=features.index)
        for modality, files in raw["modality_files"].items():
            patients = {patient for f in files for patient in f["cases"]}
            modalities[modality] = features.index.isin(patients)

        n_multi_dx = sum(len(c.get("diagnoses") or []) > 1 for c in cases)
        n_no_dx = sum(not c.get("diagnoses") for c in cases)
        notes = [
            f"{n_multi_dx} of {len(cases)} cases have more than one diagnosis record; "
            "the record flagged as the primary disease is used.",
            "Gene expression and somatic mutation are reported as per-patient file presence "
            "only; their feature matrices are not loaded.",
        ]
        if n_no_dx:
            notes.append(f"{n_no_dx} cases have no diagnosis record.")
        if raw.get("limit"):
            notes.append(f"Development snapshot limited to the first {raw['limit']} cases.")
        supplement_files = {
            name: [f["file"] for f in table["files"]]
            for name, table in (supplement or {}).get("tables", {}).items()
        }
        if supplement_files:
            notes.append(f"Supplement tables read from local files: {supplement_files}.")
        else:
            notes.append(
                "No supplement folder given: variables that live in the Clinical Supplement, "
                "TCGA-CDR and published tables are declared but not loaded."
            )
        if not fieldmap.get("confirmed"):
            notes.append(
                "Field map tcga_brca.yaml is unconfirmed: source column names have not been "
                "checked against the downloaded files."
            )

        content = {"cases": cases, "modality_files": raw["modality_files"]}
        if supplement_files:
            content["supplement"] = {
                name: [f["sha256"] for f in table["files"]]
                for name, table in supplement["tables"].items()
            }
        provenance = Provenance(
            adapter=self.name,
            adapter_version=self.version,
            repository=self.repository,
            query={
                "api": raw.get("api", API),
                "project_id": dataset,
                "case_fields": CASE_FIELDS,
                "modality_data_types": MODALITY_DATA_TYPES,
                "limit": raw.get("limit"),
            },
            retrieved_at=raw["retrieved_at"],
            data_release=raw.get("data_release"),
            content_sha256=hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest(),
            n_source_records=len(cases),
            source_files={m: len(files) for m, files in raw["modality_files"].items()},
            sentinels_normalized=dict(sorted(sentinel_counts.items())),
            notes=notes,
        )

        return DatasetProfile(
            dataset_id=dataset,
            title=f"GDC · {dataset}" + (" (SYNTHETIC)" if "SYNTHETIC" in dataset else ""),
            description=(
                "Open-access clinical records from the Genomic Data Commons, one row per "
                "patient, with per-patient presence of gene expression and somatic mutation files."
            ),
            features=features,
            feature_meta={
                name: _feature_meta(name, role, source, description, sources, has_method)
                for name, role, source, description in COLUMNS
            },
            modalities=modalities,
            provenance=provenance,
            site_column="tissue_source_site",
        )


# TODO(lead / member-4): load the gene expression and somatic mutation matrices.
#   The file ids are already in the snapshot under raw["modality_files"]. Download
#   through the GDC /data endpoint, aggregate to one row per patient (a patient can
#   have several aliquots), add the columns to `features` with modality
#   "gene_expression" / "somatic_mutation", and describe them in `feature_meta`.
#   Keep the download in fetch_raw and the aggregation in build_profile.
