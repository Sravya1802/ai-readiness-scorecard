"""Class imbalance, reported as the minority-class count. Owner: member-2.

Ratios hide the problem: 10% events in 10,000 patients is fine, 10% in 300 is
not. What limits a model is how many examples the smaller class has.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scorecard.checks.base import Check, CheckResult, Criterion, Evidence, Family, Severity, Status
from scorecard.checks.registry import register_check
from scorecard.profile import DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task


@register_check
class ClassImbalance(Check):
    id = "integrity.class_imbalance"
    title = "Class imbalance"
    family = Family.INTEGRITY
    criteria = (Criterion.CHARACTERIZATION, Criterion.EXPLAINABILITY)
    owner = "member-2"
    order = 20
    description = "Reported as minority-class count, not just ratio"

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        warn_below = task.param("class_imbalance", "min_minority_warn", 100)
        fail_below = task.param("class_imbalance", "min_minority_fail", 30)
        horizon = task.target.horizon_days
        years = round(horizon / 365.25, 1)

        target = task.survival_target(profile)
        usable = target["unusable_reason"].isna()
        n_events = int(target["event"].sum())
        labelled = target["horizon_label"].dropna()
        n_pos = int((labelled == 1).sum())
        n_neg = int((labelled == 0).sum())
        n_indeterminate = int(usable.sum()) - len(labelled)
        minority_name = (
            f"died within {years:g} years" if n_pos <= n_neg else f"followed past {years:g} years"
        )
        minority = min(n_pos, n_neg)

        unusable = target.loc[~usable, "unusable_reason"]
        evidence = [
            Evidence(
                label=f"{years:g}-year mortality view of the target",
                table=[
                    {"class": f"died within {years:g} years", "patients": n_pos},
                    {"class": f"followed past {years:g} years", "patients": n_neg},
                    {
                        "class": "censored before the horizon (no label)",
                        "patients": n_indeterminate,
                    },
                    {"class": "unusable target", "patients": int((~usable).sum())},
                ],
            ),
            Evidence(label="Events (deaths) for time-to-event modelling", value=n_events),
        ]
        if len(unusable):
            evidence.append(
                Evidence(
                    label="Patients with an unusable target, by reason",
                    table=[
                        {"reason": r, "patients": int(n)}
                        for r, n in unusable.value_counts().items()
                    ],
                    patient_ids=unusable.index[:10].tolist(),
                )
            )

        if minority < fail_below:
            status, severity = Status.FAIL, Severity.BLOCKING
        elif minority < warn_below:
            status, severity = Status.WARN, Severity.DEGRADING
        else:
            status, severity = Status.PASS, None

        summary = (
            f"Minority class n = {minority} ({minority_name}) of {len(labelled)} labelled; "
            f"{n_events} deaths in total."
        )
        if status is Status.FAIL:
            summary += " Too few to train or validate."
        elif status is Status.WARN:
            summary += " Degrading, not blocking."
        if len(unusable):
            summary += f" {len(unusable)} patients have an unusable target."

        return self.result(
            status,
            summary,
            severity=severity,
            metrics={
                "minority_count": minority,
                "positive": n_pos,
                "negative": n_neg,
                "indeterminate": n_indeterminate,
                "events": n_events,
                "unusable": int((~usable).sum()),
                "horizon_days": horizon,
            },
            evidence=evidence,
            remediation=(
                "Prefer time-to-event models, which use censored patients, over a binary "
                "horizon label; report event counts per fold; consider pooling cohorts."
                if status is not Status.PASS
                else None
            ),
        )
