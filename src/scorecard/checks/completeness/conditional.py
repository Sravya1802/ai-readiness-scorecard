"""Conditional completeness: are the question's variables filled in where they are expected?

Unlike the pack criteria, this reads the variable list from the task, counts
only eligible patients, and counts a variable only for the patients it is
expected for (`expected_when`). A required variable the dataset does not carry
fails outright, whatever the coverage of the others.

The failure is degrading by default. A task can make it blocking for the
variables the question cannot do without, by role:

    params:
      conditional_completeness:
        blocking_if_absent_roles: [treatment, outcome]

Then a required variable of that role that the source does not carry at all
(not_in_source, with no stand-in) blocks the verdict. A variable that exists in
the source but was not loaded stays degrading: loading the file fixes it.
"""

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
from scorecard.checks.task_fit.common import pct, severity_for
from scorecard.packs import PackVariable
from scorecard.population import select
from scorecard.profile import Availability, DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task, TaskVariable

KEY = "conditional_completeness"
DEFAULTS = {"required": (0.90, 0.70), "recommended": (0.70, 0.40)}


def availability_of(profile: DatasetProfile, variable: PackVariable) -> Availability:
    """Best availability across a variable's sources."""
    if variable.modality is not None:
        return (
            Availability.LOADED
            if variable.modality in profile.modalities.columns
            else Availability.NOT_IN_SOURCE
        )
    found = [profile.availability(c) for c in variable.columns]
    for level in (Availability.LOADED, Availability.NOT_LOADED):
        if level in found:
            return level
    return Availability.NOT_IN_SOURCE


def _substitute(name: str) -> PackVariable:
    if name.startswith("modality:"):
        return PackVariable(name=name, modality=name.split(":", 1)[1])
    return PackVariable(name=name, column=name)


@register_check
class ConditionalCompleteness(Check):
    id = "completeness.conditional"
    title = "Conditional completeness"
    family = Family.COMPLETENESS
    criteria = (Criterion.CHARACTERIZATION, Criterion.COMPUTABILITY)
    owner = "member-3"
    order = 60
    opt_in = True
    description = "Question variables filled in among eligible patients where expected"

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        if not task.variables:
            return self.result(Status.NOT_APPLICABLE, f"Task {task.id!r} lists no variables.")
        eligible = select(profile, task.population).eligible
        if not eligible.any():
            return self.result(
                Status.NOT_APPLICABLE, "No eligible patients to measure completeness on."
            )
        features, modalities = profile.features, profile.modalities
        allow_ids = profile.privacy.patient_level_output

        rows, examples = [], []
        for variable in task.variables:
            cutoffs = task.cutoffs(KEY, variable.need) or DEFAULTS[variable.need]
            row = self._row(profile, variable, eligible, cutoffs)
            rows.append(row)
            if allow_ids and row["status"] in ("WARN", "FAIL") and row["in_dataset"] == "loaded":
                expected = variable.applicable(features) & eligible
                gap = expected & ~variable.present(features, modalities)
                if gap.any():
                    examples.append(
                        {
                            "variable": variable.name,
                            "example_patient_ids": ", ".join(gap[gap].index[:5]),
                        }
                    )

        required = [r for r in rows if r["need"] == "required" and r["status"] != "n/a"]
        recommended = [r for r in rows if r["need"] == "recommended" and r["status"] != "n/a"]
        statuses = [Status(r["status"]) for r in required]
        # A shortfall on a nice-to-have variable is a caution at most.
        statuses += [Status.WARN for r in recommended if r["status"] != "PASS"]
        status = worst(statuses)

        scored = required or recommended
        score = round(sum(r["coverage"] or 0 for r in scored) / len(scored), 4) if scored else None
        absent = [r["variable"] for r in required if r["in_dataset"] == "not_in_source"]
        unloaded = [r["variable"] for r in required if r["in_dataset"] == "not_loaded"]
        low = sorted(
            (r for r in required if r["in_dataset"] == "loaded" and r["status"] != "PASS"),
            key=lambda r: r["coverage"] or 0,
        )
        stand_ins = [r["variable"] for r in rows if r["via_substitute"]]
        blocking_roles = set(task.param(KEY, "blocking_if_absent_roles", []) or [])
        blockers = [
            r["variable"]
            for r in required
            if r["role"] in blocking_roles
            and r["in_dataset"] == "not_in_source"
            and r["status"] == Status.FAIL.value
        ]
        n_pass = sum(r["status"] == "PASS" for r in required)

        parts = [f"{n_pass} of {len(required)} required variables are complete enough"]
        if blockers:
            parts.insert(
                0,
                f"the question cannot be answered without {', '.join(blockers)}, "
                "which this dataset does not carry",
            )
        if absent:
            parts.append(f"not carried by this dataset: {', '.join(absent)}")
        if unloaded:
            parts.append(f"not loaded: {', '.join(unloaded)}")
        if low:
            parts.append(
                "lowest: " + ", ".join(f"{r['variable']} {pct(r['coverage'])}" for r in low[:3])
            )
        if stand_ins:
            parts.append(f"only a stand-in for: {', '.join(stand_ins)}")

        fixes = []
        if absent:
            fixes.append(f"Link a source that carries {', '.join(absent)}.")
        if unloaded:
            fixes.append(f"Load the files that hold {', '.join(unloaded)} and rerun.")
        if low:
            fixes.append(f"Recover or curate {', '.join(r['variable'] for r in low)}.")

        evidence = [
            Evidence(
                label="Coverage per variable, among eligible patients where the value is expected",
                table=rows,
            )
        ]
        if examples:
            evidence.append(Evidence(label="Example patients missing a variable", table=examples))
        return self.result(
            status,
            "; ".join(parts) + ".",
            severity=severity_for(status, blocking=bool(blockers)),
            score=score,
            metrics={
                "eligible": int(eligible.sum()),
                "required_variables": len(required),
                "required_passing": n_pass,
                "required_not_in_source": len(absent),
                "required_not_loaded": len(unloaded),
                "blocking_absent": blockers,
            },
            evidence=evidence,
            remediation=" ".join(fixes) or None,
        )

    @staticmethod
    def _row(
        profile: DatasetProfile, variable: TaskVariable, eligible, cutoffs: tuple[float, float]
    ) -> dict:
        features, modalities = profile.features, profile.modalities
        expected = variable.applicable(features) & eligible
        n_expected = int(expected.sum())
        availability = availability_of(profile, variable)
        present = variable.present(features, modalities) & expected
        coverage = int(present.sum()) / n_expected if n_expected else None

        via_substitute = False
        status = "n/a" if n_expected == 0 else grade(coverage, *cutoffs).value
        if availability is not Availability.LOADED and n_expected:
            status, coverage = Status.FAIL.value, 0.0
        if status in ("WARN", "FAIL") and variable.substitutes and n_expected:
            alt = present.copy()
            for name in variable.substitutes:
                alt |= _substitute(name).present(features, modalities) & expected
            alt_coverage = int(alt.sum()) / n_expected
            if grade(alt_coverage, *cutoffs) is Status.PASS:
                # Good enough to proceed, but a stand-in never earns a full pass.
                status, via_substitute, coverage = Status.WARN.value, True, alt_coverage
        return {
            "variable": variable.name,
            "need": variable.need,
            "role": variable.role,
            "in_dataset": availability.value,
            "expected_patients": n_expected,
            "present_patients": int(present.sum()),
            "coverage": None if coverage is None else round(coverage, 4),
            "via_substitute": via_substitute,
            "status": status,
        }
