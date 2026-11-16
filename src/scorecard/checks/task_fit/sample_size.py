"""Sample size: how much data is left after the population rules?"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scorecard.checks.base import (
    Check,
    CheckResult,
    Criterion,
    Evidence,
    Family,
    Status,
    grade,
    worst,
)
from scorecard.checks.registry import register_check
from scorecard.checks.task_fit.common import find_outcome, severity_for
from scorecard.population import select
from scorecard.profile import DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task

KEY = "sample_size"


@register_check
class SampleSize(Check):
    id = "task_fit.sample_size"
    title = "Sample size"
    family = Family.TASK_FIT
    criteria = (Criterion.CHARACTERIZATION,)
    owner = "lead"
    order = 40
    opt_in = True
    description = "Eligible patients, and events per predictor"

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        eligible = select(profile, task.population).eligible
        n = int(eligible.sum())
        show = profile.privacy.count
        rows = []

        def score(metric: str, value: float | None, text: str) -> None:
            cutoffs = task.cutoffs(KEY, metric)
            status = None if cutoffs is None else grade(value, *cutoffs)
            rows.append(
                {
                    "metric": metric,
                    "value": text,
                    "pass_at": cutoffs[0] if cutoffs else None,
                    "warn_at": cutoffs[1] if cutoffs else None,
                    "status": status.value if status else "reported",
                }
            )

        score("eligible_n", n, str(show(n)))
        metrics: dict = {"eligible": n}
        summary = f"{show(n)} eligible patients"

        predictors = [v.name for v in task.variables if v.role == "predictor"]
        if n and predictors and task.target is not None:
            outcome = find_outcome(profile, task, eligible)
            if outcome.frame is not None:
                # For a label the smaller class limits the model, as events do for survival.
                events = (
                    min(outcome.n_events, outcome.n_non_events)
                    if outcome.kind == "label"
                    else outcome.n_events
                )
                epp = events / len(predictors)
                score("events_per_predictor", epp, f"{epp:.1f}")
                metrics.update(
                    events=events, predictors=len(predictors), events_per_predictor=round(epp, 2)
                )
                summary += (
                    f"; {epp:.1f} events per predictor "
                    f"({show(events)} events, {len(predictors)} predictors)"
                )
            else:
                summary += "; events per predictor not computed (no usable outcome)"

        status = worst([Status(r["status"]) for r in rows if r["status"] != "reported"])
        return self.result(
            status,
            summary + ".",
            severity=severity_for(status, blocking=False),
            metrics=metrics,
            evidence=[Evidence(label="Sample size against the task's cutoffs", table=rows)],
            remediation=(
                None
                if status is Status.PASS
                else "Pool cohorts, widen the population rules, or use fewer predictors."
            ),
        )
