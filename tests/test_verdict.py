from scorecard.checks.base import CheckResult, Criterion, Family, Severity, Status
from scorecard.verdict import Label, decide, radar


def _r(status, severity=None, score=None, criteria=(Criterion.CHARACTERIZATION,)):
    return CheckResult(
        check_id=f"x.{status.value}.{severity}",
        title="t",
        family=Family.INTEGRITY,
        criteria=list(criteria),
        owner="o",
        status=status,
        severity=severity,
        summary="s",
        score=score,
    )


def test_blocking_fail_is_not_ready():
    v = decide([_r(Status.PASS), _r(Status.FAIL, Severity.BLOCKING)])
    assert v.label is Label.NOT_READY and not v.provisional


def test_warn_is_conditional():
    assert decide([_r(Status.PASS), _r(Status.WARN, Severity.DEGRADING)]).label is Label.CONDITIONAL


def test_degrading_fail_is_conditional():
    assert decide([_r(Status.FAIL, Severity.DEGRADING)]).label is Label.CONDITIONAL


def test_all_pass_is_ready():
    assert decide([_r(Status.PASS)]).label is Label.READY


def test_stub_makes_verdict_provisional():
    v = decide([_r(Status.PASS), _r(Status.NOT_IMPLEMENTED)])
    assert v.label is Label.READY and v.provisional and "Provisional" in v.reason


def test_radar_marks_unassessed_axes():
    axes = {
        a.criterion: a.score
        for a in radar([_r(Status.WARN, Severity.DEGRADING), _r(Status.PASS, score=0.8)])
    }
    assert axes[Criterion.CHARACTERIZATION] == 0.65
    assert axes[Criterion.ETHICS] is None
