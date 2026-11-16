"""Write an invented TCGA-shaped and SEER-shaped dataset for a trial run.

Every value is random. No row comes from a real patient or a real file; the
shapes (file names, column headers, value codes) follow the published metadata
so the adapters can be exercised end to end before any real download.

    python scripts/make_synthetic_demo.py            # writes data/synthetic/
    scorecard profile --snapshot data/synthetic/gdc_synthetic_snapshot.json \\
        --supplement data/synthetic/tcga_supplement --task chemo-benefit --out out/...

Output goes under data/, which git ignores, so it is never committed.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

RNG = np.random.default_rng(20261116)
HEADER_NOTE = "Synthetic demo file. Invented values only. Not real patient data."


def pick(options, p):
    """One option, chosen with the given relative weights. Works for any kind of option."""
    index = RNG.choice(len(options), p=np.array(p, dtype=float) / sum(p))
    option = options[index]
    return option.item() if hasattr(option, "item") else option


def stage_parts(stage):
    t = {
        "I": "T1c",
        "II": pick(["T1c", "T2"], [1, 2]),
        "III": pick(["T2", "T3", "T4b"], [2, 2, 1]),
        "IV": pick(["T2", "T3"], [1, 1]),
    }[stage]
    return t


def nodes_for(stage):
    if stage == "I":
        return 0
    if stage == "II":
        return int(pick([0, 1, 2, 3], [5, 3, 2, 1]))
    if stage == "III":
        return int(RNG.integers(1, 15))
    return int(RNG.integers(0, 10))


# ---------------------------------------------------------------- TCGA-shaped


def make_tcga(out: Path, n: int) -> None:
    supp = out / "tcga_supplement"
    supp.mkdir(parents=True, exist_ok=True)
    cases, patients, drugs, rads, cdr, hrd, subtype = [], [], [], [], [], [], []
    files = {"gene_expression": [], "somatic_mutation": [], "copy_number": []}
    for k in range(1, n + 1):
        bc = f"TCGA-SY-{k:04d}"
        age = int(np.clip(RNG.normal(58, 13), 26, 90))
        er = pick(["Positive", "Negative"], [78, 22])
        pr = (
            pick(["Positive", "Negative"], [85, 15])
            if er == "Positive"
            else pick(["Positive", "Negative"], [10, 90])
        )
        ihc = pick(["Positive", "Negative", "Equivocal"], [13, 79, 8])
        fish = None
        if ihc == "Equivocal" and RNG.random() < 0.7:
            fish = pick(["Positive", "Negative"], [25, 75])
        her2_final = fish or ihc
        stage = pick(["I", "II", "III", "IV", "X"], [18, 57, 22, 2, 1])
        sub = {
            "I": "A",
            "II": pick(["A", "B"], [1, 1]),
            "III": pick(["A", "B", "C"], [3, 1, 1]),
            "IV": "",
            "X": "",
        }[stage]
        stage_label = "Stage X" if stage == "X" else f"Stage {stage}{sub}"
        nodes = nodes_for(stage if stage != "X" else "II")
        n_cat = "N0" if nodes == 0 else ("N1a" if nodes <= 3 else ("N2a" if nodes <= 9 else "N3a"))
        m_cat = "M1" if stage == "IV" else pick(["M0", "MX"], [92, 8])
        meno = (
            (
                "Pre (<6 months since LMP AND no prior bilateral ovariectomy AND not on estrogen "
                "replacement)"
            )
            if age < 46
            else (
                "Post (prior bilateral ovariectomy OR >12 mo since LMP with no prior hysterectomy)"
            )
        )
        if 46 <= age <= 54:
            meno = pick([meno, "Peri (6-12 months since last menstrual period)"], [3, 1])
        if RNG.random() < 0.10:
            meno = "[Not Available]"

        chemo = RNG.random() < (0.75 if (er == "Negative" or nodes > 0) else 0.40)
        hormone = er == "Positive" and RNG.random() < 0.80
        targeted = her2_final == "Positive" and RNG.random() < 0.6
        radiation = RNG.random() < 0.55
        neo = RNG.random() < 0.04
        dead = RNG.random() < 0.14
        follow = int(np.clip(RNG.exponential(1100) + 60, 30, 8000))
        days_to_death = int(RNG.uniform(30, follow)) if dead else None

        treatments = []
        if chemo:
            treatments.append(
                {"treatment_type": "Pharmaceutical Therapy, NOS", "treatment_or_therapy": "yes"}
            )
        elif RNG.random() < 0.3:
            treatments.append({"treatment_type": "Chemotherapy", "treatment_or_therapy": "no"})
        if radiation:
            treatments.append(
                {"treatment_type": "Radiation Therapy, NOS", "treatment_or_therapy": "yes"}
            )
        tests = [
            {"gene_symbol": "ESR1", "test_result": er},
            {"gene_symbol": "PGR", "test_result": pr},
            {"gene_symbol": "ERBB2", "test_result": ihc},
        ]
        if fish:
            tests.append({"gene_symbol": "ERBB2", "test_result": fish})
        cases.append(
            {
                "submitter_id": bc,
                "case_id": f"00000000-0000-4000-8000-{k:012d}",
                "tissue_source_site": {
                    "code": pick(["A1", "A2", "AR", "BH", "D8", "E2", "AO"], [1, 2, 3, 6, 3, 3, 2])
                },
                "demographic": {
                    "vital_status": "Dead" if dead else "Alive",
                    "days_to_death": days_to_death,
                    "sex_at_birth": pick(["female", "male"], [99, 1]),
                    "race": pick(
                        ["white", "black or african american", "asian", "not reported"],
                        [70, 16, 6, 8],
                    ),
                    "ethnicity": pick(
                        ["not hispanic or latino", "hispanic or latino", "not reported"],
                        [80, 4, 16],
                    ),
                    "age_at_index": age,
                },
                "diagnoses": [
                    {
                        "diagnosis_is_primary_disease": True,
                        "age_at_diagnosis": age * 365 + int(RNG.integers(0, 364)),
                        "year_of_diagnosis": int(RNG.integers(2002, 2014)),
                        "tissue_or_organ_of_origin": "Breast, NOS",
                        "site_of_resection_or_biopsy": "Breast, NOS",
                        "primary_diagnosis": pick(
                            [
                                "Infiltrating duct carcinoma, NOS",
                                "Lobular carcinoma, NOS",
                                "Infiltrating duct and lobular carcinoma",
                            ],
                            [72, 19, 9],
                        ),
                        "morphology": "8500/3",
                        "icd_10_code": "C50.9",
                        "tumor_grade": "Not Reported",
                        "laterality": pick(["Left", "Right"], [1, 1]),
                        "ajcc_pathologic_stage": stage_label,
                        "ajcc_pathologic_t": "TX" if stage == "X" else stage_parts(stage),
                        "ajcc_pathologic_n": n_cat,
                        "ajcc_pathologic_m": m_cat,
                        "ajcc_staging_system_edition": pick(["6th", "7th"], [1, 2]),
                        "prior_malignancy": pick(["no", "yes"], [93, 7]),
                        "progression_or_recurrence": "not reported",
                        "days_to_last_follow_up": None if dead else follow,
                        "treatments": treatments,
                    }
                ],
                "follow_ups": [{"days_to_follow_up": follow, "molecular_tests": tests}],
            }
        )
        for modality, share in (
            ("gene_expression", 0.98),
            ("somatic_mutation", 0.92),
            ("copy_number", 0.97),
        ):
            if RNG.random() < share:
                files[modality].append({"file_id": f"syn-{modality}-{k}", "cases": [bc]})

        systemic = chemo or hormone or targeted
        patients.append(
            {
                "bcr_patient_barcode": bc,
                "menopause_status": meno,
                "lymph_nodes_examined_he_count": "[Not Available]"
                if RNG.random() < 0.12
                else nodes,
                "lymph_nodes_examined_count": nodes + int(RNG.integers(1, 15)),
                "margin_status": pick(
                    ["Negative", "Positive", "Close", "[Not Available]"], [80, 6, 4, 10]
                ),
                "her2_status_by_ihc": ihc,
                "her2_fish_status": fish or "[Not Evaluated]",
                "surgical_procedure_first": pick(
                    [
                        "Modified Radical Mastectomy",
                        "Lumpectomy",
                        "Simple Mastectomy",
                        "[Not Available]",
                    ],
                    [35, 40, 21, 4],
                ),
                "history_neoadjuvant_treatment": "Yes" if neo else "No",
                "pharmaceutical_tx_adjuvant": (
                    "YES" if systemic else pick(["NO", "[Not Available]"], [1, 1])
                ),
                "radiation_treatment_adjuvant": "YES"
                if radiation
                else pick(["NO", "[Not Available]"], [1, 1]),
            }
        )
        start = int(RNG.integers(20, 200))
        if chemo:
            for drug in pick(
                [
                    ["Doxorubicin", "Cyclophosphamide", "Paclitaxel"],
                    ["Docetaxel", "Cyclophosphamide"],
                ],
                [2, 1],
            ):
                drugs.append([bc, drug, "Chemotherapy", start, start + 120])
        if hormone:
            hs = start + 150
            he = hs + int(RNG.uniform(1, 6) * 365) if RNG.random() < 0.6 else "[Not Available]"
            drugs.append(
                [
                    bc,
                    pick(["Tamoxifen", "Anastrozole", "Letrozole"], [2, 1, 1]),
                    "Hormone Therapy",
                    hs,
                    he,
                ]
            )
            if age < 46 and RNG.random() < 0.25:
                drugs.append([bc, "Goserelin", "Hormone Therapy", hs, he])
        if targeted:
            drugs.append([bc, "Trastuzumab", "Targeted Molecular therapy", start, start + 365])
        if radiation:
            rads.append([bc, "External Beam", "Primary Tumor Field"])

        pfi = RNG.random() < 0.13
        pfi_t = int(RNG.uniform(min(90, follow - 1), follow)) if pfi else follow
        cdr.append(
            {
                "bcr_patient_barcode": bc,
                "type": "BRCA",
                "PFI": int(pfi),
                "PFI.time": pfi_t,
                "DFI": "" if RNG.random() < 0.15 else int(pfi),
                "DFI.time": pfi_t,
                "DSS": int(dead and RNG.random() < 0.7),
                "DSS.time": days_to_death or follow,
            }
        )
        tnbc = er == "Negative" and pr == "Negative" and her2_final == "Negative"
        if RNG.random() < 0.92:
            score = RNG.gamma(4, 10 if tnbc else 4.5)
            hrd.append({"sample": f"{bc}-01A", "HRD": int(min(score, 95))})
        if RNG.random() < 0.85:
            subtype.append(
                {
                    "patient": bc,
                    "BRCA_Subtype_PAM50": (
                        "Basal"
                        if tnbc
                        else (
                            "Her2"
                            if her2_final == "Positive"
                            else pick(["LumA", "LumB", "Normal"], [6, 3, 1])
                        )
                    ),
                }
            )

    snapshot = {
        "snapshot_version": 1,
        "adapter": "gdc",
        "dataset": "SYNTHETIC-TCGA-BRCA",
        "limit": None,
        "api": "synthetic",
        "data_release": "synthetic demo, invented values",
        "retrieved_at": "2026-11-16T00:00:00+00:00",
        "cases": cases,
        "modality_files": files,
    }
    (out / "gdc_synthetic_snapshot.json").write_text(json.dumps(snapshot))

    def write_biotab(name, header, rows):
        with open(supp / name, "w", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(header)
            w.writerow(header)  # Biotab files carry two extra header rows
            w.writerow([f"CDE_ID:{i}" for i in range(len(header))])
            w.writerows(rows)

    p_header = list(patients[0])
    write_biotab(
        "nationwidechildrens.org_clinical_patient_brca.txt",
        p_header,
        [[p[h] for h in p_header] for p in patients],
    )
    write_biotab(
        "nationwidechildrens.org_clinical_drug_brca.txt",
        [
            "bcr_patient_barcode",
            "pharmaceutical_therapy_drug_name",
            "pharmaceutical_therapy_type",
            "pharmaceutical_tx_started_days_to",
            "pharmaceutical_tx_ended_days_to",
        ],
        drugs,
    )
    write_biotab(
        "nationwidechildrens.org_clinical_radiation_brca.txt",
        ["bcr_patient_barcode", "radiation_type", "anatomic_treatment_site"],
        rads,
    )
    for name, rows in (
        ("TCGA-CDR-synthetic.csv", cdr),
        ("HRD_scores_synthetic.csv", hrd),
        ("PAM50_subtype_synthetic.csv", subtype),
    ):
        with open(supp / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    (supp / "README.txt").write_text(HEADER_NOTE + "\n")


# ---------------------------------------------------------------- SEER-shaped


def make_seer(out: Path, n: int) -> None:
    rows = []
    for k in range(n):
        year = int(RNG.integers(2010, 2016))
        age = int(np.clip(RNG.normal(62, 13), 20, 95))
        stage = pick(["I", "II", "III", "IV", "unk"], [45, 35, 12, 6, 2])
        sub = {
            "I": "A",
            "II": pick(["A", "B"], [3, 2]),
            "III": pick(["A", "B", "C"], [3, 1, 1]),
            "IV": "",
            "unk": "",
        }[stage]
        nodes = nodes_for(stage if stage != "unk" else "II")
        nodes_code = f"{nodes:02d}" if RNG.random() > 0.08 else pick(["95", "98", "99"], [1, 3, 2])
        er = pick(["Positive", "Negative", "Borderline/Unknown"], [80, 17, 3])
        her2 = pick(["Positive", "Negative", "Borderline/Unknown"], [13, 82, 5])
        surgery = pick(["22", "23", "51", "41", "00", "99"], [40, 8, 22, 15, 4, 1])
        chemo = RNG.random() < (0.65 if (er != "Positive" or nodes > 0) else 0.25)
        seq = (
            "No systemic therapy and/or surgical procedures"
            if surgery == "00"
            else pick(
                [
                    "Systemic therapy after surgery",
                    "Systemic therapy before surgery",
                    "No systemic therapy and/or surgical procedures",
                ],
                [70, 7, 23],
            )
        )
        max_months = (2023 - year) * 12
        dead = RNG.random() < (0.55 if stage == "IV" else 0.12)
        months = (
            int(RNG.uniform(1, max_months))
            if dead
            else int(RNG.uniform(max_months - 11, max_months))
        )
        rows.append(
            {
                "Patient ID": f"{70000000 + k}",
                "Age recode with single ages and 90+": "90+ years" if age >= 90 else f"{age} years",
                "Sex": "Female",
                "Race recode (W, B, AI, API)": pick(
                    [
                        "White",
                        "Black",
                        "Asian or Pacific Islander",
                        "American Indian/Alaska Native",
                        "Unknown",
                    ],
                    [77, 11, 10, 1, 1],
                ),
                "Origin recode NHIA (Hispanic, Non-Hisp)": pick(
                    ["Non-Spanish-Hispanic-Latino", "Spanish-Hispanic-Latino"], [86, 14]
                ),
                "Year of diagnosis": year,
                "Primary Site - labeled": "C50.4-Upper-outer quadrant of breast",
                "Laterality": pick(
                    ["Left - origin of primary", "Right - origin of primary"], [1, 1]
                ),
                "Histologic Type ICD-O-3": pick(["8500", "8520", "8522"], [78, 12, 10]),
                "ICD-O-3 Hist/behav": "8500/3: Infiltrating duct carcinoma, NOS",
                "Grade Recode (thru 2017)": pick(
                    [
                        "Well differentiated; Grade I",
                        "Moderately differentiated; Grade II",
                        "Poorly differentiated; Grade III",
                        "Unknown",
                    ],
                    [20, 42, 31, 7],
                ),
                "CS tumor size (2004-2015)": f"{int(np.clip(RNG.gamma(2.2, 9), 1, 150)):03d}"
                if RNG.random() > 0.05
                else "999",
                "Regional nodes positive (1988+)": nodes_code,
                "Regional nodes examined (1988+)": f"{nodes + int(RNG.integers(1, 15)):02d}",
                "Derived AJCC Stage Group, 7th ed (2010-2015)": "UNK Stage"
                if stage == "unk"
                else f"{stage}{sub}",
                "Derived AJCC T, 7th ed (2010-2015)": "T1c" if stage == "I" else "T2",
                "Derived AJCC N, 7th ed (2010-2015)": "N0" if nodes == 0 else "N1",
                "Derived AJCC M, 7th ed (2010-2015)": "M1" if stage == "IV" else "M0",
                "Combined Summary Stage (2004+)": "Distant"
                if stage == "IV"
                else ("Localized" if nodes == 0 else "Regional"),
                "First malignant primary indicator": pick(["Yes", "No"], [88, 12]),
                "ER Status Recode Breast Cancer (1990+)": er,
                "PR Status Recode Breast Cancer (1990+)": er if RNG.random() < 0.85 else "Negative",
                "Derived HER2 Recode (2010+)": her2,
                "Breast Subtype (2010+)": "HR+/HER2-"
                if er == "Positive" and her2 == "Negative"
                else "Other",
                "RX Summ--Surg Prim Site (1998+)": surgery,
                "Chemotherapy recode (yes, no/unk)": "Yes" if chemo else "No/Unknown",
                "Radiation recode": pick(
                    ["Beam radiation", "None/Unknown", "Refused (1988+)"], [50, 48, 2]
                ),
                "RX Summ--Systemic/Sur Seq (2007+)": seq,
                "Survival months": f"{max(months, 0):04d}",
                "Vital status recode (study cutoff used)": "Dead" if dead else "Alive",
                "SEER cause-specific death classification": (
                    pick(
                        ["Dead (attributable to this cancer dx)", "Alive or dead of other cause"],
                        [6, 4],
                    )
                    if dead
                    else "Alive or dead of other cause"
                ),
            }
        )
    path = out / "seer_breast_synthetic.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data/synthetic")
    parser.add_argument("--tcga-n", type=int, default=1100)
    parser.add_argument("--seer-n", type=int, default=6000)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    make_tcga(out, args.tcga_n)
    make_seer(out, args.seer_n)
    (out / "README.txt").write_text(HEADER_NOTE + "\n")
    print(
        f"Wrote invented TCGA-shaped ({args.tcga_n}) and SEER-shaped ({args.seer_n}) data to {out}"
    )


if __name__ == "__main__":
    main()
