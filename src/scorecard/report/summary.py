"""Plain-language pieces shared by the data card, scorecard.json and the results grid."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scorecard.checks import Status

if TYPE_CHECKING:
    from scorecard.pipeline import Run


def cohort_summary(run: Run) -> dict | None:
    """The question, its population rules, and how many patients fell on each side."""
    if run.cohort is None or run.task.population is None:
        return None
    show = run.profile.privacy.count
    cohort = run.cohort
    return {
        "question": run.task.question or run.task.title,
        "population": run.task.population.description,
        "rules": [row["rule"] for row in cohort.rule_table],
        "n_patients": cohort.n,
        "eligible": show(cohort.n_eligible),
        "not_eligible": show(cohort.n_not_eligible),
        "unknown": show(cohort.n_unknown),
    }


def what_is_missing(run: Run) -> list[dict]:
    """Remediation from every failed or warned check, blocking items first."""
    items = [
        {
            "check_id": r.check_id,
            "title": r.title,
            "blocking": r.is_blocking_failure,
            "status": r.status.value,
            "finding": r.summary,
            "remediation": r.remediation,
        }
        for r in run.results
        if r.status in (Status.FAIL, Status.WARN)
    ]
    return sorted(items, key=lambda i: (not i["blocking"], i["status"] != "FAIL"))


def narrower_questions(run: Run) -> list[str]:
    """Questions the task says the dataset may still support, given what did not pass."""
    not_passed = {r.check_id for r in run.results if r.status in (Status.FAIL, Status.WARN)}
    return [f.question for f in run.task.fallbacks if not_passed & set(f.if_not_passed)]


def main_reason(run: Run) -> str:
    """One line for a grid cell: the finding that decided the verdict."""
    for wanted in (
        lambda r: r.is_blocking_failure,
        lambda r: r.status is Status.FAIL,
        lambda r: r.status is Status.WARN,
    ):
        for r in run.results:
            if wanted(r):
                return f"{r.title}: {r.summary}"
    return run.verdict.reason
