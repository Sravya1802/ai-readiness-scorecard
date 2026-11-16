"""SEER adapter: a local SEER*Stat case listing for female breast cancer.

SEER has no public API for case-level data. The input is a case listing
exported by someone who holds a SEER research data agreement, so this adapter
reads a local file and never calls a service.

Rules this adapter enforces, because SEER rows are covered by that agreement:
  - The export stays where the user put it (under the git-ignored data/ folder).
    Nothing is copied to the snapshot cache and `scorecard snapshot` is refused.
  - The SEER patient id is used only to keep one record per person and is then
    dropped. Rows get a run-local label instead.
  - The profile is marked so reports show counts and percentages only, with
    small cells suppressed and no example patients.
  - SEER patients are never joined to GDC, IDC or PDC patients (not linkable).

Source column names come from adapters/fieldmaps/seer_breast.yaml.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scorecard.adapters.base import Adapter, register_adapter
from scorecard.adapters.fieldmap import extract, find_columns, load_fieldmap
from scorecard.adapters.gdc import COLUMNS as SHARED_COLUMNS
from scorecard.adapters.vocabulary import DERIVED, derive
from scorecard.profile import (
    DAYS_PER_YEAR,
    Availability,
    DatasetProfile,
    FeatureMeta,
    PrivacyPolicy,
    Provenance,
    Role,
)

DEFAULT_MIN_CELL = 11
PRIVACY_BASIS = (
    "SEER research data use agreement: case-level rows are not shared; reports show counts "
    "and percentages only. Confirm the agreement's small-cell rule before sharing a report."
)


def _min_cell() -> int:
    return int(os.environ.get("SCORECARD_MIN_CELL", DEFAULT_MIN_CELL))


@register_adapter
class SEERAdapter(Adapter):
    name = "seer"
    repository = "SEER"
    modalities = ("registry",)
    implemented = True
    linkable = False
    allow_snapshot = False
    owner = "lead"

    def fetch_raw(self, dataset: str, *, limit: int | None = None) -> dict:
        """Read a local SEER*Stat export. `dataset` is the path to the file."""
        path = Path(dataset)
        if not path.is_file():
            raise FileNotFoundError(
                f"{dataset!r} is not a file. SEER has no download API: export a case listing "
                "from SEER*Stat, keep it under data/, and pass its path with --snapshot."
            )
        table = pd.read_csv(path, sep=None, engine="python", dtype=str, nrows=limit)
        return {
            "adapter": self.name,
            "dataset": "SEER female breast cancer",
            "source_file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
                timespec="seconds"
            ),
            "columns": [str(c) for c in table.columns],
            "rows": table.astype(object).where(table.notna(), None).to_dict(orient="records"),
        }

    def load(self, dataset, *, cache_dir=None, refresh=False, limit=None) -> DatasetProfile:
        # Deliberately no cache: case-level SEER rows are never written anywhere by this tool.
        return self.build_profile(self.fetch_raw(dataset, limit=limit))

    def load_snapshot(self, path: str | Path) -> DatasetProfile:
        return self.build_profile(self.fetch_raw(str(path)))

    def build_profile(self, raw: dict) -> DatasetProfile:
        fieldmap = load_fieldmap("seer_breast")
        table = pd.DataFrame.from_records(raw["rows"], columns=raw["columns"])
        counts: dict[str, int] = {}
        notes: list[str] = []

        # One record per person: the earliest diagnosis in the export.
        n_records = len(table)
        id_column = find_columns(table, fieldmap["patient_id"])
        if id_column:
            order = find_columns(table, fieldmap["order_by"])
            if order:
                table = table.sort_values(order[0], kind="stable")
            table = table.drop_duplicates(subset=id_column[0], keep="first")
            if len(table) < n_records:
                notes.append(
                    "Later records of people with more than one record were dropped; the "
                    "earliest diagnosis is kept."
                )
        else:
            notes.append("No patient id column in the export; every row is treated as one person.")
        table = table.reset_index(drop=True)
        index = pd.Index([f"seer-{i + 1:07d}" for i in range(len(table))], name="patient_id")

        names = [name for name, *_ in SHARED_COLUMNS]
        features = pd.DataFrame(None, index=index, columns=names, dtype=object)
        meta_extra: dict[str, dict] = {}
        not_found: list[str] = []
        months = None
        for column, spec in fieldmap["columns"].items():
            values, used = extract(table, spec, fieldmap["sentinels"], counts)
            if values is None:
                not_found.append(column)
                continue
            values.index = index
            info = {
                "source_field": " | ".join(used),
                "caveats": spec.get("caveats", []),
                "note": " ".join(spec["note"].split()) if spec.get("note") else None,
            }
            if column == "os_time_months":
                months = pd.to_numeric(values, errors="coerce")
                meta_extra["os_time_days"] = info
                continue
            features[column] = values
            meta_extra[column] = info

        if months is not None:
            features["os_time_days"] = months * DAYS_PER_YEAR / 12
            dead, alive = features["vital_status"] == "Dead", features["vital_status"] == "Alive"
            features.loc[dead, "days_to_death"] = features.loc[dead, "os_time_days"]
            features.loc[alive, "days_to_last_follow_up"] = features.loc[alive, "os_time_days"]
            if features["dss_event"].notna().any():
                features["dss_time_days"] = features["os_time_days"]
                meta_extra["dss_time_days"] = meta_extra["os_time_days"]
            for column in ("days_to_death", "days_to_last_follow_up"):
                meta_extra[column] = meta_extra["os_time_days"]
        features = derive(features)
        for column in (
            "age_at_index",
            "year_of_diagnosis",
            "days_to_death",
            "days_to_last_follow_up",
        ):
            features[column] = pd.to_numeric(features[column], errors="coerce")

        absent = fieldmap.get("not_in_source", {})
        feature_meta = {}
        for name, role, _, description in SHARED_COLUMNS:
            availability, note, source, caveats = Availability.LOADED, None, None, []
            if name in meta_extra:
                source, caveats = meta_extra[name]["source_field"], meta_extra[name]["caveats"]
                note = meta_extra[name]["note"]
            elif name in absent:
                availability, note = Availability.NOT_IN_SOURCE, absent[name]
            elif name in DERIVED and any(d in meta_extra for d in DERIVED[name]):
                source = "derived from " + ", ".join(DERIVED[name])
            else:
                availability = Availability.NOT_LOADED
                note = (
                    "Not found in this export. Add the variable to the SEER*Stat case listing, "
                    "or fix its name in adapters/fieldmaps/seer_breast.yaml."
                )
            feature_meta[name] = FeatureMeta(
                name=name,
                modality="registry",
                role=Role.IDENTIFIER if name == "gdc_case_id" else role,
                source_field=source,
                description=description or name.replace("_", " "),
                availability=availability,
                caveats=list(caveats),
                note=note,
            )
        # tissue_source_site has the SITE role in the shared vocabulary; SEER has no
        # site label here, so it is an ordinary empty column and site_column stays None.
        feature_meta["tissue_source_site"].role = Role.FEATURE

        if not_found:
            notes.append(
                "Field map variables not found in this export: " + ", ".join(sorted(not_found))
            )
        if not fieldmap.get("confirmed"):
            notes.append(
                "Field map seer_breast.yaml is unconfirmed: column names and value codes have "
                "not been checked against a real export."
            )
        notes.append("SEER patients are never linked to patients in other repositories.")

        synthetic = "synthetic" in raw["source_file"].lower()
        if synthetic:
            notes.insert(0, "Synthetic demo export: every value is invented.")
        return DatasetProfile(
            dataset_id="SEER-breast-synthetic" if synthetic else "SEER-breast",
            title="SEER · female breast cancer" + (" (SYNTHETIC)" if synthetic else ""),
            description=(
                "SEER*Stat case listing, one row per person. Registry data: no endocrine "
                "therapy, menopausal status, drug names or germline results, and chemotherapy "
                'and radiation are released as "yes" or "no/unknown".'
            ),
            features=features,
            feature_meta=feature_meta,
            modalities=pd.DataFrame({"registry": True}, index=index),
            provenance=Provenance(
                adapter=self.name,
                adapter_version=self.version,
                repository=self.repository,
                query={"source_file": raw["source_file"], "columns": raw["columns"]},
                retrieved_at=raw["retrieved_at"],
                data_release=raw.get("data_release"),
                content_sha256=raw["sha256"],
                n_source_records=n_records,
                # Small counts are left out, like any other small cell.
                sentinels_normalized={k: v for k, v in sorted(counts.items()) if v >= _min_cell()},
                notes=notes,
            ),
            site_column=None,
            linkable=False,
            privacy=PrivacyPolicy(
                patient_level_output=False, min_cell_count=_min_cell(), basis=PRIVACY_BASIS
            ),
        )
