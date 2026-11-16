"""Representativeness: does the cohort look like the population a model would be used on?"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from scorecard.checks.base import Check, CheckResult, Criterion, Evidence, Family, Status, grade
from scorecard.checks.registry import register_check
from scorecard.checks.task_fit.common import severity_for
from scorecard.population import select
from scorecard.profile import DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task

KEY = "representativeness"
MAX_SMD = 9.99


def smd_numeric(mean_a: float, sd_a: float, mean_b: float, sd_b: float) -> float:
    pooled = math.sqrt((sd_a**2 + sd_b**2) / 2)
    if pooled == 0:
        return 0.0 if mean_a == mean_b else MAX_SMD
    return min(abs(mean_a - mean_b) / pooled, MAX_SMD)


def smd_share(p_a: float, p_b: float) -> float:
    pooled = math.sqrt((p_a * (1 - p_a) + p_b * (1 - p_b)) / 2)
    if pooled == 0:
        return 0.0 if p_a == p_b else MAX_SMD
    return min(abs(p_a - p_b) / pooled, MAX_SMD)


@register_check
class Representativeness(Check):
    id = "task_fit.representativeness"
    title = "Representativeness"
    family = Family.TASK_FIT
    criteria = (Criterion.ETHICS, Criterion.CHARACTERIZATION)
    owner = "lead"
    order = 60
    opt_in = True
    description = "Standardized difference from a reference population, and thin subgroups"

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        from scorecard.reference import summarize

        columns = task.param(KEY, "compare_on", [])
        reference = profile.reference
        if reference is None:
            why = (
                "This dataset is the reference population."
                if not profile.linkable
                else "No reference population was supplied (build one with `scorecard "
                "reference` and pass it with --reference)."
            )
            return self.result(Status.NOT_APPLICABLE, why)
        eligible = select(profile, task.population).eligible
        if not eligible.any() or not columns:
            return self.result(
                Status.NOT_APPLICABLE, "No eligible patients or no variables to compare."
            )
        pass_at, warn_at = task.cutoffs(KEY, "smd") or (0.10, 0.25)
        small_n = int(task.param(KEY, "small_group_n", 50))
        show = profile.privacy.count
        n = int(eligible.sum())

        cohort = summarize(profile, task, eligible, suppress=False)
        rows, levels, thin, statuses = [], [], [], []
        for column in columns:
            mine, theirs = cohort.get(column), reference.get("variables", {}).get(column)
            if mine is None or theirs is None or mine["kind"] != theirs["kind"]:
                side = "this dataset" if mine is None else "the reference"
                rows.append(
                    {
                        "variable": column,
                        "smd": None,
                        "status": Status.WARN.value,
                        "note": f"not comparable: not available in {side}",
                    }
                )
                statuses.append(Status.WARN)
                continue
            if mine["kind"] == "numeric":
                smd = smd_numeric(mine["mean"], mine["sd"], theirs["mean"], theirs["sd"])
                note = f"mean {mine['mean']:.1f} here, {theirs['mean']:.1f} in the reference"
            else:
                smd, note = 0.0, ""
                for level in sorted(set(mine["shares"]) | set(theirs["shares"])):
                    p_a = mine["shares"].get(level, 0.0)
                    p_b = theirs["shares"].get(level, 0.0)
                    d = smd_share(p_a, p_b)
                    count = round(p_a * mine["n"])
                    levels.append(
                        {
                            "variable": column,
                            "level": level,
                            "share_here": round(p_a, 4),
                            "share_reference": round(p_b, 4),
                            "smd": round(d, 3),
                            "patients_here": count,
                        }
                    )
                    if count < small_n:
                        thin.append(f"{column} = {level}")
                    if d > smd:
                        smd, note = d, f"largest gap: {level}"
            status = grade(smd, pass_at, warn_at, lower_is_better=True)
            statuses.append(status)
            rows.append(
                {"variable": column, "smd": round(smd, 3), "status": status.value, "note": note}
            )

        status = max(statuses, key=[Status.PASS, Status.WARN, Status.FAIL].index)
        if thin and status is Status.PASS:
            status = Status.WARN
        differing = [r["variable"] for r in rows if r["status"] != Status.PASS.value]
        summary = (
            f"Compared {show(n)} eligible patients with {reference.get('title', 'the reference')} "
            f"on {len(columns)} variables; "
            + (f"differs on {', '.join(differing)}" if differing else "no variable differs")
            + f" (standardized difference above {pass_at:g})"
        )
        if thin:
            summary += f". {len(thin)} subgroups have fewer than {small_n} patients"
        evidence = [Evidence(label="Standardized difference per variable", table=rows)]
        if levels:
            evidence.append(Evidence(label="Category shares", table=levels))
        if thin:
            evidence.append(
                Evidence(
                    label=f"Subgroups with fewer than {small_n} patients", value=", ".join(thin)
                )
            )
        skipped = reference.get("rules_skipped_not_in_source") or []
        if skipped:
            evidence.append(
                Evidence(
                    label="Population rules the reference could not apply",
                    value="; ".join(skipped),
                )
            )
        return self.result(
            status,
            summary + ".",
            severity=severity_for(status, blocking=False),
            metrics={
                "eligible": n,
                "variables_compared": len(columns),
                "thin_subgroups": len(thin),
                "pass_at": pass_at,
                "warn_at": warn_at,
            },
            evidence=evidence,
            remediation=(
                None
                if status is Status.PASS
                else "State who the cohort under-represents. Do not report performance for "
                "subgroups too small to evaluate; validate on a broader cohort before use."
            ),
        )
