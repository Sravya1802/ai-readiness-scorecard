"""Missingness: overall, per feature, and whether it depends on site or target. Owner: member-2."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from scipy.stats import chi2_contingency

from scorecard.checks.base import Check, CheckResult, Criterion, Evidence, Family, Severity, Status
from scorecard.checks.registry import register_check
from scorecard.profile import DatasetProfile, Role

if TYPE_CHECKING:
    from scorecard.tasks import Task


def _association_p(missing: pd.Series, groups: pd.Series) -> float | None:
    """Chi-square p-value for missing-indicator vs group. None when untestable."""
    keep = groups.notna()
    table = pd.crosstab(groups[keep], missing[keep])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    return float(chi2_contingency(table)[1])


@register_check
class Missingness(Check):
    id = "integrity.missingness"
    title = "Missingness"
    family = Family.INTEGRITY
    criteria = (Criterion.CHARACTERIZATION, Criterion.COMPUTABILITY)
    owner = "member-2"
    order = 10
    description = "Overall and per-feature, plus whether it correlates with site or target"

    def run(self, profile: DatasetProfile, task: Task) -> CheckResult:
        p = lambda key, default: task.param("missingness", key, default)  # noqa: E731
        feature_warn = p("feature_warn", 0.20)
        overall_warn = p("overall_warn", 0.10)
        alpha = p("alpha", 0.05)
        min_site_size = p("min_site_size", 10)

        columns = profile.columns_with_role(Role.FEATURE)
        missing = profile.features[columns].isna()
        overall = float(missing.to_numpy().mean()) if columns else 0.0
        per_feature = missing.mean().sort_values(ascending=False)
        high = per_feature[per_feature > feature_warn]

        # Missingness that tracks site or outcome is informative, not random:
        # a model can learn it as a proxy. Test each partly-missing feature.
        tests: dict[str, pd.Series] = {}
        if profile.site is not None:
            site = profile.site
            sizes = site.value_counts()
            tests["site"] = site.where(site.map(sizes) >= min_site_size, "other")
        target = task.survival_target(profile)["event"]
        if target.notna().any():
            tests["target"] = target

        partly_missing = [c for c in columns if 0 < per_feature[c] < 1]
        n_tests = max(len(partly_missing), 1)
        associated: list[dict] = []
        for against, groups in tests.items():
            for column in partly_missing:
                pval = _association_p(missing[column], groups)
                # Bonferroni across features, per grouping.
                if pval is not None and pval * n_tests < alpha:
                    associated.append(
                        {
                            "feature": column,
                            "associated_with": against,
                            "p_value": float(f"{pval:.3g}"),
                            "missing_fraction": round(float(per_feature[column]), 3),
                        }
                    )

        evidence = [
            Evidence(
                label="Per-feature missingness",
                table=[
                    {"feature": c, "missing_fraction": round(float(v), 3)}
                    for c, v in per_feature.items()
                ],
            )
        ]
        if associated:
            evidence.append(
                Evidence(
                    label=f"Missingness associated with site or target (Bonferroni α = {alpha})",
                    table=associated,
                    columns=sorted({a["feature"] for a in associated}),
                )
            )

        parts = [f"{overall:.1%} overall"]
        if len(high):
            parts.append(f"{len(high)} of {len(columns)} features above {feature_warn:.0%}")
            parts.append(f"worst {high.index[0]} ({high.iloc[0]:.0%})")
        else:
            parts.append(f"no feature above {feature_warn:.0%}")
        if associated:
            groups_hit = sorted({a["associated_with"] for a in associated})
            parts.append(f"{len(associated)} associated with {' and '.join(groups_hit)}")
        elif tests:
            parts.append(f"none associated with {' or '.join(tests)}")

        problem = overall > overall_warn or len(high) > 0 or bool(associated)
        return self.result(
            Status.WARN if problem else Status.PASS,
            "; ".join(parts) + ".",
            severity=Severity.DEGRADING if problem else None,
            metrics={
                "overall_missing_fraction": round(overall, 4),
                "n_features": len(columns),
                "n_features_above_threshold": int(len(high)),
                "n_associations": len(associated),
            },
            evidence=evidence,
            remediation=(
                "Drop or impute high-missingness features inside the training folds. Treat "
                "site- or target-associated missingness as informative: model it explicitly "
                "or confirm it is not a proxy for the outcome."
                if problem
                else None
            ),
        )
