"""Cohort identifiable: can the patients the question is about be picked out?"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scorecard.checks.base import Check, CheckResult, Criterion, Evidence, Family, Status, grade
from scorecard.checks.registry import register_check
from scorecard.checks.task_fit.common import pct, severity_for
from scorecard.population import select
from scorecard.profile import Availability, DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task


@register_check
class CohortIdentifiable(Check):
    id = "task_fit.cohort_identifiable"
    title = "Cohort identifiable"
    family = Family.TASK_FIT
    criteria = (Criterion.CHARACTERIZATION, Criterion.COMPUTABILITY)
    owner = "lead"
    order = 10
    opt_in = True
    description = "Share of patients who can be labelled eligible or not eligible"

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        if task.population is None or not task.population.rules:
            return self.result(
                Status.PASS,
                f"The task sets no population rules; all {profile.n_patients:,} patients count.",
                metrics={"eligible": profile.n_patients},
            )
        pass_at, warn_at = task.cutoffs("cohort_identifiable", "decided_fraction") or (0.90, 0.75)
        cohort = select(profile, task.population)
        show = profile.privacy.count
        decided = cohort.decided_fraction

        status = grade(decided, pass_at, warn_at)
        if cohort.n_eligible == 0:
            status = Status.FAIL

        worst_rule = max(
            cohort.rule_table, key=lambda r: r["undecided_among_unknown"], default=None
        )
        parts = [
            f"{pct(decided)} of {cohort.n:,} patients can be labelled: "
            f"{show(cohort.n_eligible)} eligible, {show(cohort.n_not_eligible)} not eligible, "
            f"{show(cohort.n_unknown)} unknown"
        ]
        remediation = None
        if cohort.n_eligible == 0:
            parts.append("no patient is eligible")
        if worst_rule and worst_rule["undecided_among_unknown"]:
            column = worst_rule["column"]
            availability = profile.availability(column)
            why = {
                Availability.NOT_IN_SOURCE: ", which this dataset does not carry",
                Availability.NOT_LOADED: ", which was not loaded",
            }.get(availability, "")
            parts.append(
                f"most unknowns come from {column}{why} "
                f"(n = {show(worst_rule['undecided_among_unknown'])})"
            )
            if status is not Status.PASS:
                remediation = {
                    Availability.NOT_IN_SOURCE: (
                        f"{column} is not in this source. Link another source that has it, "
                        "or narrow the question so the rule is not needed."
                    ),
                    Availability.NOT_LOADED: (f"Load the file that holds {column} and rerun."),
                }.get(availability, f"Recover {column} for the patients where it is missing.")

        return self.result(
            status,
            "; ".join(parts) + ".",
            severity=severity_for(status, blocking=True),
            score=None if decided is None else round(decided, 4),
            metrics={
                "n_patients": cohort.n,
                "eligible": cohort.n_eligible,
                "not_eligible": cohort.n_not_eligible,
                "unknown": cohort.n_unknown,
                "decided_fraction": None if decided is None else round(decided, 4),
                "pass_at": pass_at,
                "warn_at": warn_at,
            },
            evidence=[
                Evidence(
                    label="Cohort",
                    table=[
                        {"label": "eligible", "patients": cohort.n_eligible},
                        {"label": "not eligible", "patients": cohort.n_not_eligible},
                        {
                            "label": "unknown (a rule could not be decided)",
                            "patients": cohort.n_unknown,
                        },
                    ],
                ),
                Evidence(label="Population rules", table=cohort.rule_table),
            ],
            remediation=remediation,
        )
