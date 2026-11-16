"""Treatment adequacy: can treated and untreated patients be compared fairly?

"Benefit" is a causal question. It needs both groups, a trustworthy "no", and
the variables that drive who gets treated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

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
from scorecard.population import select
from scorecard.profile import NO_UNKNOWN_MERGED, Availability, DatasetProfile

if TYPE_CHECKING:
    from scorecard.tasks import Task

KEY = "treatment_adequacy"


def overlap_share(features: pd.DataFrame, treated: pd.Series, folds: int) -> float | None:
    """Share of patients whose predicted chance of treatment is in the range both groups cover.

    The model is fitted inside cross-validation folds, with imputation and
    encoding inside the fold pipeline, so each patient's probability comes from
    a model that never saw that patient.
    """
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    features = features.loc[:, features.notna().any()]
    if features.shape[1] == 0 or treated.nunique() < 2 or treated.value_counts().min() < folds:
        return None
    numeric = [c for c in features if pd.api.types.is_numeric_dtype(features[c])]
    categorical = [c for c in features if c not in numeric]
    x = features.copy()
    x[categorical] = x[categorical].astype(object).where(x[categorical].notna(), None)
    model = make_pipeline(
        ColumnTransformer(
            [
                ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), numeric),
                (
                    "cat",
                    make_pipeline(
                        SimpleImputer(strategy="constant", fill_value="missing"),
                        OneHotEncoder(handle_unknown="ignore"),
                    ),
                    categorical,
                ),
            ]
        ),
        LogisticRegression(max_iter=1000),
    )
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=0)
    p = pd.Series(
        cross_val_predict(model, x, treated.astype(int), cv=cv, method="predict_proba")[:, 1],
        index=x.index,
    )
    low = max(p[treated].min(), p[~treated].min())
    high = min(p[treated].max(), p[~treated].max())
    return float(((p >= low) & (p <= high)).mean())


@register_check
class TreatmentAdequacy(Check):
    id = "task_fit.treatment_adequacy"
    title = "Treatment adequacy"
    family = Family.TASK_FIT
    criteria = (Criterion.EXPLAINABILITY, Criterion.CHARACTERIZATION)
    owner = "lead"
    order = 50
    opt_in = True
    description = "Treatment recorded as yes or no, group sizes, and confounders present"

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        t = task.treatment
        if t is None:
            return self.result(
                Status.NOT_APPLICABLE, f"Task {task.id!r} does not compare treatments."
            )
        eligible = select(profile, task.population).eligible
        n = int(eligible.sum())
        if n == 0:
            return self.result(
                Status.NOT_APPLICABLE, "No eligible patients, so there are no groups to compare."
            )
        show = profile.privacy.count
        name = t.title or t.column
        fail_severity = severity_for(Status.FAIL, blocking=True)

        availability = profile.availability(t.column)
        if availability is not Availability.LOADED:
            reason = (
                "is not in this source"
                if availability is Availability.NOT_IN_SOURCE
                else "was not loaded"
            )
            return self.result(
                Status.FAIL,
                f"{name} ({t.column}) {reason}, so treated and untreated patients cannot be "
                "told apart.",
                severity=fail_severity,
                metrics={"eligible": n},
                remediation=f"Add a source that records {name} as yes or no for each patient.",
            )

        meta = profile.feature_meta[t.column]
        arms = t.arms(profile.features)[eligible]
        n_treated = int((arms == "treated").sum())
        n_untreated = int((arms == "untreated").sum())
        n_unknown = n - n_treated - n_untreated
        counts = Evidence(
            label=f"{name} among eligible patients",
            table=[
                {"group": "treated (recorded yes)", "patients": n_treated},
                {"group": "untreated (recorded no)", "patients": n_untreated},
                {"group": "not recorded or no/unknown", "patients": n_unknown},
            ],
        )
        metrics: dict = {
            "eligible": n,
            "treated": n_treated,
            "untreated": n_untreated,
            "unknown": n_unknown,
        }

        if NO_UNKNOWN_MERGED in meta.caveats:
            evidence = [counts]
            if meta.note:
                evidence.append(Evidence(label="Source documentation", value=meta.note))
            return self.result(
                Status.FAIL,
                f'The source reports {name} as "yes" or "no/unknown", so untreated patients '
                f"cannot be separated from unrecorded ones ({show(n_treated)} recorded yes).",
                severity=fail_severity,
                metrics=metrics,
                evidence=evidence,
                remediation=(
                    "Use this dataset for questions about treated patients only, or link a "
                    "source that records untreated patients explicitly (claims or chart review)."
                ),
            )
        if n_untreated == 0 or n_treated == 0:
            empty = "untreated" if n_untreated == 0 else "treated"
            detail = (
                f'No eligible patient is recorded as {empty}. A patient without a "no" on '
                "record is unknown, not untreated, so there is no comparison group."
                if empty == "untreated"
                else "No eligible patient is recorded as treated, so there is no comparison."
            )
            return self.result(
                Status.FAIL,
                detail,
                severity=fail_severity,
                metrics=metrics,
                evidence=[counts],
                remediation=f'Find a source that records "{empty}" explicitly for {name}.',
            )

        rows = []

        def score(metric: str, value: float | None, text: str, *, cap: Status | None = None):
            cutoffs = task.cutoffs(KEY, metric)
            status = None if cutoffs is None else grade(value, *cutoffs)
            if status is Status.FAIL and cap is not None:
                status = cap
            rows.append(
                {
                    "metric": metric,
                    "value": text,
                    "pass_at": cutoffs[0] if cutoffs else None,
                    "warn_at": cutoffs[1] if cutoffs else None,
                    "status": status.value if status else "reported",
                }
            )

        known = n_treated + n_untreated
        smaller = min(n_treated, n_untreated)
        score("treatment_known", known / n, pct(known / n))
        score("smaller_arm_n", smaller, str(show(smaller)))
        score("smaller_arm_share", smaller / known, pct(smaller / known))
        metrics.update(
            treatment_known=round(known / n, 4), smaller_arm_share=round(smaller / known, 4)
        )

        min_coverage = task.param(KEY, "confounder_min_coverage", 0.8)
        confounders = []
        for column in t.confounders:
            carried = profile.carries(column)
            coverage = (
                float(profile.features.loc[eligible, column].notna().mean()) if carried else 0
            )
            confounders.append(
                {
                    "confounder": column,
                    "in_dataset": profile.availability(column).value,
                    "coverage": round(coverage, 4),
                    "counts_as_present": coverage >= min_coverage,
                }
            )
        if confounders:
            share = sum(c["counts_as_present"] for c in confounders) / len(confounders)
            score("confounders_present", share, pct(share))
            metrics["confounders_present"] = round(share, 4)

        overlap = task.param(KEY, "overlap", None)
        if isinstance(overlap, dict) and overlap.get("enabled", True):
            usable = [c["confounder"] for c in confounders if c["in_dataset"] == "loaded"]
            both = arms.notna()
            value = None
            if smaller >= overlap.get("min_arm_n", 30) and usable:
                value = overlap_share(
                    profile.features.loc[eligible, usable][both],
                    arms[both] == "treated",
                    int(overlap.get("cv_folds", 5)),
                )
            if value is None:
                rows.append(
                    {
                        "metric": "overlap",
                        "value": "not computed (groups too small)",
                        "pass_at": None,
                        "warn_at": None,
                        "status": "reported",
                    }
                )
            else:
                # A simple model, so a low value is a caution to look closer, not a verdict.
                score("overlap", value, pct(value), cap=Status.WARN)
                metrics["overlap"] = round(value, 4)

        status = worst([Status(r["status"]) for r in rows if r["status"] != "reported"])
        summary = (
            f"{name} is recorded as yes or no for {pct(known / n)} of {show(n)} eligible "
            f"patients: {show(n_treated)} treated, {show(n_untreated)} untreated"
        )
        missing = [c["confounder"] for c in confounders if not c["counts_as_present"]]
        if missing:
            summary += f"; confounders not adequately recorded: {', '.join(missing)}"
        below = [r["metric"] for r in rows if r["status"] in ("FAIL", "WARN")]
        if below:
            summary += f". Below cutoff: {', '.join(below)}"

        evidence = [
            counts,
            Evidence(label="Treatment metrics against the task's cutoffs", table=rows),
        ]
        if confounders:
            evidence.append(Evidence(label="Confounders", table=confounders))
        return self.result(
            status,
            summary + ".",
            severity=severity_for(status, blocking=True),
            metrics=metrics,
            evidence=evidence,
            remediation=(
                None
                if status is Status.PASS
                else "Recover treatment records and the missing confounders before estimating "
                "benefit; without them a difference between groups may reflect who was "
                "selected for treatment."
            ),
        )
