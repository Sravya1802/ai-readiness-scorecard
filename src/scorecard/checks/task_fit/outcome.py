"""Outcome adequacy: is follow-up long enough, with enough events, on the right endpoint?"""

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
from scorecard.checks.task_fit.common import find_outcome, pct, severity_for
from scorecard.population import select
from scorecard.profile import DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task

KEY = "outcome_adequacy"


@register_check
class OutcomeAdequacy(Check):
    id = "task_fit.outcome_adequacy"
    title = "Outcome adequacy"
    family = Family.TASK_FIT
    criteria = (Criterion.COMPUTABILITY, Criterion.CHARACTERIZATION)
    owner = "lead"
    order = 30
    opt_in = True
    description = "Follow-up length, event counts, and primary outcome versus stand-in"

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        if task.target is None:
            return self.result(Status.NOT_APPLICABLE, f"Task {task.id!r} declares no outcome.")
        eligible = select(profile, task.population).eligible
        if not eligible.any():
            return self.result(
                Status.NOT_APPLICABLE, "No eligible patients, so there is no outcome to assess."
            )
        outcome = find_outcome(profile, task, eligible)
        show = profile.privacy.count
        n = int(eligible.sum())

        if outcome.frame is None:
            missing = ", ".join(outcome.unavailable or []) or "the outcome"
            return self.result(
                Status.FAIL,
                f"The dataset carries no usable outcome for this question (looked for: {missing}).",
                severity=severity_for(Status.FAIL, blocking=True),
                metrics={"eligible": n},
                remediation=(
                    f"Add an outcome source: {missing}. Without one the question "
                    "cannot be trained or evaluated on this dataset."
                ),
            )

        rows: list[dict] = []
        notes: list[str] = []

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

        usable_fraction = outcome.n_usable / n
        score("usable_fraction", usable_fraction, pct(usable_fraction))
        metrics = {
            "eligible": n,
            "outcome": outcome.name,
            "is_proxy": outcome.is_proxy,
            "usable_patients": outcome.n_usable,
            "events": outcome.n_events,
        }

        if outcome.kind == "label":
            minority = min(outcome.n_events, outcome.n_non_events)
            score("minority_count", minority, str(show(minority)))
            metrics["minority_count"] = minority
            headline = (
                f"{outcome.label}: {show(outcome.n_events)} positive and "
                f"{show(outcome.n_non_events)} negative among {show(n)} eligible patients "
                f"({pct(usable_fraction)} labelled)"
            )
        else:
            followup = outcome.median_followup_years
            score(
                "median_followup_years", followup, "n/a" if followup is None else f"{followup:.1f}"
            )
            score("events", outcome.n_events, str(show(outcome.n_events)))
            metrics["median_followup_years"] = None if followup is None else round(followup, 2)
            if task.treatment is not None:
                arms = task.treatment.arms(profile.features)[eligible]
                events = outcome.frame["event"] == True  # noqa: E712
                per_arm = {
                    arm: int((events & (arms == arm)).sum()) for arm in ("treated", "untreated")
                }
                smaller = min(per_arm.values())
                score(
                    "events_per_arm",
                    smaller,
                    ", ".join(f"{arm} {show(v)}" for arm, v in per_arm.items()),
                )
                metrics["events_treated"] = per_arm["treated"]
                metrics["events_untreated"] = per_arm["untreated"]
            headline = (
                f"{outcome.label}: {show(outcome.n_events)} events among {show(n)} eligible "
                f"patients; median follow-up "
                f"{'n/a' if followup is None else f'{followup:.1f} years'} in patients without "
                "the event"
            )
            if outcome.is_proxy:
                notes.append(
                    "only a stand-in endpoint is available (not carried: "
                    + ", ".join(outcome.unavailable or [])
                    + ")"
                )
                rows.append(
                    {
                        "metric": "primary_endpoint_available",
                        "value": "no",
                        "pass_at": None,
                        "warn_at": None,
                        "status": Status.WARN.value,
                    }
                )
            floor = task.param(KEY, "proxy_min_followup_years", {}).get(outcome.name)
            if outcome.is_proxy and floor is not None and (followup is None or followup < floor):
                notes.append(
                    f"{outcome.label} is too weak a stand-in below {floor:g} years of follow-up"
                )
                rows.append(
                    {
                        "metric": f"proxy_min_followup_years[{outcome.name}]",
                        "value": "n/a" if followup is None else f"{followup:.1f}",
                        "pass_at": floor,
                        "warn_at": floor,
                        "status": Status.FAIL.value,
                    }
                )

        status = worst([Status(r["status"]) for r in rows if r["status"] != "reported"])
        short = [r["metric"] for r in rows if r["status"] == Status.FAIL.value]
        low = [r["metric"] for r in rows if r["status"] == Status.WARN.value]
        summary = headline
        if notes:
            summary += "; " + "; ".join(notes)
        if short:
            summary += f". Below the minimum: {', '.join(short)}"
        elif low:
            summary += f". Below the target: {', '.join(low)}"

        return self.result(
            status,
            summary + ".",
            severity=severity_for(status, blocking=True),
            metrics=metrics,
            evidence=[Evidence(label="Outcome metrics against the task's cutoffs", table=rows)],
            remediation=(
                None
                if status is Status.PASS
                else "Extend follow-up, pool cohorts to add events, or obtain the primary "
                "endpoint. Report the stand-in endpoint by name wherever results are shown."
            ),
        )
