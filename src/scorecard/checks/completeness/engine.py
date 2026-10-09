"""Completeness engine: scores one pack criterion against a profile. Owner: member-3.

Coverage of a variable is the share of the patients it applies to that have an
informative value. A criterion's score is the mean coverage of the variables
the task requires (all applicable variables by default). The task decides the
pass/warn thresholds and whether a shortfall blocks or only degrades.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from scorecard.checks.base import Check, CheckResult, Evidence, Family, Severity, Status
from scorecard.packs import load_pack
from scorecard.profile import DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task


class PackCriterionCheck(Check):
    """Subclass, set `criterion_id` and the identity attributes, and register."""

    family = Family.COMPLETENESS
    owner = "member-3"
    criterion_id: ClassVar[str]

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        criterion = load_pack(task.pack).criterion(self.criterion_id)
        requirement = task.completeness.get(self.criterion_id)
        label = None if criterion.validated else "draft mapping, needs domain review"
        features = profile.features

        rows = []
        for variable in criterion.variables:
            applies = variable.applicable(features)
            n_applicable = int(applies.sum())
            present = variable.present(features) & applies
            emitted = any(c in features.columns for c in variable.columns)
            rows.append(
                {
                    "variable": variable.name,
                    "columns": ", ".join(variable.columns),
                    "applicable_patients": n_applicable,
                    "present_patients": int(present.sum()),
                    "coverage": round(int(present.sum()) / n_applicable, 4)
                    if n_applicable
                    else None,
                    "in_dataset": emitted,
                    "missing_example_ids": (applies & ~present)[lambda s: s].index[:5].tolist(),
                }
            )

        wanted = requirement.required_variables if requirement else None
        scored = [
            r
            for r in rows
            if r["coverage"] is not None and (wanted is None or r["variable"] in wanted)
        ]
        not_applicable = [r["variable"] for r in rows if r["coverage"] is None]

        evidence = [
            Evidence(
                label="Coverage per variable",
                table=[{k: v for k, v in r.items() if k != "missing_example_ids"} for r in rows],
            )
        ]
        gaps = [r for r in scored if r["coverage"] < 1 and r["missing_example_ids"]]
        if gaps:
            evidence.append(
                Evidence(
                    label="Example patients missing a scored variable",
                    table=[
                        {
                            "variable": r["variable"],
                            "example_patient_ids": ", ".join(r["missing_example_ids"]),
                        }
                        for r in gaps
                    ],
                )
            )
        if criterion.review_note:
            evidence.append(Evidence(label="Review note", value=criterion.review_note.strip()))

        if requirement is None:
            return self.result(
                Status.NOT_APPLICABLE,
                f"Task {task.id!r} does not use this criterion.",
                evidence=evidence,
                label=label,
            )
        if not scored:
            return self.result(
                Status.NOT_APPLICABLE,
                "No variable in this criterion applies to these patients.",
                evidence=evidence,
                label=label,
            )

        score = round(sum(r["coverage"] for r in scored) / len(scored), 4)
        if score >= requirement.pass_at:
            status, severity = Status.PASS, None
        elif score >= requirement.warn_at:
            status, severity = Status.WARN, Severity.DEGRADING
        else:
            status, severity = Status.FAIL, requirement.severity

        weakest = sorted(scored, key=lambda r: r["coverage"])
        noun = "variable" if len(scored) == 1 else "variables"
        summary_parts = [f"{score:.0%} mean coverage over {len(scored)} {noun}"]
        low = [r for r in weakest if r["coverage"] < requirement.pass_at]
        if low:
            summary_parts.append(
                "lowest: " + ", ".join(f"{r['variable']} {r['coverage']:.0%}" for r in low[:3])
            )
        if not_applicable:
            summary_parts.append(f"not applicable: {', '.join(not_applicable)}")

        return self.result(
            status,
            "; ".join(summary_parts) + ".",
            severity=severity,
            score=score,
            metrics={
                "variables_scored": len(scored),
                "variables_not_applicable": len(not_applicable),
                "pass_at": requirement.pass_at,
                "warn_at": requirement.warn_at,
                "task_severity": requirement.severity.value,
            },
            evidence=evidence,
            label=label,
            remediation=(
                f"Recover or curate: {', '.join(r['variable'] for r in low)}. Check whether "
                "the source repository holds them in supplementary files."
                if low
                else None
            ),
        )
