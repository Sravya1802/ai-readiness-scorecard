# Technical plan

**Project:** AI-Readiness Scorecard: a task-relative profiler for multimodal CRDC datasets
**Event:** NCI Data Jamboree, **November 16–18, 2026** (dates per events.cancer.gov; the submission deck says September 10–11, so please correct it)
**Plan date:** October 5, 2026. That leaves six weeks of prework before the event.

## 1. Where we are

The base code is a **walking skeleton**: every stage of the pipeline runs on live TCGA-BRCA data and produces a data card in the prototype's layout. The table shows what is real and what is a stub.

| Piece | State |
|---|---|
| DatasetProfile IR, adapter base, check registry, pipeline, verdict, CLI | Real |
| GDC adapter (clinical, ER/PR/HER2, modality presence) | Real |
| GDC expression and mutation matrices | Not loaded (presence only) |
| Missingness, class imbalance | Real |
| Site effects, confounding, data leakage | Stubs with written specs |
| Stage/histology/grade, outcomes | Real |
| Treatment, biomarkers | Real, but draft mappings that need domain review |
| Standards conformance | Stub with written spec |
| Data card, scorecard.json, provenance.json | Real |
| Croissant, RO-Crate, IDC adapter | Stubs |

**First live result (GDC Data Release 46, 1,098 patients):** CONDITIONAL, provisional. The full table is in the README.

## 2. Goals, mapped to the submission deck

| Deck goal | Definition of done | When |
|---|---|---|
| **Baseline**: core pipeline (IR, GDC adapter, check registry) on TCGA-BRCA | Done in this skeleton | Week 1 |
| **Realistic**: first real verdict using the completeness and survival packs on TCGA-BRCA, packaged as a data card with Croissant / RO-Crate metadata | All 10 checks implemented, verdict no longer provisional, Croissant validates with `mlcroissant`, RO-Crate written | End of prework (Nov 13) |
| **Stretch**: IDC adapter and linkage matrix | IDC imaging presence joined to GDC patients; imaging row filled in on the linkage panel | At the event |
| **Long term**: leakage-safe preprocessing recommender (v1.5), grounded LLM report assistant (v2), packs beyond oncology | Out of scope for the Jamboree | After |

Moving the "Realistic" goal into prework is deliberate. It leaves the three event days for the stretch goal, onboarding collaborators, and the demo.

## 3. Roles

Roles follow the team's own breakdown. The **Member 4** role is a proposal, because the original notes stop after Member 3. Names go in once the team agrees.

### Lead (Nikita Thakur): contracts, integration, demo narrative
- Owns `profile.py`, `adapters/base.py`, `checks/base.py`, `verdict.py`, `pipeline.py`. Reviews every change to them.
- Loads the GDC expression and mutation matrices into the profile (see the TODO at the end of `adapters/gdc.py`), so the integrity checks see molecular features as well as clinical ones.
- Guards scope. A fifth new check waits until the linkage panel works.
- Owns the final presentation.
- **Done when:** the IR has not changed for two weeks, and the expression and mutation features appear in `features` with modality metadata.

### Member 2 (name): statistical engine (integrity checks)
- Implements `site_effects`, `confounding` and `leakage`. Specs are in the docstrings in `checks/integrity/stubs.py`, and thresholds are already in `tasks/survival_prediction.yaml`.
- Owns the rule that the tool must not leak while measuring leakage: every fitted model sits inside CV folds, with preprocessing in the fold pipeline.
- **Done when:** all five integrity checks are real, each with evidence and tests, and the site-effects permutation test runs in under a minute on 1,098 patients.

### Member 3 (name): oncology domain pack
- Owns `packs/oncology.yaml` and `checks/completeness/*`.
- Implements standards conformance (AJCC, ICD-O-3, ICD-10, mCODE). The spec is in `checks/completeness/standards.py`.
- Reviews the two draft criteria:
  - **Treatment.** Should each treatment type be its own variable? How do we tell "not given" from "not recorded"? Today it scores 100%, which is probably too generous.
  - **Biomarkers.** Confirm the breast panel and the `applies_to` lists.
- Validates that TCGA-BRCA field values mean what the pack assumes (for example AJCC "Stage X" counts as missing).
- **Done when:** no criterion carries the DRAFT label, and standards conformance is real.

### Member 4 (name, proposed): outputs and linkage
- Implements Croissant (with the RAI extension carrying our findings) and RO-Crate. Specs are in `report/croissant.py` and `report/rocrate.py`.
- Owns the data card's look and the linkage panel.
- At the event, builds the IDC adapter: choose a TCGA-BRCA-compatible collection, then verify that its DICOM PatientID matches TCGA submitter ids before promising a join.
- **Done when:** `croissant.json` validates, `ro-crate/` is written, and the IDC row shows real numbers.

## 4. Prework schedule (proposal)

| Week | Dates | Lead | Member 2 | Member 3 | Member 4 |
|---|---|---|---|---|---|
| 1 | Oct 5–9 | Push repo; everyone runs it; review IR together | Read the stubs' specs; set up a branch | Review pack and task YAML | Review the data card against slide 7 |
| 2 | Oct 12–16 | Freeze the IR (v0.2) | Site effects | Standards conformance: vocabularies | Croissant |
| 3 | Oct 19–23 | Expression matrix in the profile | Confounding | Standards conformance: check and tests | Croissant RAI fields; validate |
| 4 | Oct 26–30 | Mutation matrix in the profile | Leakage | Treatment and biomarker review | RO-Crate |
| 5 | Nov 2–6 | Integration; first non-provisional verdict | Performance pass on the permutation test | Second-opinion review of thresholds | IDC exploration (`idc-index`) |
| 6 | Nov 9–13 | Demo dry run; freeze `main` | Buffer and fixes | Buffer and fixes | Buffer and fixes |

**Weekly sync:** 30 minutes, with a demo of `main` every time. If `scorecard profile` does not run on `main`, fixing it is the first agenda item.

## 5. Event plan (Nov 16–18)

| Day | Goal |
|---|---|
| 1 | Onboard collaborators (README quick start; one good-first-issue per role). Start the IDC adapter and linkage. |
| 2 | IDC row on the linkage panel. Optionally run a second TCGA project (for example TCGA-LUAD) to show the pack generalizes beyond breast. |
| 3 | Freeze by midday. Final data card, slides built from it, tagged release on GitHub. |

## 6. Interface rules

- **The IR is frozen** from the end of week 2. Changes go through an issue and the lead.
- Thresholds live in the task YAML, never in code.
- Every non-PASS result carries evidence.
- Tests run offline against `tests/fixtures/`. CI must be green to merge.
- Only open-access data goes in the repo.

## 7. Risks

| Risk | Mitigation |
|---|---|
| GDC quirks: multiple diagnoses per case, "Not Reported" strings, follow-up time split across records | Already handled in the adapter. Normalized strings are counted in provenance, so changes in the source data are visible. |
| The tool leaks while measuring leakage | Member 2 owns this; CV-only fitting is in CONTRIBUTING; tests should check that fitting happens inside folds |
| Thresholds look arbitrary to reviewers | They live in YAML with comments, and the data card shows the thresholds next to each result |
| Class imbalance sits on its threshold (101 against 100) | Fine for now. Prefer time-to-event framing, which uses all 151 deaths. |
| Scope creep (more checks, more repositories) | The lead says no until the current panel is fully real |
| IDC patient IDs don't match TCGA submitter ids for the chosen collection | Verify on day 1 of the event before building the join |
| Expression matrices are large (about 1,100 files) | Cache downloads; start with a gene subset; keep aggregation in `build_profile` |

## 8. Open questions for the team

1. **Check count.** The prototype says "16 of 16 checks", but the deck defines 10. Which number is right? Are there six more we intend to build?
2. **Radar mapping.** Confirm the proposed check-to-criterion mapping in ARCHITECTURE.md §4. Provenance, Ethics and Sustainability have no check. Candidates:
   - Provenance: score the provenance record itself (release, hash, query present).
   - Ethics: completeness and balance of demographic fields (race, ethnicity, sex).
   - Sustainability: whether the source has a versioned release and a persistent identifier.
3. **Tumor grade.** It is 100% missing in GDC TCGA-BRCA. Should grade be a required variable for breast, or should the pack fall back to another field?
4. **License.** MIT is a placeholder. Does the university or NCI require a different one?
5. **Member 4.** Confirm the role and who takes it.
6. **Deck dates.** The deck says September 10–11; the event site says November 16–18.
