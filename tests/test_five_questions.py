"""Tests for the five clinical questions. Every table here is invented."""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from scorecard import pipeline
from scorecard.adapters import get_adapter
from scorecard.checks import Check, Criterion, Family, Severity, Status, get_check
from scorecard.cli import main
from scorecard.packs import PackVariable
from scorecard.pipeline import assess, checks_for
from scorecard.population import Population, select
from scorecard.profile import NO_UNKNOWN_MERGED
from scorecard.reference import build_reference
from scorecard.rules import Rule
from scorecard.tasks import list_tasks, load_task
from scorecard.verdict import Label
from tests.synthetic import chemo_cohort, make_profile

ROOT = Path(__file__).parents[1]
QUESTIONS = [
    "chemo-benefit",
    "neoadjuvant-therapy",
    "endocrine-duration",
    "ovarian-suppression",
    "hrd-germline-testing",
]


# --- Step 1: the two fixes ---------------------------------------------------


class _Crashes(Check):
    id = "test.crashes"
    title = "Crashes"
    family = Family.INTEGRITY
    criteria = (Criterion.COMPUTABILITY,)
    owner = "test"

    def run(self, profile, task):
        raise RuntimeError("boom")


def test_a_crashed_check_can_never_give_ready(monkeypatch, profile, task):
    monkeypatch.setattr(pipeline, "checks_for", lambda task: [_Crashes()])
    run = assess(profile, task)
    assert run.results[0].status is Status.FAIL
    assert run.results[0].severity is Severity.BLOCKING
    assert run.verdict.label is Label.NOT_READY


def test_data_folder_is_ignored_and_guarded():
    assert "data/" in (ROOT / ".gitignore").read_text().splitlines()
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from check_no_data import problems
    finally:
        sys.path.pop(0)
    assert problems(["src/scorecard/cli.py", "tests/fixtures/gdc_tcga_brca_40.json"]) == []
    assert (
        len(problems(["data/seer_breast.csv", "notes/export.csv", "tests/fixtures/seer.csv"])) == 3
    )


# --- Step 5: engine ----------------------------------------------------------


def test_rules_have_three_answers():
    f = pd.DataFrame({"er": ["Positive", "negative", None], "nodes": [2, 7, None]})
    assert Rule(column="er", values=["positive"]).evaluate(f).tolist() == [True, False, pd.NA]
    assert Rule(column="nodes", op="between", values=[0, 3]).evaluate(f).tolist()[:2] == [
        True,
        False,
    ]
    assert Rule(column="absent", values=["x"]).evaluate(f).isna().all()


def test_population_never_drops_unknowns():
    p = make_profile(
        4,
        {
            "er_status": ["Positive", "Negative", None, "Positive"],
            "nodes_positive": [1, None, 2, None],
        },
    )
    population = Population(
        include=[
            Rule(column="er_status", values=["Positive"]),
            Rule(column="nodes_positive", op="between", values=[0, 3]),
        ]
    )
    cohort = select(p, population)
    # Patient 2 fails a rule that can be decided, so a missing node count does not matter.
    assert cohort.label.tolist() == ["eligible", "not_eligible", "unknown", "unknown"]
    assert cohort.n_eligible + cohort.n_not_eligible + cohort.n_unknown == 4
    assert cohort.rule_table[1]["undecided_among_unknown"] == 1


def test_expected_when_that_cannot_be_evaluated_counts_as_expected():
    f = pd.DataFrame({"her2_ihc_status": ["Equivocal", "Negative", None], "fish": [None] * 3})
    variable = PackVariable(
        name="fish",
        column="fish",
        expected_when=[Rule(column="her2_ihc_status", values=["Equivocal"])],
    )
    assert variable.applicable(f).tolist() == [True, False, True]


def test_each_question_has_a_task_that_runs_only_its_checks():
    assert set(QUESTIONS) <= set(list_tasks())
    for number, task_id in enumerate(QUESTIONS, start=1):
        task = load_task(task_id)
        assert task.number == number and task.clinical_review.status == "draft"
        assert all(c.implemented for c in checks_for(task)), "placeholder checks stay out"
    short = [c.id for c in checks_for(load_task("endocrine-duration"))]
    assert short == [
        "integrity.missingness",
        "completeness.conditional",
        "task_fit.cohort_identifiable",
    ]


def test_survival_task_is_unchanged(profile, task):
    run = assess(profile, task)
    assert len(run.results) == 10 and run.verdict.provisional


# --- Step 6: the six checks --------------------------------------------------


@pytest.fixture(scope="module")
def chemo():
    return load_task("chemo-benefit")


def _run(check_id, profile, task):
    return get_check(check_id).run(profile, task)


def test_good_invented_cohort_passes_the_blocking_checks(chemo):
    p = make_profile(1200, chemo_cohort(1200), modalities={"gene_expression": [True] * 1200})
    for check_id in (
        "task_fit.cohort_identifiable",
        "task_fit.outcome_adequacy",
        "task_fit.treatment_adequacy",
        "task_fit.sample_size",
    ):
        result = _run(check_id, p, chemo)
        assert result.status is Status.PASS, (check_id, result.summary)
    run = assess(p, chemo)
    assert not run.verdict.provisional and run.verdict.label is not Label.NOT_READY


def test_empty_cohort_blocks(chemo):
    p = make_profile(50, {**chemo_cohort(50), "er_status": ["Negative"] * 50})
    result = _run("task_fit.cohort_identifiable", p, chemo)
    assert result.status is Status.FAIL and result.severity is Severity.BLOCKING
    assert _run("task_fit.outcome_adequacy", p, chemo).status is Status.NOT_APPLICABLE
    assert assess(p, chemo).verdict.label is Label.NOT_READY


def test_cohort_check_names_the_variable_causing_unknowns(chemo):
    rows = chemo_cohort(100)
    rows["nodes_positive"] = [None] * 60 + rows["nodes_positive"][60:]
    result = _run("task_fit.cohort_identifiable", make_profile(100, rows), chemo)
    assert result.status is Status.FAIL and "nodes_positive" in result.summary
    assert result.metrics["unknown"] == 60


def test_required_variable_the_dataset_does_not_carry_fails_outright(chemo):
    p = make_profile(400, chemo_cohort(400), absent=("tumor_grade",))
    result = _run("completeness.conditional", p, chemo)
    rows = {r["variable"]: r for r in result.evidence[0].table}
    assert rows["grade"]["status"] == "FAIL" and rows["grade"]["in_dataset"] == "not_in_source"
    assert result.status is Status.FAIL and result.severity is Severity.DEGRADING
    assert "grade" in result.summary


def test_a_stand_in_is_a_caution_never_a_pass(chemo):
    rows = chemo_cohort(400)
    rows["genomic_risk_score"] = [None] * 400
    p = make_profile(400, rows, modalities={"gene_expression": [True] * 400})
    table = {r["variable"]: r for r in _run("completeness.conditional", p, chemo).evidence[0].table}
    assert table["genomic_risk"]["status"] == "WARN" and table["genomic_risk"]["via_substitute"]


def test_conditional_completeness_counts_only_where_expected(chemo):
    rows = chemo_cohort(400)
    rows["her2_ihc_status"] = ["Equivocal"] * 10 + ["Negative"] * 390
    rows["her2_fish_status"] = ["Negative"] * 5 + [None] * 395
    table = {
        r["variable"]: r
        for r in _run("completeness.conditional", make_profile(400, rows), chemo).evidence[0].table
    }
    assert table["her2_fish"]["expected_patients"] == 10
    assert table["her2_fish"]["coverage"] == 0.5


def test_follow_up_is_measured_in_patients_without_the_event(chemo):
    p = make_profile(1200, chemo_cohort(1200))
    result = _run("task_fit.outcome_adequacy", p, chemo)
    # Events happen at 2 years, everyone else is followed 10: the answer is 10, not 6.
    assert result.metrics["median_followup_years"] == pytest.approx(3650 / 365.25, abs=0.01)
    assert result.metrics["events"] == 400


def test_only_a_stand_in_outcome_is_a_caution_and_weak_stand_in_fails(chemo):
    rows = chemo_cohort(1200)
    rows["pfi_event"] = rows.pop("distant_recurrence_event")
    rows["pfi_time_days"] = rows.pop("distant_recurrence_time_days")
    absent = ("distant_recurrence_event", "distant_recurrence_time_days")
    result = _run("task_fit.outcome_adequacy", make_profile(1200, rows, absent=absent), chemo)
    assert result.status is Status.WARN and result.metrics["is_proxy"]

    rows = chemo_cohort(1200)
    del rows["distant_recurrence_event"], rows["distant_recurrence_time_days"]
    rows["vital_status"] = ["Dead" if k % 3 == 0 else "Alive" for k in range(1200)]
    rows["days_to_death"] = [400] * 1200
    rows["days_to_last_follow_up"] = [1000] * 1200  # under the 5-year floor for overall survival
    absent += ("pfi_event", "pfi_time_days", "dfi_event", "dfi_time_days")
    result = _run("task_fit.outcome_adequacy", make_profile(1200, rows, absent=absent), chemo)
    assert result.status is Status.FAIL and result.severity is Severity.BLOCKING


def test_no_outcome_at_all_blocks(chemo):
    rows = chemo_cohort(300)
    del rows["distant_recurrence_event"], rows["distant_recurrence_time_days"]
    rows["vital_status"] = [None] * 300
    result = _run("task_fit.outcome_adequacy", make_profile(300, rows), chemo)
    assert result.status is Status.FAIL and result.severity is Severity.BLOCKING


def test_everyone_in_one_treatment_group_blocks(chemo):
    rows = chemo_cohort(400)
    rows["chemotherapy"] = ["yes"] * 300 + [None] * 100  # "yes" recorded, never "no"
    result = _run("task_fit.treatment_adequacy", make_profile(400, rows), chemo)
    assert result.status is Status.FAIL and result.severity is Severity.BLOCKING
    assert "unknown, not untreated" in result.summary


def test_merged_no_unknown_fails_by_design(chemo):
    rows = chemo_cohort(400)
    rows["chemotherapy"] = ["yes" if k % 2 else None for k in range(400)]
    p = make_profile(400, rows, caveats={"chemotherapy": [NO_UNKNOWN_MERGED]})
    result = _run("task_fit.treatment_adequacy", p, chemo)
    assert result.status is Status.FAIL and result.severity is Severity.BLOCKING
    assert "no/unknown" in result.summary


def test_treatment_check_wants_the_confounders(chemo):
    p = make_profile(1200, chemo_cohort(1200), absent=("menopausal_status", "tumor_grade", "race"))
    result = _run("task_fit.treatment_adequacy", p, chemo)
    assert result.status is Status.FAIL and result.metrics["confounders_present"] == 0.625


def test_sample_size_counts_eligible_patients_and_events_per_predictor(chemo):
    result = _run("task_fit.sample_size", make_profile(120, chemo_cohort(120)), chemo)
    assert result.status is Status.FAIL and result.severity is Severity.DEGRADING
    predictors = sum(v.role == "predictor" for v in chemo.variables)
    assert result.metrics["events_per_predictor"] == round(40 / predictors, 2)


def test_representativeness_against_a_reference(chemo):
    cohort = make_profile(400, chemo_cohort(400))
    same = make_profile(2000, chemo_cohort(2000), linkable=False)
    cohort.reference = build_reference(same, chemo)
    result = _run("task_fit.representativeness", cohort, chemo)
    assert result.status is Status.PASS, result.summary

    older = chemo_cohort(2000)
    older["age_at_index"] = [a + 15 for a in older["age_at_index"]]
    older["race"] = ["white"] * 2000
    cohort.reference = build_reference(make_profile(2000, older, linkable=False), chemo)
    result = _run("task_fit.representativeness", cohort, chemo)
    rows = {r["variable"]: r for r in result.evidence[0].table}
    assert rows["age_at_index"]["smd"] == pytest.approx(15 / 11.56, abs=0.03)
    assert result.status is Status.FAIL and result.severity is Severity.DEGRADING

    cohort.reference = None
    assert _run("task_fit.representativeness", cohort, chemo).status is Status.NOT_APPLICABLE


def test_label_question_needs_the_label():
    task = load_task("hrd-germline-testing")
    rows = {"ajcc_pathologic_stage": ["Stage II"] * 600, "hrd_score": [60, 10, 20] * 200}
    p = make_profile(600, rows, absent=("germline_brca_status",))
    result = _run("task_fit.outcome_adequacy", p, task)
    assert result.status is Status.PASS and result.metrics["minority_count"] == 200
    absent = make_profile(600, {"ajcc_pathologic_stage": ["Stage II"] * 600}, absent=("hrd_score",))
    assert _run("task_fit.outcome_adequacy", absent, task).is_blocking_failure


# --- Step 3: adapters, on invented files -------------------------------------

SEER_HEADER = [
    "Patient ID",
    "Age recode with single ages and 90+",
    "Sex",
    "Race recode (W, B, AI, API)",
    "Year of diagnosis",
    "Derived AJCC Stage Group, 7th ed (2010-2015)",
    "Regional nodes positive (1988+)",
    "ER Status Recode Breast Cancer (1990+)",
    "Derived HER2 Recode (2010+)",
    "RX Summ--Surg Prim Site (1998+)",
    "Chemotherapy recode (yes, no/unk)",
    "RX Summ--Systemic/Sur Seq (2007+)",
    "Survival months",
    "Vital status recode (study cutoff used)",
]


@pytest.fixture()
def seer_export(tmp_path):
    """An invented SEER*Stat-shaped listing. No real SEER row is ever committed or read."""
    rows = []
    for k in range(300):
        rows.append(
            [
                f"{90000 + k}",
                f"{45 + k % 40} years",
                "Female",
                "White" if k % 5 else "Black",
                "2012",
                "IIA" if k % 2 else "IA",
                f"{k % 3:02d}" if k % 50 else "98",
                "Positive" if k >= 5 else "Negative",  # 5 ER-negative patients: a small cell
                "Negative",
                "22",
                "Yes" if k % 2 else "No/Unknown",
                "Systemic therapy after surgery",
                f"{60 + k % 60:04d}",
                "Dead" if k % 6 == 0 else "Alive",
            ]
        )
    rows.append(rows[0][:4] + ["2015"] + rows[0][5:])  # a second record for the first person
    path = tmp_path / "data" / "seer_synthetic.csv"
    path.parent.mkdir()
    pd.DataFrame(rows, columns=SEER_HEADER).to_csv(path, index=False)
    return path


def test_seer_adapter_maps_the_export_and_keeps_rows_private(seer_export, tmp_path, monkeypatch):
    monkeypatch.setenv("SCORECARD_CACHE_DIR", str(tmp_path / "cache"))
    p = get_adapter("seer").load_snapshot(seer_export)
    assert p.n_patients == 300 and not p.linkable and p.site_column is None
    assert not p.features.index.str.contains("9000").any(), "source ids are never kept"
    f = p.features
    assert f["age_at_index"].iloc[0] == 45 and f["stage_group"].isin(["I", "II"]).all()
    assert f["nodes_positive"].isna().sum() == 6, "special code 98 is not a node count"
    assert set(f["chemotherapy"].dropna()) == {"yes"}, '"No/Unknown" is never read as no'
    assert p.has_caveat("chemotherapy", NO_UNKNOWN_MERGED)
    assert p.availability("endocrine_therapy").value == "not_in_source"
    assert p.availability("tumor_grade").value == "not_loaded"
    assert f["os_event"].sum() == 50 and f["surgery"].eq("yes").all()
    assert not (tmp_path / "cache").exists(), "SEER rows are never cached"
    assert (
        main(
            [
                "snapshot",
                "--adapter",
                "seer",
                "--dataset",
                str(seer_export),
                "--out",
                str(tmp_path / "copy.json"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "copy.json").exists()


def test_seer_report_shows_counts_only(seer_export, tmp_path):
    out = tmp_path / "out"
    code = main(
        [
            "profile",
            "--adapter",
            "seer",
            "--snapshot",
            str(seer_export),
            "--task",
            "chemo-benefit",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    scorecard = json.loads((out / "scorecard.json").read_text())
    assert scorecard["verdict"]["label"] == "NOT_READY"
    treatment = next(
        r for r in scorecard["results"] if r["check_id"].endswith("treatment_adequacy")
    )
    assert treatment["status"] == "FAIL" and "no/unknown" in treatment["summary"]
    for name in ("scorecard.json", "provenance.json", "data_card.html"):
        text = (out / name).read_text()
        assert "seer-0" not in text and "9000" not in text, f"patient ids leaked into {name}"
    cohort = next(r for r in scorecard["results"] if r["check_id"].endswith("cohort_identifiable"))
    rule = next(r for r in cohort["evidence"][1]["table"] if "er_status" in r["rule"])
    assert rule["not_met"] == "<11", "small cells are suppressed"
    assert "Counts and percentages only" in (out / "data_card.html").read_text()


def test_reference_is_aggregate_and_feeds_the_grid(seer_export, tmp_path):
    ref = tmp_path / "out" / "seer" / "reference.json"
    assert (
        main(
            [
                "reference",
                "--snapshot",
                str(seer_export),
                "--task",
                "chemo-benefit",
                "--out",
                str(ref),
            ]
        )
        == 0
    )
    reference = json.loads(ref.read_text())
    assert reference["variables"]["age_at_index"]["kind"] == "numeric"
    assert any("neoadjuvant" not in r for r in reference["rules_applied"])
    assert "seer-0" not in ref.read_text()

    for task in ("chemo-benefit", "endocrine-duration"):
        main(
            [
                "profile",
                "--adapter",
                "seer",
                "--snapshot",
                str(seer_export),
                "--task",
                task,
                "--out",
                str(tmp_path / "out" / "seer" / task),
            ]
        )
    assert (
        main(
            ["grid", "--runs", str(tmp_path / "out"), "--out", str(tmp_path / "out" / "grid.html")]
        )
        == 0
    )
    grid = json.loads((tmp_path / "out" / "grid.json").read_text())
    assert [t["number"] for t in grid["tasks"]] == [1, 3] and len(grid["cells"]) == 2
    assert "NOT READY" in (tmp_path / "out" / "grid.html").read_text()


def _case(barcode, treatments):
    return {
        "submitter_id": barcode,
        "case_id": barcode.lower(),
        "tissue_source_site": {"code": "ZZ"},
        "demographic": {"vital_status": "Alive", "sex_at_birth": "female", "age_at_index": 50},
        "diagnoses": [
            {
                "diagnosis_is_primary_disease": True,
                "ajcc_pathologic_stage": "Stage IIA",
                "ajcc_pathologic_m": "M0",
                "days_to_last_follow_up": 900,
                "treatments": [
                    {"treatment_type": kind, "treatment_or_therapy": answer}
                    for kind, answer in treatments
                ],
            }
        ],
        "follow_ups": [],
    }


def test_gdc_supplement_fills_new_columns_from_invented_files(tmp_path):
    folder = tmp_path / "data" / "tcga"
    folder.mkdir(parents=True)
    (folder / "nationwidechildrens.org_clinical_patient_brca.txt").write_text(
        "bcr_patient_barcode\tmenopause_status\tlymph_nodes_examined_he_count\t"
        "her2_status_by_ihc\ther2_fish_status\tpharmaceutical_tx_adjuvant\n"
        "bcr_patient_barcode\tmenopause_status\tnodes\ther2\tfish\tpharma\n"
        "CDE_ID:1\tCDE_ID:2\tCDE_ID:3\tCDE_ID:4\tCDE_ID:5\tCDE_ID:6\n"
        "TCGA-ZZ-0001\tPre (<6 months since LMP AND no prior bilateral ovariectomy)\t2\t"
        "Equivocal\tNegative\tYES\n"
        "TCGA-ZZ-0002\tPost (prior bilateral ovariectomy OR >12 mo since LMP)\t[Not Available]\t"
        "Negative\t[Not Evaluated]\tNO\n"
        "TCGA-ZZ-0003\t[Unknown]\t0\tPositive\t[Not Evaluated]\t[Not Available]\n"
    )
    (folder / "nationwidechildrens.org_clinical_drug_brca.txt").write_text(
        "bcr_patient_barcode\tpharmaceutical_therapy_drug_name\tpharmaceutical_therapy_type\t"
        "pharmaceutical_tx_started_days_to\tpharmaceutical_tx_ended_days_to\n"
        "TCGA-ZZ-0001\tTamoxifen\tHormone Therapy\t100\t1900\n"
        "TCGA-ZZ-0001\tGoserelin\tHormone Therapy\t120\t800\n"
    )
    pd.DataFrame(
        {
            "bcr_patient_barcode": ["TCGA-ZZ-0001", "TCGA-ZZ-0002"],
            "type": ["BRCA", "BRCA"],
            "PFI": [1, 0],
            "PFI.time": [400, 900],
        }
    ).to_csv(folder / "TCGA-CDR-synthetic.csv", index=False)

    raw = {
        "dataset": "TCGA-FAKE",
        "retrieved_at": "2026-01-01T00:00:00+00:00",
        "cases": [
            _case("TCGA-ZZ-0001", [("Chemotherapy", "yes"), ("Radiation Therapy, NOS", "no")]),
            _case("TCGA-ZZ-0002", []),
            _case("TCGA-ZZ-0003", [("Hormone Therapy", "yes")]),
        ],
        "modality_files": {"gene_expression": [], "somatic_mutation": []},
    }
    adapter = get_adapter("gdc")
    bare = adapter.build_profile(raw)
    assert bare.availability("menopausal_status").value == "not_loaded"
    assert bare.availability("germline_brca_status").value == "not_in_source"

    adapter.supplement_dir = folder
    f = adapter.build_profile(raw).features
    f = f.astype(object).where(f.notna(), None)
    assert f["menopausal_status"].tolist() == ["premenopausal", "postmenopausal", None]
    assert f["nodes_positive"].tolist()[:2] == [2, None]
    # IHC and FISH stay separate, so an equivocal IHC with a FISH follow-up is visible.
    assert f.loc["TCGA-ZZ-0001", ["her2_ihc_status", "her2_fish_status"]].tolist() == [
        "Equivocal",
        "Negative",
    ]
    # "no" only from a record that says no; no record means unknown, not untreated.
    assert f["chemotherapy"].tolist() == ["yes", "no", None]
    assert f["radiation_therapy"].tolist()[0] == "no" and f["radiation_therapy"].tolist()[2] is None
    assert f["endocrine_therapy"].tolist() == ["yes", "no", "yes"]
    assert f.loc["TCGA-ZZ-0001", "ovarian_suppression"] == "yes"
    assert f.loc["TCGA-ZZ-0001", "endocrine_therapy_duration_days"] == 1800
    assert f["pfi_event"].tolist()[:2] == [1, 0] and f["stage_group"].eq("II").all()


def test_cli_question_run_on_open_fixture(tmp_path, capsys):
    from tests.conftest import FIXTURE

    assert (
        main(
            [
                "profile",
                "--snapshot",
                str(FIXTURE),
                "--task",
                "chemo-benefit",
                "--out",
                str(tmp_path),
            ]
        )
        == 0
    )
    card = (tmp_path / "data_card.html").read_text()
    for text in ("Question and cohort", "What is missing", "Task fit", "Will the patient benefit"):
        assert text in card
    assert "PROVISIONAL" not in capsys.readouterr().out


def test_guard_script_runs():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_no_data.py")], capture_output=True, text=True
    )
    assert result.returncode in (0, 1) and "Traceback" not in result.stderr


def test_absent_treatment_or_outcome_blocks_short_questions():
    task = load_task("endocrine-duration")
    rows = {**chemo_cohort(300), "endocrine_therapy": [None] * 300}
    absent = ("endocrine_therapy", "endocrine_therapy_start_days", "endocrine_therapy_end_days")
    result = _run("completeness.conditional", make_profile(300, rows, absent=absent), task)
    assert result.status is Status.FAIL and result.severity is Severity.BLOCKING
    assert "endocrine_therapy" in result.metrics["blocking_absent"]


def test_absent_variable_with_a_stand_in_does_not_block():
    task = load_task("endocrine-duration")
    rows = chemo_cohort(300)
    rows.update(
        endocrine_therapy_start_days=[100] * 300,
        endocrine_therapy_end_days=[1900] * 300,
        drug_names=["tamoxifen"] * 300,
        pfi_event=rows.pop("distant_recurrence_event"),
        pfi_time_days=rows.pop("distant_recurrence_time_days"),
    )
    p = make_profile(300, rows, absent=("distant_recurrence_event", "distant_recurrence_time_days"))
    result = _run("completeness.conditional", p, task)
    assert result.metrics["blocking_absent"] == []
    assert result.severity is not Severity.BLOCKING


def test_full_questions_do_not_use_the_absent_rule():
    # Questions 1 and 5 have their own blocking outcome and treatment checks.
    for task_id in ("chemo-benefit", "hrd-germline-testing"):
        assert (
            load_task(task_id).param("conditional_completeness", "blocking_if_absent_roles", None)
            is None
        )
