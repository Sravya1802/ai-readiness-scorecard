# AI-Readiness Scorecard

**Does this oncology dataset support this AI task, and if not, what is missing?**

A Python package that profiles a dataset from the NCI Cancer Research Data Commons (CRDC) against a declared AI task. It returns a READY / CONDITIONAL / NOT READY verdict, with blocking deficiencies kept separate from degrading ones and every finding linked to its evidence.

NCI Data Jamboree 2026 project · University of Illinois Cancer Center
Lead: Nikita Thakur · Team: Saransh Singh, Juhi Anand, Lakshmi Sravya Rachakonda

> **Status: walking skeleton (v0.1).** The whole pipeline runs end to end on live TCGA-BRCA data. Six of the ten checks are implemented and four are registered stubs, so every verdict is marked **PROVISIONAL**. See [docs/TECHNICAL_PLAN.md](docs/TECHNICAL_PLAN.md) for who owns what.

## Quick start

You need Python 3.10 or newer. [uv](https://docs.astral.sh/uv/) is recommended; plain `pip` also works.

```bash
git clone https://github.com/<org>/ai-readiness-scorecard.git
cd ai-readiness-scorecard
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Offline, from the 40-patient fixture (no network needed)
scorecard profile --snapshot tests/fixtures/gdc_tcga_brca_40.json --out out/fixture

# Live, all 1,098 TCGA-BRCA patients from the GDC open-access API (about 20 s, cached afterwards)
scorecard profile --dataset TCGA-BRCA --task survival-prediction --out out/tcga-brca
open out/tcga-brca/data_card.html
```

`python -m scorecard ...` works the same as `scorecard ...`.

Other commands:

| Command | What it does |
|---|---|
| `scorecard checks` | All registered checks, with family, owner and real/stub state |
| `scorecard adapters` | Repository adapters (GDC is real; IDC, PDC and SEER are stubs) |
| `scorecard tasks` | Task specs |
| `scorecard snapshot --dataset TCGA-BRCA --limit 40 --out file.json` | Save a raw snapshot, for fixtures or offline runs |
| `pytest` | Offline tests. `pytest -m network` runs the live-API test. |

## What a run produces

| File | Contents |
|---|---|
| `data_card.html` | Human-readable report in the layout of the project prototype: verdict, Bridge2AI radar, multimodal linkage, the two check families, and an evidence section for every finding |
| `scorecard.json` | Everything in the data card, machine-readable |
| `provenance.json` | Which checks ran, on which snapshot (SHA-256), with which tool, pack, task and library versions |
| `croissant.json`, `ro-crate/` | Not built yet (owner: Member 4) |

## First live result (TCGA-BRCA, GDC Data Release 46)

| Check | Result |
|---|---|
| Missingness | WARN: 7.1% overall; `tumor_grade` is 100% missing; 9 features' missingness is associated with site or outcome |
| Class imbalance | PASS: 101 patients in the minority class at 5 years (just over the threshold of 100); 151 deaths in total |
| Stage, histology & grade | WARN: 83% coverage, held down by tumor grade |
| Treatment / Outcomes / Biomarkers | PASS: 100% / 100% / 94% (treatment and biomarkers are draft mappings) |
| Site effects, confounding, leakage, standards conformance | Not yet assessed |

Verdict: **CONDITIONAL (provisional)**. Two degrading deficiencies and none blocking, with four checks still to build.

## How it fits together

```
Repository adapter  ->  DatasetProfile (IR)  ->  checks (integrity + completeness)  ->  verdict  ->  data card, JSON, provenance
   gdc / idc / ...       one row per patient       read thresholds from the task spec     task-relative
```

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for diagrams and contracts, and [CONTRIBUTING.md](CONTRIBUTING.md) before your first PR.

## Repository layout

```
src/scorecard/
  profile.py              DatasetProfile: the shared intermediate representation
  adapters/               gdc.py (real); idc.py, pdc.py, seer.py (stubs)
  checks/integrity/       missingness, class imbalance (real); site effects, confounding, leakage (stubs)
  checks/completeness/    pack-driven engine + criteria (real); standards conformance (stub)
  packs/oncology.yaml     variable inventory per completeness criterion
  tasks/*.yaml            what each AI task requires: target, thresholds, severities
  verdict.py              blocking vs degrading -> verdict; Bridge2AI radar scores
  report/                 data card, scorecard.json, provenance; Croissant and RO-Crate stubs
  pipeline.py, cli.py
tests/                    offline tests against a real 40-patient fixture
docs/                     architecture and technical plan
```

## Data access

The tool uses only open-access data. It reads from the public GDC API without credentials. Never commit controlled-access data or SEER extracts.

## License

MIT (placeholder, pending confirmation by the project lead).
