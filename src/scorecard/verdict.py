"""From check results to a task-relative verdict and the Bridge2AI radar profile.

Verdict rules
  NOT_READY    any FAIL with blocking severity
  CONDITIONAL  otherwise, any WARN or degrading FAIL
  READY        otherwise

A verdict is PROVISIONAL while any registered check is not implemented, so a
partial tool never reports a dataset as ready on the strength of the checks it
happened to have.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from scorecard.checks.base import CheckResult, Criterion, Severity, Status

# How a result counts on the radar when it has no coverage score of its own.
STATUS_SCORE = {Status.PASS: 1.0, Status.WARN: 0.5, Status.FAIL: 0.0}
ASSESSED = (Status.PASS, Status.WARN, Status.FAIL)


class Label(str, Enum):
    READY = "READY"
    CONDITIONAL = "CONDITIONAL"
    NOT_READY = "NOT_READY"


class Verdict(BaseModel):
    label: Label
    provisional: bool
    reason: str
    counts: dict[str, int]
    blocking: list[str]
    degrading: list[str]
    not_assessed: list[str]
    checks_run: int
    checks_total: int


class AxisScore(BaseModel):
    criterion: Criterion
    score: float | None
    checks: list[str]


def _deficiencies(n: int, kind: str) -> str:
    return f"{n} {kind} {'deficiency' if n == 1 else 'deficiencies'}"


def decide(results: list[CheckResult]) -> Verdict:
    blocking = [r.check_id for r in results if r.is_blocking_failure]
    degrading = [
        r.check_id
        for r in results
        if r.status is Status.WARN or (r.status is Status.FAIL and r.severity is Severity.DEGRADING)
    ]
    not_assessed = [r.check_id for r in results if r.status is Status.NOT_IMPLEMENTED]
    counts = {s.value: sum(r.status is s for r in results) for s in Status}
    checks_run = sum(r.status in ASSESSED or r.status is Status.NOT_APPLICABLE for r in results)

    if blocking:
        label = Label.NOT_READY
        reason = (
            f"Does not support the task until {_deficiencies(len(blocking), 'blocking')} "
            f"{'is' if len(blocking) == 1 else 'are'} fixed; {len(degrading)} degrading."
        )
    elif degrading:
        label = Label.CONDITIONAL
        reason = (
            f"Supports the task with {_deficiencies(len(degrading), 'degrading')}; none blocking."
        )
    else:
        label = Label.READY
        reason = "Supports the task; no deficiencies found in the checks that ran."

    if not_assessed:
        reason += f" Provisional: {len(not_assessed)} of {len(results)} checks not yet implemented."

    return Verdict(
        label=label,
        provisional=bool(not_assessed),
        reason=reason,
        counts=counts,
        blocking=blocking,
        degrading=degrading,
        not_assessed=not_assessed,
        checks_run=checks_run,
        checks_total=len(results),
    )


def radar(results: list[CheckResult]) -> list[AxisScore]:
    """Score each Bridge2AI criterion as the mean of the assessed checks that inform it.

    A completeness check contributes its coverage score; other checks contribute
    1 / 0.5 / 0 for PASS / WARN / FAIL. Criteria no assessed check informs get
    score None and are drawn as "not assessed".
    """
    axes = []
    for criterion in Criterion:
        contributing = [r for r in results if criterion in r.criteria and r.status in ASSESSED]
        values = [r.score if r.score is not None else STATUS_SCORE[r.status] for r in contributing]
        axes.append(
            AxisScore(
                criterion=criterion,
                score=round(sum(values) / len(values), 4) if values else None,
                checks=[r.check_id for r in contributing],
            )
        )
    return axes
