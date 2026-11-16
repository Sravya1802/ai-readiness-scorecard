# The five clinical questions

The scorecard now assesses TCGA-BRCA and SEER against Dr. Gadi's five questions. Each question is one task file in `src/scorecard/tasks/`.

| # | Question | Depth | Task id |
| --- | --- | --- | --- |
| 1 | Will the patient benefit from chemotherapy? | Full | `chemo-benefit` |
| 2 | Chemo before surgery, alone or with immune or targeted therapy? | Short | `neoadjuvant-therapy` |
| 3 | How long should endocrine therapy last? | Short | `endocrine-duration` |
| 4 | Is ovarian suppression needed if ER+ and premenopausal? | Short | `ovarian-suppression` |
| 5 | Should the patient have germline testing (evidence of HRD)? | Full | `hrd-germline-testing` |

Every cutoff and clinical rule in these files is a draft until a clinician reviews it. Record the reviewer and date under `clinical_review` in each file.

## What was added

- **Task model.** A task can now declare a population (include and exclude rules), a treatment, a target (survival, time to event with stand-ins, or a label), a variable list with `expected_when` conditions, and the list of checks to run.
- **Population filter.** Every patient is labelled eligible, not eligible, or unknown. Unknown means a rule could not be decided because a value is missing. Unknowns are counted and reported, never dropped.
- **Six checks.** Cohort identifiable (blocking), conditional completeness, outcome adequacy (blocking), sample size, treatment adequacy (blocking), representativeness. They are opt-in: a task runs them by listing them under `checks:`.
- **Adapters.** The GDC adapter emits the full shared vocabulary (`adapters/vocabulary.py`) and can join local Clinical Supplement, TCGA-CDR and published tables from a `--supplement` folder. The SEER adapter reads a local SEER*Stat case listing.
- **Declared-absent variables.** A variable a source lacks is still a column, left empty and marked `not_in_source` or `not_loaded`. That is how a check tells "absent from the dataset" from "missing for some patients".
- **Report.** The data card shows the question, the cohort, a "what is missing" list and narrower questions the dataset may still support. `scorecard grid` builds the questions-by-datasets grid.

## Field maps: confirm before trusting a run

Source column names live in two YAML files, not in Python:

- `src/scorecard/adapters/fieldmaps/tcga_brca.yaml`
- `src/scorecard/adapters/fieldmaps/seer_breast.yaml`

Both were written from published variable metadata, without opening any data file, and are marked `confirmed: false`. After the first download and export:

1. Run the commands below.
2. Read the notes in `provenance.json` and the "not loaded" variables in the conditional completeness evidence.
3. Fix any `candidates` name that differs from the real column header, and any value in a `map`.
4. Set `confirmed: true`.

## Running it

Keep every file under `data/`, which git ignores. See `docs/DATA_HANDLING.md`.

```bash
# TCGA-BRCA, one question. --supplement points at the folder holding the Biotab
# files, TCGA-CDR and the published subtype and HRD tables.
scorecard profile --dataset TCGA-BRCA --supplement data/tcga_brca \
  --task chemo-benefit --out out/tcga-brca/chemo-benefit

# SEER, same question. The export is read in place and never copied.
scorecard profile --adapter seer --snapshot data/seer_breast.csv \
  --task chemo-benefit --out out/seer/chemo-benefit

# Representativeness: summarize SEER for the task (counts and shares only),
# then pass that summary to the TCGA run.
scorecard reference --snapshot data/seer_breast.csv --task chemo-benefit \
  --out out/seer/reference_chemo-benefit.json
scorecard profile --dataset TCGA-BRCA --supplement data/tcga_brca \
  --task chemo-benefit --reference out/seer/reference_chemo-benefit.json \
  --out out/tcga-brca/chemo-benefit

# The headline grid: five questions down the side, two datasets across.
scorecard grid --runs out --out out/grid.html
```

Reading the TCGA-CDR Excel file needs `pip install -e ".[excel]"`, or save the sheet as CSV.

## Decisions built in, to confirm

- **"No" and "unknown" stay apart.** A treatment is "no" only when a record says no. A patient with no chemotherapy record is unknown. `infer_no_from_other_drug_records` in `tcga_brca.yaml` is off until the pattern is confirmed on the full data.
- **SEER fails treatment adequacy by design.** SEER releases chemotherapy as "yes" or "no/unknown", so the adapter never emits a "no" and the check fails with SEER's own documentation as the reason.
- **Median follow-up is measured in patients without the event.**
- **HER2 IHC and FISH are separate columns**, so an equivocal IHC without a FISH result is visible.
- **A stand-in is a caution, never a pass.** RNA-seq for a commercial recurrence score, or progression-free interval for distant recurrence.
- **The propensity overlap metric is a caution at worst.** It is a simple model, fitted inside cross-validation folds.
