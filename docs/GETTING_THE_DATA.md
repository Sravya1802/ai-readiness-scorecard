# Getting the real data in

Step-by-step instructions for downloading TCGA-BRCA and SEER, putting the files where the tool expects them, running it, and confirming the field maps. Everything here runs in a plain terminal on your own machine.

Read [DATA_HANDLING.md](DATA_HANDLING.md) first. The short version: every download goes under `data/`, which git ignores, and nothing under `data/` or `out/` is ever committed.

> **Status.** The commands below were run end to end on the invented files in `data/synthetic/`. No real Clinical Supplement, TCGA-CDR, published table or SEER export has been through the code yet. Expect to fix some column names in Part 4.

## Who does what

The two datasets are independent, so two people can work in parallel.

| Track | Needs | Blocks |
| --- | --- | --- |
| A. TCGA-BRCA | A browser and about 15 minutes. No account. | Questions 1 to 5 on TCGA |
| B. SEER | A SEER*Stat account with Research Plus access | Questions 1 to 5 on SEER, and the representativeness check on TCGA |
| C. Oncotype DX (optional) | A separate request, open only to Research Plus users | The genomic risk variable for question 1 on SEER |

## Part 0. Set up once

```bash
git clone https://github.com/Sravya1802/ai-readiness-scorecard.git
cd ai-readiness-scorecard
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev,excel]"
```

`excel` installs openpyxl, which is needed to read the TCGA-CDR workbook. Python 3.10 or newer.

Create the folders:

```bash
mkdir -p data/tcga_brca data/seer
```

Check that git ignores them. This must print `data/tcga_brca`:

```bash
git check-ignore data/tcga_brca
```

Check that the tool runs before touching real data:

```bash
scorecard profile --snapshot tests/fixtures/gdc_tcga_brca_40.json --task chemo-benefit --out out/smoke
```

## Part 1. TCGA-BRCA (Track A)

The basic clinical fields (demographics, stage, ER/PR/HER2, vital status, which molecular files exist) are fetched from the GDC API by the tool. You only download the extra tables below.

### 1a. Clinical Supplement tables from the GDC Data Portal

1. Open <https://portal.gdc.cancer.gov> and go to **Repository**.
2. Set the filters:
   - Project: `TCGA-BRCA`
   - Access: `open`
   - Data Category: `clinical`
   - Data Type: `Clinical Supplement`
   - Data Format: `BCR Biotab`
3. Add these three files to the cart. The names should look like this:
   - `nationwidechildrens.org_clinical_patient_brca.txt`
   - `nationwidechildrens.org_clinical_drug_brca.txt`
   - `nationwidechildrens.org_clinical_radiation_brca.txt`
4. Open the cart and choose **Download → Cart**. Do not use the **Manifest** button: it gives a text file of file IDs, not the data.
5. Unpack the download into `data/tcga_brca/`. Subfolders are fine; the tool searches recursively.

The other Biotab files (follow-up, new tumor event, omf) are not read. Skip them.

### 1b. TCGA Clinical Data Resource (TCGA-CDR)

Curated survival, progression and disease-free endpoints from Liu et al., Cell 2018, Table S1.

1. Get `TCGA-CDR-SupplementalTableS1.xlsx` from the GDC PanCanAtlas publication page (<https://gdc.cancer.gov/about-data/publications/pancanatlas>) or from the paper's supplementary files.
2. Save it in `data/tcga_brca/` without renaming it.

The tool reads the sheet named `TCGA-CDR` and keeps the rows where `type` is `BRCA`. If you prefer, save that sheet as CSV; keep `TCGA-CDR` in the file name.

### 1c. Published PAM50 subtype and HRD score tables

These two sources are **not settled yet**. Whoever downloads them must record the exact paper, table and URL (Part 5).

| Table | What the tool needs | Likely source, to confirm |
| --- | --- | --- |
| PAM50 subtype | One row per patient or sample, a TCGA barcode column, and a subtype column | TCGA Pan-Cancer Atlas subtype table (the `BRCA_Subtype_PAM50` column) |
| HRD score | One row per patient or sample, a TCGA barcode column, and a numeric HRD sum | Pan-Cancer Atlas DNA damage repair paper (Knijnenburg et al., Cell Reports 2018) |

Save both in `data/tcga_brca/`.

### 1d. Check the file names

The tool finds each table by a pattern in the file name. Rename a file if it does not match.

| Table | File name must contain | Barcode column (first one found) |
| --- | --- | --- |
| patient | `clinical_patient_brca` | `bcr_patient_barcode` |
| drug | `clinical_drug_brca` | `bcr_patient_barcode` |
| radiation | `clinical_radiation_brca` | `bcr_patient_barcode` |
| cdr | `TCGA-CDR` or `clinical_data_resource` | `bcr_patient_barcode` |
| subtype | `subtype`, `PAM50` or `pam50` | `bcr_patient_barcode`, `patient`, `pan.samplesID`, `sample`, `Sample.ID`, `sampleID` |
| hrd | `HRD` or `hrd` | `bcr_patient_barcode`, `patient`, `sample`, `Sample.ID`, `sampleID`, `SampleBarcode` |

Rules that apply to all six:

- Accepted formats: `.txt` and `.tsv` (tab-delimited), `.csv`, `.xlsx`, `.xls`.
- Only rows whose barcode starts with `TCGA-XX-XXXX` are kept, so the two extra header rows in Biotab files are dropped automatically. Sample barcodes such as `TCGA-A2-A0T2-01` are accepted.
- Make sure no file matches two patterns. A file called `HRD_by_subtype.csv` would be read as both tables.

When you are done the folder should look roughly like this:

```
data/tcga_brca/
  nationwidechildrens.org_clinical_patient_brca.txt
  nationwidechildrens.org_clinical_drug_brca.txt
  nationwidechildrens.org_clinical_radiation_brca.txt
  TCGA-CDR-SupplementalTableS1.xlsx
  <PAM50 subtype table>
  <HRD score table>
```

### 1e. Look at the headers before running

Print the header row of a tab-delimited file, one column per line:

```bash
head -1 data/tcga_brca/nationwidechildrens.org_clinical_patient_brca.txt | tr '\t' '\n'
```

Compare against the columns the field map looks for (`src/scorecard/adapters/fieldmaps/tcga_brca.yaml`):

| Variable | Table | Column names tried, in order |
| --- | --- | --- |
| Positive nodes | patient | `lymph_nodes_examined_he_count`, `number_of_lymphnodes_positive_by_he` |
| Nodes examined | patient | `lymph_nodes_examined_count`, `lymph_node_examined_count` |
| Margin status | patient | `margin_status` |
| Menopausal status | patient | `menopause_status` |
| HER2 IHC status | patient | `her2_status_by_ihc`, `lab_proc_her2_neu_immunohistochemistry_receptor_status` |
| HER2 IHC score | patient | `her2_ihc_score`, `her2_immunohistochemistry_level_result` |
| HER2 FISH status | patient | `her2_fish_status`, `lab_procedure_her2_neu_in_situ_hybrid_outcome_type` |
| Surgery type | patient | `surgical_procedure_first`, `breast_carcinoma_surgical_procedure_name` |
| Treatment before surgery | patient | `history_neoadjuvant_treatment`, `history_of_neoadjuvant_treatment` |
| Systemic therapy flag | patient | `pharmaceutical_tx_adjuvant`, `targeted_molecular_therapy` |
| Radiation flag | patient | `radiation_treatment_adjuvant`, `radiation_therapy` |
| Drug type | drug | `pharmaceutical_therapy_type`, `therapy_type` |
| Drug name | drug | `pharmaceutical_therapy_drug_name`, `drug_name` |
| Drug start, end (days) | drug | `pharmaceutical_tx_started_days_to`, `days_to_drug_therapy_start`; `pharmaceutical_tx_ended_days_to`, `days_to_drug_therapy_end` |
| Progression-free, disease-free, disease-specific | cdr | `PFI`, `PFI.time`, `DFI`, `DFI.time`, `DSS`, `DSS.time` |
| PAM50 subtype | subtype | `BRCA_Subtype_PAM50`, `PAM50`, `PAM50.mRNA`, `Subtype_mRNA`, `SUBTYPE` |
| HRD score | hrd | `HRD`, `HRD_Score`, `HRD-sum`, `HRD_sum`, `hrd_sum`, `HRDsum` |

Tumor size in millimetres and family history have no known column in the patient file and are left empty. If you find one, add it under `candidates`.

## Part 2. SEER (Track B)

### 2a. Access

1. You need a SEER*Stat account. The chemotherapy, radiation and treatment-sequence fields are only in **Research Plus**, not the basic Research data. Check which level the account has before exporting.
2. Research Plus asks you to acknowledge the limits of the treatment fields. Read them; they are the reason the treatment adequacy check fails on SEER by design.
3. Optional (Track C): the Oncotype DX recurrence score is in a specialized database with its own request form. Submit it early or decide to go without it.

### 2b. Build the case listing in SEER*Stat

1. Start a new **Case Listing** session.
2. **Data tab:** pick the most recent Research Plus incidence database available to the account. Write down its full name for Part 5.
3. **Selection tab:** limit to female breast cancer, for example `Site recode ICD-O-3/WHO 2008 = Breast` and `Sex = Female`. Malignant behavior only. Record every selection statement.
4. **Table tab:** add the variables below as columns. Names differ slightly between data submissions (usually the year range in brackets). The tool ignores case, punctuation and anything in brackets when matching, so a different year range is fine.

| Group | SEER*Stat variable |
| --- | --- |
| Identity | Patient ID (used only to keep one record per person, then dropped) |
| Demographics | Age recode with single ages and 90+ · Sex · Race recode (W, B, AI, API) · Origin recode NHIA (Hispanic, Non-Hisp) · Year of diagnosis |
| Tumor | Primary Site - labeled · Laterality · Histologic Type ICD-O-3 · ICD-O-3 Hist/behav · Grade Pathological (2018+) · Grade Clinical (2018+) · Grade Recode (thru 2017) · Tumor Size Summary (2016+) · CS tumor size (2004-2015) · Regional nodes positive (1988+) · Regional nodes examined (1988+) |
| Stage | Derived EOD 2018 Stage Group Recode (2018+) · Derived SEER Cmb Stg Grp (2016-2017) · Derived AJCC Stage Group, 7th ed (2010-2015) · the matching T, N and M fields for each of the three · Combined Summary Stage (2004+) · First malignant primary indicator |
| Receptors | ER Status Recode Breast Cancer (1990+) · PR Status Recode Breast Cancer (1990+) · Derived HER2 Recode (2010+) · Breast Subtype (2010+) |
| Treatment | RX Summ--Surg Prim Site (1998+) · Chemotherapy recode (yes, no/unk) · Radiation recode · RX Summ--Systemic/Sur Seq (2007+) · RX Summ--Surg/Rad Seq · Time from diagnosis to treatment in days recode |
| Outcome | Survival months · Vital status recode (study cutoff used) · SEER cause-specific death classification |
| Genomic risk (only with the specialized database) | OncotypeDX Breast RS (2004-2019) · OncotypeDX Breast RS reason no score linked (2004-2019) |

Export only these variables. The full list with alternates is in `src/scorecard/adapters/fieldmaps/seer_breast.yaml`.

### 2c. Export

1. Run the session, then export the results as a delimited text file.
2. Export options that matter:
   - **Variable names as the first row.** The tool matches on these names.
   - **Labels, not numeric codes**, for coded fields. The field map expects text such as `Positive`, `Yes`, `Localized`.
   - Delimiter: comma or tab.
3. Save it as `data/seer/seer_breast.csv`. Do not email it, upload it or put it in a shared drive: SEER case-level rows are covered by the data use agreement.

### 2d. Look at the header

```bash
head -1 data/seer/seer_breast.csv
```

Only look at the header row. There is no need to open the rows in a spreadsheet.

## Part 3. Run it

Use a fresh output folder so the grid shows only real runs.

### TCGA-BRCA

The first run fetches all cases from the GDC API (about 20 seconds) and caches the snapshot in `~/.cache/ai-readiness-scorecard/gdc/TCGA-BRCA.json`. The supplement files are read fresh on every run, so you can fix a file or the field map and re-run without `--refresh`.

```bash
for t in chemo-benefit neoadjuvant-therapy endocrine-duration ovarian-suppression hrd-germline-testing; do
  scorecard profile --dataset TCGA-BRCA --supplement data/tcga_brca --task $t --out out/real/tcga-brca/$t
done
```

### SEER

The export is read in place. The tool never copies its rows.

```bash
for t in chemo-benefit neoadjuvant-therapy endocrine-duration ovarian-suppression hrd-germline-testing; do
  scorecard profile --adapter seer --snapshot data/seer/seer_breast.csv --task $t --out out/real/seer/$t
done
```

### Representativeness (needs both datasets)

Summarize SEER for the question (counts and shares only), then re-run TCGA with that summary:

```bash
scorecard reference --snapshot data/seer/seer_breast.csv --task chemo-benefit --out out/real/seer/reference_chemo-benefit.json
```

```bash
scorecard profile --dataset TCGA-BRCA --supplement data/tcga_brca --task chemo-benefit --reference out/real/seer/reference_chemo-benefit.json --out out/real/tcga-brca/chemo-benefit
```

### The grid

```bash
scorecard grid --runs out/real --out out/real/grid.html
```

## Part 4. Confirm the field maps

Both field maps are marked `confirmed: false` because the column names were written from documentation. Until they are confirmed, a variable can show as "not loaded" only because its name is wrong in the map.

1. Print the adapter's notes for a run:

   ```bash
   python -c "import json,sys; print('\n'.join(json.load(open(sys.argv[1]))['data']['notes']))" out/real/tcga-brca/chemo-benefit/provenance.json
   ```

   - TCGA: the line `Supplement tables read from local files: {...}` must list all six tables (patient, drug, radiation, cdr, subtype, hrd). A missing table means the file name did not match (Part 1d) or the barcode column was not found.
   - SEER: the line `Field map variables not found in this export: ...` lists every column the tool could not find.
2. Open `data_card.html` for the run and read the "what is missing" list. Variables marked **not loaded** are the ones to chase. Variables marked **not carried by this dataset** are expected (see [LIMITATIONS.md](LIMITATIONS.md)).
3. For each variable that should have loaded, compare the real header with `candidates` in the field map and add the real name. No Python changes are needed.
4. Check the values too, not just the names. For a mapped column, list its distinct values and make sure each one is handled by the `map` or `contains` rule in the field map. For example, for a tab-delimited Biotab file:

   ```bash
   python -c "import pandas as pd,sys; print(pd.read_csv(sys.argv[1],sep='\t',dtype=str)[sys.argv[2]].value_counts(dropna=False))" data/tcga_brca/nationwidechildrens.org_clinical_patient_brca.txt menopause_status
   ```

   Do this for TCGA freely. For SEER, value counts are fine to look at locally; do not paste them anywhere if any count is below 11.
5. Re-run. When every expected variable loads, set `confirmed: true` at the top of that field map and open a pull request with the field map change only.

Things to answer while you are here (open items from the plan):

- Is chemotherapy ever recorded as "no" in the full TCGA data? It never is in the 40-patient sample. If patients with only hormone-therapy drug records should count as "no chemotherapy", that is `infer_no_from_other_drug_records` in `tcga_brca.yaml`; leave it `false` until the team agrees.
- Tumor grade is expected to be empty for TCGA-BRCA. Confirm, then decide whether it stays a required variable.

## Part 5. Record what you downloaded

Provenance is recorded by hand for downloads; `provenance.json` only stores file names and hashes. Keep a file `data/DOWNLOAD_LOG.md` (ignored by git with the rest of `data/`) with one entry per file:

| Field | Example |
| --- | --- |
| File | `nationwidechildrens.org_clinical_patient_brca.txt` |
| Source | GDC Data Portal, Repository |
| Date | 2026-11-16 |
| Data release | GDC Data Release shown in the portal footer; SEER database name and submission |
| Filters or selection | Project = TCGA-BRCA, Access = open, Data Format = BCR Biotab |
| For published tables | Paper, table number, URL |
| Downloaded by | Name |

The limitations write-up and the final slides need the data release and the exact sources of the PAM50 and HRD tables, so fill this in at download time.

## Part 6. Before you push or share anything

1. Make sure nothing data-like is tracked:

   ```bash
   python scripts/check_no_data.py
   ```

2. `git status` must not list anything under `data/` or `out/`.
3. Read every SEER data card and the grid before sharing them. Counts from 1 to 10 are shown as `<11`, but the tool does not do complementary suppression, so a small count can sometimes be worked out from a total and the other cells. Change the threshold with the `SCORECARD_MIN_CELL` environment variable once the data use agreement's own rule is confirmed.
4. Hand-check three numbers per dataset against the source table: cohort size, one missing rate and the event count. Someone other than the person who wrote the check should do this.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `supplement folder ... does not exist` | Wrong path, or the command was not run from the repository root |
| `Reading ... needs openpyxl` | Install with `python -m pip install -e ".[excel]"`, or save the sheet as CSV |
| A table is missing from the "Supplement tables read" note | File name does not match the pattern, the format is not one of the accepted ones, or no barcode column was found |
| A table is listed but its variables are "not loaded" | Column name differs from every candidate in the field map |
| A variable loads but is mostly empty | The values are not covered by the `map` or `contains` rule, or they are sentinel strings such as `[Not Available]` |
| Many SEER variables "not found in this export" | The export used numeric codes or did not write variable names as the header row |
| GDC fetch fails | Network or GDC outage. Re-run; add `--refresh` to ignore a partial cache |
