"""Local TCGA files that add what the GDC API clinical fields do not carry.

Clinical Supplement (BCR Biotab) patient, drug and radiation tables, the TCGA
Clinical Data Resource, and published subtype and HRD tables. Nothing here
downloads anything: the files are read from a folder the user points at with
`--supplement`, which should sit under the git-ignored data/ folder.

Source column names come from adapters/fieldmaps/tcga_brca.yaml.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from pathlib import Path

import pandas as pd

from scorecard.adapters.fieldmap import clean, extract, find_columns
from scorecard.profile import Availability

BARCODE = re.compile(r"^TCGA-\w{2}-\w{4}", re.IGNORECASE)
TREATMENT_CLASSES = ("chemotherapy", "endocrine_therapy", "targeted_therapy", "immunotherapy")
Status = tuple[Availability, str | None, str | None]  # availability, note, source field


def _read(path: Path, sheet: str | None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        try:
            book = pd.ExcelFile(path)
        except ImportError as exc:
            raise ImportError(
                f"Reading {path.name} needs openpyxl (pip install openpyxl), "
                "or save the sheet as CSV."
            ) from exc
        name = sheet if sheet in book.sheet_names else book.sheet_names[0]
        return book.parse(name, dtype=str)
    return pd.read_csv(path, sep="," if suffix == ".csv" else "\t", dtype=str, low_memory=False)


def read_supplement(folder: str | Path, fieldmap: dict) -> dict:
    """Read every table the field map names. Returns a JSON-serializable snapshot part."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"supplement folder {folder} does not exist")
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    tables: dict[str, dict] = {}
    for name, spec in fieldmap["tables"].items():
        frames, used = [], []
        for path in files:
            if not any(fnmatch.fnmatch(path.name, pattern) for pattern in spec["files"]):
                continue
            if path.suffix.lower() not in (".txt", ".tsv", ".csv", ".xlsx", ".xls"):
                continue
            frame = _read(path, spec.get("sheet"))
            key = find_columns(frame, spec["key"])
            if not key:
                continue
            # Biotab files carry two extra header rows; real rows start with a barcode.
            frame = frame[frame[key[0]].astype("string").str.match(BARCODE).fillna(False)]
            for column, wanted in (spec.get("where") or {}).items():
                hit = find_columns(frame, [column])
                if hit:
                    frame = frame[frame[hit[0]].astype("string").str.upper() == str(wanted).upper()]
            frame = frame.rename(columns={key[0]: "_barcode"})
            frames.append(frame)
            used.append(
                {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
        if frames:
            table = pd.concat(frames, ignore_index=True)
            table = table.astype(object).where(table.notna(), None)
            tables[name] = {"files": used, "rows": table.to_dict(orient="records")}
    return {"folder": folder.name, "tables": tables}


def _table(supplement: dict | None, name: str) -> pd.DataFrame | None:
    if not supplement or name not in supplement.get("tables", {}):
        return None
    frame = pd.DataFrame.from_records(supplement["tables"][name]["rows"])
    if frame.empty:
        return None
    barcode = frame["_barcode"].astype("string").str.upper()
    frame["_patient"] = barcode.str[:12]
    # Sample-level tables: prefer the primary tumor sample (code 01) for each patient.
    frame["_rank"] = (~((barcode.str.len() == 12) | (barcode.str[13:15] == "01"))).astype(int)
    return frame.sort_values("_rank", kind="stable")


def _per_patient(frame: pd.DataFrame, values: pd.Series, index: pd.Index) -> pd.Series:
    values = pd.Series(values.to_numpy(), index=frame["_patient"].to_numpy())
    values = values[values.notna()]
    return values[~values.index.duplicated()].reindex(index)


def _yes_no(values: pd.Series | None) -> pd.Series | None:
    if values is None:
        return None
    text = values.astype("string").str.strip().str.lower()
    out = pd.Series(None, index=values.index, dtype=object)
    out[text == "yes"], out[text == "no"] = "yes", "no"
    return out


def _combine(current: pd.Series, new: pd.Series) -> pd.Series:
    """Merge two yes/no/empty series: any yes wins, then any no, else empty."""
    out = pd.Series(None, index=current.index, dtype=object)
    out[(current == "no") | (new == "no")] = "no"
    out[(current == "yes") | (new == "yes")] = "yes"
    return out


def apply_supplement(
    features: pd.DataFrame, supplement: dict | None, fieldmap: dict, counts: dict[str, int]
) -> dict[str, Status]:
    """Fill the supplement-backed columns of `features` in place; report where each came from."""
    sentinels = fieldmap["sentinels"]
    index = features.index
    status: dict[str, Status] = {}
    hint = "pass the folder with --supplement" if not supplement else "file not found in the folder"

    for column, spec in fieldmap["columns"].items():
        table = _table(supplement, spec["table"])
        if not spec.get("candidates"):
            status[column] = (
                Availability.NOT_LOADED,
                "No source column has been identified for this variable yet "
                "(adapters/fieldmaps/tcga_brca.yaml).",
                None,
            )
            continue
        if table is None:
            status[column] = (
                Availability.NOT_LOADED,
                f"Needs the {spec['table']} table: {hint}.",
                None,
            )
            continue
        values, used = extract(table, spec, sentinels, counts)
        if values is None:
            status[column] = (
                Availability.NOT_LOADED,
                f"None of {spec['candidates']} is a column of the {spec['table']} table; "
                "fix the field map.",
                None,
            )
            continue
        features[column] = _per_patient(table, values, index)
        status[column] = (Availability.LOADED, None, f"{spec['table']}.{used[0]}")

    patient = _table(supplement, "patient")
    flags: dict[str, pd.Series | None] = {}
    for flag, candidates in fieldmap.get("patient_flags", {}).items():
        flags[flag] = None
        if patient is not None:
            values, _ = extract(patient, {"candidates": candidates}, sentinels, counts)
            if values is not None:
                flags[flag] = _yes_no(_per_patient(patient, values, index))

    _apply_drugs(
        features,
        _table(supplement, "drug"),
        flags["systemic_therapy"],
        fieldmap,
        counts,
        status,
        hint,
    )

    radiation = _table(supplement, "radiation")
    if radiation is not None or flags["radiation_therapy"] is not None:
        new = pd.Series(None, index=index, dtype=object)
        if flags["radiation_therapy"] is not None:
            new = flags["radiation_therapy"].copy()
        if radiation is not None:
            new[index.isin(radiation["_patient"])] = "yes"
        features["radiation_therapy"] = _combine(features["radiation_therapy"], new)

    for column, note in fieldmap.get("not_in_source", {}).items():
        status[column] = (Availability.NOT_IN_SOURCE, note, None)
    return status


def _apply_drugs(features, drug, systemic_flag, fieldmap, counts, status, hint) -> None:
    spec = fieldmap["drug"]
    index = features.index
    drug_only = (
        "ovarian_suppression",
        "endocrine_therapy_start_days",
        "endocrine_therapy_end_days",
    )
    if drug is None:
        for column in (*drug_only, "drug_names"):
            if features[column].notna().any():
                continue  # already filled from the GDC API treatment records
            status[column] = (Availability.NOT_LOADED, f"Needs the drug table: {hint}.", None)
        if systemic_flag is not None:
            explicit_no = systemic_flag == "no"
            for column in TREATMENT_CLASSES:
                new = pd.Series(None, index=index, dtype=object)
                new[explicit_no] = "no"
                features[column] = _combine(features[column], new)
        return

    def column_of(key: str) -> pd.Series | None:
        values, _ = extract(drug, {"candidates": spec[key]}, fieldmap["sentinels"], counts)
        return values

    kind = column_of("type")
    name = column_of("name")
    start = (
        pd.to_numeric(column_of("start_days"), errors="coerce")
        if column_of("start_days") is not None
        else None
    )
    end = (
        pd.to_numeric(column_of("end_days"), errors="coerce")
        if column_of("end_days") is not None
        else None
    )
    patients = drug["_patient"]
    has_record = pd.Series(index.isin(patients), index=index)
    kind_text = kind.astype("string").str.lower() if kind is not None else None

    for column in TREATMENT_CLASSES:
        new = pd.Series(None, index=index, dtype=object)
        if spec.get("infer_no_from_other_drug_records"):
            new[has_record] = "no"
        if systemic_flag is not None:
            new[systemic_flag == "no"] = "no"
        if kind_text is not None:
            hit = pd.Series(False, index=drug.index)
            for keyword in spec["classes"][column]:
                hit |= kind_text.str.contains(keyword, regex=False).fillna(False)
            new[index.isin(patients[hit])] = "yes"
            if column == "endocrine_therapy":
                if start is not None:
                    features["endocrine_therapy_start_days"] = (
                        start[hit].groupby(patients[hit]).min().reindex(index)
                    )
                if end is not None:
                    features["endocrine_therapy_end_days"] = (
                        end[hit].groupby(patients[hit]).max().reindex(index)
                    )
        features[column] = _combine(features[column], new)

    if name is not None:
        names = name.astype("string").str.strip().str.lower()
        joined = (
            names.dropna().groupby(patients[names.notna()]).agg(lambda s: "; ".join(sorted(set(s))))
        )
        features["drug_names"] = (
            joined.reindex(index).astype(object).where(joined.reindex(index).notna(), None)
        )
        suppress = pd.Series(False, index=drug.index)
        for keyword in spec["ovarian_suppression_drugs"]:
            suppress |= names.str.contains(keyword, regex=False).fillna(False)
        flag = pd.Series(None, index=index, dtype=object)
        flag[index.isin(patients[suppress])] = "yes"
        features["ovarian_suppression"] = flag
    for column, source in (
        ("drug_names", name),
        ("ovarian_suppression", name),
        ("endocrine_therapy_start_days", start),
        ("endocrine_therapy_end_days", end),
    ):
        status[column] = (
            (Availability.LOADED, None, "drug table")
            if source is not None
            else (
                Availability.NOT_LOADED,
                "Column not found in the drug table; fix the field map.",
                None,
            )
        )


__all__ = ["apply_supplement", "clean", "read_supplement"]
