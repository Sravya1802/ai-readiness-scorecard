from scorecard.checks import Family, Severity, Status, get_check, list_checks


def test_registry_has_ten_checks_in_display_order():
    checks = list_checks()
    assert len(checks) == 10
    assert [c.family for c in checks[:5]] == [Family.INTEGRITY] * 5
    assert checks[0].id == "integrity.missingness"
    assert checks[5].id == "completeness.stage_histology_grade"


def test_every_check_declares_identity():
    for c in list_checks():
        assert c.owner and c.title and c.description and c.criteria, c.id


def test_stub_never_passes(profile, task):
    result = get_check("integrity.leakage").run(profile, task)
    assert result.status is Status.NOT_IMPLEMENTED


def test_missingness_flags_tumor_grade(profile, task):
    result = get_check("integrity.missingness").run(profile, task)
    assert result.status is Status.WARN
    table = {row["feature"]: row["missing_fraction"] for row in result.evidence[0].table}
    assert table["tumor_grade"] == 1.0


def test_class_imbalance_blocks_on_tiny_cohort(profile, task):
    # 40 patients give only a handful of 5-year deaths: too few to train on.
    result = get_check("integrity.class_imbalance").run(profile, task)
    assert result.metrics["minority_count"] < 30
    assert result.status is Status.FAIL and result.severity is Severity.BLOCKING


def test_survival_target_derivation(profile, task):
    target = task.survival_target(profile)
    usable = target["unusable_reason"].isna()
    assert (target.loc[usable, "time"] >= 0).all()
    dead = profile.features["vital_status"] == "Dead"
    assert target.loc[dead & usable, "event"].all()


def test_completeness_outcomes_scores_required_variables_only(profile, task):
    result = get_check("completeness.outcomes").run(profile, task)
    # progression_or_recurrence is in the pack but not required for survival prediction.
    assert result.metrics["variables_scored"] == 2
    assert result.score is not None and result.score > 0.95


def test_biomarkers_not_applicable_outside_breast(profile, task):
    result = get_check("completeness.biomarkers").run(profile, task)
    rows = {r["variable"]: r for r in result.evidence[0].table}
    assert rows["er_status"]["applicable_patients"] == 40
    assert rows["kras_status"]["applicable_patients"] == 0
    assert result.label == "draft mapping, needs domain review"
