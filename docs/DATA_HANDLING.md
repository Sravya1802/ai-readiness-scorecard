# Data handling

This repository is public. The rules below keep patient-level data out of it and out of anything the tool writes. They apply to every dataset, and they are stricter than the public datasets strictly need, so the same habits carry over when the tool is later pointed at institutional data.

## What the data is

- **TCGA-BRCA (GDC, open tier).** De-identified and open access. Not PHI. The 40-patient test fixture in `tests/fixtures/` comes from this tier.
- **SEER research data.** De-identified, but released under a data use agreement signed by each user. Case-level rows must not be shared or published.
- **UI Health or any other institutional data.** PHI under HIPAA. Do not use it with this repository until the IRB protocol covers it, and never on a machine or service that is not approved for PHI.

## Rules

1. **No data in git.** Every download and export goes in a local `data/` folder, which `.gitignore` excludes. `python scripts/check_no_data.py` fails when a data-like file is tracked; CI runs it on every pull request.
2. **Tests use invented rows.** SEER is tested against rows made up inside the test. Never commit a real SEER row, even one.
3. **SEER rows are never copied.** The SEER adapter reads the export in place. It does not write to the snapshot cache, and `scorecard snapshot --adapter seer` is refused.
4. **SEER identifiers are not kept.** The SEER patient id is used only to keep one record per person, then dropped. Rows get a run-local label.
5. **SEER reports show counts and percentages only.** No example patients, no patient ids, and counts from 1 to 10 are shown as `<11`. Change the threshold with `SCORECARD_MIN_CELL` once the agreement's own rule is confirmed.
6. **Read a SEER report before sharing it.** The tool does not do complementary suppression: a small count can sometimes be worked out from a total and the other cells.
7. **Record provenance, not data.** For each download note the date, the data release and the filters. `provenance.json` stores file hashes and column names, never rows.
8. **Minimum necessary.** Export only the variables in `src/scorecard/adapters/fieldmaps/`. Skip the pathology slide images.

## Open items

- What the SEER data use agreement allows in a public report, including its small-cell rule.
- Whether public data use needs an IRB determination at UIC.
